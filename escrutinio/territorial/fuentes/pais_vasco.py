"""Parlamento Vasco / Eusko Legebiltzarra: votaciones del Pleno con el resultado oficial por grupo.

Fuente: el Open Data del Parlamento (https://www.legebiltzarra.eus/portal/es/transparencia/open-data?opcion=pleno)
publica un XML por legislatura con cada sesión plenaria (número, fecha, tipo, diario) y sus asuntos: título,
acuerdo, expedientes tramitados («13\\11\\02\\01\\00183») y, si hubo votación electrónica, el enlace al PDF
oficial de resultados (pvgune_descargar/default/<uuid>). Ese PDF, bilingüe, trae una página por votación con
la hora, lo que se vota («Texto original», «Enmienda de totalidad del grupo PV», «Dictamen»...), los votos
emitidos (y delegados), a favor, en contra y abstenciones, y el desglose por grupo (sí, no, abstención).

El XML se regenera de tarde en tarde (en septiembre de 2026 llegaba a noviembre de 2025) y sus últimas
sesiones pueden no traer aún los PDF, que se enlazan días o semanas después: las sesiones posteriores a la
última con PDF se sacan de la aplicación de tramitación (Oracle APEX, /ords/f?p=CTP:...), sin sesión ni
formularios: la lista de sesiones del año (ESTADISTICAS_SES) y la de los últimos diarios
(DIARIO_PLENO_INFORME) dan el identificador de cada sesión; su sumario (ASUNTOS_INFORME_DIARIO), los asuntos;
cada asunto (página 10), sus iniciativas y el trámite; y la ficha de cada iniciativa (página 18), los PDF de
votación con su fecha. Si un total de la columna en castellano del PDF no cuadra con la suma de los grupos y
el de la columna en euskera sí, vale este (`extra["corregido"]` guarda la errata).

Cobertura: Pleno de la X (2012), XI (2016), XII (2020) y XIII (2024-) legislaturas; `sesion` es el número de
sesión (el del diario), `numero` el orden de la votación en la sesión. Limitaciones: unas decenas de PDF, casi
todos de enero a marzo de 2013, son imágenes sin texto y se saltan (quedan en el registro); no hay voto
nominal; el resultado de cada votación solo se da cuando el acuerdo del asunto lo dice sin ambigüedad (asunto
con una sola votación, o la enmienda o dictamen que el acuerdo da por aprobado) y cuadra con los totales, y el
XML de la X legislatura no trae acuerdos; el autor sale del título (X legislatura) o de los proponentes de la
iniciativa (sesiones de la aplicación), no del XML de la XI a la XIII. En las elecciones con candidatos,
`a_favor` son los votos del más votado y todos van en `extra["candidatos"]`; las designaciones sin votación
(«Se nombran por asentimiento») van como asentimiento.
"""

import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from ...territorio import Cuerpo, num_parlamento
from ..modelo import Iniciativa, Votacion, VotoGrupo

CUERPO = "parl-PV"
BASE = "https://www.legebiltzarra.eus"
OPEN_DATA = BASE + "/portal/es/transparencia/open-data?opcion=pleno"
SESIONES_ANIO = (BASE + "/ords/f?p=CTP:ESTADISTICAS_SES::::SESSION:RESETBRCRMB,P28_LEGISLATURA,P28_ORGANO,P28_ANIO:"
                 "Y,{leg},49,{anio}&p_lang=es")  # órgano 49: Pleno
ULTIMOS_DIARIOS = BASE + "/ords/f?p=CTP:DIARIO_PLENO_INFORME::::::&p_lang=es"
SESION = BASE + "/ords/f?p=CTP:ASUNTOS_INFORME_DIARIO:::::RESETBRCRMB,P15_SESION_ID:Y,{id}&p_lang=es"
ASUNTO = BASE + "/ords/f?p=120:10:::NO:RP:P10_ID,P10_TEXT_SHOW,P10_EXPAND:{id},N,N"
INICIATIVA = BASE + "/ords/f?p=CTP:INICIATIVA_DETALLE::::SESSION:RESETBRCRMB,P18_ID:Y,{id}&p_lang=es"
DOCUMENTO = BASE + "/dok/restAPI/pvgune_descargar/default/{uuid}"

LEGISLATURAS = {
    10: ("X", "2012-11-20", "2016-10-21"),
    11: ("XI", "2016-10-21", "2020-08-03"),
    12: ("XII", "2020-08-03", "2024-05-14"),
    13: ("XIII", "2024-05-14", None),
}

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("PV"), "Parlamento Vasco / Eusko Legebiltzarra", "Parlamento (País Vasco)",
           "autonomico", "PV", 75, LEGISLATURAS, web=BASE + "/portal/es/transparencia/open-data"),
]

NOTAS = ("Votaciones del Pleno con el PDF oficial de resultados de cada asunto: totales (emitidos, delegados, a favor, "
         "en contra, abstenciones) y voto por grupo; asuntos, expedientes y acuerdos del XML de Open Data por "
         "legislatura y, para lo que el XML aún no recoge, de la aplicación de tramitación (APEX). X a XIII "
         "legislatura (sin los PDF escaneados de principios de 2013). Sin voto nominal; resultado solo cuando el "
         "acuerdo lo dice sin ambigüedad.")

# Siglas de grupo del PDF (columna en castellano) -> nombre del grupo.
GRUPOS = {
    "EA-NV": "Grupo Parlamentario Euzko Abertzaleak-Nacionalistas Vascos (EA-NV)",
    "NV": "Grupo Parlamentario Euzko Abertzaleak-Nacionalistas Vascos (EA-NV)",
    "EH Bildu": "Grupo Parlamentario EH Bildu",
    "SV-ES": "Grupo Parlamentario Socialistas Vascos-Euskal Sozialistak (SV-ES)",
    "SV": "Grupo Parlamentario Socialistas Vascos-Euskal Sozialistak (SV-ES)",
    "ES-SV": "Grupo Parlamentario Socialistas Vascos-Euskal Sozialistak (SV-ES)",
    "PV-ETP": "Grupo Parlamentario Popular Vasco-Euskal Talde Popularra (PV-ETP)",
    "PV": "Grupo Parlamentario Popular Vasco-Euskal Talde Popularra (PV-ETP)",
    "PV+Cs": "Grupo Parlamentario Popular Vasco-Euskal Talde Popularra (PV-ETP)",
    "GPV": "Grupo Parlamentario Popular Vasco-Euskal Talde Popularra (PV-ETP)",
    "ETP-PV": "Grupo Parlamentario Popular Vasco-Euskal Talde Popularra (PV-ETP)",
    "VP-C": "Grupo Parlamentario Popular Vasco-Ciudadanos (PV-ETP+Cs)",  # XII legislatura
    "EP": "Grupo Parlamentario Elkarrekin Podemos (EP)",
    "EP-IU": "Grupo Parlamentario Elkarrekin Podemos-IU (EP-IU)",
    "Mixto-UPyD": "Grupo Mixto-UPyD", "Mixto-Vox": "Grupo Mixto-Vox", "Mixto-Sumar": "Grupo Mixto-Sumar",
    "Mixto-Ciudadanos": "Grupo Mixto-Ciudadanos",
    "Mixto": "Grupo Mixto",
}

# Sección y serie del expediente (13\11\02\01\00183) -> tipo de iniciativa.
TIPOS = {"09\\01\\00": "pl", "09\\01\\01": "presupuesto", "09\\02\\04": "ilp", "09\\02": "ppl", "10\\08": "control",
         "10\\10": "otro", "11\\01": "investidura", "11\\02": "pnl", "11\\03": "mocion", "11\\05": "otro",
         "11\\06": "organizacion", "11\\07": "organizacion", "11\\08": "control", "14\\01": "organizacion",
         "14\\02": "control", "15\\01": "organizacion", "15": "control", "17": "ppl", "18": "acuerdo", "20": "control",
         "10\\04": "control", "10\\05": "control", "10\\06": "control"}

# Asuntos que no se votan: no hace falta abrirlos en la aplicación de tramitación.
SIN_VOTO_RE = re.compile(r"^(?:Pregunta|Interpelaci[oó]n|Comparecencia|Solicitud de comparecencia|Declaraci[oó]n "
                         r"institucional|Informaci[oó]n|Toma de posesi[oó]n)", re.I)

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
UUID_RE = re.compile(r"pvgune_descargar/default/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
EXPEDIENTE_RE = re.compile(r"\b\d{2}\\\d{2}\\\d{2}\\\d{2}\\\d{5}\b")
FECHA_ES_RE = re.compile(r"\b(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})\b", re.I)
FECHA_ANTIGUA_RE = re.compile(r"\b(\d{1,2})\s+([A-Za-záéíóú]+),\s+(\d{4})\b")  # «24 enero, 2013»
HORA_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")


def _plano(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _limpio(fragmento):
    t = html.unescape(re.sub(r"<[^>]+>", " ", fragmento or "")).replace("\xa0", " ")
    return re.sub(r"\s+", " ", t).strip()


def _iso(ddmmaaaa):
    d, m, a = ddmmaaaa.split(".")
    return f"{a}-{m}-{d}"


def _grupo(sigla):
    sigla = re.sub(r"\s+", " ", sigla).strip()
    if sigla in GRUPOS:
        return GRUPOS[sigla]
    return sigla if sigla.lower().startswith(("grupo", "mixto")) else f"Grupo Parlamentario {sigla}"


def _tipo_iniciativa(expediente, titulo=""):
    if expediente:
        partes = expediente.split("\\")
        for n in (3, 2, 1):
            clave = "\\".join(partes[1:1 + n])
            if clave in TIPOS:
                return TIPOS[clave]
    t = _plano(titulo or "")
    if "presupuestos generales" in t:
        return "presupuesto"
    if "lehendakari" in t and ("designacion" in t or "investidura" in t):
        return "investidura"
    if re.search(r"designacion|eleccion|nombramiento", t):
        return "organizacion"
    return None


def _titulo(titulo, expediente):
    """«Relativa a…» -> «Proposición no de ley relativa a…» (el tipo según el expediente, igual en el XML y en la
    aplicación de tramitación)."""
    if not titulo:
        return None
    titulo = re.sub(r"\s*\[[\d\s\\]+\]\s*\.?$", "", titulo).strip()  # «… [10 11 02 01 0078]» (X legislatura)
    # «Debate y resolución definitiva de la proposición no de ley formulada por el grupo parlamentario Popular
    # Vasco, sobre violencia en el deporte» -> «Proposición no de ley sobre violencia en el deporte»
    m = re.match(r"^Debate y resoluci[oó]n definitiva (?:de|sobre) (?:la |el )?((?:proposici[oó]n no de ley|moci[oó]n)"
                 r"(?: consecuencia de (?:la )?interpelaci[oó]n)?)\s+(?:formulad[oa]|presentad[oa]) por .+?,\s+(.+)$",
                 titulo, re.I)
    if m:
        return f"{m.group(1)[:1].upper()}{m.group(1)[1:]} {m.group(2)}".rstrip(" .")
    # «Debate y resolución definitiva sobre el dictamen formulado por la Comisión X en relación con el proyecto de
    # ley Y» o «Debate de totalidad del proyecto de ley Y» -> «Proyecto de ley Y»
    m = re.match(r"^(?:Debate|Dictamen|Toma en consideraci[oó]n).{0,200}?\b(?:en relaci[oó]n con|sobre|del?) (?:el |la )?"
                 r"((?:proyecto|proposici[oó]n) de ley\b.+)$", titulo, re.I)
    if m:
        return m.group(1)[:1].upper() + m.group(1)[1:]
    nombre = None
    if expediente:
        seccion = "\\".join(expediente.split("\\")[1:3])
        nombre = NOMBRES.get(seccion)
    if nombre and re.match(r"(?:Relativ[oa]|Sobre|Acerca|Para|En relaci[oó]n|Con |De |Por |Que |A fin)", titulo):
        return f"{nombre} {titulo[:1].lower()}{titulo[1:]}"
    return titulo


NOMBRES = {"11\\02": "Proposición no de ley", "11\\03": "Moción", "09\\02": "Proposición de ley", "09\\01": "Proyecto de ley",
           "17\\00": "Proposición de ley ante las Cortes Generales"}


# ---------------------------------------------------------------- PDF de resultados

def _columna(lineas):
    """Posición en la que empieza la columna en castellano (la del rótulo «RESULTADO TOTAL» o de la fecha)."""
    for ln in lineas:
        for rotulo in ("RESULTADO TOTAL", "RESULTADO POR GRUPOS", "Votos emitidos"):
            k = ln.find(rotulo)
            if k > 20:
                return k
    for ln in lineas:
        m = FECHA_ES_RE.search(ln)
        if m and m.start() > 20:
            return m.start()
    return None


def _derecha(ln, col):
    """La parte de la línea en la columna en castellano ('' si solo tiene texto en euskera)."""
    if col is None:
        return ln.strip()
    if len(ln) <= col - 8:
        return ""
    ini = len(ln) - len(ln.lstrip())
    if ini >= col - 8:
        return ln.strip()
    # el primer hueco (dos o más espacios) que acaba en la columna o después («botoak:   75      Votos emitidos:  75»,
    # «Ez   27             No   27»); si no, el que acaba más cerca
    huecos = [m.end() for m in re.finditer(r"\s{2,}", ln)]
    despues = [c for c in huecos if c >= col - 2]
    if despues:
        return ln[despues[0]:].strip()
    cerca = [c for c in huecos if abs(c - col) <= 10]
    return ln[min(cerca, key=lambda c: abs(c - col)):].strip() if cerca else ""


def _fecha_pagina(texto):
    for m in FECHA_ES_RE.finditer(texto):
        if m.group(2).lower() in MESES:
            return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    for m in FECHA_ANTIGUA_RE.finditer(texto):
        if m.group(2).lower() in MESES:
            return f"{m.group(3)}-{MESES[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    return None


def _pagina(texto):
    """dict con lo que da una página del PDF de resultados (None si no es una votación legible)."""
    lineas = [ln.rstrip() for ln in texto.splitlines() if ln.strip()]
    if not lineas:
        return None
    col = _columna(lineas)
    d = {"hora": None, "fecha": _fecha_pagina(texto), "titulo": None, "emitidos": None, "delegados": None,
         "a_favor": None, "en_contra": None, "abstenciones": None, "blancos": None, "nulos": None,
         "grupos": [], "candidatos": []}
    m = HORA_RE.search(lineas[0]) or HORA_RE.search(texto[:400])
    d["hora"] = m.group(1) if m else None
    # título: lo que hay entre la fecha y «RESULTADO TOTAL» (columna en castellano)
    titulo, dentro, grupo = [], False, None  # grupo: el del voto por grupo que se está leyendo
    i_total = next((k for k, ln in enumerate(lineas) if re.search(r"RESULTADOS? TOTAL", ln)), None)
    if i_total is None:
        # «Se nombran por asentimiento:» (designaciones sin votación)
        i_total = next((k for k, ln in enumerate(lineas) if re.search(r"por asentimiento", ln, re.I)), None)
        if i_total is None:
            return None
        d["asentimiento"] = True
    for k, ln in enumerate(lineas[:i_total]):
        if FECHA_ES_RE.search(ln) or FECHA_ANTIGUA_RE.search(ln):
            dentro = True
            continue
        if dentro or (col is None and k > 0):
            t = _derecha(ln, col)
            if t and not HORA_RE.fullmatch(t):
                titulo.append(t)
    if not titulo and col is None:  # formato antiguo: el título va en la primera línea
        titulo = [lineas[0].strip()]
    d["titulo"] = re.sub(r"(?<=[A-Z])- (?=[A-Z])", "-", re.sub(r"\s+", " ", " ".join(titulo))).strip(" .") or None
    euskera, pendiente, candidatos = {}, None, []
    sentido_re = re.compile(r"^(?:(?P<grupo>\S.*?)\s+)?(?P<sentido>S[ií]|No votado|No|Abstenci[oó]n)\s+(?P<n>\d+)$")
    for ln in lineas[i_total:]:
        der = _derecha(ln, col) if col is not None else ln.strip()
        linea = ln
        if re.search(r"RESULTADO POR GRUPOS|EMAITZA TALDEKA|Becerro de Bengoa|Tel\.:|www\.", ln):
            continue
        m = re.search(r"(?:Votos emitidos|Presentes):\s*(\d+)(?:\s*\((\d+)\s+delegad)?", linea)
        if m:
            d["emitidos"] = int(m.group(1))
            d["delegados"] = int(m.group(2)) if m.group(2) else None
            continue
        for clave, rx in (("a_favor", r"Aldekoak:\s*(\d+)"), ("en_contra", r"Aurkakoak:\s*(\d+)"),
                          ("abstenciones", r"Abstentzioak:\s*(\d+)")):
            m = re.search(rx, linea)
            if m:  # la columna en euskera, para contrastar erratas de la castellana
                euskera[clave] = int(m.group(1))
        # voto por grupo: «EA-NV   Sí   27» y luego «No  0», «Abstención  0» (en el formato de 2013, el nombre del
        # grupo puede ir solo en su línea y hay además «No votado»)
        m = sentido_re.match(der)
        if m:
            nombre = m.group("grupo") or pendiente
            pendiente = None
            if nombre:
                grupo = {"grupo": _grupo(nombre), "sigla": nombre.strip(), "si": None, "no": None, "abstencion": None,
                         "no_vota": None}
                d["grupos"].append(grupo)
            if grupo is not None:
                s = _plano(m.group("sentido"))
                grupo["no_vota" if s == "no votado" else {"s": "si", "n": "no", "a": "abstencion"}[s[0]]] = int(m.group("n"))
            continue
        for clave, rx in (("a_favor", r"(?:A favor|\bS[IÍ]):\s*(\d+)"), ("en_contra", r"(?:En contra|\bNO):\s*(\d+)"),
                          ("abstenciones", r"Abstenci[oó]n(?:es)?:\s*(\d+)"),
                          ("blancos", r"(?:Blancos?|En blanco):?\s+(\d+)"), ("nulos", r"Nulos?:?\s+(\d+)")):
            m = re.search(rx, der or linea)
            if m:
                d[clave] = int(m.group(1))
                break
        else:
            # elección con candidatos: «Iñigo Urkullu Renteria     37» (o «Laura MINTEGI LAKARRA: 21 (EH Bildu)»)
            m = re.match(r"^(?P<nombre>[A-ZÁÉÍÓÚÑ][^\d:]{3,80}?):?\s+(?P<votos>\d+)(?:\s*\((?P<grupos>[^)]*)\))?$",
                         der or "")
            if m and not re.match(r"(?:Zuriak|Aldekoak|Aurkakoak|Abstentzioak)", m.group("nombre")):
                candidatos.append((m.group("nombre").strip(), int(m.group("votos"))))
            elif re.fullmatch(r"[A-Za-z][\w+\-]*(?:[ -][\w+\-]+){0,3}", der or "") and \
                    not re.fullmatch(r"S[ií]|No(?: votado)?|Abstenci[oó]n", der):  # «No» sin cifra: no es un grupo
                pendiente = der  # nombre de grupo solo en su línea (formato de 2013)
    if d.get("asentimiento"):
        return d
    if d["a_favor"] is None:
        if not candidatos:
            return None
        d["candidatos"] = candidatos
        d["grupos"] = []
    # erratas: si un total de la columna en castellano no cuadra con la suma de los grupos y el de la columna en
    # euskera sí, vale el de euskera («En contra: 36» frente a «Aurkakoak: 26» y 26 noes por grupo)
    if d["grupos"]:
        for clave, sentido in (("a_favor", "si"), ("en_contra", "no"), ("abstenciones", "abstencion")):
            suma = sum(g[sentido] or 0 for g in d["grupos"])
            if d[clave] != suma and euskera.get(clave) == suma:
                d.setdefault("corregido", {})[clave] = d[clave]
                d[clave] = suma
    return d


_PRECARGA = {}  # uuid -> descarga en marcha del PDF de votación


def _paginas(ctx, uuid):
    """Páginas legibles del PDF de resultados de un asunto (lista vacía si es una imagen sin texto)."""
    futuro = _PRECARGA.pop(uuid, None)
    try:
        pdf = futuro.result() if futuro else ctx.fetch(DOCUMENTO.format(uuid=uuid),
                                                       cache=f"{CUERPO}/votaciones/{uuid}.pdf", timeout=120)
    except Exception as e:  # noqa: BLE001 - un enlace roto no debe parar la recogida
        ctx.log(f"  ! {CUERPO}: no se pudo descargar el documento de votación {uuid}: {e}")
        return []
    if pdf[:5] != b"%PDF-":
        ctx.log(f"  ! {CUERPO}: el documento de votación {uuid} no es un PDF")
        return []
    out = []
    for texto in ctx.pdf_texto(pdf, layout=True).split("\f"):
        p = _pagina(texto)
        if p:
            out.append(p)
    return out


# ---------------------------------------------------------------- Open Data (XML por legislatura)

def _ficheros_open_data(ctx):
    """{legislatura: url del XML de sesiones plenarias}."""
    h = ctx.texto(OPEN_DATA, cache=f"{CUERPO}/open_data.html", caduca_dias=1)
    out = {}
    for url in re.findall(r'href="([^"]*fileName=c_pleno_open_data_(\d+)\.xml)"', h):
        out[int(url[1])] = html.unescape(url[0])
    return out


def _cdata(bloque, etiqueta):
    m = re.search(r"<%s>(.*?)</%s>" % (etiqueta, etiqueta), bloque, re.S)
    if not m:
        return None
    t = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", m.group(1).strip())
    return re.sub(r"\s+", " ", t).strip() or None


def _sesiones_xml(ctx, leg, url):
    """[dict] de las sesiones plenarias del XML de una legislatura, con sus asuntos."""
    actual = LEGISLATURAS[leg][2] is None
    raw = ctx.fetch(url, cache=f"{CUERPO}/open_data/pleno_{leg}.xml", caduca_dias=6 if actual else None, timeout=180)
    texto = raw.decode("iso-8859-1", "replace")
    sesiones = []
    for s in re.findall(r"<sesiones_pleno>(.*?)</sesiones_pleno>", texto, re.S):
        fecha = _cdata(s, "sesiones_pleno_fecha_inicio")
        num = _cdata(s, "sesiones_pleno_num_sesion")
        if not fecha or not num:
            continue
        asuntos, vistos = [], set()
        for a in re.findall(r"<sesiones_pleno_asunto>(.*?)</sesiones_pleno_asunto>", s, re.S):
            a = re.sub(r"<sesiones_pleno_asunto_indice_oradores>.*?</sesiones_pleno_asunto_indice_oradores>", "", a, flags=re.S)
            enlace = _cdata(a, "sesiones_pleno_asunto_link_votacion")
            clave = (_cdata(a, "sesiones_pleno_asunto_num_asunto"), enlace)
            if clave in vistos:
                continue  # el XML repite el asunto por cada iniciativa que tramita
            vistos.add(clave)
            expedientes = list(dict.fromkeys(EXPEDIENTE_RE.findall(
                " ".join(re.findall(r"<sesiones_pleno_asunto_tramite_num_expediente>(.*?)</", a, re.S)) + " " +
                " ".join(re.findall(r"<sesiones_pleno_asunto_iniciativa_origen_numero>(.*?)</", a, re.S)))))
            tramites = [_limpio(re.sub(r"<!\[CDATA\[|\]\]>", "", x))
                        for x in re.findall(r"<sesiones_pleno_asunto_tramite_descripcion>(.*?)</", a, re.S)]
            titulo = _cdata(a, "sesiones_pleno_asunto_titulo")
            # «… formulada por el grupo parlamentario Popular Vasco, sobre…» (títulos de la X legislatura)
            m = re.search(r"\b(?:formulad[oa]|presentad[oa])s? por (?:el |la |los |las )?(.{3,120}?),\s", titulo or "")
            asuntos.append({"num": int(clave[0] or 0), "titulo": titulo,
                            "acuerdo": _cdata(a, "sesiones_pleno_asunto_acuerdo"), "expedientes": expedientes,
                            "tramite": next((x for x in tramites if x), None),
                            "autor": m.group(1)[:1].upper() + m.group(1)[1:] if m else None,
                            "fichas": list(dict.fromkeys(re.findall(r"P18_ID:Y,\W*(\d+)", a))),
                            "votaciones": UUID_RE.findall(enlace or "")})
        sesiones.append({"num": int(num), "fecha": _iso(fecha), "tipo": _cdata(s, "sesiones_pleno_tipo_sesion"),
                         "diario": _cdata(s, "sesiones_pleno_diario_link"), "asuntos": asuntos, "origen": "xml"})
    return sesiones


# ---------------------------------------------------------------- aplicación de tramitación (APEX)

def _sesiones_apex(ctx, leg, desde_fecha):
    """[dict(num, fecha, id)] de las sesiones plenarias posteriores a `desde_fecha` según la aplicación."""
    sesiones = {}

    def filas(h):
        for num, sid, fecha in re.findall(r">(\d+)</td><td[^>]*><a href=\"[^\"]*P15_SESION_ID(?:&#x3A;|:)(\d+)\"\s*>"
                                          r"<DIV>(\d{2}\.\d{2}\.\d{4})</DIV>", h):
            f = _iso(fecha)
            if f > desde_fecha and CUERPOS[0].legislatura_de(f) == leg:
                sesiones.setdefault(int(sid), {"num": int(num), "fecha": f, "id": int(sid), "origen": "apex", "asuntos": []})

    ini = max(int(desde_fecha[:4]), int(LEGISLATURAS[leg][1][:4]))
    fin = int((LEGISLATURAS[leg][2] or "9999")[:4])
    for anio in range(ini, min(fin, date.today().year) + 1):
        h = ctx.texto(SESIONES_ANIO.format(leg=leg, anio=anio))
        filas(h)
        m = re.search(r"de (\d+)</span>", h)
        if m and int(m.group(1)) > 50:
            ctx.log(f"  ! {CUERPO}: {m.group(1)} sesiones en {anio}; la lista solo da 50")
    if LEGISLATURAS[leg][2] is None:
        filas(ctx.texto(ULTIMOS_DIARIOS))  # los 50 diarios más recientes
    return sorted(sesiones.values(), key=lambda s: (s["fecha"], s["num"]), reverse=True)


def _asuntos_apex(ctx, sesion, fija):
    """Asuntos de una sesión según la aplicación, con las votaciones de sus iniciativas en esa fecha."""
    cache = (lambda nombre: f"{CUERPO}/apex/{nombre}.html") if fija else (lambda nombre: None)
    h = ctx.texto(SESION.format(id=sesion["id"]), cache=cache(f"sesion-{sesion['id']}"))
    asuntos = []
    for fila in re.findall(r"<tr\s*>(.*?)</tr>", h, re.S):
        m = re.search(r"P10_EXPAND(?:&#x3A;|:)(\d+)", fila)
        celdas = [_limpio(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", fila, re.S)]
        if not m or len(celdas) < 5:
            continue
        num, tipo, titulo = celdas[2], celdas[3], celdas[4]
        asunto = {"num": int(num) if num.isdigit() else 0, "tipo": tipo, "titulo": titulo, "acuerdo": None,
                  "expedientes": [], "tramite": None, "autor": None, "votaciones": [], "fichas": [],
                  "id": int(m.group(1))}
        asuntos.append(asunto)
        if SIN_VOTO_RE.match(tipo):
            continue
        a = ctx.texto(ASUNTO.format(id=asunto["id"]), cache=cache(f"asunto-{asunto['id']}"))
        texto = _limpio(a)
        m = re.search(r"Autor:\s*(.+?)\s+Fecha sesi[oó]n:", texto)
        asunto["autor"] = re.sub(r"\s*\([^)]*\)\s*$", "", m.group(1)).strip() if m else None
        m = re.search(r"Tr[aá]mites\s+(Celebraci[oó]n de la sesi[oó]n plenaria.*?|Se pospone.*?)\s+Oradores\b", texto)
        asunto["tramite"] = m.group(1) if m else None
        m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*$", asunto["tramite"] or "")
        asunto["acuerdo"] = m.group(1) if m else None
        asunto["expedientes"] = list(dict.fromkeys(EXPEDIENTE_RE.findall(texto)))  # las iniciativas de origen
        asunto["fichas"] = list(dict.fromkeys(re.findall(r"P18_ID,P18_EXPAND(?:&#x3A;|:)(\d+)", a)))
        for iid in asunto["fichas"]:
            ficha = ctx.texto(INICIATIVA.format(id=iid), cache=cache(f"iniciativa-{iid}"))
            if iid == asunto["fichas"][0]:
                # el autor del asunto es el de la iniciativa («Proponentes»), no la comisión que dictamina
                fin = r"(?:Destinatarios|Ponentes|Plazos|Tr[aá]mites)\b"
                m = re.search(r"Proponentes\s+((?:(?!%s|Proponentes).)+?)\s+%s" % (fin, fin), _limpio(ficha))
                if m:  # «GP Euzko Abertzaleak-Nacionalistas Vascos (GP EA-NV) GP Socialistas... (GP SV-ES)»
                    asunto["autor"] = re.sub(r"\)\s+(?=\S)", "); ", m.group(1).strip())
            enlaces = re.findall(r'headers="VOTACION"><a href="[^"]*?default/([0-9a-f-]{36})"[^>]*>([^<]*)</a>', ficha)
            for uuid, etiqueta in enlaces:
                m = re.match(r"\s*(\d{2}\.\d{2}\.\d{4})\s*\(Pleno\)", etiqueta)
                if m and _iso(m.group(1)) == sesion["fecha"] and uuid not in asunto["votaciones"]:
                    asunto["votaciones"].append(uuid)
    sesion["asuntos"] = asuntos
    sesion["origen"] = "apex"
    return sesion


# ---------------------------------------------------------------- votaciones

def _resultado_asunto(asunto, pagina, n_paginas):
    """Resultado de una votación según el acuerdo del asunto, solo si no es ambiguo."""
    acuerdo = " ".join(x for x in (asunto.get("acuerdo"), asunto.get("tramite")) if x)
    t = _plano(acuerdo)
    if not t:
        return None
    t = re.sub(r"\bno se (?:aprueba|toma en consideracion)", "se rechaza", t)
    aprobado = re.search(r"\b(?:aprobad[oa]s?|se aprueba|se toma en consideracion|designad|elegid|se designa)", t)
    rechazado = re.search(r"\b(?:rechazad[oa]s?|se rechaza)", t)
    if n_paginas == 1:
        if aprobado and not rechazado:
            return "aprobada"
        if rechazado and not aprobado:
            return "rechazada"
        return None
    # varias votaciones: la que el acuerdo nombra («Aprobada la enmienda de totalidad de los grupos EA-NV y SV»)
    titulo = _plano(pagina["titulo"] or "")
    m = re.search(r"aprobad[oa]s? (?:la |el |las |los )?(.+?)(?:$|\.|;)", t)
    if m and titulo and len(titulo) > 6 and (titulo in m.group(1) or m.group(1).strip() == titulo):
        return "aprobada"
    if titulo in ("dictamen", "texto del dictamen") and re.search(r"se aprueba la ley|aprobada la ley", t):
        return "aprobada"
    return None


def _tipo_votacion(tipo, titulo_pagina, titulo_asunto):
    t = _plano(titulo_pagina or "")
    ta = _plano(titulo_asunto or "")
    if "lehendakari" in t + ta and re.search(r"designacion|investidura|mocion de censura|confianza", t + ta):
        return "investidura"
    if re.search(r"designacion|eleccion|nombramiento|senador", t + " " + ta) and tipo in ("organizacion", None):
        return "nombramiento"
    if tipo in ("pnl", "mocion"):
        return tipo
    if "toma en consideracion" in t or "toma en consideracion" in ta:
        return "toma_consideracion"
    if "totalidad" in t or "devolucion del proyecto" in t:
        return "totalidad"
    if "enmienda" in t or "voto particular" in t:
        return "enmiendas"
    if re.search(r"\barticulo|disposicion|exposicion de motivos|\bseccion|titulo de la ley|cuadros|anexo", t):
        return "articulado"
    if re.search(r"^dictamen|texto del dictamen|conjunto|votacion final", t) and tipo in ("pl", "ppl", "ilp", "presupuesto"):
        return "conjunto"
    if tipo == "control":
        return "control"
    return None


def _votaciones_sesion(ctx, leg, sesion, vistos):
    """[Votacion] de una sesión, en orden de asunto y de página (sin repetir los PDF de `vistos`)."""
    out, n = [], 0
    for asunto in sorted(sesion["asuntos"], key=lambda a: a["num"]):
        uuids = [u for u in asunto["votaciones"] if u not in vistos]
        vistos.update(uuids)
        paginas = []
        for uuid in uuids:
            ps = _paginas(ctx, uuid)
            if not ps:
                ctx.log(f"  {CUERPO}: sesión {sesion['num']}/{leg} ({sesion['fecha']}), asunto {asunto['num']}: "
                        f"PDF de votación sin texto legible ({uuid})")
            paginas += [(uuid, p) for p in ps]
        exp = asunto["expedientes"][0] if asunto["expedientes"] else None
        tipo = _tipo_iniciativa(exp, asunto["titulo"])
        titulo = _titulo(asunto["titulo"], exp) or (paginas[0][1]["titulo"] if paginas else None) or "Votación"
        for uuid, p in paginas:
            n += 1
            extra = {"documento": uuid}
            for k in ("hora", "delegados", "blancos", "nulos", "corregido"):
                if p.get(k) is not None:
                    extra[k] = p[k]
            if len(asunto["expedientes"]) > 1:
                extra["expedientes"] = asunto["expedientes"]
            if asunto.get("acuerdo"):
                extra["acuerdo"] = asunto["acuerdo"]
            af, ec, ab = p["a_favor"], p["en_contra"], p["abstenciones"]
            subtitulo = p["titulo"]
            if p["candidatos"]:
                # elección: los votos del más votado como «a favor» de su candidatura, el resto en extra
                extra["candidatos"] = {c: v for c, v in p["candidatos"]}
                nombre, votos = max(p["candidatos"], key=lambda c: c[1])
                af = votos
                subtitulo = f"{p['titulo']}: {nombre}" if p["titulo"] else nombre
            asentimiento = bool(p.get("asentimiento"))
            res = "aprobada" if asentimiento else _resultado_asunto(asunto, p, len(paginas)) if not p["candidatos"] else None
            if res and af is not None and ec is not None and (res == "aprobada") != (af > ec):
                extra["resultado_acuerdo"] = res
                res = None
            grupos = [VotoGrupo(grupo=g["grupo"], si=g["si"], no=g["no"], abstencion=g["abstencion"],
                                no_vota=g.get("no_vota"), sentido=_sentido(g)) for g in p["grupos"]]
            fecha = p["fecha"] if p["fecha"] and abs(_dias(p["fecha"], sesion["fecha"])) <= 3 else sesion["fecha"]
            out.append(Votacion(
                cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=sesion["num"], numero=n, legislatura=leg,
                subtitulo=subtitulo if subtitulo and subtitulo != titulo else None, expediente=exp,
                tipo_iniciativa=tipo, tipo_votacion=_tipo_votacion(tipo, p["titulo"], asunto["titulo"]),
                autor=asunto.get("autor"), a_favor=af, en_contra=ec, abstenciones=ab, presentes=p["emitidos"],
                asentimiento=asentimiento, resultado=res, grupos=grupos, url=DOCUMENTO.format(uuid=uuid), fuente="pdf",
                extra=extra))
    return out


def _sentido(g):
    """Sentido del grupo: el único con votos, o «dividido»."""
    con = [k for k in ("si", "no", "abstencion") if g[k]]
    if len(con) == 1:
        return con[0]
    return "dividido" if con else None


def _dias(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def _precargar(ctx, pool, sesiones):
    """Descarga por adelantado (hasta tres a la vez) los PDF de votación de unas sesiones."""
    for s in sesiones:
        for a in s["asuntos"]:
            for uuid in a["votaciones"]:
                if uuid not in _PRECARGA:
                    _PRECARGA[uuid] = pool.submit(ctx.fetch, DOCUMENTO.format(uuid=uuid),
                                                  cache=f"{CUERPO}/votaciones/{uuid}.pdf", timeout=120)


def descargar(ctx):
    desde = ctx.desde(CUERPO, margen_dias=45)  # los PDF de votación se enlazan días o semanas después
    ficheros = _ficheros_open_data(ctx)
    n_total, iniciativas, vistos = 0, set(), set()  # vistos: PDF de votación ya leídos
    for leg in sorted(LEGISLATURAS, reverse=True):
        ini, fin = LEGISLATURAS[leg][1], LEGISLATURAS[leg][2]
        if desde and fin and fin < desde:
            break
        sesiones = _sesiones_xml(ctx, leg, ficheros[leg]) if leg in ficheros else []
        if fin is None:
            # lo que el XML todavía no recoge (o recoge sin los PDF de votación, que se enlazan días después), de la
            # aplicación de tramitación
            corte = max((s["fecha"] for s in sesiones if any(a["votaciones"] for a in s["asuntos"])), default=ini)
            sesiones = [s for s in sesiones if s["fecha"] <= corte] + _sesiones_apex(ctx, leg, corte)
        sesiones = sorted((s for s in sesiones if not desde or s["fecha"] >= desde),
                          key=lambda s: (s["fecha"], s["num"]), reverse=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            for k, s in enumerate(sesiones):
                if s["origen"] == "apex":
                    _asuntos_apex(ctx, s, fija=_dias(date.today().isoformat(), s["fecha"]) > 60)
                _precargar(ctx, pool, sesiones[k:k + 4])
                for a in s["asuntos"]:
                    exp = a["expedientes"][0] if a["expedientes"] else None
                    if exp and exp not in iniciativas and a["titulo"] and a["votaciones"]:
                        iniciativas.add(exp)
                        yield Iniciativa(CUERPO, exp, _titulo(a["titulo"], exp), legislatura=leg,
                                         tipo_iniciativa=_tipo_iniciativa(exp, a["titulo"]), autor=a.get("autor"),
                                         resultado=a.get("acuerdo"),
                                         url=INICIATIVA.format(id=a["fichas"][0]) if a.get("fichas") else None)
                for vo in _votaciones_sesion(ctx, leg, s, vistos):
                    yield vo
                    n_total += 1
                    if ctx.limite and n_total >= ctx.limite:
                        return
