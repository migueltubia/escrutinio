"""Junta General del Principado de Asturias: votaciones del Pleno (X, XI y XII legislaturas).

Fuentes, que se cruzan:
- eParlamento (https://eparlamento.jgpa.es/transparencia/votaciones/): el sistema de voto
  electrónico publica cada día de pleno y, por votación, un XML en ISO-8859-1 (mal formado, se lee
  con expresiones regulares) con el voto de cada diputado y su grupo. Va del 25/09/2015 al
  29/03/2023. No trae el asunto (como mucho «Nº 16 (Toma en consideración)»), desde septiembre de
  2021 puede incluir votaciones de prueba o anuladas y del 6/5/2020 al 7/4/2021 le faltan los votos
  telemáticos.
- Diario de Sesiones del Pleno (https://agoranet.jgpa.es/documentos/Diarios/PDF/11J140.pdf, serie
  J numerada por legislatura): el orden del día da cada asunto con su expediente
  (11/0178/0938/28621) y el sumario, en frases muy regulares, cada votación con lo votado, el
  resultado y el recuento oficial («La enmienda 34414 ... es rechazada por 4 votos a favor, 38 en
  contra y 2 abstenciones»). Se lee con reglas.

Se recorren los Diarios del Pleno de lo más reciente a lo más antiguo. Los XML de cada día se
emparejan con las votaciones del sumario por orden y recuento (alineación de secuencias): del Diario
salen título, expediente, lo votado, autor y resultado oficial; del XML, el voto nominal y por grupo.
Las votaciones del sumario sin XML (toda la XII legislatura, cuyo voto nominal está en jgpa.es tras
una comprobación anti-bots; asentimientos; días sin XML) salen solo con los totales del Diario
(fuente «pdf-reglas»). Las elecciones por papeleta (senadores, síndicos…) no se recogen.

Limitaciones:
- El XML no trae los votos telemáticos (COVID y, después, cuando el Diario anota «(1 telemático)»).
  Si su recuento no cuadra por eso, los totales son los del Diario y el voto nominal (solo
  presencial) va en extra["nominal_presencial"], sin voto por grupo.
- XML sin pareja en el Diario: se descartan en el sistema nuevo (septiembre de 2021 en adelante:
  pruebas, anuladas) y cuando faltan telemáticos; en el antiguo salen con el nombre que les da
  eParlamento y extra["sin_asunto"]. Si el Diario da otro recuento, va en extra["totales_diario"].
- El sistema antiguo corta nombres (14 caracteres) y apellidos (15): se completan con APELLIDOS.
- Los empates que obligan a repetir la votación salen como votaciones sin resultado.
sesion = número del Diario (11J140 -> 140); numero = orden de la votación en la página de
eParlamento, o 1000 + orden en el sumario si solo está en el Diario (en la XII, el orden en el
sumario: depende del análisis del texto, así que conviene reemplazar la sesión entera al cargar).
"""

import gzip
import html
import math
import re
import unicodedata
import urllib.error
from concurrent.futures import ThreadPoolExecutor

from ... import territorio
from ..modelo import Votacion, VotoGrupo, VotoNominal

CODIGO = "parl-AS"
EPARLAMENTO = "https://eparlamento.jgpa.es/transparencia/votaciones/"
DIARIO_URL = "https://agoranet.jgpa.es/documentos/Diarios/PDF/{}.pdf"

# Fechas de las sesiones constitutivas (Diarios 10J001, 11J001 y 12J001).
LEGISLATURAS = {
    10: ("X", "2015-06-16", "2019-06-24"),
    11: ("XI", "2019-06-24", "2023-06-26"),
    12: ("XII", "2023-06-26", None),
}
# Último Diario del Pleno de cada legislatura. En la abierta es el punto de partida para buscar más.
ULTIMO_DIARIO = {10: 220, 11: 140, 12: 121}
SIN_TELEMATICOS = ("2020-05-06", "2021-04-07")  # eParlamento no recoge el voto telemático
ESCANOS = 45

CUERPOS = [
    territorio.Cuerpo(CODIGO, territorio.num_parlamento("AS"), "Junta General del Principado de Asturias",
                      "Junta General (Asturias)", "autonomico", "AS", ESCANOS, LEGISLATURAS, web="https://www.jgpa.es"),
]

NOTAS = ("Pleno desde la X legislatura (16/06/2015). Voto nominal y por grupo del XML de eParlamento "
         "(25/09/2015-29/03/2023), cruzado con el sumario del Diario de Sesiones (asunto, expediente, "
         "resultado). XII legislatura y votaciones sin XML: solo totales y resultado del Diario (el voto "
         "nominal actual está tras una comprobación anti-bots en jgpa.es). Cuando el XML no trae los "
         "votos telemáticos (2020-2023), totales del Diario y voto nominal solo presencial en extra. "
         "Sin elecciones por papeleta.")

GRUPOS = {  # siglas del XML -> nombre que da eParlamento; sin siglas -> «Sin grupo» (no adscritos)
    "GPS": "Grupo Parlamentario Socialista",
    "GPP": "Grupo Parlamentario Popular",
    "GPPOD": "Grupo Parlamentario Podemos Asturies",
    "GPIU": "Grupo Parlamentario de Izquierda Unida",
    "GPFA": "Grupo Parlamentario Foro Asturias",
    "GPC": "Grupo Parlamentario Ciudadanos",
    "GPV": "Grupo Parlamentario Vox",
    "GPVOX": "Grupo Parlamentario Vox",
    "GPFOX": "Grupo Parlamentario Vox",  # errata de GPVOX en un XML de octubre de 2019
    "GPM": "Grupo Parlamentario Mixto",  # julio de 2019, antes de formarse los grupos de Foro, IU y Vox
}
SENTIDOS = {"si": "si", "no": "no", "abstencion": "abstencion", "no vota": "no_vota"}
# El sistema antiguo de eParlamento (hasta junio de 2021) corta el nombre en 14 caracteres y los apellidos
# en 15. Se completan con la forma que dan el sistema nuevo y los Diarios de Sesiones de la legislatura.
APELLIDOS = {
    "Barbón Rodrígue": "Barbón Rodríguez", "Albaladejo Carr": "Albaladejo Carrasco",
    "González Cacher": "González Cachero", "Fernández Vilan": "Fernández Vilanova",
    "Rodríguez Guerr": "Rodríguez Guerra", "Polledo Enríque": "Polledo Enríquez",
    "Pérez García de": "Pérez García de la Mata",
    "Álvarez Campill": "Álvarez Campillo", "Fernández Rodrí": "Fernández Rodríguez",
    "Llamazares Trig": "Llamazares Trigo", "Llamado Gonzále": "Llamedo González",
    "Llamedo Gonzále": "Llamedo González", "Piernavieja Cac": "Piernavieja Cachero",
    "Martínez Oblanc": "Martínez Oblanca", "Flórez Barreale": "Flórez Barreales",
    "Fernández Ferná": "Fernández Fernández",
    "Gutiérrez Garcí": "Gutiérrez García", "Cuervas-Mons Ga": "Cuervas-Mons García-Braga",
    "Fernández Castr": "Fernández Castro", "Fernández Huerg": "Fernández Huerga",
    "Fernández Barto": "Fernández Bartolomé", "Gutiérrez Escan": "Gutiérrez Escandón",
    "Freile Fernánde": "Freile Fernández", "García Fernánde": "García Fernández",
    "Miranda Fernánd": "Miranda Fernández", "Fernández Gonzá": "Fernández González",
    "Mallada de Cast": "Mallada de Castro", "González Menénd": "González Menéndez",
    "Álvarez-Pire Sa": "Álvarez-Pire Santiago", "García Villanue": "García Villanueva",
    "de Rueda Galla": "de Rueda Gallardo", "de Rueda Gallar": "de Rueda Gallardo",
    "Sanjurjo Gonzál": "Sanjurjo González", "Suárez Fernánde": "Suárez Fernández",
    "Suárez Argüelle": "Suárez Argüelles", "Espiño Castella": "Espiño Castellanos",
    "García Rodrígue": "García Rodríguez", "Fernández Álvar": "Fernández Álvarez",
    "Morales Fuentec": "Morales Fuentecilla", "Vallina de la N": "Vallina de la Noval",
}
NOMBRES = {"Rafael Abelard": "Rafael Abelardo", "Sara Concepci": "Sara Concepción", "Sara Concepció": "Sara Concepción"}
CORREGIDOS = {  # erratas de un XML suelto
    ("García Fernánd", "María Gloria"): ("María Gloria", "García Fernández"),  # nombre y apellidos al revés
    ("Gimena", "Llamado Gonzále"): ("Jimena", "Llamedo González"),
    ("Gimena", "Llamedo Gonzále"): ("Jimena", "Llamedo González"),
}
MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}

# ---------------------------------------------------------------------------- texto


def _plano(s):
    """Minúsculas sin tildes y con lo que no es letra o cifra cambiado por espacio (misma longitud)."""
    out = []
    for c in s:
        b = unicodedata.normalize("NFKD", c)[:1].lower()
        out.append(b if b.isalnum() else " ")
    return "".join(out)


def _num(s):
    if s is None:
        return None
    s = s.lower()
    return int(s) if s.isdigit() else {"un": 1, "una": 1, "uno": 1}.get(s, 0)


# ---------------------------------------------------------------------------- Diario de Sesiones

# Cabeceras y pies de página del PDF.
MUEBLE = re.compile(
    r"www\.jgpa\.es|info@jgpa\.es|Cabo Noval|^t: \d|^f: \d|^DL: |Powered by TCPDF|Verificable en|CVE: |"
    r"^Verificable$|^en$|^CVE:|^DSJG\d|^Junta General(?: del Principado de Asturias)?$|^del Principado de Asturias$|"
    r"^DIARIO DE SESIONES$|"
    r"DIARIO DE SESIONES DE LA JUNTA GENERAL|^SERIE P\b|^[XVI]+ LEGISLATURA\b|^Publicado el|^\d{1,4}$|"
    r"^\d{1,2} DE [A-ZÁÉÍÓÚ]+ DE \d{4}$")
# Expediente (11/0178/0938/28621) o, en los asuntos de gobierno interior, referencia de la Serie C (B1102/2008/2).
_EXP = r"(\d{1,2}/\d{4}/\d{4}/\d{5}|[A-Z]\d{2,5}/\d{4}/\d{1,5})"
EXPEDIENTE = re.compile(r"\(" + _EXP + r"([^)]*)\)")
FECHA_SESION = re.compile(r"celebradas? el [^.]{0,40}?\d{4}(?:,?\s+en el (?:Hemiciclo|Salón[^.(]{0,40}?)\b)?", re.I)
# Comienzo de un asunto del orden del día: palabra clave en mayúsculas que abre el rótulo (no la que
# sigue a otra, como en «DEBATE Y VOTACIÓN») o «De don/doña» (preguntas).
ASUNTO_INICIO = re.compile(
    r"(?<![A-ZÁÉÍÓÚÜÑ]\s)«?\b(?:PROPOSICI[ÓO]N|MOCI[ÓO]N|DICTAMEN|PROYECTO|TOMA|CANDIDATURAS?|DEBATE|INFORME|"
    r"PROPUESTAS?|AUTORIZACI[ÓO]N|COMPARECENCIA|DESIGNACI[ÓO]N(?:ES)?|ELECCI[ÓO]N|DECLARACI[ÓO]N|INTERPELACI[ÓO]N|PREGUNTAS?|"
    r"CONVALIDACI[ÓO]N|TRAMITACI[ÓO]N|SOLICITUD|JURAMENTO|CONSTITUCI[ÓO]N|APERTURA|LIQUIDACI[ÓO]N|INCUMPLIMIENTO|"
    r"CUENTA|PLAN|DACI[ÓO]N|VOTACI[ÓO]N|ENMIENDAS?|MANDATO|SESI[ÓO]N|ACUERDO|RECURSO|CONFLICTO|REFORMA|"
    r"NOMBRAMIENTO|REMOCI[ÓO]N|COMUNICACI[ÓO]N|MEMORIA|COBERTURA)\b|\bDe (?:don|doña) ")
# Asunto del orden del día entero (hasta su expediente): pdftotext de poppler los intercala en el sumario.
ASUNTO_ORDEN = re.compile(r"(?:" + ASUNTO_INICIO.pattern + r")[^()]{0,1500}?Bolet[íi]n Oficial[^()]{0,300}?\("
                          + _EXP + r"[^)]*\)")
_N = r"(\d+|un|una|uno|ningún|ninguno|ninguna|cero)"
_TEL = r"(?:\s*\(([^)]{0,80})\))?"  # «(1 telemático)», «(presenciales)»
# (Tolera las erratas del sumario «por 17 a favor» y «2 contra».)
_RECUENTO = (rf"{_N}\s+(?:a\s+)?(?:votos?\s+)?a\s+favor{_TEL}(?:\s*,\s*|\s+y\s+){_N}\s+(?:votos?\s+)?(?:en\s+)?contra{_TEL}"
             rf"(?:(?:\s*,\s*y\s+|\s*,\s*|\s+y\s+){_N}\s+abstenci(?:ón|ones){_TEL})?")
_VERBO = (r"(?:\b(no)\s+)?\b(?:(?:es|son|resulta|resultan|queda|quedan|fue|fueron)\s+|se\s+(?=toma|aprueba|rechaza))"
          r"(aprobad[oa]s?|rechaza(?:d[oa]s?|s)\b|tomad[oa]s?\s+en\s+consideración|convalidad[oa]s?|desestimad[oa]s?|"
          r"toman?\s+en\s+consideración|aprueban?\b|rechazan?\b)")
VOTO = re.compile(_VERBO + r"([^.;]{0,160}?)\s+por\s+(?:(unanimidad|asentimiento)\b|" + _RECUENTO + ")")
# «Por 28 votos a favor, 14 en contra y 3 abstenciones, la proposición es tomada en consideración» o
# «..., queda rechazada la proposición no de ley»: la frase va hasta la línea de puntos del índice.
VOTO_INVERSO = re.compile(r"(?:\bPor|;\s+por)\s+" + _RECUENTO
                          + r"\s*,?\s*([^.;]{3,300}?)(?=\s*(?:\.\s*){3,}\d|[.;]\s|\s*$)")
VERBO = re.compile(_VERBO + r"|(?:\b(no)\s+)?\b(?:se\s+)?(toma|toman)\s+en\s+consideración")
# Elementos de una enumeración que comparten verbo: «…; el apartado b), por 28 votos a favor…».
ELIPSIS = re.compile(r"\s*[;,]\s*(?:y\s+)?((?:el|la|los|las)\s+"
                     r"(?:(?!\b(?:es|son|queda|quedan|resulta|resultan|fue|fueron)\b)[^;,.]){1,80}?),?\s+por\s+"
                     + _RECUENTO)
EMPATE = re.compile(r"\b(doble |triple )?empate(?: inicial)?\s+(?:de|por|a)\s+" + _RECUENTO)
TRAS_EMPATE = re.compile(r"por el resultado de\s+" + _RECUENTO)
LIDER = re.compile(r"\s*(?:\.\s*){3,}\s*\d+")
INICIO_CUERPO = re.compile(r"\((?:Se abre|Se reanuda|Comienza|Se inicia)[^)]{0,120}\)|"
                           r"(?:El|La) (?:señor|señora) [A-ZÁÉÍÓÚÜÑ]{3,}[A-ZÁÉÍÓÚÜÑ \-]*(?:\([^)]*\))?:")
PALABRAS_VACIAS = set("del los las por para con sobre que una uno unos unas este esta estos estas como mas "
                      "sus asi dicho dicha".split())
# Lo votado es una parte del asunto (y no el asunto entero), o el asunto sin más.
PARTE = re.compile(r"^(?:el|los|la|las|lo)\s+(?:punto|puntos|apartado|apartados|enmienda|enmiendas|articulo|articulos|"
                   r"disposici|voto|votos|capitulo|capitulos|titulo|titulos|exposicion|rubrica|resto|texto|redaccion|"
                   r"anexo|seccion|secciones|estado|programa|toma|propuesta de tramitacion|tramitacion|lectura|"
                   r"letra|parrafo|preambulo)\b")
GENERICA = re.compile(r"^(?:la|el)\s+(?:proposicion no de ley|mocion|proposicion|propuesta|dictamen|iniciativa|"
                      r"proyecto de ley|proposicion de ley|toma en consideracion de la proposicion)$")


def _texto_diario(ctx, cod):
    """Texto del Diario, con caché propia del texto además de la del PDF. Se lee en el orden del flujo
    del PDF (pdftotext -raw): el modo normal de poppler mezcla a veces las dos columnas del sumario."""
    ruta = ctx.carpeta(CODIGO) / "diarios" / f"{cod}.txt.gz"
    if ruta.exists():
        return gzip.decompress(ruta.read_bytes()).decode("utf-8")
    try:
        pdf = ctx.fetch(DIARIO_URL.format(cod), cache=f"{CODIGO}/diarios/{cod}.pdf")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    texto = ctx.pdf_texto(pdf, layout=False, raw=True)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(gzip.compress(texto.encode("utf-8")))
    return texto


def _existe(ctx, url):
    try:
        ctx.fetch(url, headers={"Range": "bytes=0-0"}, reintentos=2)
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False
        raise


def _ultimo_diario(ctx, leg):
    """Número del último Diario publicado: fijo en las legislaturas cerradas; en la abierta se buscan
    los siguientes al último conocido hasta dar con tres huecos seguidos."""
    ultimo = ULTIMO_DIARIO[leg]
    if LEGISLATURAS[leg][2] is not None:
        return ultimo
    prefijo = f"{leg}J"
    for p in (ctx.carpeta(CODIGO) / "diarios").glob(f"{prefijo}*.txt.gz"):
        n = p.name[len(prefijo):].split(".")[0]
        if n.isdigit():
            ultimo = max(ultimo, int(n))
    k, huecos = ultimo, 0
    while huecos < 3:
        k += 1
        if _existe(ctx, DIARIO_URL.format(f"{prefijo}{k:03d}")):
            ultimo, huecos = k, 0
        else:
            huecos += 1
    if _existe(ctx, DIARIO_URL.format(f"{max(LEGISLATURAS) + 1}J001")):
        ctx.log(f"  ! {CODIGO}: hay Diarios de la legislatura {max(LEGISLATURAS) + 1}; hay que declararla en asturias.py")
    return ultimo


def _limpio(texto):
    return " ".join(l for l in (x.strip() for x in texto.splitlines()) if l and not MUEBLE.search(l))


def _asuntos(orden):
    """Asuntos del orden del día (el expediente cierra cada uno): título, expediente y pesos de sus palabras."""
    res, pos = [], 0
    for m in EXPEDIENTE.finditer(orden):
        trozo = orden[pos:m.start()].strip()
        pos = m.end()
        if not trozo:  # segundo expediente del mismo asunto
            continue
        trozo = re.split(r"\.\s*[“\"«]?\s*Bolet[íi]n Oficial", trozo)[0].strip(" .*")
        trozo = FECHA_SESION.split(trozo)[-1]  # sin la cabecera del Diario delante del primer asunto
        # Si lleva delante texto ajeno (otro rótulo o el sumario intercalado), el asunto empieza en su
        # última palabra clave.
        inicios = [x.start() for x in ASUNTO_INICIO.finditer(trozo)]
        if inicios and inicios[-1] > 0:
            trozo = trozo[inicios[-1]:].strip(" «")
        # Encabezados de apartado («PREGUNTAS AL PRESIDENTE») pegados al asunto.
        trozo = re.sub(r"^(?:[A-ZÁÉÍÓÚÜÑ]{2,}[\s,]+)+(?=[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ])", "", trozo)
        mm = re.match(r"^[A-ZÁÉÍÓÚÜÑ]{2,}s?(?:\s+[A-ZÁÉÍÓÚÜÑ]+)*\b", trozo)
        if mm:
            trozo = mm.group(0).capitalize() + trozo[mm.end():]
        if len(trozo) < 8:
            continue
        # Para reconocerlo basta el núcleo del título (sin «; voto particular…» ni «, con enmiendas»).
        nucleo = re.sub(r",\s*con enmiendas?$", "", trozo.split(";")[0])
        palabras = [w for w in _plano(nucleo).split() if len(w) > 2 and w not in PALABRAS_VACIAS]
        res.append({"titulo": trozo, "expediente": m.group(1), "otros": m.group(2).strip(" ,") or None,
                    "palabras": set(palabras)})
    n = len(res)
    df = {}
    for a in res:
        for w in a["palabras"]:
            df[w] = df.get(w, 0) + 1
    for a in res:
        a["peso"] = {w: math.log((n + 1) / (df[w] - 0.5)) for w in a["palabras"]}
        a["total"] = sum(a["peso"].values()) or 1
    return res


def _asunto_de(texto, asuntos):
    """Asunto del orden del día que se menciona entero en el texto (o None si no está claro)."""
    palabras = set(_plano(texto).split())
    notas = sorted(((sum(p for w, p in a["peso"].items() if w in palabras) / a["total"], i)
                    for i, a in enumerate(asuntos)), reverse=True)
    if not notas:
        return None
    mejor, i = notas[0]
    segundo = notas[1][0] if len(notas) > 1 else 0
    if mejor >= 0.9 or (mejor >= 0.72 and mejor - segundo >= 0.12):
        return asuntos[i]
    return None


def _frase(trozo):
    """Lo votado: el final del texto previo al verbo, sin el título pegado delante ni frases anteriores."""
    cortes = list(LIDER.finditer(trozo))
    if cortes:
        trozo = trozo[cortes[-1].end():]
    trozo = re.split(r"(?<=[a-záéíóúüñ0-9)])\.\s+(?=[A-ZÁÉÍÓÚ¿(])|;\s+(?=[a-záéíóú])", trozo)[-1]
    trozo = re.split(r"(?<=[a-záéíóúüñ0-9)])\s+(?=(?:El|La|Los|Las|Lo)\s+[a-záéíóúüñ])", trozo)[-1]
    trozo = re.sub(r"^[\s;,.]*(?:y\s+)?", "", trozo)
    trozo = re.sub(r"[\s,;]*(?:,\s*que|que)?\s*$", "", trozo)
    return trozo[:1].upper() + trozo[1:]


def _leer_diario(texto):
    """Fecha, número de sesión y votaciones del sumario de un Diario del Pleno."""
    cabeza = texto[:1500]
    if not re.search(r"\bPleno\b", cabeza):
        return None
    m = re.search(r"celebradas? el (?:[a-záéíóú]+,?\s+)?(\d{1,2}) de ([a-z]+) de (\d{4})", cabeza, re.I)
    if not m or m.group(2).lower() not in MESES:
        return None
    fecha = f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    ses = re.search(r"SESI(?:ÓN|ONES) NÚMEROS? (\d+)", cabeza)
    diario = {"fecha": fecha, "sesion": int(ses.group(1)) if ses else None, "votos": [], "telematico": False}
    t = _limpio(texto)
    # El orden del día empieza tras la fecha y el sumario en «SUMARIO» (o, si falta el rótulo, con la
    # apertura de la sesión); los dos acaban donde empieza la transcripción. pdftotext de poppler
    # mezcla a veces las dos columnas de la primera página: los rótulos salen desplazados y parte del
    # orden del día cae dentro del sumario, así que los asuntos se buscan hasta la transcripción y se
    # quitan del sumario.
    mo = FECHA_SESION.search(t)
    ms = re.compile(r"\bSUMARIO\b|\bSe (?:abre|reanuda) la sesión a las").search(t, mo.end() if mo else 0)
    if not ms:
        return diario
    fin = INICIO_CUERPO.search(t, ms.end())
    fin = fin.start() if fin else len(t)
    orden = re.sub(r"(?:ORDEN|ÓRDENES) DEL DÍA|\bSUMARIO\b", " ", t[:fin])
    sumario = ASUNTO_ORDEN.sub(" ", re.sub(r"(?:ORDEN|ÓRDENES) DEL DÍA", " ", t[ms.end():fin]))
    diario["telematico"] = bool(re.search(r"telem[áa]tic", sumario))
    asuntos = _asuntos(orden)

    hallados = []  # (inicio, fin, frase o None, objeto, negación, verbo, sin recuento, recuento)
    for m in VOTO.finditer(sumario):
        neg, verbo, resto, sin_recuento = m.group(1, 2, 3, 4)
        objeto = resto.strip(" ,")
        objeto = objeto if re.match(r"(?:el|la|los|las)\s", objeto) else None
        recuento, pos = m.groups()[4:], m.end()
        # «es rechazada, tras producirse un empate por 21 votos…, por el resultado de 20 votos…»
        if m.start(5) >= 0 and re.search(r"empate(?: inicial)?\s+(?:de|por|a)\s+$", sumario[m.start():m.start(5)]):
            mt = TRAS_EMPATE.search(sumario, m.end(), m.end() + 250)
            if mt:
                recuento, pos = mt.groups(), mt.end()
        hallados.append((m.start(), pos, None, objeto, neg, verbo, sin_recuento, recuento))
        # Enumeraciones que comparten el verbo: «…son aprobados el apartado a), por 31 votos…; el
        # apartado b), por 28 votos…, y el apartado e), por 44 votos…».
        while (me := ELIPSIS.match(sumario, pos)):
            hallados.append((me.start(), me.end(), "…", me.group(1), neg, verbo, None, me.groups()[1:]))
            pos = me.end()
    for m in VOTO_INVERSO.finditer(sumario):
        clausula = m.group(7)
        mv = VERBO.search(clausula)
        if not mv:
            continue
        # La frase es lo que queda de la cláusula sin el verbo (va antes o después de él).
        antes = re.sub(r"^\s*el Pleno de la Cámara\b", "", clausula[:mv.start()]).strip(" ,")
        frase = antes if len(antes) > 3 else clausula[mv.end():].strip(" ,")
        hallados.append((m.start(), m.end(), frase[:1].upper() + frase[1:], None, mv.group(1) or mv.group(3),
                         mv.group(2) or "tomada en consideración", None, m.groups()[:6]))
    hallados.sort(key=lambda h: h[0])

    votos, actual, previo, base = [], None, 0, ""
    for ini, fin_v, frase, objeto, neg, verbo, sin_recuento, (si, tel1, no, tel2, ab, tel3) in hallados:
        if ini < previo:  # solapada con la anterior
            continue
        antes = sumario[previo:ini]
        if frase == "…":  # elemento de una enumeración: lo votado es lo común más el elemento
            frase = f"{base}, {objeto}" if base else objeto[:1].upper() + objeto[1:]
            antes = ""
        else:
            # El asunto cambia con los encabezados y las frases que lo citan entero.
            for trozo in LIDER.split(antes):
                a = _asunto_de(trozo, asuntos) if trozo.strip() else None
                if a:
                    actual = a
            frase = (frase or _frase(antes)).strip()
            frase = re.sub(r",?\s*tras (?:producirse |haberse producido )?(?:un |dos |sucesivos |sendos )?"
                           r"empates?\b.*$", "", frase)
            base = frase
            if objeto:
                frase = f"{frase}, {objeto}" if frase else objeto[:1].upper() + objeto[1:]
        a = _asunto_de(frase, asuntos)
        if a:
            actual = a
        elif re.match(r"(?i)^(?:la|el)\s+(?:proposición no de ley|proposición de ley|moción|propuesta|proyecto de ley|"
                      r"dictamen)\s+(?:del|de los)\s+grupos?\b",
                      frase):
            actual = None  # cita un asunto que no se reconoce: mejor sin asunto que con otro
        asunto = actual
        if sin_recuento:
            # Asentimientos: solo los de un asunto del orden del día o de una declaración institucional
            # (no los de cuestiones de procedimiento, como «este último extremo es aprobado por asentimiento»).
            md = re.search(r"declaración institucional(?:,? (?:con motivo|sobre|acerca|en relación|relativa)[^,]*)?", frase)
            if md:
                frase, asunto = md.group(0)[:1].upper() + md.group(0)[1:], None
            elif not (a or (actual and re.match(r"(?i)^(?:el|la)\s+(?:dictamen|proposición|moción|propuesta|informe|"
                                                 r"autorización|convenio|declaración|plan|acuerdo)\b", frase))):
                previo = fin_v
                continue
        voto = {
            "frase": frase, "asunto": asunto, "verbo": verbo, "asentimiento": bool(sin_recuento),
            "resultado": "rechazada" if neg or verbo.startswith(("rechaz", "desestim")) else "aprobada",
            "si": _num(si), "no": _num(no), "ab": _num(ab),
            "telematicos": "; ".join(x for x in (tel1, tel2, tel3) if x and "telem" in x) or None,
        }
        # Empates: las votaciones repetidas antes de la definitiva, con su recuento si se da o, si la
        # definitiva también es empate, con el mismo.
        zona = sumario[previo:fin_v]
        if "empate" in zona:
            me = EMPATE.search(zona)
            veces = 2 if re.search(r"tercera votación|(?:dos|sucesivos|sendos|doble) empates?", zona) else 1
            if me:
                cuenta = (_num(me.group(2)), _num(me.group(4)), _num(me.group(6)))
            elif voto["si"] is not None and voto["si"] == voto["no"]:
                cuenta = (voto["si"], voto["no"], voto["ab"])
            else:
                cuenta = None
            if cuenta:
                for _ in range(veces):
                    votos.append(dict(voto, resultado=None, si=cuenta[0], no=cuenta[1], ab=cuenta[2],
                                      frase=f"{frase} (empate: se repite la votación)"))
        previo = fin_v
        votos.append(voto)
    diario["votos"] = votos
    return diario


# ---------------------------------------------------------------------------- eParlamento


def _sesiones(ctx):
    """Días con votaciones en eParlamento: código del Diario (11J140) -> código del día (P230329)."""
    t = ctx.fetch(EPARLAMENTO + "index.php", cache=f"{CODIGO}/eparlamento/index.html", caduca_dias=30).decode("latin-1")
    return dict(re.findall(r"id='enlaceSesion(\d+J\d+)' href='index\.php\?d=(P\d{6})'", t))


def _votos_xml(ctx, dia):
    """Votaciones de un día de eParlamento, en el orden de la página (que da el número):
    [(numero, url, cabecera, [(nombre, grupo, sentido)])]. En cabecera["etiqueta"] va el nombre que
    le da la página si no es el genérico «Votación nº N» («Enmienda GPP-10-0004», «Propuesta 21139»)."""
    t = ctx.fetch(f"{EPARLAMENTO}index.php?d={dia}", cache=f"{CODIGO}/eparlamento/{dia}.html").decode("latin-1")
    filas = re.findall(r"<a href='index\.php\?d=\w+&f=([^'&]+)&tv=([^']*)'>", t)

    def bajar(f):
        nombre = f if f.endswith(".xml") else f + ".xml"
        return ctx.fetch(f"{EPARLAMENTO}index.php?d={dia}&f={f}&xml=si", cache=f"{CODIGO}/eparlamento/{dia}/{nombre}")

    with ThreadPoolExecutor(4) as ex:  # hasta 4 descargas a la vez (los plenos de presupuestos pasan de 200)
        brutos = list(ex.map(bajar, [f for f, _tv in filas]))
    out = []
    for n, ((f, tv), raw) in enumerate(zip(filas, brutos), 1):
        x = raw.decode("cp1252", "replace")
        cab = re.search(r"<votacion\b([^>]*)>", x)
        cab = {k: html.unescape(v).strip() for k, v in re.findall(r"(\w+)='([^']*)'", cab.group(1))} if cab else {}
        etiqueta = html.unescape(tv).strip()
        if etiqueta and not re.match(r"Votaci\S+ n\S* \d+$", etiqueta):
            cab["etiqueta"] = etiqueta
        votos = []
        for b in re.findall(r"<voto>(.*?)</voto>", x, re.S):
            campo = {k: html.unescape(v).strip() for k, v in re.findall(r"<(\w+)>([^<]*)</", b)}
            pila, apellidos = CORREGIDOS.get((campo.get("nvotante", ""), campo.get("avotante", "")),
                                             (campo.get("nvotante", ""), campo.get("avotante", "")))
            nom = " ".join(p for p in (NOMBRES.get(pila, pila), APELLIDOS.get(apellidos, apellidos)) if p)
            sentido = SENTIDOS.get(_plano(campo.get("valor", "")).strip())
            if nom and sentido:
                votos.append((nom, campo.get("grupo", ""), sentido))
        out.append((n, f"{EPARLAMENTO}index.php?d={dia}&f={f}", cab, votos))
    return out


def _grupo(siglas):
    return GRUPOS.get(siglas) or siglas or "Sin grupo"


def _recuento(votos):
    c = {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0}
    for _n, _g, s in votos:
        c[s] += 1
    return c


# ---------------------------------------------------------------------------- emparejamiento


def _encaja(c, d, parcial):
    """Puntuación de emparejar el recuento del XML con una votación del sumario (None si no casan)."""
    if d["asentimiento"]:
        return 1 if c["si"] and not c["no"] and not c["abstencion"] else None
    ab = d["ab"] or 0
    if (c["si"], c["no"], c["abstencion"]) == (d["si"], d["no"], ab):
        return 4
    if parcial and c["si"] <= d["si"] and c["no"] <= d["no"] and c["abstencion"] <= ab:
        return 2
    if abs(c["si"] - d["si"]) + abs(c["no"] - d["no"]) + abs(c["abstencion"] - ab) <= 2:
        return 0.5  # casi igual (un voto corregido o mal leído): mejor que dejar dos sueltas
    if _total(d) > ESCANOS:
        return 0.3  # errata del Diario (más votos que escaños): vale por su posición
    return None


def _total(d):
    return (d["si"] or 0) + (d["no"] or 0) + (d["ab"] or 0)


def _alinear(xmls, diario, parcial):
    """Alineación de secuencias (Needleman-Wunsch): índice del XML -> índice del sumario."""
    n, m = len(xmls), len(diario)
    puntos = [[0.0] * (m + 1) for _ in range(n + 1)]
    paso = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        puntos[i][0], paso[i][0] = -i, "x"
    for j in range(1, m + 1):
        puntos[0][j], paso[0][j] = -j, "d"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            mejor, p = puntos[i - 1][j] - 1, "x"
            if puntos[i][j - 1] - 1 > mejor:
                mejor, p = puntos[i][j - 1] - 1, "d"
            e = _encaja(xmls[i - 1], diario[j - 1], parcial or bool(diario[j - 1]["telematicos"]))
            if e is not None and diario[j - 1]["resultado"] is None:
                e -= 0.1  # empate repetido: a igualdad, la votación definitiva se empareja antes
            if e is not None and puntos[i - 1][j - 1] + e > mejor:
                mejor, p = puntos[i - 1][j - 1] + e, "m"
            puntos[i][j], paso[i][j] = mejor, p
    pares, i, j = {}, n, m
    while i > 0 or j > 0:
        p = paso[i][j]
        if p == "m":
            pares[i - 1] = j - 1
            i, j = i - 1, j - 1
        elif p == "x":
            i -= 1
        else:
            j -= 1
    return pares


# ---------------------------------------------------------------------------- clasificación


def _tipo_iniciativa(titulo, expediente):
    t = _plano(titulo)
    tipo = expediente.split("/")[1] if expediente else ""
    reglas = [
        (r"^proposicion no de ley", "pnl"), (r"^mocion\b", "mocion"),
        (r"presupuestos generales", "presupuesto"),
        (r"iniciativa legislativa (popular|municipal|de los ayuntamientos)", "ilp"),
        (r"decreto ley|convalidacion", "dl"),
        (r"reglamento de la junta general|reforma del reglamento|comision de investigacion|^designacion|^eleccion|"
         r"^propuesta de la mesa|estatuto de personal|incompatibilidades|^constitucion|remocion", "organizacion"),
        (r"\bproyecto de ley\b", "pl"),
        (r"\bproposicion (?!no de ley)(?:\w+ ){0,12}?de (?:reforma de la )?ley\b", "ppl"),
        (r"investidura|cuestion de confianza|mocion de censura", "investidura"),
        (r"^autorizacion|convenio|acuerdo de cooperacion|mandato marco", "acuerdo"),
        (r"^informe|^plan\b|^comunicacion|^incumplimiento|^dacion de cuentas|^liquidacion|^comparecencia|"
         r"^cuenta general|^debate (?:general|de orientacion)|^propuestas? de resolucion|^sesion informativa|"
         r"comision especial|sindicatura de cuentas", "control"),
    ]
    for patron, clave in reglas:
        if re.search(patron, t):
            return clave
    return {"0178": "pnl", "0179": "pnl", "0183": "mocion"}.get(tipo, "otro" if titulo else None)


def _tipo_votacion(frase, tipo_ini):
    f = " ".join(_plano(frase).split())
    ley = tipo_ini in ("pl", "ppl", "presupuesto", "ilp")
    if "totalidad" in f:
        return "totalidad"
    if "consideracion" in f:
        return "toma_consideracion"
    if re.match(r"(?:las?|los?|el) (?:enmiendas?|votos? particular)", f):
        return "enmiendas"
    if "convalid" in f:
        return "convalidacion"
    if "tramitacion como proyecto de ley" in f:
        return "tramitacion_ley"
    if re.search(r"\bconjunto\b|votacion final", f):
        return "conjunto"
    if ley and re.search(r"\barticulo|\bdisposici|\bcapitulo|\btitulo|exposicion de motivos|\brubrica|\banexo|"
                         r"\bseccion|\bestado|\bpreambulo", f):
        return "articulado"
    if ley and re.match(r"(?:el|la) (?:dictamen|proyecto|proposicion)\b", f):
        return "conjunto"
    if re.match(r"(?:las?) propuestas? (?:de resolucion|numero|\d|de reprobacion|relativas?)", f) or tipo_ini == "control":
        return "control"
    return {"pnl": "pnl", "mocion": "mocion", "investidura": "investidura", "dl": "convalidacion"}.get(tipo_ini)


# Nombre del grupo autor dentro del título: palabras con mayúscula unidas por «de», «por», «y» o comas.
AUTOR = re.compile(r"\b(?:del|de los)\s+(Grupos? (?:Parlamentarios?|Mixto)\b(?:,?\s+(?:de\s+|por\s+|y\s+(?:de\s+)?)?"
                   r"(?!Ley\b)[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ\-]*)*)")


def _autor(titulo, tipo_ini):
    if tipo_ini in ("pl", "presupuesto", "dl"):
        return "Consejo de Gobierno"
    m = AUTOR.search(titulo)
    if m:
        return m.group(1)
    if titulo.startswith("Propuesta de la Mesa"):
        return "Mesa de la Cámara"
    return None


def _subtitulo(frase, asunto):
    """Lo votado dentro del asunto; None si es el asunto entero sin más."""
    if not frase:
        return None
    f = " ".join(_plano(frase).split())
    if GENERICA.match(f):
        return None
    if asunto and _asunto_de(frase, [asunto]) and not PARTE.match(f):
        m = re.search(r"(con (?:la|las|el|los) (?:incorporación|enmiendas?)[^,]*|incluid[oa]s? [^,]*|"
                      r"incorporad[oa]s? [^,]*)", frase)
        return m.group(1)[:1].upper() + m.group(1)[1:] if m else None
    return re.sub(r"\s+(?:de|del)\s+(?:la|el)\s+(?:moción|proposición|proyecto|dictamen)\b.{40,}$", "", frase)


# ---------------------------------------------------------------------------- votaciones


def _votacion(leg, cod, fecha, numero, diario, d, xml=None, parcial=False):
    """Votacion a partir de la del sumario (`d`, puede faltar) y del XML (`xml`, puede faltar).

    Con `parcial` (XML sin los votos telemáticos) los totales son los del Diario y el voto nominal va
    en extra; si no, los totales salen del voto nominal del XML."""
    asunto = d["asunto"] if d else None
    frase = d["frase"] if d else None
    extra = {"diario": cod, "diario_url": DIARIO_URL.format(cod)}
    if diario.get("sesion"):
        extra["sesion_pleno"] = diario["sesion"]
    if asunto and asunto["otros"]:
        extra["expedientes"] = asunto["otros"]
    if d and d["telematicos"]:
        extra["telematicos"] = d["telematicos"]
    if d and xml and not parcial and _encaja(_recuento(xml[3]), d, False) != 4 and not d["asentimiento"]:
        extra["totales_diario"] = f"{d['si']}/{d['no']}/{d['ab']}"  # el Diario difiere en algún voto
    if asunto:
        titulo = asunto["titulo"]
    elif frase:
        titulo = frase
    else:  # XML sin pareja en el Diario: el nombre que le da eParlamento
        cab = xml[2] if xml else {}
        titulo = cab.get("etiqueta") or f"Votación n.º {numero}" + (f" (asunto {cab['asunto']})" if cab.get("asunto") else "")
        extra["sin_asunto"] = True
    expediente = asunto["expediente"] if asunto else None
    tipo_ini = _tipo_iniciativa(asunto["titulo"], expediente) if asunto else None
    v = Votacion(
        cuerpo=CODIGO, fecha=fecha, titulo=titulo, sesion=int(cod.split("J")[1]), numero=numero, legislatura=leg,
        subtitulo=_subtitulo(frase, asunto) if asunto else None, expediente=expediente, tipo_iniciativa=tipo_ini,
        tipo_votacion=_tipo_votacion(f"{frase} {d['verbo']}" if d else "", tipo_ini),
        autor=_autor(asunto["titulo"], tipo_ini) if asunto else None, resultado=d["resultado"] if d else None, extra=extra)
    if d and (parcial or not xml):
        v.asentimiento = d["asentimiento"]
        if not d["asentimiento"] and _total(d) <= ESCANOS:
            v.a_favor, v.en_contra, v.abstenciones = d["si"], d["no"], d["ab"]
        elif not d["asentimiento"]:  # errata del Diario (suma más votos que escaños): solo el resultado
            extra["recuento_diario"] = f"{d['si']}/{d['no']}/{d['ab']}"
        v.url, v.fuente = DIARIO_URL.format(cod), "pdf-reglas"
    if xml:
        _n, url, cab, votos = xml
        v.url, v.fuente = url, "xml"
        if cab.get("hora"):
            extra["hora"] = cab["hora"]
        if cab.get("asunto"):
            extra["asunto_xml"] = cab["asunto"]
        if cab.get("etiqueta"):
            extra["asunto_eparlamento"] = cab["etiqueta"]
        nominal = [VotoNominal(nom, _grupo(g), s) for nom, g, s in votos]
        if parcial:
            extra["nominal_presencial"] = [[x.nombre, x.grupo, x.sentido] for x in nominal]
        else:
            c = _recuento(votos)
            v.a_favor, v.en_contra, v.abstenciones, v.no_votan = c["si"], c["no"], c["abstencion"], c["no_vota"]
            v.nominal = nominal
            por_grupo = {}
            for _nom, g, s in votos:
                if g:  # sin grupo en el XML (no adscritos y algún error): solo en el nominal
                    por_grupo.setdefault(_grupo(g), {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0})[s] += 1
            v.grupos = [VotoGrupo(g, r["si"], r["no"], r["abstencion"], r["no_vota"]) for g, r in por_grupo.items()]
    return v


def _votaciones_diario(ctx, leg, cod, fecha, diario, dia):
    """Votaciones de un Diario del Pleno (`diario`, puede faltar) y del día de eParlamento que le
    corresponde (`dia`, «P230329», puede faltar)."""
    if not diario:
        ctx.log(f"  ! {CODIGO}: sin sumario legible en el Diario {cod}; votaciones de {fecha} sin asunto")
        diario = {"fecha": fecha, "sesion": None, "votos": []}
    elif diario["fecha"] != fecha:
        ctx.log(f"  ! {CODIGO}: el Diario {cod} es del {diario['fecha']} y eParlamento lo asocia al {fecha}")
    dvotos = diario["votos"]
    if not dia:
        return [_votacion(leg, cod, fecha, j + 1, diario, d) for j, d in enumerate(dvotos)]
    xmls = _votos_xml(ctx, dia)
    # eParlamento no recoge el voto telemático (ni en el periodo del aviso ni después, cuando el Diario
    # lo anota) y el sistema nuevo (septiembre de 2021) guarda también votaciones de prueba o anuladas.
    telematico = diario.get("telematico") or SIN_TELEMATICOS[0] <= fecha <= SIN_TELEMATICOS[1]
    dudosas = telematico or any("VOTACION" in x[1] for x in xmls)
    recuentos = [_recuento(x[3]) for x in xmls]
    pares = _alinear(recuentos, dvotos, telematico)
    out, usados, descartes = [], set(pares.values()), 0
    for i, x in enumerate(xmls):
        j = pares.get(i)
        if j is None and dudosas:
            descartes += 1  # sin pareja en el Diario: de prueba, anulada o sin los votos telemáticos
            continue
        d = dvotos[j] if j is not None else None
        parcial = bool(d and _encaja(recuentos[i], d, False) != 4 and _encaja(recuentos[i], d, True) == 2)
        out.append(_votacion(leg, cod, fecha, x[0], diario, d, x, parcial))
    for j, d in enumerate(dvotos):
        if j not in usados:
            out.append(_votacion(leg, cod, fecha, 1000 + j + 1, diario, d))
    sueltos = len(xmls) - len(pares)
    if sueltos:
        ctx.log(f"  {CODIGO} {fecha} ({cod}): {sueltos} de {len(xmls)} XML sin pareja en el Diario"
                + (f" ({descartes} descartados: de prueba, anulados o sin los votos telemáticos)" if descartes else ""))
    return out


def descargar(ctx):
    """Votaciones del Pleno, de la más reciente a la más antigua, Diario a Diario."""
    desde = ctx.desde(CODIGO)
    n, sesiones = 0, None
    for leg in sorted(LEGISLATURAS, reverse=True):
        if desde and (LEGISLATURAS[leg][2] or "9999") < desde:
            break
        for k in range(_ultimo_diario(ctx, leg), 0, -1):
            cod = f"{leg}J{k:03d}"
            texto = _texto_diario(ctx, cod)
            diario = _leer_diario(texto) if texto else None
            if diario and desde and diario["fecha"] < desde:
                return
            if leg <= 11 and sesiones is None:  # eParlamento solo cubre la X y la XI
                sesiones = _sesiones(ctx)
            dia = (sesiones or {}).get(cod)
            if not diario and not dia:
                continue
            fecha = f"20{dia[1:3]}-{dia[3:5]}-{dia[5:7]}" if dia else diario["fecha"]
            if desde and fecha < desde:
                return
            for v in _votaciones_diario(ctx, leg, cod, fecha, diario, dia):
                yield v
                n += 1
                if ctx.limite and n >= ctx.limite:
                    return
