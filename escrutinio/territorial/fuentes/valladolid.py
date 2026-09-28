"""Ayuntamiento de Valladolid: votaciones del Pleno sacadas con reglas de las actas en PDF.

Fuentes (dos, porque el Ayuntamiento cambió de plataforma en junio de 2025):

- Hasta mayo de 2025, el «Histórico de sesiones plenarias» de valladolid.es: una página por sesión
  («Acuerdos adoptados por el Pleno de la Corporación el día …», paginado con `.nodos,<desde>,20`)
  con sus ficheros: orden del día, extracto para el tablón y el acta («P-2 febrero 2021
  ordinario.pdf», «Acuerdos Pleno 7 febrero 2017 web.pdf»…). Hay páginas desde 2002, pero solo
  traen ficheros desde 2016 aproximadamente.
- Desde junio de 2025, la videoacta (https://videoactas.valladolid.es), que es una aplicación de la
  plataforma actadigital con API pública en https://api.actadigital.com/api/public/v1 (la
  institución se identifica por las cabeceras Origin/Referer): `/sesiones/lista` (paginada),
  `/sesiones/detalle?Sesion=PLENOS.AAAAMMDDnn` (orden del día en JSON, documentos, transcripción)
  y `/sesiones/documentos/<id>` (PDF). El acta de cada sesión se adjunta como «Acta Diligenciada»
  en la propia sesión o como «Acta Anterior (dd-mm-aaaa)» en la siguiente. El certificado de la API
  no pasa la verificación estricta de Python 3.14 («Missing Authority Key Identifier»), así que se
  pide con `inseguro=True`.

Las actas redactan cada votación con frases fijas:

    Votación del punto 2 de la Moción. Efectuada la votación ordinaria se obtiene el resultado de
    diecisiete votos a favor de los grupos municipales Socialista, Valladolid Toma la Palabra y
    Ciudadanos; y diez votos en contra de los grupos municipales Popular y Vox.
    Acuerdo. El Ayuntamiento Pleno, por diecisiete votos a favor de …, aprobó la Enmienda …

De ahí salen con reglas (fuente «pdf-reglas») los totales, el sentido de cada grupo (y su número
cuando es el único grupo de ese sentido), el resultado («aprobó»/«rechazó») y el subtítulo
(«Votación del punto 2 de la Moción»). «Por unanimidad de los capitulares asistentes» da
resultado aprobada; los totales solo si el acta dice cuántos o recoge la votación. El asunto sale
del epígrafe numerado del acta (en mayúsculas, se pasa a minúsculas) o, en las sesiones de la
videoacta, del orden del día en JSON.

Cobertura (septiembre de 2026): 145 actas, 125 del histórico (septiembre de 2015 a marzo de 2024)
y 20 de la videoacta (junio de 2025 en adelante); 2.133 votaciones de 2.138 frases de votación
encontradas. Hueco: de octubre de 2023 a mayo de 2025 el histórico solo trae el orden del día de
casi todas las sesiones y la videoacta no adjunta documentos anteriores a junio de 2025. Antes de
2015 las páginas del histórico no tienen ficheros. 29 concejales hasta 2019 y 27 desde entonces.

Limitaciones: los grupos llevan el nombre corto del acta con «Grupo Municipal» delante; el concejal
no adscrito va como «Concejal no adscrito». Si un grupo vota dividido se marca «dividido» sin
números por concejal. En las actas de 2015-2019 (texto justificado) pdftotext parte las líneas en
palabras sueltas y mezcla los párrafos; en esas se usa el texto en el orden del PDF (-raw). Si aun así
una frase sale revuelta, la votación conserva totales y resultado, pero no el voto por grupo
(extra["aviso"]). Las votaciones por partes contadas en una sola frase («… respecto de los puntos
1º a 4º, y … respecto del punto 5º») se quedan sin totales. Hasta un 2 % de las votaciones no
tienen asunto identificado («Asunto sin identificar»). La sesión es AAAAMMDD·10 + orden en el día
(hay días con dos plenos) y el número, el orden de la votación en el acta. Las sesiones de la
videoacta sin acta adjunta todavía (la última) no dan votaciones hasta que se publique.

Incremental: la lista de la videoacta se lee de lo más reciente a lo más antiguo y se para en
ctx.desde(cuerpo, margen_dias=90); con una fecha posterior a junio de 2025 ya no se consulta el histórico (cerrado). Los
PDF y las páginas de sesiones pasadas quedan en caché.
"""

import html
import json
import re
import unicodedata

from ... import territorio
from ..modelo import Documento, Votacion, VotoGrupo

CUERPO = "ayto-valladolid"
BASE = "https://www.valladolid.es"
WEB = BASE + "/es/ayuntamiento/corporacion-municipal/organos-gobierno/pleno/sesiones-plenarias"
HISTORICO = WEB + "/historico-sesiones-plenarias/acuerdos-adoptados-pleno"
API = "https://api.actadigital.com/api/public/v1"
VIDEOACTAS = "https://videoactas.valladolid.es"
CABECERAS_API = {"Origin": VIDEOACTAS, "Referer": VIDEOACTAS + "/", "Accept": "application/json"}
INICIO_VIDEOACTA = "2025-06-01"   # antes, el histórico de valladolid.es

CUERPOS = [
    # 29 concejales hasta 2019; 27 desde entonces (la población bajó de 300.000 habitantes).
    territorio.Cuerpo(CUERPO, territorio.num_municipio("47186"), "Ayuntamiento de Valladolid", "Ayto. Valladolid",
                      "municipal", "CL", 27,
                      {n: (v[0], v[1], v[2], 29 if n <= 10 else 27) for n, v in territorio.MANDATOS_LOCALES.items()}, WEB),
]

NOTAS = ("Actas del Pleno en PDF: histórico de valladolid.es (2015 a marzo de 2024) y videoacta (API actadigital) "
         "desde junio de 2025; hueco de octubre de 2023 a mayo de 2025 sin actas publicadas. Totales, sentido de "
         "cada grupo y resultado con reglas de las frases «Efectuada la votación…» y «Acuerdo. El Ayuntamiento "
         "Pleno, por…». Grupos con «Grupo Municipal» delante; sin voto por grupo cuando el texto del PDF sale revuelto.")

MESES = {"enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
         "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12}


def _sin_tildes(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _fecha_texto(t):
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+(?:de\s+|del\s+)?(\d{4})", t, re.I)
    if not m or _sin_tildes(m.group(2).lower()) not in MESES:
        return None
    return f"{m.group(3)}-{MESES[_sin_tildes(m.group(2).lower())]:02d}-{int(m.group(1)):02d}"


# ------------------------------------------------------------------ videoacta (desde junio de 2025)

def _api(ctx, ruta, cache=None, caduca_dias=None):
    raw = ctx.fetch(API + ruta, headers=CABECERAS_API, inseguro=True, cache=cache, caduca_dias=caduca_dias)
    return json.loads(raw)


def sesiones_videoacta(ctx, hasta):
    """Sesiones de la videoacta con fecha >= hasta, de la más reciente a la más antigua."""
    out, vistos, pagina = [], set(), 1
    while pagina < 100:
        d = _api(ctx, f"/sesiones/lista?lang=es&page={pagina}&limit=10")
        filas = d.get("data") or []
        nuevas = [f for f in filas if f.get("id") not in vistos]
        if not nuevas:
            break
        for f in nuevas:
            vistos.add(f["id"])
            out.append({"id": f["id"], "sesion": f["id"].split(".", 1)[1], "fecha": f["date"], "tipo": f.get("type"),
                        "titulo": f.get("longTitle")})
        total = (d.get("pagination") or {}).get("totalPages") or 0
        if min(f["date"] for f in nuevas) < hasta or pagina >= total:
            break
        pagina += 1
    return sorted((s for s in out if s["fecha"] >= hasta), key=lambda s: s["id"], reverse=True)


def actas_videoacta(ctx, desde):
    """[(fecha, url_pdf, nombre, orden_del_dia, sesion)] de las sesiones de la videoacta con acta publicada."""
    limite = max(INICIO_VIDEOACTA, desde or INICIO_VIDEOACTA)
    sesiones = sesiones_videoacta(ctx, limite)
    detalle, actas = {}, {}
    for s in sesiones:
        d = _api(ctx, f"/sesiones/detalle?lang=es&Sesion={s['sesion']}")
        detalle[s["fecha"]] = (s, d.get("ordendia") or [])
        for grupo in d.get("docs") or []:
            for doc in grupo.get("items") or []:
                nombre = doc.get("docName") or ""
                if not doc.get("url") or "acta" not in nombre.lower():
                    continue
                if "anterior" in nombre.lower():
                    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", nombre)
                    fecha = f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None
                else:
                    fecha = s["fecha"]
                if not fecha:
                    continue
                # Mejor la firmada o diligenciada que un borrador.
                prioridad = 2 if re.search(r"(?i)diligenciad|firmad", nombre) else 1
                if fecha not in actas or prioridad > actas[fecha][0]:
                    actas[fecha] = (prioridad, f"{API}/sesiones/documentos/{doc['url']}", nombre)
    out = []
    for fecha, (_p, url, nombre) in sorted(actas.items(), reverse=True):
        if fecha < limite:
            continue
        s, orden = detalle.get(fecha, ({"sesion": None, "tipo": None}, []))
        out.append({"fecha": fecha, "url": url, "nombre": nombre, "orden": orden, "tipo": s.get("tipo"),
                    "clave": s.get("sesion") or fecha, "fuente": "videoacta"})
    return out


# ------------------------------------------------------------------ histórico de valladolid.es (hasta mayo de 2025)

def _pagina(ctx, url, cache=None):
    raw = ctx.fetch(url, cache=cache)
    return raw.decode("utf-8", "replace")


def sesiones_historico(ctx, desde):
    """Páginas de sesión del histórico, de la más reciente a la más antigua: [{fecha, url, titulo}]."""
    out, vistas, desde_ = [], set(), 0
    ruta = HISTORICO.replace(BASE, "")
    while desde_ < 1000:
        url = HISTORICO + (f".nodos,{desde_},20" if desde_ else "")
        # El histórico está cerrado (junio de 2025): la lista cambia poco; se refresca cada mes.
        t = ctx.fetch(url, cache=f"{CUERPO}/historico/lista_{desde_}.html", caduca_dias=30).decode("utf-8", "replace")
        nuevas = 0
        for href, texto in re.findall(r'<a[^>]+href="(' + re.escape(ruta) + r'/[^"#?]+)"[^>]*>(.*?)</a>', t, re.S):
            if ".ficheros" in href or href in vistas:
                continue
            vistas.add(href)
            titulo = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", texto))).strip()
            fecha = _fecha_texto(titulo) or _fecha_texto(href.replace("-", " "))
            if not fecha:
                continue
            nuevas += 1
            out.append({"fecha": fecha, "url": BASE + href, "titulo": titulo})
        if not nuevas or (desde and out and min(s["fecha"] for s in out) < desde):
            break
        desde_ += 20
    return out


EXCLUIR_FICHERO = re.compile(r"(?i)orden[ _%20]*del[ _%20]*d|convocatoria|ruegos|preguntas|mociones presentadas|"
                             r"relaci[oó]n de|sorteo|anexo|guion|resumen")


def _elige_acta(ficheros):
    """Del listado de ficheros de una sesión, el acta (o, si no hay, el extracto de acuerdos)."""
    mejores = []
    for url, texto in ficheros:
        nombre = html.unescape(url.rsplit("/", 1)[-1])
        todo = f"{nombre} {texto}"
        if EXCLUIR_FICHERO.search(todo.replace("%20", " ")):
            continue
        if re.search(r"(?i)extracto|tabl[oó]n", todo):
            puntos = 1
        elif re.search(r"(?i)\bacta\b|acuerdos|^\d+-P-", todo):
            puntos = 3
        else:
            puntos = 2
        mejores.append((puntos, url))
    return max(mejores)[1] if mejores else None


def actas_historico(ctx, desde):
    out = []
    if desde and desde >= INICIO_VIDEOACTA:
        return out                    # el histórico está cerrado: nada nuevo que pedir
    for s in sesiones_historico(ctx, desde):
        if s["fecha"] >= INICIO_VIDEOACTA or (desde and s["fecha"] < desde):
            continue
        clave = ctx.clave(s["url"])
        t = _pagina(ctx, s["url"], cache=f"{CUERPO}/historico/sesion_{clave}.html")
        ficheros = [(html.unescape(u), re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip())
                    for u, x in re.findall(r'<a[^>]+href="([^"]+\.ficheros/[^"]+)"[^>]*>(.*?)</a>', t, re.S)]
        url = _elige_acta(ficheros)
        if not url:
            continue
        tipo = "extraordinaria" if "extraordinari" in s["titulo"].lower() else (
            "ordinaria" if "ordinaria" in s["titulo"].lower() else None)
        out.append({"fecha": s["fecha"], "url": BASE + url if url.startswith("/") else url, "nombre": s["titulo"],
                    "orden": [], "tipo": tipo, "clave": s["url"], "fuente": "historico"})
    return out


# ------------------------------------------------------------------ texto del acta

RUIDO = [
    re.compile(r"Código Seguro de Verificación.*?Página\s+\d+\s*/\s*\d+", re.S | re.I),
    re.compile(r"^\s*Plaza Mayor, 1 47001 Valladolid.*$", re.M),
    re.compile(r"^\s*Ayuntamiento de Valladolid\s*$", re.M),
    re.compile(r"^\s*Secretaría General.*Actas.*$", re.M),
    re.compile(r"^\s*Página \d+ de \d+\s*$", re.M),
    re.compile(r"https://(?:videoactas|sede)\.valladolid\.es/\S*"),
]
# Restos del pie de firma que, según cómo salga el texto del PDF, quedan sueltos.
LINEA_RUIDO = re.compile(r"(?i)^(?:\d{1,3}|\d{1,3}\s*/\s*\d{1,3}|Fecha|Página|Url de verificación|Normativa|Firmante|"
                         r"\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}|[A-Z0-9]{20,}(?:\s+Firma electrónica.*)?|"
                         r"Código Seguro de Verificación.*)$")


def limpiar(texto):
    texto = texto.replace("\f", "\n")
    for r in RUIDO:
        texto = r.sub("\n", texto)
    lineas = [ln.strip() for ln in texto.split("\n")]
    lineas = [ln for ln in lineas if ln and not LINEA_RUIDO.match(ln)]
    # Los nombres de los firmantes («JESÚS MOZO AMO») se repiten en cada página.
    veces = {}
    for ln in lineas:
        veces[ln] = veces.get(ln, 0) + 1
    firmantes = {ln for ln, n in veces.items()
                 if n >= 5 and len(ln) < 80 and re.fullmatch(r"[A-ZÁÉÍÓÚÑÜ. ]+", ln) and len(ln.split()) >= 2}
    return "\n".join(ln for ln in lineas if ln not in firmantes)


def _palabras_sueltas(texto):
    """Proporción de líneas que son una palabra sola entre dos líneas en blanco: pdftotext ha partido las
    líneas justificadas («E)⏎⏎MOCIÓN⏎⏎DEL⏎⏎GRUPO…»)."""
    lineas = [ln.strip() for ln in texto.replace("\r", "").split("\n")]
    sueltas = sum(1 for i in range(1, len(lineas) - 1)
                  if not lineas[i - 1] and not lineas[i + 1] and re.fullmatch(r"[^\W\d_]{2,}[,;.]?", lineas[i]))
    return sueltas / max(1, sum(1 for ln in lineas if ln))


def _arreglar_raw(texto):
    """Texto de pdftotext -raw con las palabras cortadas a final de línea unidas («muni-⏎cipales») y los rótulos
    espaciados letra a letra juntos («M O C I Ó N»)."""
    texto = re.sub(r"(?<=[a-záéíóúñü])-[ \t]*\r?\n[ \t]*(?=[a-záéíóúñü])", "", texto)
    return re.sub(r"\b(?:[^\W\d_] ){3,}[^\W\d_]\b", lambda m: m.group(0).replace(" ", ""), texto)


def _texto_acta(ctx, acta):
    nombre = re.sub(r"[^\w.-]+", "_", acta["url"].rsplit("/", 1)[-1])[-80:]
    pdf = ctx.fetch(acta["url"], cache=f"{CUERPO}/actas/{acta['fecha']}_{nombre}",
                    headers=CABECERAS_API if acta["fuente"] == "videoacta" else None,
                    inseguro=acta["fuente"] == "videoacta")
    texto = ctx.pdf_texto(pdf, layout=False)
    if _palabras_sueltas(texto) > 0.18:
        # Actas de 2015-2019 (texto justificado): partidas así, los epígrafes no se reconocen y las frases de
        # votación salen revueltas; en el orden del PDF (-raw) salen bien. No se usa siempre: en alguna acta el
        # PDF repite el texto superpuesto y -raw lo da varias veces.
        texto = _arreglar_raw(ctx.pdf_texto(pdf, layout=False, raw=True))
    return texto


# ------------------------------------------------------------------ reglas

NUMEROS = {
    "cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
    "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24,
    "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30,
}

GRUPOS = {
    "socialista": "Socialista", "socialista-psoe": "Socialista", "psoe": "Socialista",
    "popular": "Popular", "popular-pp": "Popular", "pp": "Popular",
    "vox": "Vox", "ciudadanos": "Ciudadanos", "ciudadanos-cs": "Ciudadanos",
    "valladolid toma la palabra": "Valladolid Toma la Palabra",
    "si se puede valladolid": "Sí Se Puede Valladolid", "si se puede": "Sí Se Puede Valladolid",
    "izquierda unida": "Izquierda Unida", "upyd": "UPyD", "union progreso y democracia": "UPyD",
}


def _numero(palabra):
    p = _sin_tildes(palabra.lower())
    return int(p) if p.isdigit() else NUMEROS.get(p)


SENTIDO_RE = re.compile(r"(?P<num>\d+|[a-záéíóúñ]+)\s+(?P<tipo>votos?\s+a\s+favor|(?:votos?\s+)?en\s+contra|"
                        r"abstenci[oó]n(?:es)?)", re.I)
NO_ADSCRITO_RE = re.compile(r"(?:\by\s+)?\bdel?\s+(?:los\s+|la\s+|el\s+)?[Cc]oncejal(?:a|es)?\s+no\s+adscrit[oa]s?"
                            r"(?:,?\s*(?:D|Dª|Dña|Doña|Don)§?\s*(?:[A-ZÁÉÍÓÚÑ][\wáéíóúñª]*§?\s*)+)?")


def _grupos(texto):
    """«de los grupos municipales Socialista, Popular y Vox» -> ["Socialista", "Popular", "Vox"]."""
    t = re.sub(r"\([^()]*\)?", " ", texto)          # aclaraciones entre paréntesis (a veces sin cerrar)
    # Coletillas tras la lista de grupos: «…, lo que representa la mayoría absoluta…», «respecto del punto 2».
    t = re.split(r"(?i)[,;]?\s*(?:lo que representa|consider[áa]ndose|decidiendo|respecto (?:del?|de los|a los|al) "
                 r"punto|segunda votaci[óo]n|que no estuv|al no estar|por ausencia)", t)[0]
    extra = []
    if NO_ADSCRITO_RE.search(t):
        extra = ["Concejal no adscrito"]
        t = NO_ADSCRITO_RE.sub(" ", t)
    t = re.sub(r"(?i)\bde\s+(?:los|las)\s+grupos?(?:\s+municipal\s?(?:es|aes)?|\s+pol[íi]ticos?)?\b|"
               r"\bdel\s+grupo(?:\s+municipal|\s+pol[íi]tico)?\b|\bgrupos?\s+municipal\s?(?:es|aes)?\b", " ", t)
    t = re.sub(r"\s*[–-]\s*(?:PP|PSOE|VOX|Cs)\s*-?", " ", t)
    t = re.sub(r"[;:.§]", " ", t)
    t = re.sub(r"(?i)\bde\s+este\s+Ayuntamiento\b|\ben\s+funciones\b|\bde\s+(?:los|las)\s+concejal(?:es|as)?\b|"
               r"\bde\s+la\s+concejala\b|\bdel\s+concejal\b", " ", t)
    out, raros = [], 0
    for trozo in re.split(r",|\s+[yY]\s+", t):
        trozo = re.sub(r"\s+", " ", trozo).strip()
        trozo = re.sub(r"(?i)^(?:y|de|del|los|las|el)\s+", "", trozo).strip()
        if not trozo:
            continue
        clave = _sin_tildes(trozo.lower())
        if clave in GRUPOS:
            out.append(GRUPOS[clave])
        elif "presencio" in clave or "no adscrit" in clave:
            out.append("Concejal no adscrito")      # D. Jesús Presencio, concejal no adscrito en 2016-2019
        elif _varios(clave):
            out.extend(_varios(clave))             # «Popular Vox» (falta la coma)
        elif re.search(r"[a-záéíóúñ]{3}", trozo):
            raros += 1                             # texto revuelto del PDF o concejal citado por su nombre
    return [g for g in dict.fromkeys(out + extra)], raros


def _varios(clave):
    """«popular vox» -> ["Popular", "Vox"] si la cadena es una sucesión exacta de grupos conocidos."""
    palabras, out, i = clave.split(), [], 0
    while i < len(palabras):
        for j in range(len(palabras), i, -1):
            nombre = " ".join(palabras[i:j])
            if nombre in GRUPOS:
                out.append(GRUPOS[nombre])
                i = j
                break
        else:
            return []
    return out if len(out) > 1 else []


def recuento(texto):
    """«diecisiete votos a favor de …; y diez votos en contra de …» -> {si|no|abstencion: (n, [grupos])}."""
    marcas = list(SENTIDO_RE.finditer(texto))
    res = {}
    for i, m in enumerate(marcas):
        n = _numero(m.group("num"))
        if n is None:
            continue
        tipo = m.group("tipo").lower()
        clave = "si" if "favor" in tipo else ("no" if "contra" in tipo else "abstencion")
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        if clave in res:
            res["_partes"] = True     # «… respecto de los puntos 1º a 4º, y … respecto del punto 5º»
            continue
        grupos, raros = _grupos(texto[m.end():fin])
        res[clave] = (n, grupos)
        if raros:
            res["_raros"] = res.get("_raros", 0) + raros
    return res


VERBOS = (r"aprob[óo]|rechaz[óo]|adopt[óo]|acord[óo]|desestim[óo]|estim[óo]|tom[óo]|ratific[óo]|dio\s+por|"
          r"dej[óo]|declar[óo]|design[óo]|nombr[óo]|resolvi[óo]|otorg[óo]|conced[ií][óo]|aprueba|rechaza|acuerda|"
          r"manifest[óo]|expres[óo]|mostr[óo]|se\s+adhiri[óo]|inst[óo]|solicit[óo]|reprob[óo]|autoriz[óo]")
EFECTUADA_RE = re.compile(
    r"(?i)efectuada\s+la\s+votaci[óo]n(?:\s+ordinaria|\s+nominal|\s+secreta)?\s*,?\s*(?:se\s+obtiene|arroja|da|dio)\s*,?"
    r"\s*(?:como\s+)?(?:el\s+)?(?:siguiente\s+)?resultado\s*(?:el\s+)?(?:de\s+)?:?\s*(?P<rec>.{5,700}?)"
    r"(?=\.\s|\.$|\s+Acuerdo\b)")
ACUERDO_RE = re.compile(
    r"\bAcuerdo\s*[.:]?\s+(?:Por\s+tanto,?\s+)?El\s+(?:Excmo\.?\s+)?Ayuntamiento(?:\s+Pleno|\s+de\s+Valladolid)?\s*,?\s*"
    r"(?P<rec>.{3,700}?)\s*,?\s+(?P<verbo>" + VERBOS + r")\b")
UNANIME_RE = re.compile(
    r"(?i)(?:fue|ha\s+sido|queda(?:ndo)?|qued[óo]|resulta|result[óo]|se\s+dio\s+por|se\s+da\s+por|se\s+aprueba|es|"
    r"se\s+aprob[óo])\s+(?:aprobad[oa]s?\s+)?por\s+unanimidad(?:\s+de\s+(?:los|todos\s+los|las|todas\s+las)\s+"
    r"(?:(?P<n>[a-záéíóúñ\d]+)\s+)?(?:capitulares|miembros|concejal[ae]s|presentes|asistentes))?")
UNANIMIDAD_N_RE = re.compile(r"(?i)unanimidad\s+de\s+(?:los|las|sus)\s+(?P<n>[a-záéíóúñ\d]+)\s+(?:capitulares|miembros|concejal)")
ETIQUETA_RE = re.compile(r"(?i)Votaci[óo]n\s*[.:]?\s*(?P<que>[^.]{0,200}?)\s*[.:]?\s*(?:Sin\s+deliberaci[óo]n\s+previa,\s*)?$")

# Epígrafes: «3.1. APROBACIÓN DEL …», «2.- DESPACHO ORDINARIO. 2.1.- FELICITACIONES.», «A) MOCIÓN DEL GRUPO …»
NUM_EPIGRAFE = r"(?:\d{1,2}\s?\.\s?\d{1,2}(?:\s?\.\s?\d{1,2})*\.?\s*[-–]?|\d{1,2}\s?\.\s?[-–]?|\d{1,2}\s?[-–]|[A-Z]\))"
EPIGRAFE_RE = re.compile(r"^(" + NUM_EPIGRAFE + r")\s*(?=[A-ZÁÉÍÓÚÑ«“\"])")
PARTE_RE = re.compile(r"(?:(?<=\s)|^)(" + NUM_EPIGRAFE + r")\s*(?=[A-ZÁÉÍÓÚÑ«“\"])")


def _mayus(palabra):
    letras = [c for c in palabra if c.isalpha()]
    return not letras or all(c.isupper() for c in letras) or palabra.lower() in ("de", "y", "del", "la", "el", "en")


def _prefijo_mayusculas(linea):
    """Tramo inicial en mayúsculas de una línea (el título del epígrafe, antes del texto)."""
    palabras = linea.split(" ")
    n = 0
    for i, p in enumerate(palabras):
        if _mayus(p):
            n = i + 1
        else:
            break
    return " ".join(palabras[:n]).strip()


def _num_normal(num):
    num = re.sub(r"\s+", "", num).rstrip(".-–")
    return num


def epigrafe(linea):
    """(número, título) si la línea abre un asunto del orden del día; si no, None."""
    if not EPIGRAFE_RE.match(linea):
        return None
    prefijo = _prefijo_mayusculas(linea)
    letras = [c for c in prefijo if c.isalpha()]
    if len(letras) < 6:
        return None
    # «3.3 MOCIONES. A) MOCIÓN DEL GRUPO …»: tras un apartado corto («MOCIONES», «DESPACHO
    # ORDINARIO») viene el asunto. Un número dentro de un título largo («ARTÍCULO 8.4. APARTADO…»)
    # no abre otro epígrafe.
    partes = list(PARTE_RE.finditer(prefijo))
    elegidas = [partes[0]]
    for p in partes[1:]:
        if len(prefijo[elegidas[-1].end():p.start()].split()) <= 5:
            elegidas.append(p)
        else:
            break
    titulo = prefijo[elegidas[-1].end():].strip(" .-–")
    numeros = [_num_normal(p.group(1)) for p in elegidas]
    if len([c for c in titulo if c.isalpha()]) < 5:
        return None
    return numeros, titulo


NO_EPIGRAFE = re.compile(r"^(?:SE\s|ACUERD|PRIMER|SEGUND|TERCER|CUART|QUINT|ANTECEDENTES|FUNDAMENTOS|ENMIENDA|EXPOSICI|"
                         r"PROPUESTA|RESUELV|DISPONGO|TOTAL|CAP[IÍ]TULO|ART[IÍ]CULO|ANEXO|PREGUNTA|RUEGO|MOCI[OÓ]N$|"
                         r"VOTACI|D\.|DÑA|CONSIDERANDO|RESULTANDO|VISTO|DE CONFORMIDAD|[IÍ]NDICE)")


def epigrafe_sin_numero(linea):
    """Actas antiguas (2016-2018), con los asuntos sin numerar: línea entera en mayúsculas."""
    if NO_EPIGRAFE.match(linea) or _prefijo_mayusculas(linea) != linea.strip():
        return None
    trozos = [t for t in re.split(r"\.\s+", linea.strip(" .")) if t]
    while len(trozos) > 1 and len(trozos[0].split()) <= 3:
        trozos = trozos[1:]           # «DESPACHO ORDINARIO. MOCIONES. MOCIÓN CORPORATIVA …»
    titulo = ". ".join(trozos)
    if len(titulo.split()) < 5 or not re.match(r"[A-ZÁÉÍÓÚÑ«“\"]", titulo):
        return None
    return [], titulo


SIGLAS = ("pgou", "iva", "ibi", "icio", "epel", "zbe", "pimussva", "covid", "vox", "psoe", "pp", "sacyl", "aquavall",
          "auvasa", "ue", "onu", "sa", "s.a")


def _frase(s):
    """Título en mayúsculas -> frase («ACTA DE LA SESIÓN ANTERIOR. APROBAR…» -> «Acta de la sesión anterior. Aprobar…»)."""
    s = re.sub(r"\s+", " ", s).strip(" .").lower()
    s = re.sub(r"(^|[.:]\s+|[«“\"]\s*)([a-záéíóúñ])", lambda m: m.group(1) + m.group(2).upper(), s)
    for sigla in SIGLAS:
        s = re.sub(rf"\b{re.escape(sigla)}\b", sigla.upper(), s)
    for nombre in PROPIOS:
        s = re.sub(rf"\b{re.escape(nombre.lower())}\b", nombre, s)
    return s


PROPIOS = ("Valladolid Toma la Palabra", "Sí Se Puede Valladolid", "Valladolid", "Gobierno de España", "España",
           "Junta de Castilla y León", "Castilla y León", "Ciudadanos", "Socialista", "Popular", "Pisuerga",
           "Unión Europea", "Aquavall", "Auvasa")


def _proteger(t):
    """Evita que «D. Jesús» o «Dª. Mª» corten las frases."""
    return re.sub(r"\b(D|Dª|Dña|Sr|Sra|Mª|Art|núm|Nº)\.\s", r"\1§ ", t)


def eventos(texto):
    """Votaciones de un acta limpia: [dict(pos, asunto, que, rec, verbo, unanimidad_n, tipo)]."""
    lineas = texto.split("\n")
    plano, asuntos, pos = [], [], 0
    ruta = []
    numerados = sum(1 for ln in lineas if epigrafe(ln))
    anterior_epigrafe = False
    for i, ln in enumerate(lineas):
        e = epigrafe(ln) or (epigrafe_sin_numero(ln) if numerados < 2 else None)
        if e and not e[0] and anterior_epigrafe and asuntos:
            # Título sin numerar partido en dos líneas: se une al anterior.
            p0, r0, t0 = asuntos[-1]
            asuntos[-1] = (p0, r0, f"{t0} {ln.strip()}")
            e = None
        anterior_epigrafe = bool(e)
        if e and e[0] and _prefijo_mayusculas(ln) == ln.strip():
            # Título numerado que sigue en las líneas siguientes (texto con saltos de línea físicos).
            numeros, titulo = e
            for siguiente in lineas[i + 1:i + 4]:
                resto = _prefijo_mayusculas(siguiente)
                if not resto or epigrafe(siguiente) or len([c for c in resto if c.isalpha()]) < 3:
                    break
                titulo = f"{titulo} {resto}"
                if resto != siguiente.strip():
                    break
            e = (numeros, titulo)
        if e:
            numeros, titulo = e
            for n in numeros:
                if re.fullmatch(r"[A-Z]\)", n):
                    base = [x for x in ruta if not re.fullmatch(r"[a-z]", x)]
                    ruta = base + [n[0].lower()]
                else:
                    ruta = [x for x in re.split(r"\.", n) if x]
            asuntos.append((pos, ".".join(ruta), titulo))
        plano.append(ln)
        pos += len(ln) + 1
    t = _proteger(" ".join(plano))
    evs = []
    for m in EFECTUADA_RE.finditer(t):
        evs.append({"pos": m.start(), "fin": m.end(), "clase": "E", "rec": m.group("rec")})
    for m in ACUERDO_RE.finditer(t):
        evs.append({"pos": m.start(), "fin": m.end(), "clase": "A", "rec": m.group("rec"), "verbo": m.group("verbo")})
    for m in UNANIME_RE.finditer(t):
        if not any(e["pos"] <= m.start() < e["fin"] + 5 for e in evs):
            evs.append({"pos": m.start(), "fin": m.end(), "clase": "U", "rec": m.group(0), "verbo": "aprob"})
    evs.sort(key=lambda e: e["pos"])

    def asunto_de(p):
        previo = [a for a in asuntos if a[0] <= p]
        return previo[-1] if previo else (0, "", None)

    out, pendiente = [], None
    for e in evs:
        a = asunto_de(e["pos"])
        if pendiente and (asunto_de(pendiente["pos"]) != a or e["clase"] == "E"):
            out.append(pendiente)
            pendiente = None
        if e["clase"] == "E":
            antes = t[max(0, e["pos"] - 260):e["pos"]]
            etiqueta = ETIQUETA_RE.search(antes)
            pendiente = {"pos": e["pos"], "asunto": a, "E": e["rec"], "A": None, "verbo": None,
                         "que": (etiqueta.group("que").strip() if etiqueta else None)}
        elif e["clase"] == "A" and pendiente:
            pendiente.update(A=e["rec"], verbo=e["verbo"])
            out.append(pendiente)
            pendiente = None
        else:
            out.append({"pos": e["pos"], "asunto": a, "E": None, "A": e["rec"], "verbo": e["verbo"], "que": None,
                        "U": e["clase"] == "U"})
    if pendiente:
        out.append(pendiente)
    return out


def _voto(ev, escanos):
    """Evento -> campos de Votacion (totales, grupos, resultado) o None si no hay nada que guardar."""
    rec_a = recuento(ev["A"] or "")
    rec_e = recuento(ev["E"] or "") if ev["E"] else {}
    # «Efectuada la votación…» es el recuento y el «Acuerdo» lo repite; cualquiera de los dos puede
    # salir incompleto («catorce en contra» sin «votos») o revuelto por el orden del texto del PDF.
    # Se toma el más completo (más sentidos, menos nombres irreconocibles) y, a igualdad, el de la votación.
    def _cifras(r):
        return {k: v[0] for k, v in r.items() if not k.startswith("_")}

    def _puntos(r):
        return (len(_cifras(r)), -r.get("_raros", 0))

    rec = dict(rec_a if rec_a and (not rec_e or _puntos(rec_a) > _puntos(rec_e)) else rec_e)
    avisos = []
    if rec_e and rec_a and _cifras(rec_e) != _cifras(rec_a) and len(_cifras(rec_e)) == len(_cifras(rec_a)):
        avisos.append("el recuento de la votación y el del acuerdo no coinciden; se usa el más completo")
    if rec.pop("_raros", 0):
        # Nombres que no son grupos: texto revuelto al extraerlo del PDF. Los totales valen; los
        # grupos podrían estar mal repartidos entre sentidos, así que no se guardan.
        avisos.append("texto revuelto o concejales citados por su nombre: sin voto por grupo")
        rec = {k: (v[0], []) for k, v in rec.items() if not k.startswith("_")} | (
            {"_partes": True} if rec.get("_partes") else {})
    total = sum(v[0] for k, v in rec.items() if not k.startswith("_"))
    if rec.pop("_partes", False):
        avisos.append("votación por partes en una sola frase: sin totales")
        rec = {}
    elif total > escanos:
        avisos.append(f"el acta suma {total} votos con {escanos} concejales: sin totales")
        rec = {}
    texto = f"{ev['E'] or ''} {ev['A'] or ''}"
    unanimidad = bool(re.search(r"(?i)unanimidad", texto))
    resultado = None
    if ev["verbo"]:
        # «rechazó» es lo único que tumba la propuesta; «desestimó» o «reprobó» son acuerdos adoptados.
        resultado = "rechazada" if re.match(r"(?i)rechaz", ev["verbo"]) else "aprobada"
    a_favor = rec["si"][0] if "si" in rec else None
    if unanimidad and a_favor is None:
        m = UNANIMIDAD_N_RE.search(texto)
        if m and _numero(m.group("n")):
            a_favor = _numero(m.group("n"))
            rec["si"] = (a_favor, rec.get("si", (0, []))[1])
    if resultado is None and a_favor is None and not unanimidad:
        return None
    if unanimidad and resultado is None:
        resultado = "aprobada"
    en_contra = rec["no"][0] if "no" in rec else (0 if a_favor is not None and unanimidad else None)
    abst = rec["abstencion"][0] if "abstencion" in rec else (0 if a_favor is not None and unanimidad else None)
    if a_favor is not None and not unanimidad:
        en_contra = en_contra if en_contra is not None else 0
        abst = abst if abst is not None else 0
    por_grupo = {}
    for clave in ("si", "no", "abstencion"):
        n, grupos = rec.get(clave, (None, []))
        for g in grupos:
            por_grupo.setdefault(g, {})[clave] = n if len(grupos) == 1 else None
    grupos = []
    for g, d in por_grupo.items():
        nombre = g if g.startswith("Concejal") else f"Grupo Municipal {g}"
        if len(d) > 1:
            grupos.append(VotoGrupo(nombre, sentido="dividido"))
        else:
            (clave, n), = d.items()
            grupos.append(VotoGrupo(nombre, sentido=clave, **({clave: n} if n is not None else {})))
    return {"a_favor": a_favor, "en_contra": en_contra, "abstenciones": abst, "resultado": resultado,
            "grupos": grupos, "unanimidad": unanimidad, "avisos": avisos}


def _tipo_iniciativa(t):
    n = _sin_tildes(t).upper()
    if "MOCION" in n:
        return "mocion"
    if re.search(r"\b(ORDENANZA|REGLAMENTO)\b", n[:90]):
        return "ordenanza"
    if "PRESUPUESTO GENERAL" in n and not re.search(r"MODIFICACION|LIQUIDACION|EJECUCION DEL PRESUPUESTO", n):
        return "presupuesto"
    if re.search(r"ACTA DE LA SESION|ACTAS? DE (LAS )?SESION|DESIGNACION|NOMBRAMIENTO|REPRESENTANTE|TOMA DE POSESION|"
                 r"COMPOSICION|RENUNCIA|CONCEJAL|ELECCION|ALCALDE|PERIODICIDAD|ORGANIZACION", n):
        return "organizacion"
    if re.search(r"PREGUNTA|INTERPELACION|DACION|DA CUENTA|COMPARECENCIA|INFORME", n):
        return "control"
    return "acuerdo"


def _autor(t):
    m = re.search(r"(?i)moci[óo]n\s+(?:conjunta\s+)?de(?:l| los| la)\s+((?:grupos?\s+municipal(?:es)?|concejal[a]?)\s+.+?)"
                  r"\s+(?:para|de|sobre|en|relativa|por|contra|a favor|instando|que|con|ante)\b", t)
    if not m:
        return None
    grupos, _raros = _grupos(" de los " + m.group(1))
    if grupos:
        return ", ".join(g if g.startswith("Concejal") else f"Grupo Municipal {g}" for g in grupos)
    return m.group(1)


def votaciones_acta(texto, acta, sesion):
    orden = {str(p.get("punto", "")).strip().rstrip(".").lower(): (p.get("titulo") or "").strip()
             for p in acta.get("orden") or []}
    out = []
    cuerpo = CUERPOS[0]
    escanos = cuerpo.escanos_de(cuerpo.legislatura_de(acta["fecha"]) or 0)
    evs = eventos(limpiar(texto))
    for n, ev in enumerate(evs, 1):
        v = _voto(ev, escanos)
        if not v:
            continue
        _pos, ruta, titulo = ev["asunto"]
        titulo_od = orden.get(ruta.lower()) if ruta else None
        if titulo_od and titulo_od == titulo_od.upper():
            titulo_od = _frase(titulo_od)
        tit = titulo_od or (_frase(titulo) if titulo else "Asunto sin identificar")
        tipo = _tipo_iniciativa(titulo_od or titulo or "")
        que = ev.get("que")
        subtitulo = ("Votación " + re.sub(r"\s+", " ", que).strip()).replace("§", ".") if que else None
        tv = None
        # «de la Enmienda de Adición…», «de punto 11 de la Enmienda…»; no «del punto 2 de la Moción,
        # incorporada la Enmienda…», que vota la moción.
        if que and re.match(r"(?i)(?:de\s+(?:la|las)\s+|del?\s+punto\s+\S+\s+de\s+la\s+)?(?:primera\s+|segunda\s+|"
                            r"tercera\s+|cuarta\s+|quinta\s+|sexta\s+)?enmienda", que):
            tv = "enmiendas"
        elif tipo == "mocion":
            tv = "mocion"
        extra = {"punto": ruta or None}
        if v["avisos"]:
            extra["aviso"] = "; ".join(v["avisos"])
        if acta.get("tipo"):
            extra["sesion_tipo"] = acta["tipo"]
        out.append(Votacion(
            cuerpo=CUERPO, fecha=acta["fecha"], titulo=tit, sesion=sesion, numero=n, subtitulo=subtitulo,
            tipo_iniciativa=tipo, tipo_votacion=tv, autor=_autor(titulo_od or titulo or ""),
            a_favor=v["a_favor"], en_contra=v["en_contra"], abstenciones=v["abstenciones"],
            resultado=v["resultado"], grupos=v["grupos"], url=acta["url"], fuente="pdf-reglas", extra=extra,
            # «Por unanimidad» sin recuento: aprobada sin totales (modelo.Votacion.asentimiento).
            asentimiento=v["unanimidad"] and v["a_favor"] is None))
    return out, len(evs)


# ------------------------------------------------------------------ conector

def _numeradas(lista):
    """Sin repetidas, de la más reciente a la más antigua y con su número de sesión estable (fecha y orden en el día)."""
    todas, urls = [], set()
    for a in lista:
        if a["url"] not in urls:
            urls.add(a["url"])
            todas.append(a)
    todas.sort(key=lambda a: (a["fecha"], str(a["clave"])), reverse=True)
    por_dia = {}
    for a in sorted(todas, key=lambda a: (a["fecha"], str(a["clave"]))):
        k = por_dia.get(a["fecha"], 0)
        por_dia[a["fecha"]] = k + 1
        a["sesion"] = int(a["fecha"].replace("-", "")) * 10 + k
    return todas


def _actas(ctx):
    """Las de la videoacta y después las del histórico. No comparten días (el histórico acaba donde empieza la
    videoacta), así que numerarlas por separado da los mismos números. Como generador, el histórico (sin caché,
    una página por sesión desde 2015) solo se pide si hace falta: el listado de documentos para en cuanto llena
    su cupo."""
    desde = ctx.desde(CUERPO, margen_dias=90)   # el acta se adjunta a la sesión siguiente
    yield from _numeradas(actas_videoacta(ctx, desde))
    yield from _numeradas(actas_historico(ctx, desde))


def actas(ctx):
    """Todas las actas, de la más reciente a la más antigua, con su número de sesión estable."""
    return list(_actas(ctx))


def descargar(ctx):
    n = total_eventos = total_votos = sin_votos = 0
    for acta in actas(ctx):
        texto = _texto_acta(ctx, acta)
        if len(texto.strip()) < 500:
            ctx.log(f"  {CUERPO}: acta sin texto {acta['url']}")
            continue
        votos, evs = votaciones_acta(texto, acta, acta["sesion"])
        total_eventos += evs
        total_votos += len(votos)
        sin_votos += not votos
        for v in votos:
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    ctx.log(f"  {CUERPO}: {total_votos} votaciones de {total_eventos} frases de votación; {sin_votos} actas sin ninguna")


def documentos(ctx):
    n = 0
    for acta in _actas(ctx):
        yield Documento(cuerpo=CUERPO, fecha=acta["fecha"], url=acta["url"], sesion=acta["sesion"], formato="pdf",
                        idioma="es", titulo=acta["nombre"], extra={"origen": acta["fuente"]})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    acta = {"url": doc.url, "fecha": doc.fecha, "fuente": doc.extra.get("origen", "historico")}
    return limpiar(_texto_acta(ctx, acta))
