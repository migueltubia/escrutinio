"""Parlamento de Canarias: iniciativas (API de datos abiertos) y votaciones del Diario de Sesiones del Pleno.

Fuentes (datos abiertos, catálogo CKAN en https://datos.parcan.es, que enlaza a la API de parcan.es)
- Iniciativas: https://www.parcan.es/api/iniciativas/<año>/<legislatura>/<TIPO>/?format=json, un
  conjunto por tipo, año y legislatura desde 1995 (IV legislatura). Cada fila trae el código
  («11L/PNLP-0343»), el extracto, la fecha de entrada, la situación y el tipo de finalización
  («Aprobada», «Rechazada», «Retirada»…). No trae el autor. La lista de conjuntos existentes sale de
  https://datos.parcan.es/api/3/action/package_list («iniciativas_tipopnlp_anio2025_xilegislatura»).
  Solo se piden los tipos que se votan en el Pleno (leyes, decretos ley, PNL, mociones, reforma del
  Reglamento, comisiones, nombramientos, debates generales, comunicaciones y planes del Gobierno,
  Cuenta General, informes a emitir por el Parlamento); no las preguntas, comparecencias, escritos
  ni los informes del Gobierno o de la Audiencia de Cuentas (miles, y ninguno llega a votarse).
- Diario de Sesiones del Pleno: https://www.parcan.es/api/pub/<legislatura>/ds/texto/?format=json
  (conjunto «diario_sesiones_por_legislatura»), un JSON por legislatura con cada diario (id_ds,
  n_ds, f_publicacion = fecha de la sesión, comprobado con la portada del PDF) y su texto en párrafos
  (orden = punto del orden del día). Cada punto empieza con el código de la iniciativa («11L/DL-0003
  CONVALIDACIÓN O DEROGACIÓN DE DECRETO LEY…»). Hay texto desde la VII legislatura (2007); de la VI
  solo 16 de 145 diarios, y de la IV y la V solo la lista (número y fecha). El PDF de cada diario
  está en https://www.parcan.es/files/pub/diarios/<leg>l/<nnn>/ds<nnn>.pdf y la página en
  /pub/ds.py/<año>/<n>/.
  Ningún conjunto de datos trae votaciones estructuradas: no hay voto nominal ni por grupo. El
  Diario sí da el recuento de cada votación en una frase bastante regular («Votos emitidos, 67: sí,
  4; no, 63; abstenciones, cero», «Resultado: 53 presentes; 34 a favor, ninguno en contra y 19
  abstenciones», «59 votos emitidos: 11, sí; 33, no; 15 abstenciones»).

Qué se genera
- descargar(): Iniciativa de los tipos votables y Votacion sacadas con reglas del texto del Diario:
  totales (sí, no, abstenciones y votos emitidos o presentes), resultado si el presidente lo dice
  («queda rechazada»), expediente y título del punto del orden del día que se está tratando, autor
  si el título lo dice («del Grupo Parlamentario Popular»), subtítulo con lo que se vota cuando se
  anuncia («votación de la enmienda del Grupo Parlamentario VOX») o el nombre del candidato en las
  elecciones, y la frase original del recuento en extra["texto"]. También las aprobaciones «por
  unanimidad» o «por asentimiento» sin recuento que siguen a una llamada a votar (asentimiento=True).
  `sesion` = número del diario (una sesión de dos días tiene dos diarios); `numero` = orden de la
  votación en el diario. De la VII legislatura en adelante (y los 16 diarios con texto de la VI) se
  parte del texto en párrafos del JSON (fuente «json-reglas»); de la IV a la VI, sin ese texto, se
  saca el mismo recuento de la transcripción literal del PDF del diario (fuente «pdf-reglas»),
  reconstruida en párrafos equivalentes: un párrafo por frase de cada orador y por epígrafe en
  mayúsculas (sin código de iniciativa hasta la VI, así que el tipo, cuando se puede, sale de las
  propias palabras del epígrafe: «proposición no de ley», «moción»…). Se parte siempre de donde
  empieza la transcripción («Se abre la sesión…»/«Se reanuda la sesión…»), sin usar el resumen previo
  (SUMARIO) que traen los diarios más antiguos, que no da recuentos y en dos columnas descoloca el
  texto de pdftotext.
  Reglas contra errores: se descartan los recuentos que suman más que los escaños o que se
  contradicen, y un segundo recuento sin nueva llamada a votar y casi igual al anterior se toma
  como corrección del primero (votos telemáticos, «perdón, 19 abstenciones»), no como otra votación.
- documentos(): para el LLM, solo los diarios en los que se vota pero no se ha reconocido ningún
  recuento (con el texto del JSON o, si no lo hay, del PDF, vía texto()): las investiduras y
  elecciones de cargos por papeleta o llamamiento (sin recuento de sí/no/abstenciones), las
  votaciones secretas y los recuentos con erratas que no cuadran. Las sesiones sin ninguna
  votación (control al Gobierno, comparecencias, preguntas) no se mandan.

Limitaciones: recuentos con erratas en el propio Diario (sumas imposibles) se pierden; las
votaciones a mano alzada sin recuento solo se recogen si se dice «por unanimidad/asentimiento»; el
subtítulo solo existe si el presidente anuncia qué se vota. Los títulos de la VIII a la XI vienen
en mayúsculas en el Diario (el título bueno está en la iniciativa); en la IV y la V, sin código de
iniciativa, el expediente queda sin determinar y el tipo, a veces.
"""

import json
import re

from ...territorio import Cuerpo, num_parlamento, romano
from ..contexto import Contexto, ErrorDescarga
from ..modelo import Documento, Iniciativa, Votacion

CUERPO = "parl-CN"
WEB = "https://www.parcan.es"
CKAN = "https://datos.parcan.es/api/3/action/package_list"

# Fecha de la sesión constitutiva (diario número 1). 60 escaños hasta 2019 y 70 desde la X.
LEGISLATURAS = {
    4: ("IV", "1995-06-27", "1999-07-07", 60),
    5: ("V", "1999-07-07", "2003-06-18", 60),
    6: ("VI", "2003-06-18", "2007-06-25", 60),
    7: ("VII", "2007-06-25", "2011-06-21", 60),
    8: ("VIII", "2011-06-21", "2015-06-23", 60),
    9: ("IX", "2015-06-23", "2019-06-25", 60),
    10: ("X", "2019-06-25", "2023-06-27"),
    11: ("XI", "2023-06-27", None),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("CN"), "Parlamento de Canarias", "Parlamento (Canarias)", "autonomico", "CN", 70,
           LEGISLATURAS, web=WEB),
]

ACTIVO = True
NOTAS = __doc__

# Tipo de iniciativa del Parlamento -> clave de modelo.TIPOS_INICIATIVA. Los que no están aquí no
# se votan en el Pleno (preguntas, comparecencias, escritos…) y no se piden a la API.
TIPOS = {
    "PL": "pl", "PPL": "ppl", "PPLC": "ppl", "PPLE": "ppl", "PREA": "ppl", "PPLP": "ilp", "PPLA": "ilp",
    "DL": "dl", "PNL": "pnl", "PNLP": "pnl", "M": "mocion",
    "PRRP": "organizacion", "AGND": "organizacion", "AGOR": "organizacion", "AGCE": "organizacion",
    "AGIV": "organizacion", "AGOC": "organizacion", "AGSC": "organizacion",
    "DGEN": "control", "DGR": "control", "CG": "control", "PPG": "control", "IACG": "control",
    "IAE": "acuerdo", "ADCI": "acuerdo",
}
# Tipos que solo aparecen en el Diario (para clasificar votaciones, no para pedir iniciativas).
TIPOS_DIARIO = {**TIPOS, "PNLC": "pnl", "RM": "organizacion", "NGI": "organizacion", "C": "control",
                "C/P": "control", "I": "control", "PO/P": "control", "SD": "control", "IG": "control",
                "IAC": "control", "IDC": "control"}


def url_pdf(leg, n):
    return f"{WEB}/files/pub/diarios/{leg}l/{n:03d}/ds{n:03d}.pdf"


def _escanos(leg):
    return CUERPOS[0].escanos_de(leg)


# ---------------------------------------------------------------------------- iniciativas

def _conjuntos(ctx):
    """{(legislatura, año, TIPO)} de los conjuntos de iniciativas publicados en el catálogo."""
    d = json.loads(ctx.fetch(CKAN, cache=f"{CUERPO}/ckan_package_list.json", caduca_dias=1))
    romanos = {romano(n).lower(): n for n in range(1, 30)}
    out = set()
    for nombre in d.get("result") or []:
        m = re.fullmatch(r"iniciativas_tipo([a-z]+)_anio(\d{4})_([ivxl]+)legislatura", nombre)
        if m and m.group(1).upper() in TIPOS and romanos.get(m.group(3)) in LEGISLATURAS:
            out.add((romanos[m.group(3)], int(m.group(2)), m.group(1).upper()))
    return out


def _iniciativas(ctx, leg, anios):
    actual = LEGISLATURAS[leg][2] is None
    for anio, tipo in anios:
        url = f"{WEB}/api/iniciativas/{anio}/{leg}/{tipo}/?format=json"
        filas = json.loads(ctx.fetch(url, cache=f"{CUERPO}/iniciativas/{leg}/{tipo}_{anio}.json",
                                     caduca_dias=1 if actual else None) or b"[]")
        for f in filas:
            exp = (f.get("id_iniciativa") or "").strip()
            if not exp:
                continue
            titulo = (f.get("extracto") or "").strip() or exp
            clave = TIPOS[tipo]
            if clave == "pl" and re.search(r"(?i)presupuestos generales de la comunidad", titulo):
                clave = "presupuesto"
            yield Iniciativa(
                cuerpo=CUERPO, expediente=exp, titulo=titulo, legislatura=int(f.get("legislatura") or leg),
                tipo_iniciativa=clave, autor=None, fecha_presentacion=f.get("f_creacion") or None,
                resultado=(f.get("tipo_finalizacion") or "").strip() or (f.get("situacion") or "").strip() or None,
                url=f"{WEB}/iniciativas/ver.py?id_iniciativa={exp}",
                extra={k: f.get(k) for k in ("situacion", "procedimiento", "tipo_descripcion") if f.get(k)},
            )


# ---------------------------------------------------------------------------- Diario de Sesiones

_MEMO = {}


def _diarios(ctx, leg):
    """Diarios de una legislatura (JSON de la API, con el texto por párrafos)."""
    if leg not in _MEMO:
        _MEMO.clear()  # un JSON por legislatura ocupa cientos de MB en memoria: solo el último
        actual = LEGISLATURAS[leg][2] is None
        raw = ctx.fetch(f"{WEB}/api/pub/{leg}/ds/texto/?format=json", cache=f"{CUERPO}/ds/ds_{leg}.json",
                        caduca_dias=1 if actual else None, timeout=300)
        _MEMO[leg] = json.loads(raw)
    return _MEMO[leg]


def _limpia(t):
    t = (t or "").replace(" ", " ").replace("\xa0", " ").replace("­", "")
    return re.sub(r"\s+", " ", t).strip().strip("'").strip()


# --- recuentos ----------------------------------------------------------------

NUMEROS = {"cero": 0, "ninguno": 0, "ninguna": 0, "ningún": 0, "ningun": 0, "un": 1, "uno": 1, "una": 1, "dos": 2,
           "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8, "nueve": 9, "diez": 10}
_NUM = r"(\d+|" + "|".join(sorted(NUMEROS, key=len, reverse=True)) + r")"
# (clave, patrón, admite texto detrás: «40 votos favorables a la convalidación del decreto»)
_CLAVES = [
    ("presentes", r"(?:votos?\s+)?(?:totales\s+)?(?:emitidos|presentes|presenciales|totales|votantes)"
                  r"(?:\s+(?:presentes|presenciales|totales|emitidos))*|votos", False),
    ("si", r"(?:votos?\s+)?(?:a\s+favor|afirmativos?|favorables?|s[ií]es)", True),
    ("si", r"(?:votos?\s+)?s[ií]", False),
    ("no", r"(?:votos?\s+)?(?:en\s+contra|negativos?|noes)", True),
    ("no", r"(?:votos?\s+)?no", False),
    ("abstencion", r"(?:votos?\s+de\s+)?abstenci[oó]n(?:es)?", True),
]
_NUM_CLAVE = [(k, re.compile(r"(?:.*\s)?" + _NUM + r"\s*(?:votos?\s+)?(?:" + p + ")" + (r"\b.*" if cola else r"\s*"), re.I))
              for k, p, cola in _CLAVES]
_CLAVE_NUM = [(k, re.compile(r"(?:.*\s)?(?:" + p + r")(?:\s+(?:han\s+sido|son|es|fueron))?\s*" + _NUM + r"\s*", re.I))
              for k, p, _c in _CLAVES]
_SOLO_CLAVE = [(k, re.compile(r"(?:.*\s)?(?:" + p + r")\s*", re.I)) for k, p, _c in _CLAVES]
_SOLO_NUM = re.compile(r"(?:.*\s)?" + _NUM + r"(?:\s+m[aá]s\b.*)?", re.I)
_PREFILTRO = re.compile(r"(?i)abstenci|en contra|\bnoe?s?\b\s*[,;]|[,;:]\s*no\b|emitidos|presentes|negativos|favorables")
_HAY_NUM = re.compile(r"(?i)\d|\bcero\b|\bning[uú]n")
_CORRIGE = re.compile(r"(?i)\b(?:perd[oó]n|corrijo|rectifico|repito|mejor dicho)\b")


def _valor(t):
    t = t.lower()
    return int(t) if t.isdigit() else NUMEROS[t]


def _clasifica(p):
    if len(p) > 90:
        return ("otro", None, None)
    for k, r in _NUM_CLAVE:
        m = r.fullmatch(p)
        if m:
            return ("par", k, _valor(m.group(1)))
    for k, r in _CLAVE_NUM:
        m = r.fullmatch(p)
        if m:
            return ("par", k, _valor(m.group(1)))
    for k, r in _SOLO_CLAVE:
        if r.fullmatch(p):
            return ("clave", k, None)
    m = _SOLO_NUM.fullmatch(p)
    if m:
        return ("num", None, _valor(m.group(1)))
    return ("otro", None, None)


def _empareja(trozo, res, corrige):
    """Empareja claves y números de un trozo («sí, 38», «11, sí», «38 votos a favor»)."""
    cs = []
    for p in re.split(r",|\s+y\s+", trozo):
        p = re.sub(r"\s+", " ", re.sub(r"[()¿?¡!.«»\"'“”]", " ", p)).strip()
        if p:
            cs.append(_clasifica(p))
    i = 0
    while i < len(cs):
        tipo, k, v = cs[i]
        if tipo == "clave" and i + 1 < len(cs) and cs[i + 1][0] == "num":
            v = cs[i + 1][2]
            i += 1
        elif tipo == "num" and i + 1 < len(cs) and cs[i + 1][0] == "clave":
            k = cs[i + 1][1]
            i += 1
        elif tipo != "par":
            i += 1
            continue
        if k in res and res[k] != v and not corrige:
            return False
        res[k] = v
        i += 1
    return True


def recuento(frase, escanos=70):
    """{si, no, abstencion, presentes} de una frase de resultado de votación, o None."""
    if len(frase) > 400 or not _PREFILTRO.search(frase) or not _HAY_NUM.search(frase):
        return None
    res, corrige = {}, bool(_CORRIGE.search(frase))
    for trozo in re.split(r"[;:]", frase):
        if not _empareja(trozo, res, corrige):
            return None
    if "si" not in res and {"presentes", "no", "abstencion"} <= set(res):
        res["si"] = res["presentes"] - res["no"] - res["abstencion"]
        res["si_deducido"] = True
    if "si" not in res or not ({"no", "abstencion", "presentes"} & set(res)):
        return None
    if set(res) == {"si", "presentes"} and res["si"] > res["presentes"]:
        return None
    if res["si"] < 0 or sum(res.get(k, 0) for k in ("si", "no", "abstencion")) > escanos or res.get("presentes", 0) > escanos:
        return None
    return res


def _frases(texto):
    return [f for f in re.split(r"(?<=[.!?])\s+(?=[A-ZÁÉÍÓÚÑ¿¡(])", texto) if f.strip()]


# --- contexto de cada votación -----------------------------------------------

# Código de iniciativa («11L/PNLP-0343»); el Diario a veces mete espacios («11L /M-0028», «11L/AGCE- 0001»).
CODIGO_RE = re.compile(r"^[\s·•\-–]*(\d{1,2})\s?L\s?/\s?([A-Z]+(?:\s?/\s?[A-Z]+)?)\s?-\s?(\d+)\b[\s.,:\-–]*(.*)$", re.S)
CODIGOS_RE = re.compile(r"\b\d{1,2}L/[A-Z]+(?:/[A-Z]+)?-\d+\b")
NUEVA = re.compile(r"(?i)votaci[oó]n|votamos|votar\b|enmienda|\bpunto\b|secci[oó]n|art[ií]culo|disposici[oó]n|"
                   r"propuesta|t[ií]tulo|pre[aá]mbulo|exposici[oó]n de motivos|\(pausa|timbre|siguiente")
LLAMADA = re.compile(r"(?i)llamamos a votaci|comienza la votaci|\bvotamos\b|se somete|someto|sometemos|\(pausa|timbre|"
                     r"¿\s*votos a favor|(?:procedemos|pasamos|vamos) a (?:la )?votaci|lanzo (?:la )?votaci|"
                     r"iniciamos la votaci|votaci[oó]n (?:de|del|separada|conjunta)\b|resultado de la votaci")
# Llamada inequívoca a votar (para saber si en un diario sin recuentos reconocidos se votó).
VOTA = re.compile(r"(?i)llamamos a votaci|comienza la votaci|s[eo]m[eé]t\w* a votaci|resultado de la votaci|"
                  r"(?:procedemos|pasamos|vamos) a (?:la )?votaci|lanzo (?:la )?votaci|iniciamos la votaci|"
                  r"llamada a (?:la )?votaci|¿\s*votos a favor")
ANUNCIO = [re.compile(r"(?i)\b(votaci[oó]n\s+(?:de|del|sobre)\s+(?!nuevo\b).{4,220}?)(?=[.:;?(]|\s+votamos|\s+comienza|$)"),
           re.compile(r"(?i)¿\s*votos a favor\s+((?:de|del)\s+.{4,220}?)\s*\?")]
RESULTADO = re.compile(r"(?i)\b(?:queda|quedan|resulta|resultan)\b[^.]{0,50}?\b(aprobad|rechazad|convalidad|derogad|"
                       r"elegid|designad|otorgad)|^\W*(aprobad|rechazad)|\bno\s+(?:se\s+aprueba|prospera)")
UNANIME = re.compile(r"(?i)^\W*(?:(?:queda|quedan)\s+(?:,?\s*por\s+(?:lo\s+)?tanto,?\s*)?)?(?:aprobad[oa]s?|se aprueban?)"
                     r"\b[^.]{0,80}?\bpor\s+(unanimidad|asentimiento)")
ORADOR_RE = re.compile(r"^(?:El|La)\s+se[ñn]ora?\s+[^:]{2,90}?:\s*")
NOMBRE_RE = re.compile(r"(?:[Yy]\s+)?(?:Don|Doña|D\.ª|Dña\.|D\.)?\s*[A-ZÁÉÍÓÚÑ][a-záéíóúñü\-]+"
                       r"(?:\s+(?:de\s+la\s+|de\s+los\s+|de\s+|del\s+|y\s+)?[A-ZÁÉÍÓÚÑ][a-záéíóúñü\-]+){1,5}")


def _resultado(texto):
    m = RESULTADO.search(texto or "")
    if not m:
        return None
    raiz = (m.group(1) or m.group(2) or "").lower()
    return "rechazada" if (raiz in ("rechazad", "derogad") or not raiz) else "aprobada"


def _cabecera(texto):
    """(expediente, tipo, título, otros expedientes) de la cabecera de un punto del orden del día."""
    m = CODIGO_RE.match(texto)
    if m:
        tipo = re.sub(r"\s", "", m.group(2))
        exp = f"{m.group(1)}L/{tipo}-{int(m.group(3)):04d}"  # como en la API: 4 cifras
        otros = [c for c in CODIGOS_RE.findall(m.group(4)) if c != exp]
        return exp, tipo, (m.group(4).strip(" .") or exp)[:1000], otros
    return None, None, texto.strip("·•- .")[:1000], []


def _autor(titulo):
    m = re.search(r"(?i)\b(?:del|de\s+los)\s+(grupos?\s+parlamentarios?\s+[^,]+?)\s*,?\s+(?:sobre|consecuencia|relativa|por\s+el)\b",
                  titulo)
    return m.group(1).strip() if m else None


_TIPO_TEXTO_RE = [
    # de la IV a la VI legislatura el Diario no lleva código de iniciativa: el tipo, cuando se puede, sale
    # de las mismas palabras del epígrafe (mayúsculas, como los títulos de la VIII a la XI).
    ("pnl", r"proposici[oó]n\s+no\s+de\s+ley"),
    ("mocion", r"\bmoci[oó]n\b"),
    ("dl", r"decreto[\s-]*ley"),
    ("ppl", r"proposici[oó]n\s+de\s+ley"),
    ("pl", r"proyecto\s+de\s+ley"),
    ("acuerdo", r"\bdictamen\b|propuesta\s+de\s+acuerdo"),
    ("control", r"interpelaci[oó]n|comparecencia|propuestas?\s+de\s+resoluci[oó]n|informe\s+(?:del|extraordinario)"),
    ("organizacion", r"reglamento\s+de\s+la\s+c[aá]mara|elecci[oó]n|designaci[oó]n|nombramiento"),
]


def _tipo_por_texto(t):
    for clave, patron in _TIPO_TEXTO_RE:
        if re.search(patron, t):
            return clave
    return None


def _tipos(tipo_codigo, titulo, sub):
    t = f"{titulo} {sub or ''}".lower()
    clave = TIPOS_DIARIO.get(tipo_codigo or "") if tipo_codigo else _tipo_por_texto(t)
    if re.search(r"investidura|candidat[oa] a la presidencia del gobierno|moci[oó]n de censura|cuesti[oó]n de confianza", t):
        clave = "investidura"
    elif clave == "pl" and "presupuestos generales de la comunidad" in t:
        clave = "presupuesto"
    s = (sub or "").lower()
    voto = None
    if clave == "investidura":
        voto = "investidura"
    elif clave == "pnl":
        voto = "enmiendas" if "enmienda" in s else "pnl"
    elif clave == "mocion":
        voto = "enmiendas" if "enmienda" in s else "mocion"
    elif clave == "dl":
        voto = "tramitacion_ley" if re.search(r"tramita\w*\s+como\s+proyecto", s) else "convalidacion"
    elif clave in ("pl", "ppl", "ilp", "presupuesto"):
        if re.search(r"toma en consideraci", t):
            voto = "toma_consideracion"
        elif re.search(r"enmiendas? a la totalidad|debate de totalidad|primera lectura", t):
            voto = "totalidad"
        elif "enmienda" in s or "voto particular" in s or "votos particulares" in s:
            voto = "enmiendas"
        elif re.search(r"votaci[oó]n final|de conjunto|en su conjunto|totalidad del proyecto", s):
            voto = "conjunto"
        elif re.search(r"pre[aá]mbulo|exposici[oó]n de motivos|art[ií]culo|disposici[oó]n|t[ií]tulo|anexo|secci[oó]n|dictamen", s):
            voto = "articulado"
    elif tipo_codigo == "AGND" or re.search(r"elecci[oó]n|designaci[oó]n|nombramiento", t):
        voto = "nombramiento"
    elif clave == "organizacion":
        voto = "organizacion"
    elif clave == "control" and (tipo_codigo in ("DGEN", "DGR", "CG", "PPG", "IG", "IAC", "IACG", "IDC")
                                 or re.search(r"propuestas? de resoluci[oó]n", t)):
        voto = "control"  # lo que se vota son propuestas de resolución
    return clave, voto


def _etiqueta(frase):
    """Nombre que precede al recuento en las elecciones de personas («Doña Ana Pérez: 61 síes…»)."""
    f = ORADOR_RE.sub("", frase)
    if ":" in f:
        pre = f.split(":", 1)[0].strip()
        if NOMBRE_RE.fullmatch(pre):
            return re.sub(r"^[Yy]\s+", "", pre)
    return None


_ANALISIS = {}


def analizar_diario(ds, leg):
    """Votaciones de un diario (lista de dicts) y si en él se llama a votar. Sin red: solo el texto."""
    clave = (leg, ds.get("id_ds"), len(ds.get("parrafos") or []))
    if clave not in _ANALISIS:
        _ANALISIS[clave] = _analizar(ds, leg)
    return _ANALISIS[clave]


def _analizar(ds, leg):
    escanos = _escanos(leg)
    votos, hay_votacion = [], False
    cab = (None, None, None, [])
    orden = object()
    contexto = []                 # frases desde la última votación o cabecera (para el anuncio)
    ultimo, desde_ultimo = None, 99  # última votación y párrafos desde ella
    parrafos = [(_limpia(p.get("texto")), p.get("orden")) for p in ds.get("parrafos") or []]
    for i, (t, o) in enumerate(parrafos):
        if not t:
            continue
        cambia = o != orden
        orden = o
        if CODIGO_RE.match(t) and not recuento(t, escanos):
            cab, contexto, ultimo = _cabecera(t), [], None
            continue
        if cambia and not t.startswith("("):
            # Punto nuevo sin código: su primer párrafo es el título si lo parece; si no, sin cabecera.
            corta = len(t) <= 700 and not ORADOR_RE.match(t)
            cab, contexto, ultimo = (_cabecera(t) if corta else (None, None, None, [])), [], None
            if corta:
                continue
        desde_ultimo += 1
        previo = " ".join(p for p, _o in parrafos[max(0, i - 3):i])
        if VOTA.search(t):
            hay_votacion = True
        encontrado = False
        for f in _frases(t):
            r = recuento(f, escanos)
            if not r:
                contexto.append(f)
                continue
            etiqueta = _etiqueta(f)
            entre = " ".join(contexto)
            siguiente = parrafos[i + 1][0] if i + 1 < len(parrafos) else ""
            resultado = _resultado(f + " " + t.split(f, 1)[-1][:300] + " " + siguiente[:200])
            if (ultimo and ultimo["r"] and not etiqueta and not ultimo["etiqueta"] and desde_ultimo <= 5
                    and not NUEVA.search(entre)
                    and sum(abs(r.get(k, 0) - ultimo["r"].get(k, 0)) for k in ("si", "no", "abstencion")) <= 4):
                # Segundo recuento sin nueva llamada y casi igual: corrige el anterior (voto telemático…).
                ultimo.update(r=r, texto=f, corregido=True, resultado=resultado or ultimo["resultado"])
            elif ultimo is None and desde_ultimo > 6 and not LLAMADA.search(previo + " " + entre[-400:]):
                contexto.append(f)  # recuento citado en un discurso, lejos de cualquier llamada a votar
                continue
            else:
                anuncio = None
                for rx in ANUNCIO:
                    for m in rx.finditer(entre[-600:]):
                        anuncio = m.group(1)
                ultimo = {"r": r, "texto": f, "cab": cab, "anuncio": anuncio, "etiqueta": etiqueta, "resultado": resultado}
                votos.append(ultimo)
            encontrado = hay_votacion = True
            contexto, desde_ultimo = [], 0
        if encontrado:
            continue
        # Aprobación sin recuento («Aprobada por unanimidad», «queda aprobado por asentimiento»).
        m = UNANIME.search(t)
        if m and len(t) < 200 and desde_ultimo > 1 and LLAMADA.search(previo):
            ultimo = {"r": None, "texto": t, "cab": cab, "anuncio": None, "etiqueta": None, "resultado": "aprobada",
                      "forma": m.group(1).lower()}
            votos.append(ultimo)
            contexto, desde_ultimo = [], 0
    return votos, hay_votacion


def _votaciones_diario(ds, leg):
    fecha = ds["f_publicacion"]
    n_ds = int(ds["n_ds"])
    fuente = "pdf-reglas" if ds.get("pdf") else "json-reglas"
    votos, _hay = analizar_diario(ds, leg)
    for numero, v in enumerate(votos, 1):
        exp, tipo_cod, titulo, otros = v["cab"]
        sub = v["etiqueta"] or (v["anuncio"][0].upper() + v["anuncio"][1:] if v["anuncio"] else None)
        titulo = titulo or sub or f"Votación {numero} del Diario de Sesiones {n_ds}"
        clave, voto = _tipos(tipo_cod, titulo, sub)
        r = v["r"] or {}
        extra = {"id_ds": ds.get("id_ds"), "texto": v["texto"][:400]}
        if otros:
            extra["otros_expedientes"] = otros
        if v.get("corregido"):
            extra["recuento_corregido"] = True
        if r.get("si_deducido"):
            extra["si_deducido"] = True
        if v.get("forma"):
            extra["forma"] = v["forma"]
        yield Votacion(
            cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=n_ds, numero=numero, legislatura=leg, subtitulo=sub,
            expediente=exp, tipo_iniciativa=clave, tipo_votacion=voto, autor=_autor(titulo),
            a_favor=r.get("si"), en_contra=r.get("no"), abstenciones=r.get("abstencion"), presentes=r.get("presentes"),
            asentimiento=v["r"] is None, resultado=v["resultado"], url=url_pdf(leg, n_ds), fuente=fuente,
            extra=extra,
        )


# --- diarios sin texto JSON (IV a VI legislatura): párrafos reconstruidos del PDF ---------------
#
# De la IV a la VI legislatura (1995-2007, salvo 16 diarios de la VI) la API no da el texto en
# párrafos, así que hay que sacarlo del PDF con pdftotext (sin -layout: los epígrafes en dos
# columnas del SUMARIO inicial salen mezclados, pero la transcripción literal de la sesión, que es
# lo único que se usa, va a una columna). El SUMARIO (un resumen sin recuentos, previo a la
# transcripción) no se usa: se parte del «(Se abre la sesión...)» o «(Se reanuda la sesión...)» con
# que empieza la transcripción literal, se quitan las cabeceras y pies de página repetidos y el
# texto que queda se junta en «párrafos» (turno de cada orador, cada epígrafe en mayúsculas y cada
# acotación entre paréntesis) igual que los que da el JSON, para que los analice el mismo
# `_analizar`. Sin código de iniciativa (no se usa hasta la VI): el epígrafe es el único título, y
# el tipo, cuando se puede, sale de sus propias palabras (`_tipo_por_texto`).

_RUIDO_PDF_RE = re.compile(r"(?i)^(?:n[uú]m\.?\s*\d+\s*/\s*\d+|diario de sesiones del parlamento de canarias)$")
_FECHA_PDF_RE = re.compile(r"(?i)^(?:(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo),?\s+)?"
                           r"\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4}$")
INICIO_CUERPO_RE = re.compile(r"(?i)\((?:se\s+abre|se\s+reanuda|comienza|se\s+inicia)\s+la\s+sesi[oó]n\b")


_CODIGO_EN_LINEA_RE = re.compile(r"\s*(?=\b\d{1,2}L/[A-Z]+(?:/[A-Z]+)?-\d+\b)")


def _lineas_pdf(texto):
    """Líneas útiles de la transcripción literal de un diario: sin el SUMARIO ni cabeceras de página.

    Desde la VI legislatura el epígrafe empieza por el código de la iniciativa («10L/C/P-1091 Comparecencia
    del señor consejero…»), y pdftotext a veces lo deja pegado a la frase anterior sin salto de línea: se
    corta ahí, para que quede como el principio de una línea (y de un epígrafe) nuevos.
    """
    m = INICIO_CUERPO_RE.search(texto)
    cuerpo = texto[m.start():] if m else texto
    out = []
    for ln in cuerpo.replace("\f", "\n").splitlines():
        ln = _limpia(ln)
        if not ln or _RUIDO_PDF_RE.match(ln) or _FECHA_PDF_RE.match(ln):
            continue
        out.extend(p for p in _CODIGO_EN_LINEA_RE.split(ln) if p)
    return out


def _turno_pdf(lineas, k, maximo=3):
    """(texto, líneas consumidas) si en la línea k empieza el turno de un orador («El señor XXX:»),
    uniendo hasta `maximo` líneas por si el nombre se parte («El señor SECRETARIO...\\n(Apellido):»)."""
    for n in range(1, min(maximo, len(lineas) - k) + 1):
        bloque = " ".join(lineas[k:k + n])
        if ORADOR_RE.match(bloque):
            return bloque, n
    return None


def _es_cabecera_pdf(bloque):
    mayus = len(re.findall(r"[A-ZÁÉÍÓÚÑÜ]", bloque))
    minus = len(re.findall(r"[a-záéíóúñü]", bloque))
    return mayus >= 8 and minus <= max(2, mayus * 0.08)


def _cabecera_pdf(lineas, k, maximo=12):
    """(texto, líneas consumidas) si en la línea k empieza un epígrafe: un bloque que empieza por el
    código de la iniciativa (desde la VI legislatura) o, si no lo hay, casi todo en mayúsculas y que
    acaba en punto, como los títulos de los diarios de la VIII a la XI antes de pasar por la API.
    Con código, hasta 12 líneas: las comparecencias llevan un epígrafe largo («…dirigida al Sr.
    consejero de…»); sin él, como antes, para no confundir un párrafo largo con un epígrafe."""
    if lineas[k].startswith("(") or ORADOR_RE.match(lineas[k]):
        return None
    con_codigo = bool(CODIGO_RE.match(lineas[k]))
    tope = maximo if con_codigo else 6
    bloque = ""
    for n in range(1, min(tope, len(lineas) - k) + 1):
        if n > 1 and (lineas[k + n - 1].startswith("(") or ORADOR_RE.match(lineas[k + n - 1])):
            return None  # lo anterior no cerró como epígrafe: empieza ya el turno de un orador
        bloque = f"{bloque} {lineas[k + n - 1]}".strip()
        if len(bloque) > (1000 if con_codigo else 500):
            return None
        if bloque.endswith((".", ":")):
            return (bloque, n) if (con_codigo or _es_cabecera_pdf(bloque)) else None
    return None


_FRASE_PDF_RE = re.compile(r"(?<=[.!?)])\s+(?=[A-ZÁÉÍÓÚÑ¿¡(])")


def _parrafos_pdf(texto):
    """[(texto, orden)] de la transcripción de un diario sin JSON, reconstruidos del PDF: un párrafo
    por frase de un turno de un orador y por epígrafe, como el JSON de la API (que da los párrafos
    sueltos, no discursos enteros). `orden` cambia en cada epígrafe nuevo, para que `_analizar`
    reconozca dónde empieza cada punto."""
    lineas = _lineas_pdf(texto)
    parrafos, orden = [], 0
    buf = ""

    def agrega(s):
        nonlocal buf
        buf = f"{buf[:-1]}{s}" if buf.endswith("-") and s[:1].islower() else f"{buf} {s}".strip()

    def cierra():
        nonlocal buf
        for f in _FRASE_PDF_RE.split(buf):
            f = _limpia(f)
            if f:
                parrafos.append((f, orden))
        buf = ""

    k = 0
    while k < len(lineas):
        turno = _turno_pdf(lineas, k)
        if turno:
            cierra()
            buf = turno[0]
            k += turno[1]
            continue
        cab = _cabecera_pdf(lineas, k)
        if cab:
            cierra()
            orden += 1
            parrafos.append((cab[0], orden))
            k += cab[1]
            continue
        agrega(lineas[k])
        k += 1
    cierra()
    return parrafos


_DS_PDF = {}


def _ds_pdf(ctx, leg, n_ds, fecha):
    """ds sintético (con la misma forma que los del JSON) de un diario sin texto estructurado, leyendo
    su PDF; en caché, como `_diarios`, para no repetir la conversión a texto en la misma ejecución."""
    clave = (leg, n_ds)
    if clave not in _DS_PDF:
        url = url_pdf(leg, n_ds)
        raw = ctx.fetch(url, cache=f"{CUERPO}/docs/{Contexto.clave(url)}.pdf", timeout=120)
        parrafos = []
        if raw[:5] == b"%PDF-":
            texto = Contexto.pdf_texto(raw, layout=False)
            parrafos = [{"texto": t, "orden": o} for t, o in _parrafos_pdf(texto)]
        _DS_PDF[clave] = {"f_publicacion": fecha, "n_ds": n_ds, "id_ds": f"pdf-{leg}-{n_ds}", "parrafos": parrafos,
                          "pdf": True}
    return _DS_PDF[clave]


def _legislaturas(desde):
    for leg in sorted(LEGISLATURAS, reverse=True):
        fin = LEGISLATURAS[leg][2]
        if desde and fin and fin < desde:
            break
        yield leg


def descargar(ctx):
    desde = ctx.desde(CUERPO)
    conjuntos = _conjuntos(ctx)
    n = 0
    for leg in _legislaturas(desde):
        # Iniciativas: todas en una recogida completa; en una incremental, las de este año y el anterior
        # (su situación cambia). Para probar (límite), solo el año más reciente.
        anios = sorted(((a, t) for lg, a, t in conjuntos if lg == leg), reverse=True)
        if desde:
            anios = [(a, t) for a, t in anios if a >= int(desde[:4]) - 1]
        if ctx.limite and anios:
            anios = [(a, t) for a, t in anios if a == anios[0][0]]
        yield from _iniciativas(ctx, leg, anios)
        for ds in sorted(_diarios(ctx, leg), key=lambda d: (d["f_publicacion"], d["n_ds"]), reverse=True):
            if desde and ds["f_publicacion"] < desde:
                break
            if not ds.get("parrafos"):
                # IV a VI legislatura (o alguno de la VI sin JSON): se intenta con el texto del PDF.
                try:
                    ds = _ds_pdf(ctx, leg, int(ds["n_ds"]), ds["f_publicacion"])
                except ErrorDescarga as e:
                    ctx.log(f"  ! {CUERPO}: diario {ds['n_ds']} ({ds['f_publicacion']}): {e}")
                    continue
                if not ds.get("parrafos"):
                    continue
            for v in _votaciones_diario(ds, leg):
                yield v
                n += 1
                if ctx.limite and n >= ctx.limite:
                    return


def documentos(ctx):
    desde = ctx.desde(CUERPO)
    n = 0
    for leg in _legislaturas(desde):
        for ds_api in sorted(_diarios(ctx, leg), key=lambda d: (d["f_publicacion"], d["n_ds"]), reverse=True):
            fecha = ds_api["f_publicacion"]
            if desde and fecha < desde:
                break
            nds = int(ds_api["n_ds"])
            es_json = bool(ds_api.get("parrafos"))
            ds = ds_api
            if not es_json:
                try:
                    ds = _ds_pdf(ctx, leg, nds, fecha)
                except ErrorDescarga as e:
                    ctx.log(f"  ! {CUERPO}: diario {nds} ({fecha}): {e}")
                    ds = ds_api  # no se pudo comprobar: se manda igualmente, por si tiene votos
            if ds.get("parrafos"):
                votos, hay_votacion = analizar_diario(ds, leg)
                if votos or not hay_votacion:
                    continue  # lo cubren las reglas, o no se vota (sesión de control sin votaciones)
            yield Documento(
                cuerpo=CUERPO, fecha=fecha, url=url_pdf(leg, nds), sesion=nds, formato="pdf", idioma="es",
                titulo=f"Diario de Sesiones del Parlamento de Canarias núm. {nds} ({romano(leg)} legislatura)",
                legislatura=leg,
                extra={"id_ds": ds_api.get("id_ds"), "texto_json": es_json,
                       "pagina": f"{WEB}/pub/ds.py/{fecha[:4]}/{nds}/"},
            )
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


def texto(ctx, doc):
    """Texto del diario: el del JSON de la API si lo hay (más limpio que el PDF); si no, el del PDF."""
    if doc.extra.get("texto_json"):
        for ds in _diarios(ctx, doc.legislatura):
            if ds.get("id_ds") == doc.extra.get("id_ds"):
                return "\n".join(_limpia(p.get("texto")) for p in ds.get("parrafos") or [])
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/docs/{Contexto.clave(doc.url)}.pdf", timeout=120)
    if raw[:5] != b"%PDF-":
        raise RuntimeError(f"Parlamento de Canarias: no es un PDF: {doc.url}")
    return Contexto.pdf_texto(raw, layout=False)
