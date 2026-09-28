"""Parlamento de Navarra: votaciones del Pleno sacadas con reglas del Diario de Sesiones (PDF).

Fuente: el buscador de la web (Drupal) filtrado por tipo «Diario de sesiones» y órgano «Pleno»
(https://parlamentodenavarra.es/es/busquedas/organo/48/tipo-contenido/parlamento_diario_sesiones?page=N),
diez por página y ordenado por la fecha de la sesión, del más reciente al más antiguo; cada entrada trae
el enlace al PDF (Plen11084.pdf, aunque el nombre varía: PLEN9145.pdf, diario-sesiones-Plen9005.pdf o
Plen11096_0.pdf si se ha sustituido), el número del diario y la fecha. El RSS de diarios solo da los diez
últimos de todos los órganos. No hay datos abiertos de votaciones ni voto por grupo o nominal: el voto
es electrónico y la Secretaría lee solo los totales.

Qué se saca: el SUMARIO de cada diario resume cada punto del orden del día (con su expediente,
«11-26/MOC-00020», desde finales de 2022) y cada votación con una frase muy regular: «Se aprueba la
moción por 30 votos a favor, 4 en contra y 16 abstenciones», «Queda rechazado el punto número 2 por...».
Cada frase de resultado es una votación, con el título y el autor del punto (de su cabecera en el
sumario) y lo que se vota de subtítulo. En el cuerpo, cada votación acaba con la lectura de la Secretaría
(«SRA. SECRETARIA PRIMERA (...): 30 votos a favor, 4 en contra, 16 abstenciones») y el anuncio del
resultado por la Presidencia. Las lecturas de cada punto se casan con el sumario: si hay tantas como
votaciones y los totales coinciden, la votación queda verificada (`extra["verificada"]`) y lo aprobado
«por unanimidad» recibe los totales leídos. Las dos listas se alinean en orden: las lecturas sin pareja
entre dos de un mismo punto (presupuestos y leyes, que el sumario resume en una frase) se añaden, con lo que
anuncia la Presidencia de subtítulo y el resultado que proclama (`extra["de_cuerpo"]`); si sumario y lectura
difieren en un total, manda la lectura (`extra["discrepancia"]`); las votaciones repetidas por empate o error
no se cuentan. Las lecturas en euskera («30 alde, 19 kontra») y su traducción entre corchetes también valen.
En los debates conjuntos (varias cabeceras seguidas) las votaciones se reparten en orden si hay una por punto;
si no, llevan los títulos de todos (`extra["debate_conjunto"]`) y el expediente solo si es común.

Cobertura: Pleno de la IX (2015), X (2019) y XI (2023-) legislaturas; `sesion` es el número del diario
(una sesión de varios días tiene un diario por día). Limitaciones: solo totales; hasta finales de 2022 el
sumario no trae el número de expediente (queda en blanco); las elecciones por papeletas con candidatos no
se recogen: esos diarios (sesiones constitutivas, designaciones) van al LLM con `documentos()`. Si el
resultado no cuadra con los totales y no se cita una mayoría cualificada, el resultado se deja en blanco
(`extra["resultado_texto"]`). Los diarios salen con semanas de retraso (o se sustituyen por otra versión):
la recogida incremental repasa los dos últimos meses.
"""

import html
import re
import unicodedata

from ...territorio import Cuerpo, num_parlamento
from ..modelo import Documento, Iniciativa, Votacion

CUERPO = "parl-NC"
BASE = "https://parlamentodenavarra.es"
LISTADO = BASE + "/es/busquedas/organo/48/tipo-contenido/parlamento_diario_sesiones?page={pagina}"
FICHA = BASE + "/es/expedientes/{clave}"

LEGISLATURAS = {
    9: ("IX", "2015-06-17", "2019-06-19"),
    10: ("X", "2019-06-19", "2023-06-16"),
    11: ("XI", "2023-06-16", None),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("NC"), "Parlamento de Navarra", "Parlamento (Navarra)", "autonomico", "NC", 50,
           LEGISLATURAS, web=BASE + "/es/publicaciones/diarios-sesiones"),
]

NOTAS = ("Votaciones del Pleno con reglas sobre el Diario de Sesiones en PDF: el sumario da cada votación (totales, "
         "resultado, título, autor y, desde finales de 2022, expediente) y las lecturas de la Secretaría en el cuerpo "
         "la verifican, completan lo aprobado por unanimidad y desglosan presupuestos y leyes. Sin voto por grupo ni "
         "nominal. IX, X y XI legislaturas. Los diarios se publican con semanas de retraso.")

# Tipo de expediente (11-26/MOC-00020) -> tipo de iniciativa.
TIPOS = {"MOC": "mocion", "PRO": "ppl", "PRC": "ppl", "LEY": "pl", "DLF": "dl", "AUT": "acuerdo", "CIE": "organizacion",
         "ELC": "organizacion", "ELCR": "organizacion", "ELCO": "organizacion", "ELCC": "organizacion",
         "MES": "organizacion", "OTL": "acuerdo", "CDP": "control", "DPGC": "control", "DFP": "control",
         "ITP": "control", "POR": "control", "PEI": "control"}

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
NUMEROS = {"un": 1, "uno": 1, "una": 1, "ningun": 0, "ninguno": 0, "ninguna": 0, "cero": 0, "dos": 2, "tres": 3,
           "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}

ITEM_LISTADO_RE = re.compile(r'<a href="(https?://[^"]*/diarios-sesiones/[^"]+?\.pdf)"[^>]*>\s*([^<]*?)\s*</a>'
                             r'(?:(?!</li>).)*?content="(\d{4}-\d{2}-\d{2})', re.S | re.I)
FECHA_RE = re.compile(r"Pamplona,\s+(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)
EXPEDIENTE_RE = re.compile(r"^(?:\d{1,2}-(?=\d{1,2}-\d{2}/))?(\d{1,2}-\d{2}/([A-ZÑ]{2,6})-\d{4,5})\.\s*")
SUMARIO_RE = re.compile(r"^\s*S ?U ?M ?A ?R ?I ?O\s*$", re.M)
INICIO_SUMARIO_RE = re.compile(r"^(?:Comienza|Se reanuda) la sesi[oó]n", re.M)
CABECERA_DIARIO_RE = re.compile(r"^SESI[OÓ]N PLENARIA N[UÚ]M.*$", re.M)
# principio del cuerpo del diario («(COMIENZA LA SESIÓN...»; en algunos la Z y la T salen en minúscula: «COMIENzA»)
CUERPO_RE = re.compile(r"^\s*(?:\((?:C ?OMIEN[Zz]A|S ?E ?REANUDA)\s+LA\s+SESI|(?:SR|SRA)\. PRESIDEN[Tt][EA]\s*(?:\(\d\))?\s*:)",
                       re.M)
RUIDO_RE = re.compile(r"^(?:D\.S\. del Parlamento de Navarra.*|Sesi[oó]n n[uú]m\..*|\d{1,3}|"
                      r"DIARIO DE SESIONES|DEL|PARLAMENTO DE NAVARRA)$")
PAG_RE = re.compile(r"\s*\(P[áa]gs?\.\s*[\d\sy,-]*\)")
# Cabecera de un punto del orden del día en el sumario (sin expediente hasta finales de 2022).
CABECERA_RE = re.compile(
    r"^(?:[a-e]\)\s*)?(?:Debate|Toma en consideraci[oó]n|Aprobaci[oó]n,? si procede|Elecci[oó]n|Designaci[oó]n|"
    r"Pregunta|Interpelaci[oó]n|Moci[oó]n|Proposici[oó]n|Proyecto|Propuestas?|Comparecencia|Declaraci[oó]n|"
    r"Convalidaci[oó]n|Dictamen|Informe|Sesi[oó]n|Juramento|Lectura|Toma de posesi[oó]n|Constituci[oó]n|"
    r"Comunicaci[oó]n|Presentaci[oó]n|Reprobaci[oó]n|Solicitud|Creaci[oó]n|Tramitaci[oó]n)\b")
SUBPUNTO_RE = re.compile(r"^[b-e]\)\s")

NUM = r"(\d+|una?|uno|ning[uú]n(?:o|a)?(?: voto)?|cero|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|(?:el )?resto)"
# (la lectura en euskera: «30 alde, 19 kontra», «baiezko botoak, 30; aurkakoak, 20; abstentzioak, 0»)
CONCEPTOS = {"a_favor": r"(?:(?:votos?\s+)?a\s+(?:votos?\s+)?favor|s[ií]es\b|(?:botoa?k?\s+)?alde\b|"
                        r"baiezko(?:\s+botoak)?)",
             "en_contra": r"(?:(?:votos?\s+)?en\s+con-?\s*tra|noes\b|(?:botoa?k?\s+)?kontra\b|aurka\b|ezezko\b|"
                          r"aurkako(?:ak|\s+botoak)?)",
             "abstenciones": r"(?:absten-?\s*ci(?:[oó]n|ones)|abstentzio(?:ak|a)?\b)"}
TRAS = r"(?!\s+(?:votos?\s+)?(?:a\s+favor|en\s+contra|abstenci|alde\b|kontra\b|aurka\b|abstentzio))"
ANTES_RE = {k: re.compile(r"\b" + NUM + r"\s+" + c, re.I) for k, c in CONCEPTOS.items()}
DESPUES_RE = {k: re.compile(c + r"\s*[,:]?\s*" + NUM + r"\b" + TRAS, re.I) for k, c in CONCEPTOS.items()}
CUENTA_RE = re.compile(r"\b(?:por|con(?: el resultado de)?|tras el resultado de)\s+\d+\s+(?:votos?\s+)?a\s+(?:votos?\s+)?favor"
                       r"|\bpor unanimidad\b|\bpor asentimiento\b", re.I)
RESULTADO_RE = re.compile(
    r"\b(?P<neg>no\s+(?:se\s+|ha\s+)?(?:aprueba|toma|convalida|prospera|obtiene|obtenido|supera|alcanza))"
    r"|\b(?P<rech>rechaz(?:a|an|ad[oa]s?)\b|derogad[oa]s?\b|deroga\b|decae\b|decaen\b|desestimad[oa]s?\b|"
    r"con el rechazo\b|baztertu\w*)"
    r"|\b(?P<apr>aprobad[oa]s?\b|aprueban?\b|convalidad[oa]s?\b|convalida\b|se\s+toman?\s+en\s+consideraci[oó]n|"
    r"tomad[oa]s?\s+en\s+consideraci[oó]n|C[aá]mara\s+toma\s+en\s+consideraci[oó]n|con la aprobaci[oó]n\b|"
    r"obtenido la confianza|otorga(?:da)? la confianza|se acuerda\b|"
    r"proclamad[oa]\b|elegid[oa]s?\b|designad[oa]s?\b|investid[oa]\b|ratificad[oa]s?\b|pr[oó]speran?\b|se modifica\b|"
    r"onetsi\w*|onartu\w*|onartzen da\b)", re.I)  # en euskera: baztertuta (rechazada), onetsi/onartu (aprobada)
MAYORIA_RE = re.compile(r"mayor[ií]a absoluta|mayor[ií]a cualificada|mayor[ií]a de (?:dos tercios|tres quintos)", re.I)
# orador de cada turno («SRA. SECRETARIA PRIMERA (Sra. Ibáñez Pérez):»); en algunos diarios la T sale en minúscula
TURNO_RE = re.compile(r"(?<![\w.])(?:SR|SRA)\.\s+([A-ZÁÉÍÓÚÑÜ][A-ZÁÉÍÓÚÑÜt .'-]*?)\s*:?\s*(?:\([^)]{0,80}\)\s*)?:\s")
LECTOR_RE = re.compile(r"SECRETARI[OA]|VICEPRESIDENT[EA]|PRESIDENT[EA]")
# traducción entre corchetes de la lectura en euskera: «[El resultado es: 24 votos a favor y 26 votos en contra]»
TRADUCCION_RE = re.compile(r"\[[^\]]{0,80}?[Ee]l resultado(?: de la votaci[oó]n)? es(?: el siguiente)?:?\s*([^\]]+)\]"
                           r"|\[Es el siguiente:?\s*([^\]]+)\]")
# tras la lectura, la Presidencia manda repetir la votación (empate o error): esa lectura no cuenta
REPETIDA_RE = re.compile(r"\brepet|\bempate|\bberdinketa|volvemos a votar|vuelta a votar|tercera votaci[oó]n|"
                         r"por (?:segunda|tercera) vez", re.I)
COMIENZA_RE = re.compile(r"comienza la votaci[oó]n|se inicia la votaci[oó]n|iniciamos la votaci[oó]n|"
                         r"comenzamos(?: con la votaci[oó]n| a votar)?\b|hasten gara|idazkari jauna", re.I)


def _plano(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _letras(s):
    return re.sub(r"[^a-z0-9]", "", _plano(s))


def _entero(s):
    if s is None:
        return None
    s = _plano(s).strip()
    if s.isdigit():
        return int(s)
    return NUMEROS.get(s.split()[0]) if s else None


def _totales(seg):
    """(a favor, en contra, abstenciones, «el resto») de un recuento en texto; None donde no se lee."""
    d, resto = {}, False
    for k in CONCEPTOS:
        m = ANTES_RE[k].search(seg) or DESPUES_RE[k].search(seg)
        if m and _plano(m.group(1)).endswith("resto"):
            resto = True
            d[k] = None
        else:
            d[k] = _entero(m.group(1)) if m else None
    if d["en_contra"] is None and re.search(r"aurkakorik ez|ning[uú]n voto en contra|sin votos? en contra", seg, re.I):
        d["en_contra"] = 0
    if d["abstenciones"] is None and re.search(r"abstentziorik ez|ninguna abstenci", seg, re.I):
        d["abstenciones"] = 0
    if d["a_favor"] is None:
        m = re.search(r"\bunanimidad,?\s*(\d+)\s+votos", seg, re.I)
        if m:
            d = {"a_favor": int(m.group(1)), "en_contra": 0, "abstenciones": 0}
    return d["a_favor"], d["en_contra"], d["abstenciones"], resto


# ---------------------------------------------------------------- listado

def _diarios(ctx, desde):
    """[(número, fecha, url)] de los diarios del Pleno, del más reciente al más antiguo, hasta `desde`."""
    primera = min(v[1] for v in LEGISLATURAS.values())
    vistos, pagina = set(), 0
    while True:
        h = ctx.texto(LISTADO.format(pagina=pagina))
        items = ITEM_LISTADO_RE.findall(h)
        for url, titulo, fecha in items:
            m = re.search(r"(\d+)\s*\.?\s*$", html.unescape(titulo))
            if not m or url in vistos:
                continue
            vistos.add(url)
            if fecha < primera or (desde and fecha < desde):
                return
            yield int(m.group(1)), fecha, url
        if not items or f"page={pagina + 1}" not in h:
            return
        pagina += 1


# ---------------------------------------------------------------- texto del diario

def _fecha(texto):
    m = FECHA_RE.search(texto[:3000])
    if not m or m.group(2).lower() not in MESES:
        return None
    return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"


def _partes(texto):
    """(sumario, cuerpo) del diario. El sumario va del rótulo «SUMARIO» (o, si el rótulo es una imagen, de
    «Comienza la sesión» o del final de la cabecera) al principio del cuerpo («(COMIENZA LA SESIÓN...»)."""
    f = CUERPO_RE.search(texto)
    fin = f.start() if f else len(texto)
    for rx in (SUMARIO_RE, INICIO_SUMARIO_RE, CABECERA_DIARIO_RE):  # siempre antes del cuerpo
        m = rx.search(texto, 0, fin)
        if m:
            return texto[m.start() if rx is INICIO_SUMARIO_RE else m.end():fin], texto[fin:]
    return "", texto[fin:]


def _lineas(fragmento):
    """Líneas útiles, sin cabeceras ni números de página, con las palabras partidas unidas."""
    out = []
    for ln in fragmento.replace("\f", "\n").splitlines():
        ln = ln.strip()
        if not ln or RUIDO_RE.match(ln):
            continue
        if out and out[-1].endswith("-") and re.match(r"[a-záéíóúñü]", ln):
            out[-1] = out[-1][:-1] + ln
            continue
        out.append(ln)
    return out


def _termina(linea):
    return bool(re.search(r"(?:[.:]|\(P[áa]gs?\.[^)]*\)\.?)$", linea)) and not re.search(
        r"\b(?:Sr|Sra|Sres|D|Dña|D\.ª|Ilmo|Ilma|Excmo|Excma|núm|art)\.$", linea)


def _frases(lineas):
    """Une las líneas del sumario en frases; cada frase empieza en una línea nueva."""
    out = []
    for ln in lineas:
        if out and not _termina(out[-1]) and not EXPEDIENTE_RE.match(ln) and not ln.startswith("— "):
            out[-1] += " " + ln
        else:
            out.append(ln)
    return out


def _limpia(t):
    t = PAG_RE.sub("", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def _titulo_autor(cabecera):
    """(título, autor) legibles de la cabecera de un punto del sumario."""
    t = _limpia(EXPEDIENTE_RE.sub("", cabecera)).rstrip(". ")
    autor = None
    # «Debate y votación de las enmiendas a la totalidad presentadas por X al proyecto de Ley Foral Y»: el título es Y
    m = re.search(r"enmiendas? a la totalidad\b.*?\b(?:al|a la) ((?:proyecto|proposici[oó]n) de [Ll]ey .+)$", t)
    if m:
        return m.group(1)[:1].upper() + m.group(1)[1:], None
    m = re.search(r",?\s+presentad[oa]s? por (?:el |la |los |las )?(.+)$", t)
    if m:
        autor = re.sub(r"^(?:Ilm[oa]s?\.|Excm[oa]s?\.)\s*(?:Sr[a]?\.|Sres\.)\s*(?:D\.ª|D\.|Dña\.)?\s*", "", m.group(1)).strip()
        t = t[:m.start()]
    t = re.sub(r"^[a-e]\)\s*", "", t)
    t2 = re.sub(r"^(?:Aprobaci[oó]n,? si procede,? de la tramitaci[oó]n directa y en lectura [uú]nica,?(?: y votaci[oó]n)?"
                r"(?: de| del)?|Debate y votaci[oó]n(?: del dictamen aprobado por la Comisi[oó]n de .+? en relaci[oó]n con)?"
                r"(?: de| del| sobre)?|Debate (?:sobre|de)(?: la)?(?: totalidad de)?|Toma en consideraci[oó]n,? si procediere,? de|"
                r"Debate de totalidad de)\s+(?:la |el |los |las )?", "", t, flags=re.I)
    if len(t2) > 15:
        t = t2[:1].upper() + t2[1:]
    return t.strip(" ,."), autor


def _puntos(frases):
    """[{expediente, cabecera, frases}] del sumario, en orden."""
    puntos, actual = [], None
    for f in frases:
        if f.startswith("— "):
            continue  # orden del día que se cuela cuando el rótulo del sumario es una imagen
        m = EXPEDIENTE_RE.match(f)
        if m:
            actual = {"expediente": m.group(1), "cabecera": f, "frases": []}
            puntos.append(actual)
            continue
        if SUBPUNTO_RE.match(f) and actual is not None and actual["cabecera"]:
            actual["frases"].append(f)  # «b) Aprobación...»: sigue el mismo punto
            continue
        if CABECERA_RE.match(f) and not CUENTA_RE.search(f):
            if any(p["cabecera"] and _letras(PAG_RE.sub("", p["cabecera"])) == _letras(PAG_RE.sub("", f)) for p in puntos):
                continue  # el mismo punto repetido en el sumario (debate que sigue tras otro punto)
            actual = {"expediente": None, "cabecera": f, "frases": []}
            puntos.append(actual)
            continue
        if actual is None:
            actual = {"expediente": None, "cabecera": None, "frases": []}
            puntos.append(actual)
        actual["frases"].append(f)
    return puntos


def _clausulas(frase):
    """Parte una frase del sumario en cláusulas con un resultado cada una («...; se rechaza el punto 2 por...»)."""
    t = _limpia(frase)
    partes = re.split(r";\s+|\.\s+(?=[A-ZÁÉÍÓÚ])|,\s+y\s+(?=(?:tambi[eé]n\s+)?(?:se\s+)?(?:aprueba|rechaza|queda))", t)
    out = []
    for p in partes:
        # dos recuentos en la misma cláusula («Los puntos 1 y 2 quedan aprobados por 48 votos a favor y 2 en contra,
        # y el punto 3 por 30...»): se parte en la última coma antes del segundo
        while True:
            cuentas = list(CUENTA_RE.finditer(p))
            if len(cuentas) < 2:
                break
            sep = r",\s+(?:y\s+)?|\s+y\s+(?=(?:tambi[eé]n\s+)?(?:el|la|los|las|se|quedan?)\s)"
            comas = [m.start() for m in re.finditer(sep, p[:cuentas[1].start()]) if m.start() >= cuentas[0].end()]
            if not comas:
                break
            out.append(p[:comas[-1]].strip())
            p = re.sub(r"^(?:" + sep + ")", "", p[comas[-1]:])
        out.append(p.strip())
    return [p for p in out if p]


def _resultado(texto, primero=False):
    """«aprobada» o «rechazada» según el último verbo de resultado antes del recuento (o el primero después);
    con `primero`, el primer verbo del texto (lo que proclama la Presidencia tras la lectura)."""
    if not texto:
        return None
    m = CUENTA_RE.search(texto)
    corte = 0 if primero else m.start() if m else len(texto)
    antes = list(RESULTADO_RE.finditer(texto[:corte]))
    r = antes[-1] if antes else RESULTADO_RE.search(texto, corte)
    if not r:
        return None
    return "rechazada" if r.group("neg") or r.group("rech") else "aprobada"


def _objeto(clausula):
    """Lo que se vota: la cláusula sin el recuento."""
    t = re.split(r"\s+(?:por|con(?: el resultado de)?|tras el resultado de)\s+(?:\d+\s+(?:votos?\s+)?a\s+(?:votos?\s+)?favor|"
                 r"unanimidad|asentimiento)", clausula, maxsplit=1, flags=re.I)[0]
    return t.strip(" ,.;")


def _votos_sumario(punto):
    """[dict] de las votaciones que el sumario da para un punto."""
    votos, contexto, autor = [], None, None
    for f in punto["frases"]:
        if not CUENTA_RE.search(f) or re.search(r"delegaci[oó]n de voto", f, re.I):
            continue
        previo = anterior = None
        for cl in _clausulas(f):
            cuenta = CUENTA_RE.search(cl)
            if cuenta and re.search(r"\bla Mesa\b|Junta de Portavoces", cl[:cuenta.start()]):
                continue  # lo que votó la Mesa o la Junta de Portavoces, no el Pleno
            if not cuenta:
                anterior = cl
                previo = _resultado(cl) or previo
                # «Se votan las propuestas de resolución del Grupo Parlamentario EH Bildu Nafarroa.»
                m = re.match(r"^(?:A continuaci[oó]n,?\s*)?Se votan? (?:las|los|la|el) (.{10,200}?)\.?$", cl)
                if m and not RESULTADO_RE.search(cl):
                    contexto = m.group(1)[:1].upper() + m.group(1)[1:]
                    g = re.search(r"\b(?:del|de la|presentad[oa]s por (?:el|la)) ((?:Grupo|Agrupaci[oó]n) .+)$", contexto)
                    autor = g.group(1) if g else None
                continue
            af, ec, ab, resto = _totales(cl)
            unan = bool(re.search(r"\bunanimidad\b", cl, re.I))
            asent = bool(re.search(r"\basentimiento\b", cl, re.I)) and af is None
            res = _resultado(cl) or previo or ("aprobada" if unan or asent else None)
            previo = res
            if af is None and not unan and not asent:
                continue
            objeto = _objeto(cl)
            if len(objeto) < 25:  # «Se aprueba por asentimiento»: lo votado está en la cláusula anterior
                if anterior:
                    objeto = f"{anterior.rstrip('. ')}: {objeto}"
                elif re.search(r"(?:,\s*y|\sy)$", objeto):  # «Efectuado el escrutinio, y»: la cláusula entera
                    objeto = cl.rstrip(". ")
            anterior = None
            votos.append({"texto": cl, "objeto": f"{contexto}: {objeto}" if contexto else objeto, "a_favor": af,
                          "en_contra": ec, "abstenciones": ab, "resto": resto, "unanimidad": unan,
                          "asentimiento": asent, "resultado": res, "autor_votacion": autor})
    return votos


# ---------------------------------------------------------------- cuerpo: lecturas de la Secretaría

def _turnos(cuerpo):
    """[(posición, orador, texto)] del cuerpo del diario, con el texto ya unido en una línea."""
    texto = " ".join(_lineas(cuerpo))
    marcas = list(TURNO_RE.finditer(texto))
    fines = [m.start() for m in marcas[1:]] + [len(texto)]
    return texto, [(m.start(), m.group(1).strip().upper(), texto[m.end():fin]) for m, fin in zip(marcas, fines)]


def _anuncio(turnos, i):
    """Lo que anuncia la Presidencia antes de la lectura i: la última frase antes de «comienza la votación»."""
    for k in range(i - 1, max(i - 25, -1), -1):  # con voto delegado, la Presidencia pregunta a cada portavoz
        orador, t = turnos[k][1], turnos[k][2]
        if "PRESIDENT" not in orador or len(t) < 40:
            continue
        m = list(COMIENZA_RE.finditer(t))
        if m:  # cortar en la primera de las fórmulas del final («Comenzamos con la votación (PAUSA). Idazkari jauna...»)
            n = len(m) - 1
            while n > 0 and m[n].start() - m[n - 1].end() < 40:
                n -= 1
            t = t[:m[n].start()]
        t = re.sub(r"\((?:PAUSA|MURMULLOS|RUMORES)[^)]*\)\.?", " ", t)
        t = re.sub(r"\s*(?:Señorías,?|Por (?:lo )?tanto,?|Bien\.)\s*$", "", t.strip(" .,")).strip(" .,")
        if len(t) < 15 or (len(t) < 70 and re.search(r"resultado|emaitza", t, re.I)) or \
                (len(t) < 160 and re.search(r"¿\s*(?:voto|votaci[oó]n|sentido)", t, re.I)):
            continue  # solo la fórmula de inicio o la petición del resultado: lo anunciado está en un turno anterior
        frases = re.split(r"(?<=[.?!])\s+(?=[A-ZÁÉÍÓÚ¿])", t)
        out = ""
        for fr in reversed(frases):
            out = (fr + " " + out).strip()
            if len(out) > 60 or (len(out) > 35 and re.search(r"vot", fr, re.I)):
                break
        out = re.sub(r"\s{2,}", " ", out).strip()
        if len(out) > 350:
            out = "…" + out[-350:]
        return out or None
    return None


def _lecturas(cuerpo):
    """[dict] de las lecturas del recuento en el cuerpo, en orden, con su posición en el texto unido."""
    texto, turnos = _turnos(cuerpo)
    out = []
    for i, (pos, orador, t) in enumerate(turnos):
        m = TRADUCCION_RE.search(t[:600])
        seg = (m.group(1) or m.group(2)) if m else t[:220]
        if not LECTOR_RE.search(orador) and not m:
            continue
        cabeza = seg[:60]
        if not re.search(r"\d+\s+(?:votos?\s+)?a\s+favor|a\s+favor,?\s*\d+|unanimidad,?\s*\d+|\d+\s+(?:botoa?k?\s+)?alde\b|\d+\s+s[ií]es\b|"
                         r"baiezko botoak,?\s*\d+", cabeza, re.I):
            continue
        seg = re.split(r"(?<=[a-z\d\]])\.\s", seg, maxsplit=1)[0]
        af, ec, ab, resto = _totales(seg)
        if af is None:
            continue
        if "PRESIDENT" in orador and out and out[-1]["turno"] == i - 1 and \
                (out[-1]["a_favor"], out[-1]["en_contra"], out[-1]["abstenciones"]) == (af, ec, ab):
            continue  # la Presidencia repite el recuento que acaba de leer la Secretaría
        siguiente = next((x[2] for x in turnos[i + 1:i + 3] if "PRESIDENT" in x[1]), "")
        # la Presidencia corrige la lectura: «Creo que es al revés, 24 votos en contra, 23 a favor...»
        correccion = re.match(r".{0,80}?(?:al rev[eé]s|perd[oó]n|corrijo|rectific)[^.]{0,20}?[,:]?\s*(\d+\s+(?:votos?\s+)?"
                              r"(?:a favor|en contra)[^.]{0,80})", siguiente, re.I)
        if correccion and _totales(correccion.group(1))[0] is not None:
            seg = correccion.group(1)
            af, ec, ab, resto = _totales(seg)
        despues = t[len(seg):] if "PRESIDENT" in orador else ""
        res_txt = re.sub(r"^\s*\d+\s+votos a favor[^.]*\.\s*", "", despues + " " + siguiente)[:300]
        res = _resultado(res_txt, primero=True)
        out.append({"pos": pos, "turno": i, "a_favor": af, "en_contra": ec, "abstenciones": ab, "resto": resto,
                    "texto": seg.strip(), "anuncio": _anuncio(turnos, i), "resultado": res,
                    "repetida": res is None and bool(REPETIDA_RE.search(res_txt[:200])),
                    "resultado_texto": res_txt.strip()[:200]})
    return texto, out


def _posiciones(puntos, texto):
    """Posición de la cabecera de cada punto del sumario en el cuerpo (None si no se encuentra)."""
    letras, mapa = [], []
    for i, c in enumerate(_plano(texto)):
        if c.isalnum():
            letras.append(c)
            mapa.append(i)
    letras = "".join(letras)
    out, desde = [], 0
    for p in puntos:
        pos = None
        if p["cabecera"]:
            if p["expediente"]:
                claves = [_letras(p["expediente"])]
            else:  # sin expediente, por el texto de la cabecera (largo: muchas empiezan igual)
                texto_cab = _letras(PAG_RE.sub("", p["cabecera"]))
                claves = [texto_cab[:n] for n in (220, 150, 90) if len(texto_cab) >= min(n, 40)]
            for clave in claves:
                k = letras.find(clave, desde) if len(clave) >= 12 else -1
                if k >= 0:
                    pos, desde = mapa[k], k + 1
                    break
        out.append(pos)
    return out


def _compatible(v, lec):
    if v["a_favor"] is None:
        return v["unanimidad"] and not lec["en_contra"] and not lec["abstenciones"]
    if v["a_favor"] != lec["a_favor"]:
        return False
    # lo que el sumario no dice («por 47 votos a favor») o deja en «el resto» vale lo que se lea, y al revés
    return all(v[k] is None or (lec[k] is None and lec["resto"]) or v[k] == (lec[k] or 0)
               for k in ("en_contra", "abstenciones"))


def _parecidas(v, lec):
    """¿La misma votación con un total mal transcrito? (coinciden al menos dos de los tres totales)."""
    if v["a_favor"] is None:
        return False
    return sum((v[k] or 0) == (lec[k] or 0) for k in ("a_favor", "en_contra", "abstenciones")) >= 2


def _alinear(votos, lecturas, dentro, permitido):
    """Pares (i, j) de la alineación en orden de mayor puntuación entre votaciones del sumario y lecturas del
    cuerpo: un punto por pareja compatible (y `permitido(i, j)`: la lectura no cae lejos del tramo de su punto)
    y una centésima más si cae dentro del tramo (`dentro(i, j)`), para deshacer empates entre recuentos
    repetidos («20 a favor, 30 en contra»)."""
    n, m = len(votos), len(lecturas)
    ok = [[_compatible(votos[i], lecturas[j]) and permitido(i, j) for j in range(m)] for i in range(n)]
    mejor = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            op = max(mejor[i + 1][j], mejor[i][j + 1])
            if ok[i][j]:
                op = max(op, 1 + (0.01 if dentro(i, j) else 0) + mejor[i + 1][j + 1])
            mejor[i][j] = op
    pares, i, j = [], 0, 0
    while i < n and j < m:
        if ok[i][j] and abs(mejor[i][j] - (1 + (0.01 if dentro(i, j) else 0) + mejor[i + 1][j + 1])) < 1e-9:
            pares.append((i, j))
            i, j = i + 1, j + 1
        elif abs(mejor[i][j] - mejor[i + 1][j]) < 1e-9:
            i += 1
        else:
            j += 1
    return pares


def _de_lectura(lec, v=None):
    """Votación sacada de una lectura del cuerpo (con los textos del sumario si casó con una)."""
    d = {"texto": v["texto"] if v else lec["texto"], "objeto": v["objeto"] if v else lec["anuncio"],
         "a_favor": lec["a_favor"], "en_contra": lec["en_contra"], "abstenciones": lec["abstenciones"],
         "resto": lec["resto"], "unanimidad": bool(v and v["unanimidad"]), "asentimiento": False,
         "resultado": (v["resultado"] if v else None) or lec["resultado"], "verificada": v is not None,
         "autor_votacion": v.get("autor_votacion") if v else None, "conjunto": v.get("conjunto") if v else None}
    if v and v["a_favor"] is None:
        d["totales_de_lectura"] = True
    if not v:
        d["de_cuerpo"] = True
        d["repetida"] = lec["repetida"]
        d["lectura"] = lec["texto"]
        d["proclamacion"] = lec["resultado_texto"]
    return d


def _analizar(texto):
    """(fecha, [dict] de votaciones) de un diario en texto; cada dict lleva los datos del punto.

    Las votaciones del sumario y las lecturas del cuerpo se alinean en orden. Las parejas quedan verificadas;
    una lectura sin pareja se añade si cae entre dos lecturas casadas con votaciones del mismo punto (el
    sumario resumió varias votaciones en una frase) o si está en el tramo de un punto del que el sumario no
    da ninguna votación con pareja; las votaciones repetidas (empate, error) no se añaden."""
    sumario, cuerpo = _partes(texto)
    puntos = _puntos(_frases(_lineas(sumario)))
    unido, lecturas = _lecturas(cuerpo)
    posiciones = _posiciones(puntos, unido)
    tramos = []  # (inicio, fin) del tramo de cada punto en el cuerpo
    for k, ini in enumerate(posiciones):
        fin = next((p for p in posiciones[k + 1:] if p is not None), len(unido) + 1)
        tramos.append((ini, fin) if ini is not None else None)

    def punto_de(pos):
        return next((k for k, t in enumerate(tramos) if t and t[0] <= pos < t[1]), None)

    def cerca(k, pos, margen=3000):
        """¿La lectura cae en el tramo del punto k (con margen: la maquetación a veces pone la cabecera del
        punto siguiente antes que la última lectura del anterior)? Sin tramo conocido, vale cualquiera."""
        return tramos[k] is None or tramos[k][0] - margen <= pos < tramos[k][1] + margen

    sv = [(k, v) for k, p in enumerate(puntos) for v in _votos_sumario(p)]
    # debate conjunto: varias cabeceras seguidas, sin nada entre ellas, y las votaciones tras la última; si hay una
    # votación por punto se reparten en orden, y si no, cada una lleva los títulos de todos (`debate_conjunto`)
    k = 0
    while k < len(puntos):
        j = k
        while j + 1 < len(puntos) and puntos[j]["cabecera"] and not puntos[j]["frases"] and puntos[j + 1]["cabecera"]:
            j += 1
        if j > k:
            grupo = list(range(k, j + 1))
            idx = [i for i, (kk, _) in enumerate(sv) if kk == j]
            if len(idx) == len(grupo):
                for i, kk in zip(idx, grupo):
                    sv[i] = (kk, sv[i][1])
            else:
                for i in idx:
                    sv[i][1]["conjunto"] = grupo
        k = j + 1
    pares = _alinear([v for _, v in sv], lecturas, lambda i, j: punto_de(lecturas[j]["pos"]) == sv[i][0],
                     lambda i, j: cerca(sv[i][0], lecturas[j]["pos"]))
    entradas = []  # (punto, clave de orden, votación)
    for i, j in pares:
        entradas.append((sv[i][0], j, _de_lectura(lecturas[j], sv[i][1])))
    con_pareja = {sv[i][0] for i, _ in pares}
    # huecos entre parejas: votaciones del sumario y lecturas sin pareja
    limites = [(-1, -1)] + pares + [(len(sv), len(lecturas))]
    for (i0, j0), (i1, j1) in zip(limites, limites[1:]):
        s_hueco = list(range(i0 + 1, i1))
        # las del sumario sin totales (asentimiento, unanimidad sin recuento) no impiden añadir lecturas
        s_duras = [i for i in s_hueco if sv[i][1]["a_favor"] is not None]
        l_hueco = [j for j in range(j0 + 1, j1) if not lecturas[j]["repetida"]]
        k_i = sv[i0][0] if i0 >= 0 else -1
        k_d = sv[i1][0] if i1 < len(sv) else len(puntos)
        if s_duras and len(s_duras) == len(l_hueco) and                 all(_parecidas(sv[i][1], lecturas[j]) for i, j in zip(s_duras, l_hueco)):
            # tantas como votaciones: la misma votación con los totales transcritos distinto en el sumario y en
            # la lectura; manda la lectura y el sumario queda en extra
            for i in s_hueco:
                if i not in s_duras:
                    entradas.append((sv[i][0], j0 + 0.5 + i * 1e-4, sv[i][1]))
            for i, j in zip(s_duras, l_hueco):
                d = _de_lectura(lecturas[j], sv[i][1])
                d["verificada"] = False
                v = sv[i][1]
                d["discrepancia"] = f"sumario {v['a_favor']}-{v['en_contra']}-{v['abstenciones']}"
                entradas.append((sv[i][0], j, d))
            continue
        for i in s_hueco:  # votación del sumario sin lectura, detrás de la última lectura casada
            entradas.append((sv[i][0], j0 + 0.5 + i * 1e-4, sv[i][1]))
        if s_duras:
            continue  # no se sabe qué lectura corresponde a qué votación: vale el sumario
        for j in l_hueco:  # lecturas que el sumario resume en una frase (presupuestos, leyes) o no detalla
            if k_i == k_d:
                k = k_i
            else:
                kp = punto_de(lecturas[j]["pos"])
                k = kp if kp is not None and k_i <= kp <= k_d and (kp not in con_pareja or kp in (k_i, k_d)) else None
            if k is not None:
                entradas.append((k, j, _de_lectura(lecturas[j])))
    votos = []
    for k, _clave, v in sorted(entradas, key=lambda e: (e[0], e[1])):
        p = puntos[k]
        titulo, autor = _titulo_autor(p["cabecera"]) if p["cabecera"] else (None, None)
        expediente = p["expediente"]
        if v.get("conjunto"):
            fichas = [_titulo_autor(puntos[i]["cabecera"]) for i in v["conjunto"]]
            v["debate_conjunto"] = [t for t, _a in fichas]
            titulo = " / ".join(t for t, _a in fichas)
            autores = {a for _t, a in fichas}
            autor = autores.pop() if len(autores) == 1 else None
            expedientes = {puntos[i]["expediente"] for i in v["conjunto"]}
            expediente = expedientes.pop() if len(expedientes) == 1 else None
        v.update(expediente=expediente, titulo=titulo, autor=v.get("autor_votacion") or autor)
        votos.append(v)
    return _fecha(texto), votos


# ---------------------------------------------------------------- votaciones

OBJETO_RE = re.compile(r"(?:votamos|votaremos|votar|votaci[oó]n de|se votan?|se aprueban?|se rechazan?|quedan? aprobad[oa]s?|"
                       r"quedan? rechazad[oa]s?)\s+(?:a continuaci[oó]n,?\s*|conjuntamente\s*|ahora\s*|"
                       r"en (?:primer|segundo|[uú]ltimo) lugar,?\s*|finalmente,?\s*)?(?:el |la |los |las )?"
                       r"(en?miendas?|votos? particular(?:es)?|texto articulado|articulado|art[ií]culos?|disposici|exposici|"
                       r"t[ií]tulo|partidas?|secci)")


def _tipo_votacion(tipo, texto, titulo):
    t = (texto or "").lower()
    ti = (titulo or "").lower()
    if re.search(r"investidura|la confianza|candidat[oa] a la presidencia|moci[oó]n de censura", t + " " + ti):
        return "investidura"
    if re.search(r"tramitaci[oó]n directa|lectura [uú]nica|procedimiento de urgencia|tramitad[oa] como proyecto", t):
        return "tramitacion_ley" if "tramitad" in t and "decreto" in t else "organizacion"
    if "toma en consideraci" in t:
        return "toma_consideracion"
    if "totalidad" in t:
        return "totalidad"
    if re.search(r"convalid|derogaci", t) or (tipo == "dl" and not re.search(r"enmienda|art[ií]culo", t)):
        return "convalidacion"
    # lo que se vota según el verbo manda sobre lo que se mencione después («el texto articulado ... con la
    # incorporación de las enmiendas aprobadas»)
    m = OBJETO_RE.search(t)
    if m:
        obj = m.group(1)
        if obj.startswith(("enmienda", "emienda", "voto")):
            return "enmiendas"
        if obj.startswith(("texto articulado", "articulado", "art", "disposici", "exposici", "partida", "secci", "t")):
            return "articulado"
    if re.search(r"en?mienda|zuzenketa|voto particular|votos particulares", t) and not re.search(
            r"con (?:la |las )?(?:incorporaci[oó]n de (?:la |las )?)?enmiendas?", t):
        return "enmiendas"
    if re.search(r"\bart[ií]culos?\b|articulado|disposici[oó]n|exposici[oó]n de motivos|\bsecci[oó]n|anexo|partidas", t):
        return "articulado"
    if re.search(r"elecci[oó]n|designaci[oó]n|nombramiento|elegid", t + " " + ti):
        return "nombramiento"
    if re.search(r"propuestas? (?:de )?resoluci[oó]n", t + " " + ti) or tipo == "control":
        return "control"
    if tipo in ("pl", "ppl", "presupuesto") and re.search(r"\bley foral\b|\bproyecto\b|\bproposici[oó]n\b|conjunto", t):
        return "conjunto"
    if tipo == "mocion":
        return "mocion"
    return None


def _tipo_iniciativa(exp, titulo):
    t = (titulo or "").lower()
    if "presupuestos generales" in t and (not exp or "/LEY-" in exp):
        return "presupuesto"
    if exp:
        return TIPOS.get(exp.split("/")[1].split("-")[0], "otro")
    for patron, tipo in (("moci", "mocion"), ("proyecto de ley", "pl"), ("proposici", "ppl"), ("decreto", "dl"),
                         ("investidura", "investidura"), ("propuesta de resoluci", "control"),
                         ("comunicaci", "control"), ("debate", "control"), ("análisis", "control"), ("elecci", "organizacion"),
                         ("designaci", "organizacion"),
                         ("propuesta de reforma", "ppl"), ("dictamen", "acuerdo")):
        if t.startswith(patron):
            return tipo
    return None


def _votacion(leg, num, fecha, url, n, v):
    exp = v["expediente"]
    objeto = v.get("objeto")
    titulo = v["titulo"] or objeto or v["texto"]
    tipo = _tipo_iniciativa(exp, titulo)
    af, ec, ab = v["a_favor"], v["en_contra"], v["abstenciones"]
    extra = {"texto": v["texto"]}
    for k in ("verificada", "totales_de_lectura", "de_cuerpo", "lectura", "proclamacion", "resto", "discrepancia",
              "debate_conjunto"):
        if v.get(k):
            extra[k] = v[k]
    if af is not None and not v["resto"]:
        ec = 0 if ec is None else ec
        ab = 0 if ab is None else ab
    res = v["resultado"]
    contexto = " ".join(x for x in (v["texto"], objeto or "") if x)
    # la investidura en primera votación y algunas leyes forales piden mayoría absoluta
    cualificada = MAYORIA_RE.search(contexto) or re.search(r"investidura|la confianza|candidat", contexto + " " + titulo, re.I)
    if res and af is not None and ec is not None:
        if (res == "aprobada") != (af > ec) and not cualificada:
            extra["resultado_texto"] = res
            res = None
    if af is not None and sum(x or 0 for x in (af, ec, ab)) > CUERPOS[0].escanos_de(leg):
        extra["totales_descartados"] = f"{af}-{ec}-{ab}"
        af = ec = ab = None
    return Votacion(
        cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=num, numero=n, legislatura=leg,
        subtitulo=objeto if objeto and objeto != titulo else None, expediente=exp, tipo_iniciativa=tipo,
        tipo_votacion=_tipo_votacion(tipo, contexto, titulo), autor=v["autor"],
        a_favor=af, en_contra=ec, abstenciones=ab, asentimiento=v["asentimiento"],
        resultado="aprobada" if v["asentimiento"] else res,
        mayoria="absoluta" if re.search(r"mayor[ií]a absoluta", contexto, re.I) else None,
        url=url, fuente="pdf-reglas", extra=extra)


def _texto_diario(ctx, url):
    pdf = ctx.fetch(url, cache=f"{CUERPO}/diarios/{url.rsplit('/', 1)[1]}", timeout=120)
    if pdf[:5] != b"%PDF-":
        raise RuntimeError(f"{CUERPO}: no es un PDF: {url}")
    return ctx.pdf_texto(pdf, raw=True)


_ANALISIS = {}  # url -> (fecha, votaciones, ¿se vota?): descargar() y documentos() leen los mismos diarios
VOTACION_EN_CUERPO_RE = re.compile(r"comienza la votaci[oó]n|comenzamos con la votaci[oó]n|se inicia la votaci[oó]n|"
                                   r"iniciamos la votaci[oó]n|bozketaren emaitza (?:hauxe|honako hau|hurrengoa)", re.I)


def _analisis(ctx, url):
    if url not in _ANALISIS:
        texto = _texto_diario(ctx, url)
        fecha, votos = _analizar(texto)
        _ANALISIS[url] = (fecha, votos, bool(VOTACION_EN_CUERPO_RE.search(_partes(texto)[1])))
    return _ANALISIS[url]


def descargar(ctx):
    desde = ctx.desde(CUERPO, margen_dias=60)  # los diarios salen con semanas de retraso
    n_total, iniciativas = 0, set()
    for num, fecha_listado, url in _diarios(ctx, desde):
        fecha, votos, _ = _analisis(ctx, url)
        fecha = fecha or fecha_listado
        leg = CUERPOS[0].legislatura_de(fecha)
        if leg is None:
            continue
        for n, v in enumerate(votos, 1):
            exp = v["expediente"]
            if exp and exp not in iniciativas and v["titulo"]:
                iniciativas.add(exp)
                yield Iniciativa(CUERPO, exp, v["titulo"], legislatura=leg, tipo_iniciativa=_tipo_iniciativa(exp, v["titulo"]),
                                 autor=v["autor"], url=FICHA.format(clave=exp.replace("/", "").lower()))
            vo = _votacion(leg, num, fecha, url, n, v)
            if vo.resultado is None and vo.a_favor is None and not vo.asentimiento:
                ctx.log(f"  {CUERPO}: diario {num} ({fecha}), votación {n} sin resultado ni totales: {v['texto'][:120]}")
                continue
            yield vo
            n_total += 1
            if ctx.limite and n_total >= ctx.limite:
                return


def documentos(ctx):
    """Diarios del Pleno en los que se vota («comienza la votación») pero las reglas no leen ninguna votación:
    para el LLM."""
    desde = ctx.desde(CUERPO, margen_dias=60)
    n = 0
    for num, fecha_listado, url in _diarios(ctx, desde):
        fecha, votos, se_vota = _analisis(ctx, url)
        if votos or not se_vota:
            continue
        fecha = fecha or fecha_listado
        leg = CUERPOS[0].legislatura_de(fecha)
        if leg is None:
            continue
        yield Documento(cuerpo=CUERPO, fecha=fecha, url=url, sesion=num, formato="pdf", idioma="es",
                        titulo=f"Diario de Sesiones del Parlamento de Navarra, Pleno núm. {num} "
                               f"({LEGISLATURAS[leg][0]} legislatura)", legislatura=leg)
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    return _texto_diario(ctx, doc.url)
