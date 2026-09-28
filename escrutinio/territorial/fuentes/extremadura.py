"""Asamblea de Extremadura: «Informe de votaciones» del Pleno en PDF (totales, grupos y voto nominal).

Fuente: cada sesión plenaria publica un informe de votaciones generado por el sistema de voto
electrónico, firmado y en PDF, con una página de índice y, por cada votación, el punto del orden del
día («PROPUESTA DE IMPULSO ANTE EL PLENO (7.1 PDIP 175 1)»), el texto del asunto con su expediente
(«(PDIP-175)»), los resultados totales (presentes, sí, no, abstención, no votó), los parciales por
grupo y la lista nominal por grupo.
- I a XI legislatura: web antigua, congelada desde enero de 2026. Listado paginado
  https://www.asambleaex.es/plenos[-N] → ficha pleno-<id> → enlace «Informe de votaciones»
  (vertranscrippleno-<id>, PDF).
- XII legislatura: WordPress https://www.asambleaex.es/plenosxii/, categoría 46 («Sesiones
  Plenarias»), leída por su API REST (?rest_route=/wp/v2/posts). El informe es el PDF de la pestaña
  «Votaciones» («Informe_Firmado_N.pdf», «Informe_Votaciones_Presupuestos_Firmado.pdf»).

Cobertura: Pleno desde la IX legislatura (julio de 2015) hasta hoy. Las sesiones de investidura y las
constitutivas no tienen informe (el voto por llamamiento solo está en el Diario de Sesiones); la
Diputación Permanente no se recoge.

Limitaciones:
- Desde 2020 los votos delegados (y los de la pandemia) cuentan en los totales pero no en los
  parciales por grupo ni en la lista nominal. Los totales son los oficiales y los grupos van como se
  publican (solo votos emitidos en el hemiciclo). A la lista nominal se le añaden los delegantes
  (diputados de la legislatura, según la web, que faltan en la lista y cuyos apellidos están en la
  nota de delegación) solo si su voto se deduce: todos los votos que faltan van en un sentido, o cada
  delegante es de un grupo que votó unánime y esos sentidos suman justo lo que falta (queda anotado
  en extra["votos_delegados_deducidos"]). Si no, la lista nominal se omite (extra["nominal_omitido"];
  NOMINAL_INCOMPLETO = True la incluiría tal cual).
- En algún informe de 2019 faltan los nombres de grupo (fuente sin texto): esas votaciones van sin
  grupos ni nominal.
- El resultado no se publica: se calcula después con los totales.
- Una XIII legislatura estrenará probablemente otro WordPress («plenosxiii»): habrá que añadirlo.
"""

import html
import json
import re
import unicodedata
from collections import Counter
from datetime import date

from ...territorio import Cuerpo, num_parlamento
from ..modelo import Votacion, VotoGrupo, VotoNominal
from ..partidos import codigo_grupo

CUERPO = "parl-EX"
BASE = "https://www.asambleaex.es"
API_XII = BASE + "/plenosxii/?rest_route=/wp/v2/posts&categories=46&per_page=100&page={}"
INICIO_XII = "2026-01-20"
INICIO_COBERTURA = "2015-06-23"

CUERPOS = [
    Cuerpo(CUERPO, num_parlamento("EX"), "Asamblea de Extremadura", "Asamblea (Extremadura)", "autonomico", "EX", 65,
           {9: ("IX", "2015-06-23", "2019-06-18"),
            10: ("X", "2019-06-18", "2023-06-20"),
            11: ("XI", "2023-06-20", "2026-01-20"),
            12: ("XII", "2026-01-20", None)},
           web=BASE),
]

NOTAS = ("Informe de votaciones del Pleno en PDF (voto electrónico): totales, parciales por grupo y nominal, con "
         "expediente. IX a XII (desde julio de 2015). Desde 2020 los votos delegados solo están en los totales: se "
         "añaden a la lista nominal cuando su sentido se deduce (unánime o por grupo) y si no la lista se omite. Sin "
         "investiduras (no hay informe) ni Diputación Permanente. Resultado calculado con los totales.")

# Si el cargador llega a admitir listas nominales que no suman los totales (votos delegados fuera de la
# lista), basta con ponerlo a True.
NOMINAL_INCOMPLETO = False

MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
FECHA_TITULO_RE = re.compile(r"(\d{1,2})\s+(?:de\s+)?([a-záéíóú]+)\s+(?:de\s+)?(\d{4})", re.I)
PLENO_RE = re.compile(r'href="pleno-(\d+)"[^>]*>(.*?)</a>', re.S)
INFORME_RE = re.compile(r'href="(vertranscrippleno-\d+)"[^>]*>(.*?)</a>', re.S)
PDF_WP_RE = re.compile(r'<a href="([^"]+\.pdf)"[^>]*>(.*?)</a>', re.S)

# Texto del PDF
RUIDO_RE = re.compile(r"^(Código seguro de Verificación|CSV :|DIRECCIÓN DE VALIDACIÓN|FIRMANTE\(|INFORME DE FIRMA|"
                      r"https?://\S+$|Sin acción específica)")
# Sello de firma en el margen, en vertical: xpdf lo da en una línea (la quita RUIDO_RE) y poppler, palabra a palabra.
SELLO_RE = re.compile(
    r"(?:C[óo]digo\s+seguro\s+de\s+Verificaci[óo]n|INFORME\s+DE\s+FIRMA,\s+no\s+sustituye\s+al\s+documento\s+"
    r"original\s*\|\s*C\.S\.V\.)\s*:\s*\S+\s*\|\s*Puede\s+verificar\s+la\s+integridad\s+de\s+este\s+documento\s+en\s+"
    r"la\s+siguiente\s+direcci[óo]n\s*:(?:\s*https?://\S+)?")
PAGINA_RE = re.compile(r"^Página \d+/\d+$")
CABECERA_RE = re.compile(r"^Pleno:\s*(\d+)\s+Legislatura:\s*[IVXL]*\s*(?:(Expediente:)\s*(.*?))?\s*"
                         r"(?:Fecha:\s*(\d\d)/(\d\d)/(\d{4}))?$")
ENTRADA_RE = re.compile(r"\)$|^\(")
FECHA_SOLA_RE = re.compile(r"^Fecha:\s*\d\d/\d\d/\d{4}$")
TOTALES_RE = re.compile(r"^(\d+) (\d+) (\d+) (\d+) (\d+)$")
PARCIAL_RE = re.compile(r"^(.*?)\s*(\d+) (\d+) (\d+) (\d+)$")
VOTO = "Sí|No|Abstención|No votaron|No votó|No Votó"
NOMINAL_RE = re.compile(rf"^(.+?,.+?) ({VOTO})$")
VOTO_SOLO_RE = re.compile(rf"^({VOTO})$")
SENTIDO = {"Sí": "si", "No": "no", "Abstención": "abstencion"}

# Análisis del texto del asunto
BLOQUE_RE = re.compile(r"^(\d{1,2}(\.\d{1,2})*\.?-?\s|\*|\(Nuevo|Delega|-?\s*Han? delegado|Y por último|"
                       r"Formulad|Efectuad|Solicitad|Presentad|Aprobad|Remitid|Votaci|Se somete|Tras la votaci|"
                       r"Enmienda|ENMIENDA|Punto|Puntos|Resto|Propuestas? de resoluci|Texto|Debate|Adopci|Toma en|"
                       r"El Grupo Parl\w* .{0,80}solicita)", re.I)
NOTA_RE = re.compile(r"^(\*|\(Nuevo|Delega|-?\s*Han? delegado|Y por último)", re.I)
# Línea que sigue la frase de la anterior aunque case con BLOQUE_RE («…para que se puedan acotar los» /
# «puntos de venta…», «…la Ley 33/2011, de» / «4 de octubre…»); «1.1.1. Debate…» sí abre párrafo.
FRASE_ABIERTA_RE = re.compile(r"[a-záéíóúñü\d,]$")
SIGUE_FRASE_RE = re.compile(r"^(?!\d{1,2}\.\d)[a-záéíóúñü\d]")
RE_RE = re.compile(r"^R\.\s?E\.\s*(n\.?\s?[ºo°]s?\.?)?\s*[\d.]+\.?\s*")
# registro al final del título, con lo que lo introduce («…, presentadas en escrito con R.E. nº 23.781.»)
RE_FINAL_RE = re.compile(r"(?:,?\s+(?:presentadas?\s+)?en\s+escrito\s+con|\s+en)?\s+R\.\s?E\.\s*(n\.?\s?[ºo°]s?\.?)?\s*"
                         r"[\d.]+\.?$")
RE_PARTIDO_RE = re.compile(r"R\.\s?E\.$")  # «R.E.» a final de línea: el número va en la siguiente
NUM_RE_RE = re.compile(r"^(n\.?\s?[ºo°]s?\.?\s*)?\d[\d.]*")
AUTOR_RE = re.compile(r"^(Formulad|Efectuad|Solicitad|Presentad|Aprobad|Remitid)", re.I)
POR_RE = re.compile(r"\bpor\s+(?:el|la|los|las)\s+((?:Grupos?|Mesa|Junta|Consejo|Comisi|Diputad|Gobierno)[^.]*?)"
                    r"(?:\.\s|\.$|,?\s+R\.\s?E\.|$)")
EXPEDIENTE_RE = re.compile(r"\(([A-ZÑ]{2,6}\d?-\d+)\)")
CODIGO_RE = re.compile(r"\b([A-Z]{2,6})[ -](\d+)\b")
NUMERACION_RE = re.compile(r"^\d{1,2}(\.\d{1,2})*\.?-?\s*(?=[^\d\s.,])")  # «2.1.», no «14.611»

TIPOS_ETIQUETA = [  # (texto de la tipología del índice, tipo de iniciativa)
    ("CONVALIDACI", "dl"), ("PROYECTO", "pl"), ("PROPUESTA DE LEY", "ppl"), ("PROPOSICIÓN DE LEY", "ppl"),
    ("PROPUESTAS DE LEY", "ppl"), ("INICIATIVA LEGISLATIVA POPULAR", "ilp"), ("REFORMA DEL ESTATUTO", "ppl"),
    ("MOCIÓN DE CENSURA", "investidura"), ("CUESTIÓN DE CONFIANZA", "investidura"), ("INVESTIDURA", "investidura"),
    ("MOCIÓN", "mocion"), ("IMPULSO", "pnl"), ("PRONUNCIAMIENTO", "pnl"), ("PROPOSICIÓN NO DE LEY", "pnl"),
    ("REFORMA DEL REGLAMENTO", "organizacion"), ("ELECCI", "organizacion"), ("DESIGNACI", "organizacion"),
    ("CREACIÓN", "organizacion"), ("DEBATE", "control"), ("RESOLUCI", "control"), ("PLANES", "control"),
    ("INFORME", "control"), ("COMPARECENCIA", "control"),
]
TIPOS_SIGLA = {"CDL": "dl", "PLEY": "pl", "PRL": "ppl", "PPL": "ppl", "ILP": "ilp", "MOCI": "mocion", "PDIP": "pnl",
               "PPRO": "pnl", "PNL": "pnl", "RERA": "organizacion", "DEMO": "control"}


# ---------------------------------------------------------------------------------------------- PDF

def _texto_pdf(ctx, pdf):
    """Texto del PDF en el orden del flujo de contenido (pdftotext -raw), que respeta las filas. Con el mismo
    pdftotext que el resto (el de poppler, que es el de GitHub Actions); sin él, pypdf da un orden parecido."""
    return ctx.pdf_texto(pdf, raw=True)


def _paginas(texto):
    paginas, act = [], {"cab": None, "exp": None, "lineas": []}
    for linea in SELLO_RE.sub("\n", texto).split("\n"):
        linea = html.unescape(linea).strip()  # algunos informes traen «&#8230;» o «&#8220;» en el texto
        if not linea or RUIDO_RE.match(linea):
            continue
        if PAGINA_RE.match(linea):
            paginas.append(act)
            act = {"cab": None, "exp": None, "lineas": []}
            continue
        m = CABECERA_RE.match(linea)
        if m and act["cab"] is not None and not act["lineas"]:
            # cabecera sin el pie de la página anterior: poppler pierde el texto de las páginas dañadas
            paginas.append(act)
            act = {"cab": None, "exp": None, "lineas": []}
        if m and act["cab"] is None:
            act["cab"] = m
            act["exp"] = (m.group(3) or "").strip() if m.group(2) else None
            continue
        if FECHA_SOLA_RE.match(linea) and not act["lineas"]:
            continue
        act["lineas"].append(linea)
    if act["lineas"]:
        paginas.append(act)
    return paginas


def leer_informe(texto):
    """(sesión, fecha, [entradas del índice], [votaciones en bruto]) de un informe de votaciones."""
    paginas = _paginas(texto)
    sesion = fecha = None
    for p in paginas:
        if p["cab"]:
            sesion = int(p["cab"].group(1))
            if p["cab"].group(6):
                fecha = f"{p['cab'].group(6)}-{p['cab'].group(5)}-{p['cab'].group(4)}"
            break
    # El índice ocupa las primeras páginas, antes de la primera votación: sin expediente en la cabecera
    # (o con él vacío y la mitad de las líneas en forma de entrada, «TIPO (código)»).
    primera = next((i for i, p in enumerate(paginas) if any(l.startswith("Resultados Totales") for l in p["lineas"])),
                   len(paginas))
    indice, cuerpo = [], []
    for i, p in enumerate(paginas):
        lineas = [l for l in p["lineas"] if l != "Iniciativas Parlamentarias"]
        entradas_pag = sum(1 for l in lineas if ENTRADA_RE.search(l))
        if not cuerpo and i < primera and not p["exp"] and (p["exp"] is None or 2 * entradas_pag >= len(lineas)):
            indice += lineas
        else:
            cuerpo += p["lineas"]
    entradas, buf = [], ""
    for linea in indice:
        if linea.startswith("(") and entradas and not buf:  # «(Prop resoluc 1)» en su propia línea
            entradas[-1] += " " + linea
            continue
        buf = f"{buf} {linea}".strip()
        if buf.endswith(")"):
            entradas.append(buf)
            buf = ""
    if buf:
        entradas.append(buf)
    votos, v, estado, grupo, desc, saltar = [], None, "desc", None, [], False
    for k, linea in enumerate(cuerpo):
        if saltar:
            saltar = False
            continue
        if linea.startswith("Resultados Totales"):
            v = {"desc": desc, "totales": None, "grupos": [], "nominal": []}
            votos.append(v)
            desc, estado = [], "totales"
            continue
        if estado == "totales":
            m = TOTALES_RE.match(linea)
            if m:
                v["totales"] = tuple(int(x) for x in m.groups())
                estado = "tras_totales"
                continue
        if v is not None and linea.startswith("Resultados Parciales"):
            estado = "parciales"
            continue
        if v is not None and linea == "Votaciones:":
            estado = "nominal"
            continue
        if estado == "parciales":
            m = PARCIAL_RE.match(linea)
            if m:
                v["grupos"].append((m.group(1).strip(), *(int(x) for x in m.groups()[1:])))
                continue
        if estado == "nominal":
            if linea.startswith("Diputados :"):
                grupo = linea.split(":", 1)[1].strip()
                continue
            if linea in ("Nombre Voto", "Nombre", "Voto"):
                continue
            m = NOMINAL_RE.match(linea)
            if not m and k + 1 < len(cuerpo) and VOTO_SOLO_RE.match(cuerpo[k + 1]):
                # en páginas dañadas xpdf parte la fila en dos líneas: nombre y voto
                m = NOMINAL_RE.match(f"{linea} {cuerpo[k + 1]}")
                saltar = m is not None
            if m:
                v["nominal"].append((m.group(1).strip(), grupo, m.group(2)))
                continue
        estado, grupo = "desc", None
        desc.append(linea)
    return sesion, fecha, entradas, votos


# ------------------------------------------------------------------------------------ asunto votado

def _corte(b, fin):
    """Última línea del párrafo que abre el bloque b: la primera que cumple fin(l) o, si esa acaba en «R.E.»,
    la siguiente, que lleva el número."""
    corte = next((i for i, l in enumerate(b) if fin(l)), len(b) - 1)
    if corte + 1 < len(b) and RE_PARTIDO_RE.search(b[corte]) and NUM_RE_RE.match(b[corte + 1]):
        corte += 1
    return corte


def _autor(b):
    """(autor, líneas que siguen) de la frase del autor que abre b, que acaba en el registro de entrada."""
    corte = _corte(b, lambda l: l.endswith(".") or re.search(r"R\.\s?E\.", l))
    texto = " ".join(b[:corte + 1])
    m = POR_RE.search(texto)
    autor = m.group(1).strip(" ,") if m else None
    if not autor and "Consejo de Gobierno de la Junta de Extremadura" in texto:
        autor = "Junta de Extremadura"
    return autor, b[corte + 1:]


def _describir(lineas, entrada):
    """Título, subtítulo, autor, expediente y notas a partir del texto que precede a los resultados."""
    lineas = list(lineas)
    while lineas and entrada and lineas[0] in entrada:  # la cabecera repite la entrada del índice
        lineas.pop(0)
    bloques, en_frase = [], []  # en_frase: (bloque, línea) de frases de autor que siguen a otra frase
    for linea in lineas:
        if bloques and FRASE_ABIERTA_RE.search(bloques[-1][-1]) and SIGUE_FRASE_RE.match(linea):
            if AUTOR_RE.match(linea):
                en_frase.append((bloques[-1], len(bloques[-1])))
            bloques[-1].append(linea)
        elif not bloques or BLOQUE_RE.match(linea):
            bloques.append([linea])
        else:
            bloques[-1].append(linea)
    titulo, resto, autor, notas = None, [], None, []
    for b in bloques:
        texto = " ".join(b)
        if NOTA_RE.match(texto):
            notas.append(texto)
        elif AUTOR_RE.match(texto):
            # lo que sigue al registro de entrada es otro párrafo
            propio, siguen = _autor(b)
            if siguen:
                resto.append(" ".join(siguen))
            autor = autor or propio
        elif titulo is None:
            # el primer párrafo: hasta la primera línea que acaba en punto
            corte = _corte(b, lambda l: l.endswith("."))
            primero = NUMERACION_RE.sub("", " ".join(b[:corte + 1])).strip()
            if len(primero) < 60 and not re.search(r"[a-záéíóúñ]", primero):
                continue  # rótulo de sección del orden del día («1. PROYECTOS DE LEY»)
            titulo = primero
            if b[corte + 1:]:
                resto.append(" ".join(b[corte + 1:]))
        else:
            resto.append(NUMERACION_RE.sub("", texto).strip())
    if not autor:  # «…de conformidad con la propuesta / efectuada por el Grupo…»
        autor = next((a for a in (_autor(b[i:])[0] for b, i in en_frase) if a), None)
    etiqueta =re.sub(r"\s*\([^()]*\)$", "", entrada or "").strip()
    if not titulo or titulo.startswith("-"):
        titulo = " ".join(x for x in (etiqueta, titulo) if x) or etiqueta
    titulo = RE_FINAL_RE.sub("", titulo).strip()
    m = EXPEDIENTE_RE.search(" ".join(lineas[:8]))
    expediente = m.group(1) if m else None
    codigo = re.search(r"\(([^()]*)\)$", entrada or "")
    codigo = codigo.group(1) if codigo else None
    if not expediente and codigo:
        m = CODIGO_RE.search(codigo)
        if m and m.group(1) in TIPOS_SIGLA:
            expediente = f"{m.group(1)}-{m.group(2)}"
    subtitulo = re.sub(r"\s+", " ", " ".join(RE_RE.sub("", r) for r in resto)).strip()[:600] or None
    return titulo, subtitulo, autor, expediente, codigo, etiqueta, notas


def _tipos(etiqueta, expediente, titulo, subtitulo):
    tipo = next((t for clave, t in TIPOS_ETIQUETA if clave in (etiqueta or "").upper()), None)
    if not tipo and expediente:
        tipo = TIPOS_SIGLA.get(expediente.split("-")[0])
    if tipo == "pl" and re.search(r"Presupuestos Generales", titulo or "", re.I):
        tipo = "presupuesto"
    s = (subtitulo or "").lower()
    if tipo == "dl":
        tv = "tramitacion_ley" if re.search(r"tramit(?:aci.n|e).{0,40}proyecto de ley", s) else "convalidacion"
    elif "totalidad" in s:
        tv = "totalidad"
    elif "toma en consideración" in s:
        tv = "toma_consideracion"
    elif "enmienda" in s:
        tv = "enmiendas"
    elif "conjunto" in s:
        tv = "conjunto"
    elif "articulado" in s or "sección" in s:
        tv = "articulado"
    elif "lectura única" in s:
        tv = "organizacion"
    elif tipo in ("mocion", "pnl", "control", "investidura"):
        tv = tipo
    elif tipo == "organizacion" and re.search(r"elecci|designaci|nombramiento", f"{etiqueta} {titulo}", re.I):
        tv = "nombramiento"
    else:
        tv = None
    return tipo, tv


def _norm(t):
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", t)).strip()


def _etiqueta_grupo(largo, etiquetas):
    """La etiqueta del informe («PSOE») que corresponde al nombre largo del grupo en la web."""
    n = _norm(largo)
    buenas = [e for e in etiquetas if e and re.search(r"\b" + re.escape(_norm(e)) + r"\b", n)]
    if buenas:
        return max(buenas, key=len)
    buenas = [e for e in etiquetas if e and codigo_grupo(e)[0] == codigo_grupo(largo)[0]]
    return buenas[0] if len(buenas) == 1 else None


def _completar_nominal(nominal, si, no, abst, grupos, notas, diputados):
    """Añade a la lista nominal los votos delegados que solo cuentan en los totales, si se deducen sin duda.

    Los delegantes son los diputados de la legislatura que no están en la lista y cuyos apellidos
    aparecen en la nota de delegación. Su voto se deduce si todos los votos que faltan van en un solo
    sentido, o si cada delegante es de un grupo que votó unánime y esos sentidos suman justo lo que
    falta. Devuelve (lista, método) o (None, None).
    """
    cuenta = Counter(n.sentido for n in nominal)
    falta = Counter({"si": si - cuenta["si"], "no": no - cuenta["no"], "abstencion": abst - cuenta["abstencion"]})
    if min(falta.values()) < 0:
        return None, None
    falta = +falta
    if not falta:
        return nominal, None
    texto = _norm(" ".join(notas))
    presentes = {_norm(n.nombre) for n in nominal}
    delegantes = []
    for nombre, largos in diputados.items():
        apellidos = _norm(nombre.split(",")[0])
        if _norm(nombre) in presentes or len(apellidos) < 5:
            continue
        # «Gómez de Tejada Díaz» aparece a veces sin el último apellido
        partes = apellidos.split()
        formas = [apellidos] + ([" ".join(partes[:-1])] if len(partes) > 2 else [])
        if any(re.search(rf"\b{re.escape(f)}\b", texto) for f in formas):
            delegantes.append((nombre, largos))
    if len(delegantes) != sum(falta.values()):
        return None, None
    etiquetas = [g.grupo for g in grupos]
    con_grupo = []
    for nombre, largos in delegantes:  # el grupo puede haber cambiado de nombre, no de etiqueta
        propias = {_etiqueta_grupo(largo, etiquetas) for largo in largos}
        if len(propias) != 1 or None in propias:
            return None, None
        con_grupo.append((nombre, propias.pop()))
    if len(falta) == 1:
        sentido = next(iter(falta))
        return nominal + [VotoNominal(n, g, sentido) for n, g in con_grupo], "aritmetica"
    unanime = {}
    for g in grupos:
        votos = {"si": g.si or 0, "no": g.no or 0, "abstencion": g.abstencion or 0}
        if sum(1 for x in votos.values() if x) == 1:
            unanime[g.grupo] = next(k for k, x in votos.items() if x)
    sentidos = [unanime.get(g) for _n, g in con_grupo]
    if None in sentidos or Counter(sentidos) != falta:
        return None, None
    return nominal + [VotoNominal(n, g, s) for (n, g), s in zip(con_grupo, sentidos)], "grupo"


def votaciones_informe(texto, url, fecha_defecto=None, desplazamiento=0, diputados=None):
    """Votacion de cada votación de un informe (texto de pdftotext -raw).

    `diputados(legislatura)` -> {nombre: {grupos}} sirve para completar los votos delegados.
    """
    sesion, fecha, entradas, votos = leer_informe(texto)
    fecha = fecha or fecha_defecto
    usar_indice = len(entradas) == len(votos)
    for i, v in enumerate(votos, 1):
        if not v["totales"]:
            continue
        entrada = entradas[i - 1] if usar_indice else (v["desc"][0] if v["desc"] else "")
        titulo, subtitulo, autor, expediente, codigo, etiqueta, notas = _describir(v["desc"], entrada)
        if not titulo:
            continue
        tipo, tipo_votacion = _tipos(etiqueta, expediente, titulo, subtitulo)
        if not autor and tipo in ("pl", "presupuesto", "dl"):
            autor = "Junta de Extremadura"
        presentes, si, no, abst, no_vota = v["totales"]
        extra = {"punto": codigo} if codigo else {}
        if notas:
            extra["notas"] = " ".join(notas)[:800]
        grupos = [VotoGrupo(g, si=a, no=b, abstencion=c, no_vota=d) for g, a, b, c, d in v["grupos"]]
        nominal = [VotoNominal(n, g, SENTIDO.get(s, "no_vota")) for n, g, s in v["nominal"] if g]
        if any(not g.grupo for g in grupos) or len(nominal) < len(v["nominal"]):
            grupos, nominal = [], []  # informe sin nombres de grupo
            extra["sin_grupos"] = True
        cuenta = [sum(1 for n in nominal if n.sentido == k) for k in ("si", "no", "abstencion")]
        if nominal and cuenta != [si, no, abst] and not NOMINAL_INCOMPLETO:
            # faltan los votos delegados o telemáticos: se añaden si se deducen sin duda
            completa, metodo = None, None
            leg = CUERPOS[0].legislatura_de(fecha) if fecha else None
            if diputados and notas and leg:
                completa, metodo = _completar_nominal(nominal, si, no, abst, grupos, notas, diputados(leg))
            if completa:
                extra["votos_delegados_deducidos"] = f"{len(completa) - len(nominal)} ({metodo})"
                nominal = completa
            else:
                extra["nominal_omitido"] = len(nominal)
                nominal = []
        mayoria = "absoluta" if re.search(r"mayoría absoluta", f"{titulo} {subtitulo}", re.I) else None
        yield Votacion(
            cuerpo=CUERPO, fecha=fecha, titulo=titulo, sesion=sesion or 0, numero=desplazamiento + i,
            subtitulo=subtitulo, expediente=expediente, tipo_iniciativa=tipo, tipo_votacion=tipo_votacion,
            autor=autor, a_favor=si, en_contra=no, abstenciones=abst, no_votan=no_vota, presentes=presentes,
            mayoria=mayoria, grupos=grupos, nominal=nominal, url=url, fuente="pdf", extra=extra)


# ----------------------------------------------------------------------------------------- listados

def _fecha_titulo(titulo):
    fechas = FECHA_TITULO_RE.findall(titulo or "")
    for d, mes, a in reversed(fechas):
        if mes.lower() in MESES:
            return f"{a}-{MESES[mes.lower()]:02d}-{int(d):02d}"
    return None


def _decodificar(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("iso-8859-1")


def _limpio(h):
    return html.unescape(re.sub(r"<[^>]+>|\s+", " ", h)).strip()


def _sesiones_xii(ctx):
    """(fecha aproximada, título, [urls de informes]) de las sesiones plenarias de la XII, de la más nueva."""
    pagina = 1
    while True:
        datos = json.loads(ctx.fetch(API_XII.format(pagina), cache=f"{CUERPO}/xii/posts-{pagina}.json",
                                     caduca_dias=0.2))
        for post in datos:
            titulo = _limpio(post["title"]["rendered"])
            informes = []
            for href, texto in PDF_WP_RE.findall(post["content"]["rendered"]):
                if re.search(r"informe|votaci", f"{href} {_limpio(texto)}", re.I):
                    url = href if href.startswith("http") else BASE + href
                    if url not in informes:
                        informes.append(url)
            yield _fecha_titulo(titulo) or post["date"][:10], titulo, informes
        if len(datos) < 100:
            return
        pagina += 1


def _sesiones_antiguas(ctx):
    """(fecha aproximada, título, id de la ficha) de las sesiones plenarias de la web antigua (hasta la XI)."""
    desde = 1
    while True:
        url = f"{BASE}/plenos" + (f"-{desde}" if desde > 1 else "")
        h = _decodificar(ctx.fetch(url, cache=f"{CUERPO}/antiguo/plenos-{desde}.html", caduca_dias=30))
        filas = PLENO_RE.findall(h)
        if not filas:
            return
        for pid, titulo in filas:
            titulo = _limpio(titulo)
            if "Plenaria" not in titulo:  # Diputación Permanente
                continue
            yield _fecha_titulo(titulo), titulo, pid
        desde += 20


DIPUTADO_RE = re.compile(r'<li><a class="pn-title" href="verdiputado-\d+">(.*?)</a>\s*<p class="pn-normal">(.*?)</p>',
                         re.S)


def _diputados(ctx, leg):
    """{nombre: {grupos}} de todos los diputados de la legislatura (con altas y bajas)."""
    grupos = {}
    actual = leg == max(CUERPOS[0].legislaturas)
    for desde in range(1, 400, 20):
        h = _decodificar(ctx.fetch(f"{BASE}/dipslegis-{leg}-TODO-{desde}", caduca_dias=7 if actual else 90,
                                   cache=f"{CUERPO}/diputados/{leg}-{desde}.html"))
        filas = DIPUTADO_RE.findall(h)
        if not filas:
            break
        for nombre, grupo in filas:
            grupo = re.sub(r"\s+(BADAJOZ|C[ÁA]CERES)$", "", _limpio(grupo))
            grupos.setdefault(_limpio(nombre), set()).add(grupo)
    return grupos


def _informes_pleno(ctx, pid):
    h = _decodificar(ctx.fetch(f"{BASE}/pleno-{pid}", cache=f"{CUERPO}/antiguo/pleno-{pid}.html"))
    # «Informe de votaciones»; los «Resultado votación previa al acta» de 2020 son un avance del mismo informe
    return [BASE + "/" + href for href, texto in INFORME_RE.findall(h)
            if re.search(r"informe.*votaci", _limpio(texto), re.I)]


def _votaciones_sesion(ctx, informes, fecha, vistos, diputados):
    for k, url in enumerate(informes):
        if url in vistos:  # la misma sesión en dos entradas (continuación)
            continue
        vistos.add(url)
        pdf = ctx.fetch(url, cache=f"{CUERPO}/informes/{ctx.clave(url)}.pdf")
        if pdf[:5] != b"%PDF-":  # alguno se sirve vacío: no se guarda, por si lo arreglan
            (ctx.carpeta(CUERPO) / "informes" / f"{ctx.clave(url)}.pdf.gz").unlink(missing_ok=True)
            ctx.log(f"  ! {url}: no es un PDF")
            continue
        texto = _texto_pdf(ctx, pdf)
        propia = leer_informe(texto)[1]
        if fecha and propia and abs((date.fromisoformat(propia) - date.fromisoformat(fecha)).days) > 10:
            ctx.log(f"  ! {url}: el informe es del {propia} y la sesión del {fecha}; se descarta")
            continue
        for v in votaciones_informe(texto, url, fecha, desplazamiento=1000 * k, diputados=diputados):
            if v.a_favor + v.en_contra + v.abstenciones > CUERPOS[0].escanos:
                ctx.log(f"  ! {url} n{v.numero}: el informe da más votos que escaños; se descarta")
                continue
            yield v


def descargar(ctx):
    desde = ctx.desde(CUERPO)
    n, vistos, memo = 0, set(), {}

    def diputados(leg):
        if leg not in memo:
            try:
                memo[leg] = _diputados(ctx, leg)
            except Exception as e:  # noqa: BLE001 - sin la lista solo se pierde el voto delegado
                ctx.log(f"  ! diputados de la legislatura {leg}: {e}")
                memo[leg] = {}
        return memo[leg]

    def corta(fecha):
        return fecha and ((desde and fecha < desde) or fecha < INICIO_COBERTURA)

    for fecha, titulo, informes in _sesiones_xii(ctx):
        if corta(fecha):
            return
        for v in _votaciones_sesion(ctx, informes, fecha, vistos, diputados):
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
    if desde and desde >= INICIO_XII:
        return
    for fecha, titulo, pid in _sesiones_antiguas(ctx):
        if corta(fecha):
            return
        for v in _votaciones_sesion(ctx, _informes_pleno(ctx, pid), fecha, vistos, diputados):
            yield v
            n += 1
            if ctx.limite and n >= ctx.limite:
                return
