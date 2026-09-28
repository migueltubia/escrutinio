"""Ayuntamiento de Alicante: votaciones del Pleno sacadas con reglas de las actas en PDF.

Fuente: consulta de sesiones del Pleno de la Secretaría General del Pleno,
https://w3.alicante.es/ayuntamiento/plenos/

- Listado por año (`?anyo=AAAA`, desde 1999): una ficha por sesión con su carácter (ordinaria,
  extraordinaria, extraordinaria y urgente, especial, constitutiva) y enlaces al extracto
  (`extracto.php?fecha=DD/MM/AAAA&sesion=N`), al orden del día (`descarga-documento.php?tipo=1&…`)
  y al acta (`descarga-documento.php?tipo=2&…`). El parámetro `sesion` es el código del carácter
  (1 ordinaria, 2 extraordinaria, 3 extraordinaria y urgente, 4 especial, 5 constitutiva): la
  fecha y ese código identifican la sesión.
- El acta (PDF con texto) trae cada punto con su epígrafe («I-2.1. DEROGACIÓN DE LA ORDENANZA…»,
  hasta 2004 «1.1.» o «1.-») y el voto por grupo en una frase muy regular: «El Pleno del
  Ayuntamiento, por mayoría – 25 votos a favor (GP, GS y GV), 1 voto en contra (GEUP) y 2
  abstenciones (GC) –, adopta los siguientes ACUERDOS» o «Sometida la Moción a votación, es
  RECHAZADA, por mayoría de 17 votos en contra (GP y GV) y 11 votos a favor (GS, GC y GEUP)». Hasta
  2004 los números van a menudo en letra («por quince votos a favor (GP) y doce abstenciones…»).
- El extracto (HTML) lista los puntos con su título en minúsculas y, desde 2005, el resultado
  («Aprobado.», «Rechazada.», «Enterado.»). Se usa para el título y, si el acta aún no está
  publicada (se publica cuando la aprueba el pleno siguiente) o no se encuentra la votación en
  ella, para dar al menos el resultado (fuente «html»).

Cobertura: desde el pleno constitutivo del 3 de julio de 1999 (mandato VI) hasta hoy.

Lo que se saca de cada punto votado (fuente «pdf-reglas»): título (el del extracto si coincide con
el del acta; si no, el epígrafe del acta, en mayúsculas), resultado, totales (a favor, en contra,
abstenciones), sentido de cada grupo y su número de votos cuando es el único grupo citado en ese
sentido. Unanimidad sin recuento: resultado «aprobada» y asentimiento, sin totales ni grupos (el
acta no los da). Los grupos van con su nombre completo (las actas usan siglas: GP, GS, GC, GC's,
GEUP…); los concejales citados por su nombre se asignan a su grupo con la lista de asistentes del
acta (los no adscritos van como «Concejales no adscritos»). Tipo de iniciativa por el título y el
apartado del orden del día (mociones y declaraciones institucionales de los grupos, con su autor).
Si un punto se vota por partes («PRIMERO: es APROBADO…», «1. Sometido a votación…», «2ª …»), sale
una votación por parte con su subtítulo.

Claves: `sesion` es AAAAMMDD * 10 + código del carácter (algún día hay dos sesiones). `numero` sale
del código del punto (I-2.1 → 1020100; 1.12 → 1120000; 14.3 → 14030000; las votaciones por partes,
+1, +2…; un código repetido por errata del acta, +50), así que ordena como el orden del día y es el
mismo tanto si la votación sale del acta como del extracto: al publicarse el acta, su votación
sustituye a la del extracto.

Recogida incremental: se repasan las sesiones desde `ctx.desde` menos 120 días (el acta llega
cuando la aprueba el pleno siguiente). Actas y extractos de sesiones pasadas quedan en caché; los
listados por año caducan en un día (los dos últimos años) o en 30.

Limitaciones:
- Solo se recoge la votación principal de cada punto. Las previas (urgencia, ratificación de la
  inclusión en el orden del día, enmiendas, retirada) no se guardan.
- Si los totales de una frase suman más que los concejales o repiten sentido (erratas del acta como
  «15 votos en contra (GP) y 14 votos a favor (GS) y 14 abstenciones (GS)»), se descartan totales y
  grupos y queda solo el resultado (extra["aviso"]).
- Un concejal ausente cuenta como abstención (art. 113.2 ROP) y el acta lo cita aparte: su grupo
  sale entonces como «dividido».
- Los votos de concejales citados por su nombre que no están en la lista de asistentes (algunas
  actas de 2003 no la dividen por grupos) cuentan en los totales pero no en los grupos.
- Las sesiones sin acta publicada solo tienen el resultado del extracto (fuente «html»), que antes
  de 2005 no lo trae.
- Los títulos de las actas anteriores a 2005 sin extracto quedan en mayúsculas, como en el acta.
"""

import re
import unicodedata
from collections import Counter
from datetime import date, timedelta
from html import unescape
from urllib.error import HTTPError

from ...territorio import MANDATOS_LOCALES, Cuerpo, num_municipio
from ..contexto import CACHE_DIR, ErrorDescarga
from ..modelo import Documento, Votacion, VotoGrupo

WEB = "https://w3.alicante.es/ayuntamiento/plenos/"
CUERPO = "ayto-alicante"
PRIMER_ANYO = 1999
MARGEN_DIAS = 120  # repaso hacia atrás en la recogida incremental (ver _sesiones)

# Mandatos anteriores a 2011 (fecha del pleno constitutivo). Hasta 2007 Alicante tenía 27
# concejales; desde entonces, 29.
LEGISLATURAS = {
    6: ("VI", "1999-07-03", "2003-06-14", 27),
    7: ("VII", "2003-06-14", "2007-06-16", 27),
    8: ("VIII", "2007-06-16", "2011-06-11"),
    **MANDATOS_LOCALES,
}

CUERPOS = [
    Cuerpo(CUERPO, num_municipio("03014"), "Ayuntamiento de Alicante", "Ayto. Alicante", "municipal", "VC", 29,
           LEGISLATURAS, WEB),
]

NOTAS = __doc__

CARACTER = {1: "ordinaria", 2: "extraordinaria", 3: "extraordinaria y urgente", 4: "especial", 5: "constitutiva"}

# Siglas que usan las actas -> nombre del grupo (el que se reconoce luego en territorial/partidos.py).
GRUPOS = {
    "GP": "Grupo Popular",
    "GPP": "Grupo Popular",
    "GS": "Grupo Socialista",
    "GSOE": "Grupo Socialista",
    "GPSOE": "Grupo Socialista",
    "GV": "Grupo Vox",
    "GC": "Grupo Compromís",
    "GCS": "Grupo Ciudadanos",
    "GCIUDADANOS": "Grupo Ciudadanos",
    "GEUP": "Grupo Esquerra Unida Podem",
    "GEU": "Grupo Esquerra Unida",
    "GEUPV": "Grupo Esquerra Unida",
    "GEULENTESA": "Grupo Esquerra Unida",
    "GEUUP": "Grupo Esquerra Unida",
    "GUP": "Grupo Unides Podem",
    "GUPEUPV": "Grupo Unides Podem",
    "GUPYD": "Grupo Unión Progreso y Democracia",
    "GGA": "Grupo Guanyar Alacant",
    "GG": "Grupo Guanyar Alacant",
    "GM": "Grupo Mixto",
    "GEM": "Grupo Mixto",
    "CGS": "Grupo Ciudadanos",  # errata frecuente de GC's
    "CS": "Grupo Ciudadanos",
    "NA": "Concejales no adscritos",
}
NO_ADSCRITOS = "Concejales no adscritos"

NUMEROS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
    "dieciséis": 16, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
    "veintiuno": 21, "veintiún": 21, "veintiuna": 21, "veintidós": 22, "veintidos": 22, "veintitrés": 23,
    "veintitres": 23, "veinticuatro": 24, "veinticinco": 25, "veintiséis": 26, "veintiseis": 26,
    "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "ninguno": 0, "ninguna": 0,
}
_NUM = r"(?:\d{1,2}|" + "|".join(sorted(NUMEROS, key=len, reverse=True)) + r")"
_PAREN = r"\((?:[^()]|\([^()]*\))*\)"
# «25 votos a favor (GP, GS y GV)», «una abstención (GEU)», «doce en contra (GSOE y GEUPV)»
TROZO_RE = re.compile(
    rf"(?<![\w.,])(?P<n>{_NUM})\s+(?:votos?\s+)?(?P<s>(?:en\s+)?a\s+favor|favorables?|(?:a\s+)?en\s+contra|abstenci[oó]n(?:es)?)\b"
    rf"(?:\s+de\s+la\s+propuesta)?\s*,?\s*(?P<g>{_PAREN}(?:\s*,?\s*(?:y\s+)?{_PAREN})*)?", re.I)
# Al revés (hacia 2003): «votos a favor 15 (GP y GM) y votos en contra 10 (GS y GEU)»
TROZO_INV_RE = re.compile(
    rf"\b(?:votos?\s+)?(?P<s>a\s+favor|en\s+contra|abstenci[oó]n(?:es)?)\s+(?P<n>{_NUM})\b(?!\s*(?:votos?\b|%|de\b))"
    rf"\s*(?P<g>{_PAREN}(?:\s*,?\s*(?:y\s+)?{_PAREN})*)?", re.I)
# En forma de lista (hacia 2002): «− A favor: 15 votos (GP). − En contra: 10 votos (GS y GM). − Abstención: 1 (GEU-PV).»
TROZO_LISTA_RE = re.compile(
    rf"(?P<s>\ba\s+favor(?:\s+de\s+la\s+propuesta)?|\ben\s+contra|\babstenci[oó]n(?:es)?)\s*:\s*(?P<n>{_NUM})\b\s*(?:votos?\b)?"
    rf"\s*(?P<g>{_PAREN}(?:\s*,?\s*(?:y\s+)?{_PAREN})*)?", re.I)

# Epígrafe de un punto: «I-2.1. TÍTULO», «II-5.2. …», «1.12. TÍTULO», «1.- TÍTULO», «14. 1.- …», «1.9 TÍTULO»
EPIGRAFE_RE = re.compile(
    r"^(?:(?P<rom>I{1,3}|IV|V)\s?[-–]\s?)?(?P<num>\d{1,2}(?:\s?\.\s?\d{1,2}){0,3})"
    r"\s?(?P<sep>\.\s?[-–]|\.|[-–]|(?=\s))\s*(?P<tit>[A-ZÁÉÍÓÚÑÜ¿¡“\"«(].*)$")
ROMANOS = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
MARCAS = ("DEBATE", "VOTACIÓN Y ACUERDOS", "VOTACION Y ACUERDOS", "ACUERDOS", "VOTACIÓN", "INTERVENCIONES")
MARCA_RE = re.compile(r"\bVOTACI(?:ÓN|ON|ONES)\b([^:\n.]{0,100})[:.]")

DECISION_RE = re.compile(
    r"\b(?:adopta|adoptan|acuerda|acuerdan|aprueba|aprobad[oa]s?|rechazad[oa]s?|rechaza|obtiene|ratifica|"
    r"declara|se\s+acepta|se\s+admite|admite|da\s+su\s+aprobaci[oó]n|sometid[oa]s?\s+a\s+votaci[oó]n|"
    r"sometid[oa]s?\s+(?:el|la|los|las|dich[oa]s?)\b[^.]{0,120}\ba\s+votaci[oó]n|se\s+vota\b|se\s+votan\b|"
    r"siguiente\s+resultado|produce\s+el\s+resultado|resultado\s+de\s+\d|votaci[oó]n\s+arroja|se\s+registran|"
    r"resultaron|efectuad[ao]\s+la\s+votaci[oó]n|se\s+obtienen?)", re.I)
# Frases que citan acuerdos anteriores o de otros órganos, o intervenciones del debate.
PASADO_RE = re.compile(
    r"\b(?:aprob[oó]|aprobaron|adopt[oó]|adoptaron|acord[oó]|acordaron|fue(?:ron)?\s+aprobad|dictaminad|"
    r"sesi[oó]n\s+(?:celebrada|de\s+fecha|del\s+d[ií]a)|se\s+aprob[oó]|se\s+ha(?:n)?\s+aprobado|"
    r"ha(?:n|bía|bían)?\s+(?:sido\s+)?aprobad|acuerdos?\s+adoptad|han\s+votado|votaron|votó)\b", re.I)
DEBATE_RE = re.compile(
    r"\b(?:dice|señala|afirma|recuerda|manifiesta|resalta|alude|explica|expone|considera|entiende|critica|"
    r"lamenta|anuncia|destaca|subraya|opina|replica|responde|contesta|añade|asegura|insiste|argumenta|"
    r"reprocha|denuncia|apunta|comenta|agradece|pregunta|advierte|reconoce|sostiene|defiende|puntualiza|"
    r"indica|reseña|estima|propone|solicita|pide|cree|piensa|valora|celebra|concluye|finaliza|termina|"
    r"interviene|lee|recalca|aclara|precisa|matiza|reitera|incide|hace\s+hincapi[ée])\b", re.I)
OTRO_ORGANO_RE = re.compile(r"\b(?:Mesa\s+de\s+Contrataci[oó]n|Junta\s+de\s+Gobierno|Consejo|Cortes|Comisi[oó]n|"
                            r"Congreso|Senado|Diputaci[oó]n|Consell|Generalitat|Junta\s+General|Asamblea)\b")
URGENCIA_RE = re.compile(r"urgencia|inclusi[oó]n\s+(?:del\s+asunto\s+)?en\s+el\s+orden\s+del\s+d[ií]a|"
                         r"inclusi[oó]n\s+en\s+el\s+orden|ratificaci[oó]n\s+de\s+su\s+inclusi[oó]n|"
                         r"\bratifica\s+(?:la|su)\s+inclusi[oó]n", re.I)
RETIRADA_RE = re.compile(r"\bretirada\b|\bretirar\b|sobre\s+la\s+mesa|aplazamiento|\baplazar\b", re.I)
# Votación de una enmienda (no de la propuesta con las enmiendas ya incorporadas).
ENMIENDA_RE = re.compile(
    r"(?:votaci[oó]n|sometid[oa]s?|vot[aá]\w*)\s+(?:a\s+votaci[oó]n\s+)?(?:de\s+)?(?:la|las|dicha|dichas|esta|estas|una)\s+"
    r"(?:\w+\s+){0,2}enmiendas?|^\W*(?:la|las)\s+enmiendas?\b|enmiendas?\b[^.]{0,120}\b(?:es|son|resulta|resultan|queda|"
    r"quedan)\s+(?:aprobad|rechazad|desestimad)|incorporar\s+(?:una|la|las)\s+enmienda|se\s+admite[^.]{0,60}enmienda|"
    r"\benmiendas?\b[^.]{0,40}:\s*[-−–]?\s*a\s+favor|\b(?:aprueba|rechaza|desestima|acepta)\s+(?:la|las)\s+enmiendas?", re.I)
ACTUAL_RE = re.compile(r"^\W*El\s+Pleno(?:\s+del\s+Ayuntamiento)?\s*,?\s*por\s+(?:unanimidad|mayor[ií]a)", re.I)
# Votación de la propuesta misma (aunque cite enmiendas ya aprobadas).
PROPUESTA_RE = re.compile(
    r"^\W*(?:\d{1,2}\s*[.ºª)]\s*)?Sometid[oa]s?\s+(?:a\s+votaci[oó]n\s+)?(?:la|el)\s+(?:propuesta\s+de\s+)?(?:moci[oó]n|"
    r"propuesta|declaraci[oó]n|dictamen|asunto|texto|expediente|proposici[oó]n|solicitud)", re.I)
RECHAZO_RE = re.compile(r"\brechazad[oa]s?\b|\brechaza\b|\bno\s+prospera|\bno\s+(?:es|son|resulta|queda)\s+aprobad|"
                        r"\b(?:es|son|resulta|resultan|queda|quedan)\s+desestimad|"
                        r"\bno\s+se\s+aprueba", re.I)
APROBACION_RE = re.compile(r"\baprobad[oa]s?\b|\bse\s+aprueba\b|\badopt(?:a|an|ó)\b|\bacuerda\b|\bacuerdan\b|\baprueba\b|"
                           r"\bratifica\b|da\s+su\s+aprobaci[oó]n|\bse\s+acepta\b|\bse\s+admite\b", re.I)
# En la frase siguiente a un recuento sin verbo («Así pues, por mayoría, … el Pleno ACUERDA:»).
RECHAZO_SIGUE_RE = re.compile(RECHAZO_RE.pattern + r"|\bdeclara\w*\s+desestimad", re.I)

ABREVIATURAS = {"d", "dª", "dña", "sr", "sra", "sres", "sras", "srs", "excmo", "excma", "iltmo", "iltma", "ilmo",
                "ilma", "art", "arts", "núm", "nº", "n.º", "pág", "avda", "c", "s.a", "s.l", "etc", "ud", "uds",
                "dr", "dra", "prof", "vol", "apdo", "ptas", "ref", "exp", "expte", "cía", "hnos", "mª", "sto", "sta"}

TIPOS_TITULO = [
    (re.compile(r"\bmoci[oó]n|declaraci[oó]n\s+institucional", re.I), "mocion"),
    (re.compile(r"\bcomparecencia|\bdaci[oó]n\s+de\s+cuenta|\bpuesta\s+en\s+conocimiento|\bruegos?\b|\bpreguntas?\b|"
                r"\binforme\s+(?:de|sobre)\s+(?:la\s+)?(?:gesti[oó]n|alcald)", re.I), "control"),
    (re.compile(r"\baprobaci[oó]n\s+de(?:l|\s+las?)\s+actas?\b|\belecci[oó]n\b|\bnombramiento|\bdesignaci[oó]n|"
                r"\bcomposici[oó]n\b|\bconstituci[oó]n\s+de\s+(?:las?\s+)?comisi|\bperiodicidad|"
                r"\bdedicaci[oó]n\b|\bretribuciones\s+de\s+los\s+miembros|\btoma\s+de\s+posesi[oó]n|\bcese\b|"
                r"\brepresentantes?\b|\bportavoces?\b|\bcompatibilidad|\bcreaci[oó]n\s+de\s+(?:una\s+)?comisi[oó]n|"
                r"\btenencias?\s+de\s+alcald|\bgrupos?\s+pol[ií]ticos?", re.I), "organizacion"),
    (re.compile(r"\bordenanza|\breglamento\b|\bestatutos?\b", re.I), "ordenanza"),
]
PRESUPUESTO_RE = re.compile(r"\bpresupuestos?\s+(?:general|municipal)", re.I)
NO_PRESUPUESTO_RE = re.compile(r"cr[ée]dito|modificaci[oó]n|liquidaci[oó]n|reconocimiento|base|prorrog|cuenta\s+general|"
                               r"remanente|ejecuci[oó]n|informe|estabilidad|plan\s+econ", re.I)

RESULTADO_HTML_RE = re.compile(
    r"^(?P<r>(?:Aprobad[oa]s?|Rechazad[oa]s?|Enterad[oa]s?|Contestad[oa]s?|Retirad[oa]s?|Aceptad[oa]s?|"
    r"Denegad[oa]s?|Se\s+acepta|Se\s+rechaza|Se\s+considerar[áa]|No\s+se\s+considera|Se\s+estudiar[áa]|"
    r"Se\s+estudia|Queda\s+sobre\s+la\s+mesa|Desestimad[oa]s?|Efectuad[oa]s?)(?:\s+[^.]{0,60})?)\.?$")


# ---------------------------------------------------------------------- utilidades

def _decodificar(raw):
    """El HTML mezcla UTF-8 con bytes sueltos en Windows-1252 (guiones, comillas)."""
    partes, i = [], 0
    while True:
        try:
            partes.append(raw[i:].decode("utf-8"))
            return "".join(partes)
        except UnicodeDecodeError as e:
            partes.append(raw[i:i + e.start].decode("utf-8"))
            partes.append(raw[i + e.start:i + e.end].decode("cp1252", "replace"))
            i += e.end


def _limpio(t):
    return re.sub(r"\s+", " ", (t or "").replace("\xa0", " ")).strip()


def _html_texto(h):
    h = re.sub(r"(?i)<br\s*/?>", "\n", h)
    return unescape(re.sub(r"(?s)<[^>]+>", " ", h))


def _mayusculas(t, minimo=0.85):
    letras = [c for c in t[:120] if c.isalpha()]
    return len(letras) >= 4 and sum(c.isupper() for c in letras) / len(letras) >= minimo


def _numero(n):
    n = n.lower()
    return int(n) if n.isdigit() else NUMEROS.get(n)


def _codigo(rom, num):
    """(parte, n1, n2, …) del epígrafe: «I-2.1» -> (1, 2, 1); «1.12» -> (1, 12); «14. 3» -> (14, 3)."""
    partes = tuple(int(x) for x in re.findall(r"\d+", num))
    return ((ROMANOS[rom],) if rom else ()) + partes


def _numero_punto(codigo):
    """Número estable de la votación a partir del código del punto (cuatro niveles de dos cifras)."""
    c = (tuple(codigo) + (0, 0, 0, 0))[:4]
    return c[0] * 1_000_000 + c[1] * 10_000 + c[2] * 100 + c[3]


def _sigue(previo, codigo, salto=6):
    """¿Puede `codigo` ser el epígrafe siguiente a `previo`? (evita tomar listas numeradas del texto)."""
    if previo is None:
        return all(x <= 3 for x in codigo)
    if codigo <= previo:
        return False
    for k in range(len(previo) + 1):
        if tuple(codigo[:k]) != tuple(previo[:k]):
            return False
        if k == len(previo):  # hijo: I-2 -> I-2.1
            return len(codigo) > k and all(x <= 3 for x in codigo[k:])
        if len(codigo) > k and previo[k] < codigo[k] <= previo[k] + salto:  # hermano de algún nivel
            return all(x <= 3 for x in codigo[k + 1:])
    return False


# ---------------------------------------------------------------------- listado de sesiones

def _url_listado(anyo):
    return f"{WEB}?anyo={anyo}"


def _url_doc(tipo, fecha, cod):
    a, m, d = fecha.split("-")
    return f"{WEB}descarga-documento.php?tipo={tipo}&fecha={d}%2F{m}%2F{a}&sesion={cod}"


def _url_extracto(fecha, cod):
    a, m, d = fecha.split("-")
    return f"{WEB}extracto.php?fecha={d}%2F{m}%2F{a}&sesion={cod}"


def listar_sesiones(ctx, anyo):
    """Sesiones de un año, de la más reciente a la más antigua: [{fecha, cod, caracter, acta, extracto}]."""
    caduca = 1 if anyo >= date.today().year - 1 else 30
    html = _decodificar(ctx.fetch(_url_listado(anyo), cache=f"{CUERPO}/listado/{anyo}.html", caduca_dias=caduca))
    sesiones, vistas = [], set()
    for ficha in re.split(r'<div class="card bg-light', html)[1:]:
        m = re.search(r"fecha=(\d\d)%2F(\d\d)%2F(\d{4})&(?:amp;)?sesion=(\d+)", ficha)
        if not m:
            continue
        fecha, cod = f"{m[3]}-{m[2]}-{m[1]}", int(m[4])
        if (fecha, cod) in vistas or not fecha.startswith(str(anyo)):
            continue
        vistas.add((fecha, cod))
        car = re.search(r'caracter_pleno">(.*?)</p>', ficha, re.S)
        sesiones.append({
            "fecha": fecha, "cod": cod,
            "caracter": _limpio(_html_texto(car.group(1))) if car else CARACTER.get(cod),
            "acta": "tipo=2&" in ficha.replace("&amp;", "&"),
            "extracto": "extracto.php" in ficha,
        })
    sesiones.sort(key=lambda s: (s["fecha"], s["cod"]), reverse=True)
    return sesiones


def _sesion_id(s):
    return int(s["fecha"].replace("-", "")) * 10 + s["cod"]


def _antigua(fecha, dias=120):
    return date.fromisoformat(fecha) < date.today() - timedelta(days=dias)


# ---------------------------------------------------------------------- extracto (HTML)

def extracto(ctx, s):
    """Puntos del extracto: {código: (código en texto, título, resultado en texto, apartado)}."""
    caduca = None if _antigua(s["fecha"]) else 1
    raw = ctx.fetch(_url_extracto(s["fecha"], s["cod"]), cache=f"{CUERPO}/extracto/{s['fecha']}_{s['cod']}.html",
                    caduca_dias=caduca)
    html = _decodificar(raw)
    puntos = {}
    for li in re.findall(r'(?s)<li class="list-group-item">(.*?)</li>', html):
        h4 = re.search(r"(?s)<h4>(.*?)</h4>", li)
        apartado = _limpio(_html_texto(h4.group(1))) if h4 else ""
        cuerpo = re.sub(r"(?s)<h4>.*?</h4>", "", li)
        texto = _html_texto(cuerpo)
        # Cada punto empieza por su código al principio de una línea.
        trozos = re.split(r"\n\s*(?=(?:I{1,3}|IV|V)?\s?[-–]?\s?\d{1,2}(?:\s?\.\s?\d{1,2}){0,3}\s?(?:\.\s?[-–]|\.|[-–]|(?=\s))\s)",
                          "\n" + texto)
        for t in trozos:
            t = _limpio(t)
            m = re.match(r"(?:(?P<rom>I{1,3}|IV|V)\s?[-–]\s?)?(?P<num>\d{1,2}(?:\s?\.\s?\d{1,2}){0,3})"
                         r"\s?(?P<sep>\.\s?[-–]|\.|[-–]|(?=\s))\s*(?P<tit>.+)", t)
            if not m or not (m["sep"] or m["rom"] or "." in m["num"]):
                continue
            codigo = _codigo(m["rom"], m["num"])
            titulo, resultado = _separar_resultado(m["tit"])
            puntos.setdefault(codigo, (_texto_codigo(m), titulo, resultado, apartado))
    return puntos


def _separar_resultado(t):
    """«Fiestas locales para 2027: aprobación. Aprobado.» -> («Fiestas locales…: aprobación», «Aprobado»)."""
    t = _limpio(t)
    frases = re.split(r"(?<=[.:)»\"”])\s+(?=[A-ZÁÉÍÓÚ])", t)
    if len(frases) > 1:
        m = RESULTADO_HTML_RE.match(frases[-1])
        if m:
            return " ".join(frases[:-1]).rstrip(" ."), m["r"]
    # Resultado pegado sin espacio tras el punto o al final sin punto («… definitiva. Aprobado»).
    m = re.match(r"^(?P<t>.*[.:)»\"”])\s*(?P<r>Aprobad[oa]s?|Rechazad[oa]s?|Enterad[oa]s?|Contestad[oa]s?)\.?$", t)
    if m:
        return m["t"].rstrip(" ."), m["r"]
    return t.rstrip(" ."), None


def _resultado_html(r):
    if not r:
        return None
    if re.fullmatch(r"Aprobad[oa]s?(?:\s+con\s+(?:enmiendas?|correcciones|modificaciones))?", r):
        return "aprobada"
    if re.fullmatch(r"Rechazad[oa]s?", r):
        return "rechazada"
    return None


# ---------------------------------------------------------------------- acta (PDF)

def _lineas(texto):
    out = []
    for ln in texto.replace("\f", "\n").split("\n"):
        ln = _limpio(ln)
        if not ln or re.fullmatch(r"\d{1,3}|[-−–]\s*\d{1,3}\s*[-−–]", ln):
            continue  # vacías y números de página
        out.append(ln)
    return out


CODIGO_SOLO_RE = re.compile(r"^(?:(?:I{1,3}|IV|V)\s?[-–]\s?\d{1,2}(?:\s?\.\s?\d{1,2}){0,3}|\d{1,2}(?:\s?\.\s?\d{1,2}){1,3})"
                            r"\s?(?:\.\s?[-–]|\.|[-–])?$")


def _juntar_codigos(lineas):
    """«I-1.1.» solo en una línea y el título en la siguiente: se juntan."""
    out, i = [], 0
    while i < len(lineas):
        if CODIGO_SOLO_RE.match(lineas[i]) and i + 1 < len(lineas) and re.match(r"[A-ZÁÉÍÓÚÑ“\"«]", lineas[i + 1]):
            out.append(lineas[i] + " " + lineas[i + 1])
            i += 2
            continue
        out.append(lineas[i])
        i += 1
    return out


def puntos_acta(texto, codigos_extracto=()):
    """Trocea el acta por epígrafes: [(código, título, apartado previo, texto del punto)]."""
    lineas = _juntar_codigos(_lineas(texto))
    conocidos = set(codigos_extracto)
    # Candidatos: líneas con forma de epígrafe. Desde 2005 los epígrafes llevan la parte en romanos
    # («I-2.1.»); entonces las listas numeradas del texto («3. RECLAMACIONES…») no cuentan.
    candidatos = []  # (índice de línea, código, match, peso)
    for i, ln in enumerate(lineas):
        m = EPIGRAFE_RE.match(ln)
        if m and (m["sep"] or "." in m["num"]):  # sin separador solo «1.9 TÍTULO»
            candidatos.append((i, _codigo(m["rom"], m["num"]), m))
    romanos = sum(1 for _i, _c, m in candidatos if m["rom"]) >= 3
    elegibles = []
    for i, codigo, m in candidatos:
        if romanos and not m["rom"]:
            continue
        peso = 2 if codigo in conocidos else 1 if _mayusculas(m["tit"]) else 0.5 if m["rom"] and len(codigo) >= 2 else 0
        if peso:
            elegibles.append((i, codigo, m, peso))
    # La cadena de epígrafes más larga (con más peso) en la que cada uno puede seguir al anterior.
    mejor, padre = [], []
    for k, (_i, codigo, _m, peso) in enumerate(elegibles):
        b, p = (peso, None) if _sigue(None, codigo) else (None, None)
        for j in range(k):
            if mejor[j] is not None and (b is None or mejor[j] + peso > b) and _sigue(elegibles[j][1], codigo):
                b, p = mejor[j] + peso, j
        mejor.append(b)
        padre.append(p)
    cadena = []
    if any(b is not None for b in mejor):
        k = max((b, k) for k, b in enumerate(mejor) if b is not None)[1]
        while k is not None:
            cadena.append(elegibles[k])
            k = padre[k]
        cadena.reverse()
    if romanos:
        # Epígrafes en mayúsculas fuera de la cadena: erratas de numeración («I-1.1» repetido). Se
        # cortan igual, para no atribuir su votación al punto anterior.
        en_cadena = {e[0] for e in cadena}
        cadena = sorted(cadena + [e for e in elegibles if e[0] not in en_cadena and len(e[1]) >= 2
                                  and _mayusculas(e[2]["tit"])], key=lambda e: e[0])
    epigrafes = []  # (línea del epígrafe, primera línea del cuerpo, código, texto del código, título, apartado)
    for i, codigo, m, _peso in cadena:
        tit = m["tit"]
        # El título puede seguir en las líneas siguientes (en mayúsculas) hasta acabar en punto.
        j = i + 1
        while (not tit.rstrip().endswith((".", ":")) and j < len(lineas) and j <= i + 4 and _mayusculas(tit)
               and _mayusculas(lineas[j], 0.9) and not EPIGRAFE_RE.match(lineas[j])
               and lineas[j].rstrip(":. ").upper() not in MARCAS):
            tit += " " + lineas[j]
            j += 1
        apartado = lineas[i - 1] if i > 0 and len(lineas[i - 1]) < 80 and not EPIGRAFE_RE.match(lineas[i - 1]) else ""
        epigrafes.append((i, j, codigo, _texto_codigo(m), _limpio(tit), apartado))
    puntos = []
    for k, (i, j, codigo, cod_txt, tit, apartado) in enumerate(epigrafes):
        fin = epigrafes[k + 1][0] if k + 1 < len(epigrafes) else len(lineas)
        puntos.append((codigo, cod_txt, tit, apartado, " ".join(lineas[j:fin])))
    return puntos


def _parecidos(a, b, minimo=0.5):
    """¿Son el mismo título? (el del extracto en minúsculas y el del acta en mayúsculas)."""
    pa = {w for w in re.findall(r"\w{4,}", _sin_tildes(a or ""))}
    pb = {w for w in re.findall(r"\w{4,}", _sin_tildes(b or ""))}
    if not pa or not pb:
        return True
    return len(pa & pb) / min(len(pa), len(pb)) >= minimo


def _texto_codigo(m):
    """«I-2.1», «1.12», «14.3»: el código del punto tal como se escribe."""
    num = ".".join(re.findall(r"\d+", m["num"]))
    return f"{m['rom']}-{num}" if m["rom"] else num


_ORDINALES = r"(?:PRIMER[OA]|SEGUND[OA]|TERCER[OA]|CUART[OA]|QUINT[OA]|SEXT[OA]|S[ÉE]PTIM[OA]|OCTAV[OA]|NOVEN[OA]|D[ÉE]CIM[OA])"
# Fin de frase: «. », «: », «; » ante mayúscula, ante «2. Sometido…» o ante «SEGUNDO:» (votación por puntos).
FIN_FRASE_RE = re.compile(
    rf"[.:;][”\"»]?\s+(?:\d{{1,3}}\s+(?=[A-ZÁÉÍÓÚÑ][a-záéíóúñ]))?(?=[A-ZÁÉÍÓÚÑ¿“\"«(]|\d{{1,2}}(?:\.|[ªº]\.?)\s+[A-ZÁÉÍÓÚÑ])"
    rf"|(?<!,)(?<!\sy)\s+(?={_ORDINALES}\s*:\s*(?:es|son)\s)"
    r"|(?<=[A-ZÁÉÍÓÚÑ)])\s+(?=El\s+Pleno\s+del\s+Ayuntamiento\s*,\s*por\s)")  # «…queda RECHAZADA El Pleno del…»


def _frases(texto):
    """Divide en frases [(posición, frase)] sin cortar en abreviaturas («D.», «art.», «Sra.»)."""
    frases, inicio = [], 0
    for m in FIN_FRASE_RE.finditer(texto):
        if texto[m.start()] == "." and not re.match(r"\.[”\"»]", m.group()):  # «…Hepatitis C.” Sometido…» sí corta
            antes = re.search(r"(\S+)$", texto[inicio:m.start()])
            palabra = (antes.group(1) if antes else "").lower().strip("(“\"«")
            if palabra in ABREVIATURAS or re.fullmatch(r"[a-zñ]|\d+", palabra):
                continue
        frases.append((inicio, texto[inicio:m.start() + 1]))
        inicio = m.end()
    frases.append((inicio, texto[inicio:]))
    return frases


def _es_votacion(f):
    if not (TROZO_RE.search(f) or TROZO_LISTA_RE.search(f) or TROZO_INV_RE.search(f) or re.search(r"unanimidad", f, re.I)):
        return False
    # El recuento en forma de lista («A FAVOR: 13 votos (…) EN CONTRA: 16 votos (…)») no lleva verbo.
    if not DECISION_RE.search(f) and not ACTUAL_RE.match(f) and len(TROZO_LISTA_RE.findall(f)) < 2:
        return False
    # «El Pleno del Ayuntamiento, por unanimidad, adoptó el siguiente ACUERDO» (así en algunas actas de 2019)
    # es la votación del punto; las citas de acuerdos anteriores no empiezan así.
    if (PASADO_RE.search(f) and not ACTUAL_RE.match(f)) or DEBATE_RE.search(f):
        return False
    # Acuerdos de otros órganos citados en el expediente («la Mesa de Contratación, por unanimidad, acuerda…»).
    if OTRO_ORGANO_RE.search(f) and not re.search(r"\bPleno\b|^\W*Sometid", f):
        return False
    return True


def _clase(f):
    """principal | urgencia | retirada | enmienda."""
    if URGENCIA_RE.search(f):
        return "urgencia"
    if RETIRADA_RE.search(f):
        return "retirada"
    if PROPUESTA_RE.match(f):  # «Sometida la Moción a votación (con la enmienda …), es APROBADA»
        return "principal"
    if ENMIENDA_RE.search(f):
        return "enmienda"
    return "principal"


def _marcas(texto):
    """Rótulos de votación del acta: [(posición, clase, texto)] con clase principal | enmienda | urgencia.

    «VOTACIÓN Y ACUERDOS:», «VOTACIONES Y ACUERDOS:», «VOTACIÓN DE LAS ENMIENDAS DEL GS:»,
    «VOTACIÓN SOBRE EL FONDO DEL ASUNTO Y ACUERDOS:», «VOTACIÓN Y ACUERDO.» (hacia 2002),
    «VOTACIÓN COINCIDENTE EN LOS ACUERDOS PRIMERO A SEXTO» (hacia 2020).
    """
    out = []
    for m in MARCA_RE.finditer(texto):
        resto = m.group(1).upper()
        clase = "enmienda" if "ENMIENDA" in resto else "urgencia" if "URGENCIA" in resto else "principal"
        out.append((m.start(), clase, re.sub(r"\s+A\s+FAVOR$", "", _limpio(m.group(1)))))
    return out


PUNTO_SEPARADO_RE = re.compile(
    rf"^\W*(?:VOTACI\w+[^:]*:\s*)?(?:\d{{1,2}}\s*[.ºª)]|{_ORDINALES}\b|(?:Los|El)\s+(?:acuerdos?|puntos?|apartados?)\b|"
    r"(?:Es|Son)\s+(?:APROBAD|RECHAZAD)|En\s+(?:primera|segunda|tercera)\s+votaci[oó]n)")


def _etiqueta_punto(f, k):
    """Qué se vota en cada votación separada: «PRIMERO», «SEGUNDO, TERCERO y CUARTO», «1», «2ª»…"""
    f = re.sub(r"^\W*(?:VOTACI\w+[^:]*:\s*)?", "", f)
    m = re.match(r"En\s+(primera|segunda|tercera)\s+votaci[oó]n", f, re.I)
    if m:  # empate y segunda votación (voto de calidad)
        return f"{m.group(1).capitalize()} votación"
    m = re.match(rf"(\d{{1,2}}[ªº]?)\s*[.)]?\s|((?:{_ORDINALES}(?:\s*,\s*|\s+y\s+)?)+)", f)
    if m and m.group(1):
        return f"Votación separada {m.group(1)}"
    if m and m.group(2):
        return f"Votación separada: {_limpio(m.group(2)).rstrip(',')}"
    m = re.match(r"(?:Los|El)\s+(?:acuerdos?|puntos?|apartados?)\s+([^:]{1,60}):", f)
    if m:
        return f"Votación separada: {_limpio(m.group(1))}"
    return f"Votación separada n.º {k}"


def votaciones_punto(texto):
    """Votaciones de un punto del acta: ([(frase, frase siguiente, subtítulo)], ¿parecía haber votación?, nº de otras).

    Tras «VOTACIÓN Y ACUERDOS:» (desde 2005) vale la primera votación que no sea de enmiendas,
    urgencia o retirada; si se vota por puntos («PRIMERO: es APROBADO…», «1. Sometido a votación…»),
    una por punto. Sin ese rótulo, la última del punto (antes van la ratificación de la urgencia, las
    enmiendas y las citas de otros acuerdos).
    """
    marcas = _marcas(texto)
    frases = _frases(texto)

    def previa(k):
        antes = [(c, t) for p, c, t in marcas if p <= frases[k][0] + 5]
        return antes[-1] if antes else (None, "")

    def clase(k):
        c, f = previa(k)[0], frases[k][1]
        if c in ("enmienda", "urgencia") and not PROPUESTA_RE.match(f) and not (
                ACTUAL_RE.match(f) and re.search(r"siguientes?\s+acuerdos?", f, re.I)):
            return c  # bajo el rótulo «VOTACIÓN DE LAS ENMIENDAS…», salvo «Sometida la Moción a votación…»
        return _clase(f)

    candidatas = [k for k, (_pos, f) in enumerate(frases) if _es_votacion(f)]
    principales = [k for k in candidatas if clase(k) == "principal"]
    if not principales:  # ¿había un rótulo de votación del punto? (si no, se retiró o no se votó)
        return [], any(c == "principal" for _p, c, _t in marcas), 0

    def siguiente(k):  # hasta tres frases siguientes, por si el resultado va aparte (empates, recuentos en lista)
        return " \n".join(f for _p, f in frases[k + 1:k + 4])

    inicio = next((p for p, c, _t in marcas if c == "principal"), None)
    tras = [k for k in principales if inicio is not None and frases[k][0] + 5 >= inicio]
    if tras:
        separadas = [k for k in tras if PUNTO_SEPARADO_RE.match(frases[k][1])]
        if len(separadas) >= 2 and separadas[0] == tras[0]:
            return ([(frases[k][1], siguiente(k), _etiqueta_punto(frases[k][1], i + 1)) for i, k in enumerate(separadas)],
                    True, len(principales) - len(separadas))
        # Un rótulo por votación: «VOTACIÓN COINCIDENTE EN LOS ACUERDOS PRIMERO A SEXTO … A FAVOR: 13 votos…»
        rotulos = [previa(k) for k in tras]
        if len(tras) >= 2 and len({t for _c, t in rotulos}) == len(tras) and all(t for _c, t in rotulos):
            return ([(frases[k][1], siguiente(k), f"Votación separada: {t.lower().strip(' .:')}")
                     for k, (_c, t) in zip(tras, rotulos)], True, len(principales) - len(tras))
        return [(frases[tras[0]][1], siguiente(tras[0]), None)], True, len(principales) - 1
    k = principales[-1]
    return [(frases[k][1], siguiente(k), None)], True, len(principales) - 1


def _sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


def grupo_canonico(nombre):
    """Nombre del grupo tal como lo escribe la lista de asistentes -> nombre común de este conector."""
    n = _sin_tildes(nombre)
    for patron, grupo in (
        (r"no adscrit", NO_ADSCRITOS), (r"popular", "Grupo Popular"), (r"socialista", "Grupo Socialista"),
        (r"\bvox\b", "Grupo Vox"), (r"compromis", "Grupo Compromís"), (r"ciudadanos", "Grupo Ciudadanos"),
        (r"unides|unidas podemos", "Grupo Unides Podem"), (r"esquerra unida.*podem|eu.?podem", "Grupo Esquerra Unida Podem"),
        (r"esquerra unida|\beu\b", "Grupo Esquerra Unida"), (r"guanyar", "Grupo Guanyar Alacant"),
        (r"progreso y democracia|upyd", "Grupo Unión Progreso y Democracia"), (r"mixto", "Grupo Mixto"),
    ):
        if re.search(patron, n):
            return grupo
    return _limpio(nombre).title()


ASISTENTE_RE = re.compile(
    r"(?:GRUPO|Grupo)\s+(?P<grupo>.+?)(?=\s+(?:Alcalde|Concejal|Excm|Iltm|Ilm|Don\b|Doña\b))"
    r"|(?P<na>CONCEJAL(?:ES|A)?\s+NO\s+ADSCRIT[OA]S?|Concejal(?:es|a)?\s+no\s+adscrit[oa]s?)"
    r"|\b(?:Don|Doña)\s+(?P<nombre>[A-ZÁÉÍÓÚÑ][^\s]*(?:\s+(?:(?:de|del|de\s+la|y)\s+)?"
    r"(?!(?:Don|Doña|Concejal\w*|Alcalde\w*|GRUPO|Grupo|CONCEJAL\w*)\b)[A-ZÁÉÍÓÚÑ][^\s]*)*)")


def plantilla(texto):
    """{nombre del concejal: grupo} según la lista de asistentes del principio del acta."""
    cab = texto[:8000]
    fin = re.search(r"\bInterventor|\bSecretari[oa]\b|\n\s*En la (?:Muy|Ciudad)", cab)
    cab = _limpio(cab[:fin.start()] if fin else cab[:3000])
    grupo, out = None, {}
    for m in ASISTENTE_RE.finditer(cab):
        if m["grupo"]:
            grupo = grupo_canonico(m["grupo"])
        elif m["na"]:
            grupo = NO_ADSCRITOS
        elif grupo:
            out[m["nombre"]] = grupo
    return out


def _grupo_persona(trozo, asistentes):
    """Grupo de un concejal citado por su nombre («Dª Nerea Belmonte Aliaga», «Sra. Remiro»)."""
    t = re.sub(r"^(?:(?:la|el|los|las)\s+de\s+|abstenci[oó]n\s+de\s+|de\s+)", "", trozo.strip(), flags=re.I)
    t = re.sub(r"^(?:D\.|Dª\.?|Dña\.?|Don|Doña|Sr\.|Sra\.|Srta\.)\s*", "", re.sub(r"\(.*", "", t))
    palabras = {_sin_tildes(w) for w in re.findall(r"[A-ZÁÉÍÓÚÑ][\wáéíóúñü’'\-]+", t)}
    if not palabras:
        return None
    grupos = {g for nombre, g in asistentes.items()
              if palabras <= {_sin_tildes(w) for w in re.findall(r"[\wáéíóúñüÁÉÍÓÚÑÜ’'\-]+", nombre)}}
    return grupos.pop() if len(grupos) == 1 else None


def _clave(t):
    return re.sub(r"[\s’'´`\-.]", "", t).upper()


def _grupos_de(parentesis, asistentes=None):
    """Grupos de un paréntesis de votación y si queda algún votante sin grupo reconocido.

    «(GP, GS y GV)», «(GS) (GG) y (GC)», «(GP, GC’s, Dª Nerea Belmonte Aliaga (NA) y …)»,
    «(abstención de D. Miguel Ull Laita del GS, por hallarse ausente…)», «(Sra. Remiro)».
    """
    t = parentesis.replace("GUP y D", "GUPyD").replace("GUPy D", "GUPyD")
    grupos, raro = [], False
    for trozo in re.split(r",|;|\s+[yY]\s+|\)\s*\(", t):
        trozo = trozo.strip(" ()–-.")
        if not trozo:
            continue
        clave = _clave(trozo)
        del_grupo = re.search(r"\bdel\s+(G[\w’'´\-]{1,10})\b|\((G[\w’'´\-]{0,10}|NA)\)?\s*$", trozo)
        if clave in GRUPOS:
            grupos.append(GRUPOS[clave])
        elif re.search(r"adscrit", trozo, re.I):
            grupos.append(NO_ADSCRITOS)
        elif del_grupo and _clave(del_grupo.group(1) or del_grupo.group(2)) in GRUPOS:
            grupos.append(GRUPOS[_clave(del_grupo.group(1) or del_grupo.group(2))])
        elif all(_clave(x) in GRUPOS for x in trozo.split()):  # «GP GUPyD», sin coma
            grupos.extend(GRUPOS[_clave(x)] for x in trozo.split())
        elif re.match(r"(?:(?:la|el)\s+de\s+)?(?:D\.|Dª|Dña|Don|Doña|Sr\.|Sra\.|Srta)", trozo):
            g = _grupo_persona(trozo, asistentes or {})
            if g:
                grupos.append(g)
            else:
                raro = True
        elif re.match(r"(?:G[A-Z]|Grupo\b)", trozo):
            g = GRUPOS.get(clave) or (grupo_canonico(trozo) if trozo.startswith("Grupo") else None)
            if g:
                grupos.append(g)
            else:
                raro = True
        # El resto son aclaraciones («por estar ausente en el momento de la votación»).
    vistos = []
    for g in grupos:
        if g not in vistos:
            vistos.append(g)
    return vistos, raro


def analizar_frase(f, escanos, asistentes=None, siguiente=""):
    """Totales, grupos y resultado de una frase de votación. Devuelve dict."""
    r = {"a_favor": None, "en_contra": None, "abstenciones": None, "grupos": [], "resultado": None,
         "unanimidad": bool(re.search(r"unanimidad", f, re.I)), "aviso": None, "raro": False}
    sentidos = {}  # sentido -> (n, [grupos])
    campo = {"si": "a_favor", "no": "en_contra", "abstencion": "abstenciones"}
    trozos = list(TROZO_RE.finditer(f))
    trozos += [m for m in TROZO_INV_RE.finditer(f) if not any(m.start() < t.end() and t.start() < m.end() for t in trozos)]
    trozos = sorted(trozos, key=lambda m: m.start()) or list(TROZO_LISTA_RE.finditer(f))
    for m in trozos:
        s = m["s"].lower()
        sentido = "si" if "favor" in s else "no" if "contra" in s else "abstencion"
        n = _numero(m["n"])
        grupos, raro = _grupos_de(m["g"], asistentes) if m["g"] else ([], False)
        r["raro"] |= raro
        if sentido in sentidos:  # el mismo sentido dos veces: errata
            r["aviso"] = "sentido repetido"
            n0, g0 = sentidos[sentido]
            sentidos[sentido] = (n0 + n, g0 + [g for g in grupos if g not in g0])
        else:
            sentidos[sentido] = (n, grupos)
    for sentido, (n, _g) in sentidos.items():
        r[campo[sentido]] = n
    total = sum(n for n, _g in sentidos.values())
    if total > escanos or r["aviso"]:
        r["aviso"] = f"los totales ({total}) no cuadran con {escanos} concejales" if total > escanos else \
            "el mismo sentido aparece dos veces"
        r["a_favor"] = r["en_contra"] = r["abstenciones"] = None
        sentidos = {}
    # Grupos: sentido de cada uno y su número si es el único grupo citado en ese sentido.
    por_grupo = {}
    for sentido, (n, grupos) in sentidos.items():
        for g in grupos:
            por_grupo.setdefault(g, {})[sentido] = n if len(grupos) == 1 else None
    for g, ss in por_grupo.items():
        vg = VotoGrupo(g, sentido=next(iter(ss)) if len(ss) == 1 else "dividido")
        if all(v is not None for v in ss.values()):
            for sentido, n in ss.items():
                setattr(vg, sentido, n)
        r["grupos"].append(vg)
    if RECHAZO_RE.search(f):
        r["resultado"] = "rechazada"
    elif APROBACION_RE.search(f) or r["unanimidad"]:
        r["resultado"] = "aprobada"
    else:
        # Recuento sin verbo («se produce el siguiente resultado: − A favor: 15 votos…», «En primera votación, se
        # obtienen 13 votos favorables y 13 en contra. Ante el empate… el Pleno adopta…»): lo dicen las frases
        # siguientes, hasta la próxima que traiga otro recuento.
        for sig in (siguiente or "").split(" \n"):
            if TROZO_RE.search(sig) or TROZO_LISTA_RE.search(sig):
                break
            if re.search(r"voto\s+de\s+calidad", sig, re.I):
                r["nota"] = "empate decidido por el voto de calidad de la Presidencia"
            if RECHAZO_SIGUE_RE.search(sig):
                r["resultado"] = "rechazada"
                break
            if APROBACION_RE.search(sig):
                r["resultado"] = "aprobada"
                break
    return r


def tipo_iniciativa(titulo, apartado=""):
    for patron, tipo in TIPOS_TITULO:
        if patron.search(titulo):
            return tipo
    if PRESUPUESTO_RE.search(titulo) and not NO_PRESUPUESTO_RE.search(titulo):
        return "presupuesto"
    if re.search(r"\bmociones\b|declaraciones\s+institucionales", apartado, re.I):
        return "mocion"
    if re.search(r"ruegos|preguntas|comparecencias|informes?\s+de\s+los\s+[oó]rganos", apartado, re.I):
        return "control"
    return "acuerdo"


def _nombres_grupos(texto):
    """«Socialista, Compromís y Esquerra Unida Podem» -> «Grupo Socialista, Grupo Compromís y Grupo Esquerra Unida Podem»."""
    partes = [p for p in re.split(r"\s*,\s*|\s+y\s+(?!democracia)", texto, flags=re.I) if p.strip()]
    nombres = []
    for p in partes:
        clave = _clave(p)
        g = GRUPOS.get(clave) or GRUPOS.get("G" + clave) or grupo_canonico(p)
        if g not in nombres:
            nombres.append(g)
    return nombres[0] if len(nombres) == 1 else ", ".join(nombres[:-1]) + " y " + nombres[-1]


def autor_mocion(titulo, apartado):
    """Grupo (o grupos) que presenta la moción o declaración, si se dice."""
    m = re.search(r"\((Grupos?\s[^()]+)\)", apartado or "") or re.fullmatch(r"(Grupos?\s+[^.]{3,60})", apartado or "")
    if m:  # extracto: «Mociones (Grupo Socialista)»; acta: línea «Grupo Esquerra Unida» antes del epígrafe
        return _nombres_grupos(re.sub(r"^Grupos?\s+(?:Municipal(?:es)?\s+)?", "", m.group(1)))
    m = re.search(r"\b(?:del|de\s+los)\s+grupos?\s+(?:pol[ií]tic[oa]s\s+)?(?:municipal(?:es)?\s+)?(?:de\s+)?"
                  r"(?!(?:sobre|por|para|en|de|del|relativ\w*|con|que|a|al|acerca|y|municipal\w*|pol[ií]tic\w*)\b)(\w.+?)"
                  r"(?=\s+(?:por|para|en|sobre|relativ\w*|con|que|instando|interesando|contra|de|del|a|al|acerca)\b|[,.:;(]\s*"
                  r"(?:don|doña|d\.|dª|a\s+la|por|para|en|sobre)\b|[.:;(]|$)", titulo, re.I)
    if m and len(m.group(1)) <= 80:
        return _nombres_grupos(m.group(1))
    m = re.search(r"\b(?i:del|de\s+los)\s+((?:G[A-Z][A-Za-z’'´\-]{0,10})(?:\s*(?:,|\s[yY]\s)\s*G[A-Z][A-Za-z’'´\-]{0,10})*)\b",
                  titulo)
    if m and all(_clave(x) in GRUPOS for x in re.split(r"\s*,\s*|\s+[yY]\s+", m.group(1))):
        return _nombres_grupos(m.group(1))
    return None


# ---------------------------------------------------------------------- descarga

def _borrar_cache(ruta):
    p = CACHE_DIR / (ruta + ".gz")
    try:
        p.unlink()
    except OSError:
        pass


def acta_texto(ctx, s):
    """Texto del acta de una sesión (None si no hay PDF)."""
    ruta = f"{CUERPO}/actas/{s['fecha']}_{s['cod']}.pdf"
    try:
        raw = ctx.fetch(_url_doc(2, s["fecha"], s["cod"]), cache=ruta, timeout=180)
    except (HTTPError, ErrorDescarga) as e:
        ctx.log(f"  ! {CUERPO} {s['fecha']}: acta no disponible ({e})")
        return None
    if not raw.startswith(b"%PDF"):
        _borrar_cache(ruta)
        ctx.log(f"  ! {CUERPO} {s['fecha']}: el acta no es un PDF")
        return None
    return ctx.pdf_texto(raw, layout=False)


def _sesiones(ctx):
    # El acta se publica cuando la aprueba el pleno siguiente (un mes o más después): se repasan los
    # últimos cuatro meses para cambiar el resultado del extracto por la votación del acta.
    desde = ctx.desde(CUERPO, margen_dias=MARGEN_DIAS)
    primero = max(PRIMER_ANYO, int(desde[:4])) if desde else PRIMER_ANYO
    for anyo in range(date.today().year, primero - 1, -1):
        try:
            sesiones = listar_sesiones(ctx, anyo)
        except (HTTPError, ErrorDescarga) as e:
            ctx.log(f"  ! {CUERPO}: no se pudo leer el listado de {anyo} ({e})")
            continue
        for s in sesiones:
            if desde and s["fecha"] < desde:
                return
            if s["fecha"] < LEGISLATURAS[6][1]:
                return
            yield s


def votaciones_sesion(ctx, s, cuentas):
    """Votaciones de los puntos de una sesión, en el orden del día."""
    esc = CUERPOS[0].escanos_de(CUERPOS[0].legislatura_de(s["fecha"]))
    ext = {}
    if s["extracto"]:
        try:
            ext = extracto(ctx, s)
        except (HTTPError, ErrorDescarga) as e:
            ctx.log(f"  ! {CUERPO} {s['fecha']}: extracto no disponible ({e})")
    texto = acta_texto(ctx, s) if s["acta"] else None
    base = dict(cuerpo=CUERPO, fecha=s["fecha"], sesion=_sesion_id(s))
    salida, usados, cubiertos = [], set(), set()
    asistentes = plantilla(texto) if texto else {}
    for codigo, cod_txt, tit_acta, apartado_acta, cuerpo in (puntos_acta(texto, ext.keys()) if texto else ()):
        votos, parecia, otras = votaciones_punto(cuerpo)
        _cod, tit_ext, res_ext, apartado_ext = ext.get(codigo, (None, None, None, ""))
        if tit_ext and not _parecidos(tit_ext, tit_acta):
            tit_ext, res_ext, apartado_ext = None, None, ""  # erratas de numeración: es otro punto
        if not votos:
            if parecia:
                cuentas["puntos con votación no reconocida"] += 1
                if cuentas["puntos con votación no reconocida"] <= 20:
                    ctx.log(f"  ? {CUERPO} {s['fecha']} {cod_txt}: votación no reconocida")
            continue
        base_num = _numero_punto(codigo)
        if base_num in cubiertos:  # código repetido por errata del acta
            cuentas["códigos de punto repetidos"] += 1
            base_num += 50
            while base_num in cubiertos:
                base_num += 1
        cubiertos.add(base_num)
        titulo = tit_ext or tit_acta.rstrip(" .")
        apartado = apartado_ext or apartado_acta
        tipo = tipo_iniciativa(titulo, apartado)
        cuentas["  puntos con otras votaciones descartadas"] += bool(otras)
        for k, (frase, siguiente, subtitulo) in enumerate(votos):
            numero = base_num + k  # por puntos: la primera ocupa el número del punto (el del extracto)
            r = analizar_frase(frase, esc, asistentes, siguiente)
            con_totales = r["a_favor"] is not None or r["en_contra"] is not None
            if r["resultado"] is None and r["a_favor"] is None:
                cuentas["votaciones sin resultado ni votos a favor"] += 1
                if cuentas["votaciones sin resultado ni votos a favor"] <= 10:
                    ctx.log(f"  ? {CUERPO} {s['fecha']} {cod_txt}: votación sin resultado ni votos a favor")
                continue
            if numero in usados:
                cuentas["números repetidos"] += 1
                continue
            usados.add(numero)
            cuentas["votaciones del acta"] += 1
            cuentas["  con totales"] += con_totales
            cuentas["  con voto por grupo"] += bool(r["grupos"])
            cuentas["  unanimidad sin recuento"] += r["unanimidad"] and not con_totales
            cuentas["  por puntos"] += bool(subtitulo)
            cuentas["  totales descartados (no cuadran)"] += bool(r["aviso"])
            cuentas["  con algún votante sin grupo reconocido"] += r["raro"]
            extra = {"caracter": s["caracter"], "punto": cod_txt, "frase": _limpio(frase)[:400]}
            if r["aviso"]:
                extra["aviso"] = r["aviso"]
            if r.get("nota"):
                extra["nota"] = r["nota"]
            if res_ext:
                extra["resultado_extracto"] = res_ext
            salida.append(Votacion(
                **base, numero=numero, titulo=titulo, subtitulo=subtitulo, tipo_iniciativa=tipo,
                autor=autor_mocion(titulo, apartado) if tipo == "mocion" else None,
                a_favor=r["a_favor"], en_contra=r["en_contra"], abstenciones=r["abstenciones"],
                asentimiento=r["unanimidad"] and not con_totales, resultado=r["resultado"], grupos=r["grupos"],
                url=_url_doc(2, s["fecha"], s["cod"]), fuente="pdf-reglas", extra=extra))
    # Puntos del extracto con resultado que no salen del acta (acta sin publicar o votación no reconocida).
    for codigo, (cod_txt, titulo, res, apartado) in ext.items():
        resultado = _resultado_html(res)
        numero = _numero_punto(codigo)
        if not resultado or numero in cubiertos or numero in usados:
            continue
        if re.match(r"(?:ruego|pregunta|toma\s+de\s+posesi)", titulo, re.I) or re.search(r"ruegos|preguntas", apartado, re.I):
            continue  # un ruego «rechazado» o una toma de posesión no son votaciones
        cuentas["resultado solo del extracto (" + ("con acta" if texto else "sin acta") + ")"] += 1
        usados.add(numero)
        tipo = tipo_iniciativa(titulo, apartado)
        salida.append(Votacion(
            **base, numero=numero, titulo=titulo, tipo_iniciativa=tipo,
            autor=autor_mocion(titulo, apartado) if tipo == "mocion" else None, resultado=resultado,
            url=_url_extracto(s["fecha"], s["cod"]), fuente="html",
            extra={"caracter": s["caracter"], "punto": cod_txt, "resultado_extracto": res}))
    salida.sort(key=lambda v: v.numero)
    return salida


def descargar(ctx):
    cuentas = Counter()
    n = 0
    try:
        for s in _sesiones(ctx):
            cuentas["sesiones"] += 1
            for v in votaciones_sesion(ctx, s, cuentas):
                yield v
                n += 1
                if ctx.limite and n >= ctx.limite:
                    return
    finally:
        ctx.log(f"{CUERPO}: " + ", ".join(f"{k} {v}" for k, v in cuentas.items()))


def documentos(ctx):
    """Un documento por acta publicada (para el extractor con LLM, si las reglas no bastan)."""
    n = 0
    for s in _sesiones(ctx):
        if not s["acta"]:
            continue
        yield Documento(cuerpo=CUERPO, fecha=s["fecha"], url=_url_doc(2, s["fecha"], s["cod"]), sesion=_sesion_id(s),
                        formato="pdf", idioma="es", titulo=f"Acta del Pleno ({s['caracter'].lower()}) de {s['fecha']}",
                        extra={"caracter": s["caracter"]})
        n += 1
        if ctx.limite and n >= ctx.limite:
            return


def texto(ctx, doc):
    """Texto del acta, con la misma caché que `descargar`."""
    m = re.search(r"fecha=(\d\d)%2F(\d\d)%2F(\d{4})&sesion=(\d+)", doc.url)
    s = {"fecha": f"{m[3]}-{m[2]}-{m[1]}", "cod": int(m[4])}
    return acta_texto(ctx, s) or ""
