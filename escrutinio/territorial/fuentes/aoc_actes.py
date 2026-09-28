"""Ayuntamientos catalanes de más de 20.000 habitantes: actas del Pleno del Consorci AOC (para LLM).

Fuente: conjunto de datos multientidad «Actes de Ple» del Consorci Administració Oberta de
Catalunya (https://dadesobertes.seu-e.cat/dataset/agn-ag-actes-de-ple, CC0), un almacén CKAN con
API (datastore_search_sql). Cada fila es un acta subida por el ente a su sede electrónica:
DATA_ACORD (fecha de la sesión), TIPUS (Ordinària, Extraordinària, Urgent), ENLLAÇ_ACTA (PDF en
media.seu-e.cat), CODI_ACTA, CODI_ENS (código AOC del ente: las cinco primeras cifras, con ceros a
la izquierda, son el código INE del municipio) y NOM_ENS. No trae ni los acuerdos ni los votos:
solo el enlace al acta, que es texto libre en catalán con el voto por grupo o nominal
(«Vots a favor: 27 …»). Por eso este conector solo da documentos para el extractor LLM.

Cobertura: el conjunto reúne unas 142.500 actas de 1.135 entes (945 ayuntamientos) desde 2010. Se
limita a los 69 ayuntamientos que pasan de 20.000 habitantes (cifras oficiales del padrón del INE
de 2014, 2018, 2022 o 2025) y que publican en él, porque el coste de pasar al LLM las actas de
945 municipios (la mayoría con plenos casi siempre unánimes) no compensa; son las ciudades con
debate político entre varios grupos. Premià de Mar es el único de más de 20.000 que no publica
aquí. Barcelona solo tiene actas desde 2018; Terrassa deja de publicar en 2018, Sant Adrià en 2021
y Olot en 2023. Se recogen los mandatos X, XI y XII (desde el 13/06/2015).

Concejales (escanos): no vienen en los datos; se calculan con la escala del art. 179 de la LOREG
sobre la población oficial a 1 de enero del año anterior a cada elección (2014, 2018 y 2022),
descargada una vez del INE (tablas 2861, 2870, 2878 y 2900) y fijada aquí.

Limitaciones:
- Algunos entes suben al mismo conjunto actas de la Junta de Govern Local o de juntas generales de
  sus empresas; se descartan las que lo dicen en el nombre del fichero (JGL, Junta de Govern,
  Junta General), pero puede colarse alguna (p. ej. las de VIGEM, VIQUAL o VIMED de Viladecans).
- Hay actas repetidas (mismo día y mismo fichero): se deja una. Si un día hay varias actas
  distintas (ordinaria y extraordinaria, o partes), cada una es un documento.
- Solo PDF y DOCX (el texto del DOCX se saca aquí); los DOC antiguos, RAR o ZIP se descartan.
- sesion = AAAAMMDD * 10 + orden del acta ese día (0, 1…; por tipo de sesión y nombre de fichero).
"""

import html
import io
import json
import re
import unicodedata
import urllib.parse
import zipfile

from ... import territorio
from ..modelo import Documento

RECURSO = "b5d370d0-7916-48b6-8a69-3c7fa62a1467"
API_SQL = "https://dadesobertes.seu-e.cat/api/3/action/datastore_search_sql"
WEB = "https://dadesobertes.seu-e.cat/dataset/agn-ag-actes-de-ple"
INICIO = "2015-06-13"  # mandato X
POR_PAGINA = 5000

# (código INE, CODI_ENS del Consorci AOC, nombre, concejales en los mandatos X, XI y XII).
MUNICIPIOS = [
    ("08019", 801930008, "Barcelona", (41, 41, 41)),
    ("08101", 810170005, "L'Hospitalet de Llobregat", (27, 27, 27)),
    ("08279", 827980001, "Terrassa", (27, 27, 27)),
    ("08015", 801550006, "Badalona", (27, 27, 27)),
    ("08187", 818780001, "Sabadell", (27, 27, 27)),
    ("25120", 2512070005, "Lleida", (27, 27, 27)),
    ("43148", 4314820002, "Tarragona", (27, 27, 27)),
    ("08121", 812130008, "Mataró", (27, 27, 27)),
    ("08245", 824570005, "Santa Coloma de Gramenet", (27, 27, 27)),
    ("43123", 4312330008, "Reus", (27, 27, 27)),
    ("17079", 1707920002, "Girona", (25, 27, 27)),
    ("08205", 820550006, "Sant Cugat del Vallès", (25, 25, 25)),
    ("08073", 807340003, "Cornellà de Llobregat", (25, 25, 25)),
    ("08200", 820090004, "Sant Boi de Llobregat", (25, 25, 25)),
    ("08184", 818460009, "Rubí", (25, 25, 25)),
    ("08113", 811360009, "Manresa", (25, 25, 25)),
    ("08307", 830730008, "Vilanova i la Geltrú", (25, 25, 25)),
    ("08056", 805690004, "Castelldefels", (25, 25, 25)),
    ("08301", 830150006, "Viladecans", (25, 25, 25)),
    ("08169", 816910007, "El Prat de Llobregat", (25, 25, 25)),
    ("08096", 809610007, "Granollers", (25, 25, 25)),
    ("08266", 826650006, "Cerdanyola del Vallès", (25, 25, 25)),
    ("08124", 812490004, "Mollet del Vallès", (25, 25, 25)),
    ("08298", 829810007, "Vic", (21, 21, 21)),
    ("17066", 1706690004, "Figueres", (21, 21, 21)),
    ("08089", 808980001, "Gavà", (21, 21, 21)),
    ("08077", 807710007, "Esplugues de Llobregat", (21, 21, 21)),
    ("08211", 821140003, "Sant Feliu de Llobregat", (21, 21, 21)),
    ("17095", 1709500000, "Lloret de Mar", (21, 21, 21)),
    ("17023", 1702370005, "Blanes", (21, 21, 21)),
    ("08305", 830540003, "Vilafranca del Penedès", (21, 21, 21)),
    ("08102", 810220002, "Igualada", (21, 21, 21)),
    ("43163", 4316340003, "El Vendrell", (21, 21, 21)),
    ("08180", 818030008, "Ripollet", (21, 21, 21)),
    ("17114", 1711430008, "Olot", (21, 21, 21)),
    ("08194", 819440003, "Sant Adrià de Besòs", (21, 21, 21)),
    ("08125", 812520002, "Montcada i Reixac", (21, 21, 21)),
    ("43038", 4303850006, "Cambrils", (21, 21, 21)),
    ("43155", 4315540003, "Tortosa", (21, 21, 21)),
    ("08217", 821720002, "Sant Joan Despí", (21, 21, 21)),
    ("17155", 1715570005, "Salt", (21, 21, 21)),
    ("08252", 825200000, "Barberà del Vallès", (21, 21, 21)),
    ("08231", 823100000, "Sant Pere de Ribes", (21, 21, 21)),
    ("43037", 4303790004, "Calafell", (21, 21, 21)),
    ("08270", 827040003, "Sitges", (21, 21, 21)),
    ("43905", 4390570005, "Salou", (21, 21, 21)),
    ("08163", 816350006, "Pineda de Mar", (21, 21, 21)),
    ("08114", 811410007, "Martorell", (21, 21, 21)),
    ("08263", 826340003, "Sant Vicenç dels Horts", (21, 21, 21)),
    ("08123", 812340003, "Molins de Rei", (21, 21, 21)),
    ("08196", 819600000, "Sant Andreu de la Barca", (21, 21, 21)),
    ("08260", 826060009, "Santa Perpètua de Mogoda", (21, 21, 21)),
    ("43161", 4316130008, "Valls", (21, 21, 21)),
    ("08051", 805170005, "Castellar del Vallès", (21, 21, 21)),
    ("08147", 814770005, "Olesa de Montserrat", (21, 21, 21)),
    ("08118", 811890004, "El Masnou", (21, 21, 21)),
    ("17117", 1711750006, "Palafrugell", (21, 21, 21)),
    ("43171", 4317110007, "Vila-seca", (21, 21, 21)),
    ("17160", 1716090004, "Sant Feliu de Guíxols", (21, 21, 21)),
    ("43014", 4301410007, "Amposta", (21, 21, 21)),
    ("08076", 807650006, "Esparreguera", (21, 21, 21)),
    ("08112", 811200000, "Manlleu", (21, 21, 21)),
    ("08219", 821910007, "Vilassar de Mar", (21, 21, 21)),
    ("08221", 822120002, "Sant Just Desvern", (17, 17, 17)),
    ("08086", 808630008, "Les Franqueses del Vallès", (17, 17, 21)),
    ("17015", 1701570005, "Banyoles", (17, 17, 21)),
    ("08035", 803510007, "Calella", (17, 17, 17)),
    ("17152", 1715230008, "Roses", (17, 17, 17)),
    ("08238", 823840003, "Sant Quirze del Vallès", (17, 17, 21)),
]

# Actas que no son del Pleno según el nombre del fichero («junta» a secas no: está en «Ajuntament»).
NO_PLENO = re.compile(r"(?i)junta\s*(de\s*)?govern|junta\s+general|jgl|(?<![a-z])jg(?![a-z])|j\.\s*g\.\s*l")
ORDEN_TIPUS = {"Ordinària": 0, "Extraordinària": 1, "Urgent": 2}
FORMATOS = {"pdf": "pdf", "docx": "docx"}


def _slug(nombre):
    s = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def _legislaturas(esc):
    return {n: (rom, ini, fin, esc[i]) for i, (n, (rom, ini, fin)) in
            enumerate((n, territorio.MANDATOS_LOCALES[n]) for n in (10, 11, 12))}


def _nombre_oficial(nombre):
    """«Ajuntament de Sabadell», «Ajuntament d'Olot», «Ajuntament de l'Hospitalet…», «Ajuntament del Prat…»."""
    if nombre.startswith("L'"):
        return "Ajuntament de l'" + nombre[2:]
    if nombre.startswith("El "):
        return "Ajuntament del " + nombre[3:]
    if nombre.startswith(("La ", "Les ")):
        return "Ajuntament de " + nombre[0].lower() + nombre[1:]
    if nombre[0] in "AEIOUÀÈÉÍÒÓÚ":
        return "Ajuntament d'" + nombre
    return "Ajuntament de " + nombre


CUERPOS = []
_POR_ENS = {}
for _ine, _ens, _nombre, _esc in MUNICIPIOS:
    _c = territorio.Cuerpo(f"ayto-{_slug(_nombre)}", territorio.num_municipio(_ine), _nombre_oficial(_nombre),
                           _nombre, "municipal", "CT", _esc[-1], _legislaturas(_esc), web=WEB)
    CUERPOS.append(_c)
    _POR_ENS[_ens] = _c

NOTAS = ("Actas del Pleno (texto libre en catalán, para el extractor LLM) de los 69 ayuntamientos catalanes "
         "de más de 20.000 habitantes que publican en el conjunto «Actes de Ple» del Consorci AOC (CC0), "
         "desde el mandato X (13/06/2015). El conjunto solo trae fecha, tipo de sesión y enlace al acta; "
         "no trae votos. Concejales por la escala de la LOREG sobre el padrón del INE. Se descartan las "
         "actas de Junta de Govern o juntas generales que lo dicen en el nombre del fichero y las que no "
         "son PDF ni DOCX. Barcelona solo desde 2018; Terrassa hasta 2018, Sant Adrià hasta 2021, Olot "
         "hasta 2023. sesion = AAAAMMDD*10 + orden del acta del día.")


def _consulta(ctx, desde):
    """Filas del conjunto para los municipios elegidos, de la más reciente a la más antigua."""
    ens = ",".join(str(e) for e in _POR_ENS)
    campos = '"CODI_ENS","DATA_ACORD","TIPUS","ENLLAÇ_ACTA","CODI_ACTA"'
    offset = 0
    while True:
        sql = (f'SELECT {campos} FROM "{RECURSO}" WHERE "CODI_ENS" IN ({ens}) AND "DATA_ACORD" >= \'{desde}\' '
               f'ORDER BY "DATA_ACORD" DESC, "CODI_ENS", "CODI_ACTA" LIMIT {POR_PAGINA} OFFSET {offset}')
        url = API_SQL + "?" + urllib.parse.urlencode({"sql": sql})
        d = json.loads(ctx.fetch(url, cache=f"aoc-actes/llistat-{ctx.clave(url)}.json", caduca_dias=1))
        if not d.get("success"):
            raise RuntimeError(f"Consorci AOC: la API respondió con error: {str(d)[:300]}")
        filas = d["result"]["records"]
        yield from filas
        if len(filas) < POR_PAGINA:
            return
        offset += POR_PAGINA


def _fichero(url):
    return urllib.parse.unquote(url.rsplit("/", 1)[-1]).strip()


def documentos(ctx):
    desdes = {c.codigo: ctx.desde(c.codigo) for c in CUERPOS}
    minimo = INICIO if any(d is None for d in desdes.values()) else max(INICIO, min(desdes.values()))
    # Agrupa por (ente, día) para quitar repetidas y numerar las actas de un mismo día.
    dias = {}
    descartes = {"no pleno": 0, "formato": 0, "repetida": 0}
    for f in _consulta(ctx, minimo):
        cuerpo = _POR_ENS.get(int(f["CODI_ENS"]))
        url = (f.get("ENLLAÇ_ACTA") or "").strip()
        fecha = (f.get("DATA_ACORD") or "")[:10]
        if not cuerpo or not url or not fecha:
            continue
        desde = desdes[cuerpo.codigo]
        if fecha < INICIO or (desde and fecha < desde):
            continue
        fichero = _fichero(url)
        if NO_PLENO.search(fichero):
            descartes["no pleno"] += 1
            continue
        ext = fichero.rsplit(".", 1)[-1].lower() if "." in fichero else ""
        if ext not in FORMATOS:
            descartes["formato"] += 1
            continue
        lista = dias.setdefault((fecha, cuerpo.codigo), [])
        if any(x["fichero"] == fichero for x in lista):
            descartes["repetida"] += 1
            continue
        lista.append({"cuerpo": cuerpo, "fecha": fecha, "url": url, "fichero": fichero, "formato": FORMATOS[ext],
                      "tipus": (f.get("TIPUS") or "").strip(), "codi_acta": f.get("CODI_ACTA")})
    ctx.log(f"  AOC: {sum(len(v) for v in dias.values())} actas; descartadas {descartes}")
    n = 0
    for (fecha, codigo), lista in sorted(dias.items(), key=lambda kv: (kv[0][0], kv[0][1]), reverse=True):
        lista.sort(key=lambda x: (ORDEN_TIPUS.get(x["tipus"], 3), x["fichero"].lower(), x["codi_acta"] or ""))
        if len(lista) > 10:
            ctx.log(f"  AOC: {codigo} {fecha} tiene {len(lista)} actas; solo se dan las 10 primeras")
        for k, x in enumerate(lista[:10]):
            c = x["cuerpo"]
            tipus = x["tipus"] or "sin tipo"
            yield Documento(c.codigo, fecha, x["url"], sesion=int(fecha.replace("-", "")) * 10 + k,
                            formato=x["formato"], idioma="ca",
                            titulo=f"Acta del Ple de {c.corto} ({tipus}) del {fecha}: {x['fichero']}",
                            legislatura=c.legislatura_de(fecha),
                            extra={"codi_acta": x["codi_acta"], "tipus": x["tipus"], "fitxer": x["fichero"]})
            n += 1
            if ctx.limite and n >= ctx.limite:
                return


def _texto_docx(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "\t", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def texto(ctx, doc):
    raw = ctx.fetch(doc.url, cache=f"{doc.cuerpo}/docs/{ctx.clave(doc.url)}.{doc.formato}")
    if doc.formato == "docx" or raw[:2] == b"PK":
        return _texto_docx(raw)
    return ctx.pdf_texto(raw, layout=False)
