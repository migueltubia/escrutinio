"""Programas electorales: catálogo, descarga, texto y registro de lo hecho.

Un programa no cambia después de las elecciones, así que cada documento se descarga, se lee y se guarda
una sola vez. El registro, data/llm/programas/registro.jsonl (una línea por documento), dice qué está
hecho para que nadie lo repita, sea GitHub Actions o una persona en su equipo:

- Si un documento ya está registrado con el mismo sha256, no se vuelve a registrar ni a leer.
- Si el fichero cambia (el partido corrige el PDF), entra como documento nuevo con su propia línea
  («generales-2023-psoe-2»); la lectura anterior no se borra.
- Un cambio de prompt no relee nada por sí solo: releer es una orden explícita (`programas-releer`).
- Los fallos quedan como «error» con el motivo y solo se reintentan al pedirlo.

El texto extraído se guarda en data/raw/programas/<id>.txt, versionado, con un salto de página (\\f)
entre páginas: la cita de cada compromiso sigue siendo comprobable aunque el partido retire el PDF.
El PDF solo se guarda en la caché local (data/raw/programas/pdf/).
"""

import hashlib
import html
import io
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path

from .. import http_util
from ..config import LLM_DIR, RAW_DIR

PROGRAMAS_DIR = LLM_DIR / "programas"
REGISTRO = PROGRAMAS_DIR / "registro.jsonl"
TEXTOS_DIR = RAW_DIR / "programas"
PDF_DIR = TEXTOS_DIR / "pdf"
MIN_CARACTERES_PAGINA = 200  # por debajo, de media, el PDF está escaneado (sin capa de texto)

# Programas que se recogen: (id, elección, fecha, institución de Escrutinio, partido con las siglas de sus
# grupos, título, URL que se descarga, origen, URL oficial). El partido cubre la legislatura que empieza
# tras la elección. Si la web del partido no deja descargarlo (psoe.es está tras una protección contra
# robots, que no se intenta saltar) o ya no lo enlaza (Junts, EH Bildu), se usa la copia que publicó un
# medio y, si se conoce, se guarda también la URL oficial.
PROGRAMAS = [
    ("generales-2023-psoe", "generales-2023", "2023-07-23", "congreso", "PSOE",
     "Programa electoral. Elecciones generales 23 de julio de 2023",
     "https://theobjective.com/wp-content/uploads/2023/07/PROGRAMA_ELECTORAL-GENERALES-2023-1.pdf", "copia-prensa",
     "https://www.psoe.es/media-content/2023/07/PROGRAMA_ELECTORAL-GENERALES-2023.pdf"),
    ("generales-2023-pp", "generales-2023", "2023-07-23", "congreso", "PP",
     "Un proyecto al servicio de un gran país. 365 medidas",
     "https://www.pp.es/wp-content/uploads/2023/07/programa_electoral_pp_23j_feijoo_2023.pdf", "web-partido", None),
    ("generales-2023-vox", "generales-2023", "2023-07-23", "congreso", "VOX",
     "Programa electoral para las elecciones generales del 23J de 2023",
     "https://www.voxespana.es/wp-content/uploads/2023/07/Programa-VOX-2023-con-menos-peso.pdf", "web-partido", None),
    ("generales-2023-sumar", "generales-2023", "2023-07-23", "congreso", "Sumar",
     "Un programa para ti",
     "https://movimientosumar.es/transparencia/wp-content/uploads/sites/6/2023/12/un-programa-para-ti.pdf", "web-partido", None),
    ("generales-2023-erc", "generales-2023", "2023-07-23", "congreso", "ERC",
     "Defensa Catalunya! Eleccions espanyoles 2023",
     "https://defensacatalunya.esquerrarepublicana.cat/documents/e2023-programa.pdf", "web-partido", None),
    ("generales-2023-junts", "generales-2023", "2023-07-23", "congreso", "Junts",
     "Per Catalunya. Programa electoral, eleccions generals 2023",
     "https://img.beteve.cat/wp-content/uploads/2023/07/programa-junts-per-catalunya-eleccions-generals-2023.pdf", "copia-prensa", None),
    ("generales-2023-bildu", "generales-2023", "2023-07-23", "congreso", "Bildu",
     "Compromiso de Euskal Herria Bildu. Elecciones generales 2023",
     "https://www.elnacional.cat/uploads/s1/42/81/42/33/programa-electoral-eh-bildu-eleccions-generals-2023.pdf", "copia-prensa", None),
    ("generales-2023-pnv", "generales-2023", "2023-07-23", "congreso", "PNV",
     "Con voz propia. Programa electoral 23-J",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/20945/pdf/con-voz-propia-programa-electoral-23-j", "web-partido", None),

    # Generales de 2011 (X legislatura). IU-ICV es el grupo de La Izquierda Plural: vale el programa federal de IU.
    ("generales-2011-psoe", "generales-2011", "2011-11-20", "congreso", "PSOE", "Programa electoral. Elecciones generales 2011",
     "https://web.archive.org/web/20170518223426id_/http://www.psoe.es/media-content/2015/03/Programa-Electoral-Generales-2011.pdf",
     "archivo-web", "https://www.psoe.es/media-content/2015/03/Programa-Electoral-Generales-2011.pdf"),
    ("generales-2011-pp", "generales-2011", "2011-11-20", "congreso", "PP", "Lo que España necesita. Programa electoral 2011",
     "https://www.pp.es/wp-content/uploads/2013/11/5751-20111101123811.pdf", "web-partido", None),
    ("generales-2011-ciu", "generales-2011", "2011-11-20", "congreso", "CiU", "Programa electoral de Convergència i Unió. Eleccions generals 2011",
     "https://web.archive.org/web/20121029035201id_/http://www.ciu.cat/media/68631.pdf", "archivo-web", "http://www.ciu.cat/media/68631.pdf"),
    ("generales-2011-iu", "generales-2011", "2011-11-20", "congreso", "IU-ICV", "Propuestas electorales de Izquierda Unida. Elecciones 2011",
     "https://izquierdaunida.org/wp-content/uploads/2020/11/PROGRAMA-ELECTORAL-IU-GENERALES-2011.pdf", "web-partido", None),
    ("generales-2011-upyd", "generales-2011", "2011-11-20", "congreso", "UPyD", "Elecciones generales 2011. Programa electoral",
     "https://web.archive.org/web/20120113045527id_/http://www.upyd.es/contenidos/ficheros/68955", "archivo-web", "http://www.upyd.es/contenidos/ficheros/68955"),
    # El oficial del PNV está escaneado (sin capa de texto): se usa la copia que publicó El Mundo.
    ("generales-2011-pnv", "generales-2011", "2011-11-20", "congreso", "PNV", "Programa EAJ-PNV. Elecciones generales 2011",
     "https://e00-elmundo.uecdn.es/elecciones/elecciones-generales/2011/programas/pdf/pnv.pdf", "copia-prensa",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/9936/pdf/elecciones-generales-2011"),

    # Generales de 2015 (XI legislatura). El de Ciudadanos solo existe como imagen: queda registrado como escaneado.
    ("generales-2015-psoe", "generales-2015", "2015-12-20", "congreso", "PSOE", "Programa electoral. Elecciones generales 2015",
     "https://web.archive.org/web/20151223180208id_/http://www.psoe.es/media-content/2015/12/PSOE_Programa_Electoral_2015.pdf",
     "archivo-web", "https://www.psoe.es/media-content/2015/12/PSOE_Programa_Electoral_2015.pdf"),
    ("generales-2015-pp", "generales-2015", "2015-12-20", "congreso", "PP", "Seguir avanzando 2016-2020. Programa electoral 2015",
     "https://www.pp.es/wp-content/uploads/2015/12/programa2015.pdf", "web-partido", None),
    ("generales-2015-podemos", "generales-2015", "2015-12-20", "congreso", "Podemos", "Queremos, sabemos, Podemos. Un programa para cambiar nuestro país",
     "https://web.archive.org/web/20151223100551id_/http://unpaiscontigo.es/wp-content/plugins/programa/data/programa-es.pdf",
     "archivo-web", "http://unpaiscontigo.es/wp-content/plugins/programa/data/programa-es.pdf"),
    ("generales-2015-cs", "generales-2015", "2015-12-20", "congreso", "Cs", "El nuevo proyecto común para España. Programa electoral 2015",
     "https://web.archive.org/web/20151202151928id_/https://www.ciudadanos-cs.org/var/public/sections/page-programa-electoral-20d/programa-electoral.pdf?__v=147_0",
     "archivo-web", "https://www.ciudadanos-cs.org/var/public/sections/page-programa-electoral-20d/programa-electoral.pdf"),
    ("generales-2015-erc", "generales-2015", "2015-12-20", "congreso", "ERC", "Programa electoral. Eleccions a les Corts espanyoles 2015",
     "https://static.esquerra.cat/uploads/20171218/e2015_programa.pdf", "web-partido", None),
    ("generales-2015-dl", "generales-2015", "2015-12-20", "congreso", "DL", "Programa de Democràcia i Llibertat #20D",
     "https://web.archive.org/web/20151223151727id_/http://www.democraciaillibertat.cat/wp-content/uploads/2015/12/programa-DL-2015.pdf",
     "archivo-web", "http://www.democraciaillibertat.cat/wp-content/uploads/2015/12/programa-DL-2015.pdf"),
    ("generales-2015-pnv", "generales-2015", "2015-12-20", "congreso", "PNV", "Lehenik Euskadi, es lo que importa. Programa electoral 2015",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/17970/pdf/programa-electoral-2015", "web-partido", None),

    # Generales de 2016 (XII legislatura). Ciudadanos solo lo publicó en HTML: la copia en PDF es de un medio.
    ("generales-2016-psoe", "generales-2016", "2016-06-26", "congreso", "PSOE", "Programa electoral. Elecciones generales 2016",
     "https://web.archive.org/web/20160630144135id_/http://www.psoe.es/media-content/2016/05/PSOE-Programa-Electoral-2016.pdf",
     "archivo-web", "https://www.psoe.es/media-content/2016/05/PSOE-Programa-Electoral-2016.pdf"),
    ("generales-2016-pp", "generales-2016", "2016-06-26", "congreso", "PP", "Seguir avanzando 2016-2020. Programa electoral 2016",
     "https://web.archive.org/web/20170707124516id_/http://www.pp.es/sites/default/files/documentos/programa-electoral-elecciones-generales-2016.pdf",
     "archivo-web", "https://www.pp.es/sites/default/files/documentos/programa-electoral-elecciones-generales-2016.pdf"),
    ("generales-2016-up", "generales-2016", "2016-06-26", "congreso", "UP", "Programa electoral 26J. Súmate al país que viene",
     "https://web.archive.org/web/20160615120919id_/http://lasonrisadeunpais.es/wp-content/uploads/2016/06/Podemos-Programa-Electoral-Elecciones-Generales-26J.pdf",
     "archivo-web", "http://lasonrisadeunpais.es/wp-content/uploads/2016/06/Podemos-Programa-Electoral-Elecciones-Generales-26J.pdf"),
    ("generales-2016-cs", "generales-2016", "2016-06-26", "congreso", "Cs", "350 soluciones para cambiar España a mejor",
     "https://s.libertaddigital.com/doc/programa-electoral-de-ciudadanos-para-las-elecciones-del-26-de-junio-de-2016-41913426.pdf", "copia-prensa", None),
    ("generales-2016-erc", "generales-2016", "2016-06-26", "congreso", "ERC", "Programa electoral. Eleccions a les Corts espanyoles 2016",
     "https://static.esquerra.cat/uploads/20171218/e2016_programa.pdf", "web-partido", None),
    ("generales-2016-pnv", "generales-2016", "2016-06-26", "congreso", "PNV", "Lehenik Euskadi, es lo que importa. Programa electoral 2016",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/18191/pdf/programa-eaj-pnv-elecciones-generales-2016", "web-partido", None),

    # Generales de abril de 2019 (XIII legislatura). Ciudadanos solo publicó el programa completo como página web.
    ("generales-2019-04-cs", "generales-2019-04", "2019-04-28", "congreso", "Cs", "Programa electoral. Elecciones generales 2019 (28A)",
     "https://web.archive.org/web/20190418113340id_/https://www.ciudadanos-cs.org/programa-electoral", "archivo-web",
     "https://www.ciudadanos-cs.org/programa-electoral"),
    ("generales-2019-04-psoe", "generales-2019-04", "2019-04-28", "congreso", "PSOE", "Programa electoral. Elecciones generales 2019",
     "https://web.archive.org/web/20190417002326id_/https://www.psoe.es/media-content/2019/04/PSOE-programa-electoral-elecciones-generales-28-de-abril-de-2019.pdf",
     "archivo-web", "https://www.psoe.es/media-content/2019/04/PSOE-programa-electoral-elecciones-generales-28-de-abril-de-2019.pdf"),
    ("generales-2019-04-pp", "generales-2019-04", "2019-04-28", "congreso", "PP", "Programa electoral. Elecciones generales, autonómicas y municipales 2019",
     "https://web.archive.org/web/20190423134820id_/http://www.pp.es/sites/default/files/documentos/programa-electoral-elecciones-generales-2019.pdf",
     "archivo-web", "https://www.pp.es/sites/default/files/documentos/programa-electoral-elecciones-generales-2019.pdf"),
    ("generales-2019-04-up", "generales-2019-04", "2019-04-28", "congreso", "UP", "Programa de Podemos para un nuevo país",
     "https://podemos.info/wp-content/uploads/2019/04/Podemos_programa_generales_28A.pdf", "web-partido", None),
    ("generales-2019-04-vox", "generales-2019-04", "2019-04-28", "congreso", "VOX", "100 medidas urgentes de VOX para España",
     "https://web.archive.org/web/20190426023631id_/https://www.voxespana.es/wp-content/uploads/2019/04/100medidasngal_101319181010040327.pdf",
     "archivo-web", "https://www.voxespana.es/wp-content/uploads/2019/04/100medidasngal_101319181010040327.pdf"),
    ("generales-2019-04-erc", "generales-2019-04", "2019-04-28", "congreso", "ERC", "Programa eleccions generals 2019",
     "https://static.esquerra.cat/arxius/programes/e2019-programa.pdf", "web-partido", None),
    ("generales-2019-04-pnv", "generales-2019-04", "2019-04-28", "congreso", "PNV", "Zurea, gurea. Programa electoral elecciones generales 2019",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/19093/pdf/programa-electoral-elecciones-generales-2019", "web-partido", None),

    # Generales de noviembre de 2019 (XIV legislatura). VOX mantuvo sus 100 medidas; EH Bildu queda fuera (no se ha
    # encontrado en PDF ni en su web).
    ("generales-2019-11-cs", "generales-2019-11", "2019-11-10", "congreso", "Cs", "Un gran acuerdo nacional para poner España en marcha",
     "https://web.archive.org/web/20191117072209id_/https://www.ciudadanos-cs.org/programa-electoral", "archivo-web",
     "https://www.ciudadanos-cs.org/programa-electoral"),
    ("generales-2019-11-psoe", "generales-2019-11", "2019-11-10", "congreso", "PSOE", "Ahora, progreso. Programa electoral 10N",
     "https://web.archive.org/web/20191109163211id_/https://www.psoe.es/media-content/2019/10/Ahora-progreso-programa-PSOE-10N-31102019.pdf",
     "archivo-web", "https://www.psoe.es/media-content/2019/10/Ahora-progreso-programa-PSOE-10N-31102019.pdf"),
    ("generales-2019-11-pp", "generales-2019-11", "2019-11-10", "congreso", "PP", "Por todo lo que nos une. Programa electoral 2019",
     "https://web.archive.org/web/20191102145634id_/http://www.pp.es/sites/default/files/documentos/pp_programa_electoral_2019.pdf",
     "archivo-web", "http://www.pp.es/sites/default/files/documentos/pp_programa_electoral_2019.pdf"),
    ("generales-2019-11-vox", "generales-2019-11", "2019-11-10", "congreso", "VOX", "100 medidas para la España Viva",
     "https://web.archive.org/web/20191124110055id_/https://www.voxespana.es/biblioteca/espana/2018m/gal_c2d72e181103013447.pdf",
     "archivo-web", "https://www.voxespana.es/biblioteca/espana/2018m/gal_c2d72e181103013447.pdf"),
    ("generales-2019-11-up", "generales-2019-11", "2019-11-10", "congreso", "UP", "Programa de Podemos. Las razones siguen intactas",
     "https://podemos.info/wp-content/uploads/2019/10/Podemos_programa_generales_10N.pdf", "web-partido", None),
    ("generales-2019-11-erc", "generales-2019-11", "2019-11-10", "congreso", "ERC", "Programa eleccions generals 2019. Tornarem més forts",
     "https://static.esquerra.cat/arxius/programes/e2019-2_programa.pdf", "web-partido", None),
    ("generales-2019-11-pnv", "generales-2019-11", "2019-11-10", "congreso", "PNV", "Programa electoral elecciones generales 2019-2023 (10N)",
     "https://www.eaj-pnv.eus/es/adjuntos-documentos/19437/pdf/programa-electoral-elecciones-generales-2019-10n", "web-partido", None),
]


def catalogo(ids=None):
    campos = ("id", "eleccion", "fecha_eleccion", "cuerpo", "partido", "titulo", "url", "origen", "url_oficial")
    salida = [dict(zip(campos, p)) for p in PROGRAMAS]
    return [p for p in salida if not ids or p["id"] in ids]


# ---------------------------------------------------------------- registro

def leer_registro():
    if not REGISTRO.exists():
        return []
    return [json.loads(l) for l in REGISTRO.read_text(encoding="utf-8").splitlines() if l.strip()]


def guardar_registro(entradas):
    PROGRAMAS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRO.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entradas), encoding="utf-8")


def vigentes(entradas):
    """La última entrada de cada programa del catálogo (las anteriores se conservan, pero no se usan)."""
    por_base = {}
    for e in entradas:
        por_base[e["base"]] = e
    return list(por_base.values())


def actualizar_entrada(entrada):
    """Reescribe la línea de esa entrada en el registro (por id)."""
    entradas = [entrada if e["id"] == entrada["id"] else e for e in leer_registro()]
    guardar_registro(entradas)


def ruta_texto(id_):
    return TEXTOS_DIR / f"{id_}.txt"


def texto(id_):
    return ruta_texto(id_).read_text(encoding="utf-8")


# ---------------------------------------------------------------- descarga

def _corte_columnas(ancho, palabras):
    """Coordenada x (en puntos) del hueco entre dos columnas de una página, o None. Se busca en la zona central la
    franja más ancha por la que no pasa ninguna palabra (con al menos 6 puntos y una cuarta parte de las palabras a
    cada lado) y se corta por su centro."""
    if len(palabras) < 40:
        return None
    ocupado = [0] * (int(ancho) + 2)
    for x0, x1 in palabras:
        for x in range(max(0, int(x0)), min(len(ocupado), int(x1) + 1)):
            ocupado[x] += 1
    mejor, i = None, int(ancho * 0.3)
    while i < int(ancho * 0.7):
        if ocupado[i]:
            i += 1
            continue
        j = i
        while j < int(ancho * 0.7) and not ocupado[j]:
            j += 1
        if j - i >= 6 and (not mejor or j - i > mejor[1] - mejor[0]):
            mejor = (i, j)
        i = j
    if not mejor:
        return None
    x = (mejor[0] + mejor[1]) / 2
    izquierda = sum(1 for x0, _x1 in palabras if x0 < x)
    return x if min(izquierda, len(palabras) - izquierda) >= len(palabras) / 4 else None


def _pdf_a_texto(pdf, columnas=True):
    """Texto en orden de lectura, con \\f entre páginas (pdftotext; si no está, pypdf).

    Con columnas, las páginas a dos columnas se extraen mitad a mitad: en algunos PDF, pdftotext mezcla las líneas
    de una columna con las de la otra y las citas dejan de aparecer seguidas. El hueco entre columnas sale de las
    coordenadas de cada palabra (pdftotext -bbox).
    """
    from ..territorial.contexto import _pdftotext

    exe = _pdftotext()
    if exe:
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "doc.pdf"
            entrada.write_bytes(pdf)

            def texto(*args):
                r = subprocess.run([exe, "-enc", "UTF-8", *args, str(entrada), "-"], capture_output=True, timeout=300)
                return r.stdout.decode("utf-8", "replace").replace("\r\n", "\n") if r.returncode == 0 else None

            plano = texto()
            if plano is None or not columnas:
                return plano if plano is not None else ""
            paginas = plano.split("\f")
            cajas = texto("-bbox") or ""
            for k, (w, h, cuerpo) in enumerate(re.findall(r'<page width="([\d.]+)" height="([\d.]+)">(.*?)</page>', cajas, re.S)):
                if k >= len(paginas):
                    break
                palabras = [(float(a), float(b)) for a, b in re.findall(r'<word xMin="([\d.]+)" yMin="[\d.]+" xMax="([\d.]+)"', cuerpo)]
                x = _corte_columnas(float(w), palabras)
                if x is None:
                    continue
                n, alto = str(k + 1), str(int(float(h)) + 1)
                izquierda = texto("-f", n, "-l", n, "-x", "0", "-y", "0", "-W", str(int(x)), "-H", alto)
                derecha = texto("-f", n, "-l", n, "-x", str(int(x)), "-y", "0", "-W", str(int(float(w) - x) + 1), "-H", alto)
                if izquierda is not None and derecha is not None:
                    paginas[k] = izquierda.rstrip("\f") + "\n" + derecha.rstrip("\f")
            return "\f".join(paginas)
    from pypdf import PdfReader

    return "\f".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)


def _html_a_texto(crudo):
    """Programa publicado como página web: texto con un salto de página (\\f) antes de cada apartado (<h3>, o <h2> si
    no hay), que hace de «página» para citar. Sin menús, scripts ni estilos."""
    h = crudo.decode("utf-8", "replace")
    h = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", " ", h)
    corte = "h3" if re.search(r"(?i)<h3[\s>]", h) else "h2"
    h = re.sub(rf"(?i)<{corte}[\s>]", lambda m: "\f" + m.group(0), h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>|</tr>", "\n", h)
    h = html.unescape(re.sub(r"(?s)<[^>]+>", " ", h))
    h = re.sub(r"[ \t\xa0]+", " ", h)
    return re.sub(r"\n\s*\n+", "\n\n", h).strip()


def _formato(crudo):
    if crudo.startswith(b"%PDF-"):
        return "pdf"
    return "html" if re.search(rb"(?i)<(!doctype html|html)[\s>]", crudo[:4000]) else None


def _texto(crudo):
    return _pdf_a_texto(crudo) if _formato(crudo) == "pdf" else _html_a_texto(crudo)


def descargar(ids=None, forzar=False, log=print):
    """Descarga y registra los programas del catálogo. Lo que ya está registrado con el mismo sha256 no cambia.

    Casi todos son PDF; si un partido solo publicó el programa como página web, se guarda el HTML y cada apartado
    hace de página (formato «html» en el registro).
    """
    entradas = leer_registro()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    nuevos = []
    for p in catalogo(ids):
        cache = next((c for c in (PDF_DIR / f"{p['id']}.pdf", PDF_DIR / f"{p['id']}.html") if c.exists()), None)
        if forzar or not cache:
            try:
                crudo = http_util.fetch(p["url"], timeout=180)
            except Exception as e:
                log(f"  ! {p['id']}: no se pudo descargar: {e}")
                continue
            if not _formato(crudo):
                log(f"  ! {p['id']}: la URL no devuelve un PDF ni una página web (¿protección contra robots?)")
                continue
            cache = PDF_DIR / f"{p['id']}.{_formato(crudo)}"
            cache.write_bytes(crudo)
        crudo = cache.read_bytes()
        sha = hashlib.sha256(crudo).hexdigest()
        previas = [e for e in entradas if e["base"] == p["id"]]
        if any(e["sha256"] == sha for e in previas):
            igual = next(e for e in previas if e["sha256"] == sha)
            if not ruta_texto(igual["id"]).exists():  # clon nuevo sin el texto: se regenera, el registro no cambia
                ruta_texto(igual["id"]).write_text(_texto(crudo), encoding="utf-8")
            log(f"  {igual['id']}: ya registrado ({igual['estado']}), sin cambios")
            continue
        id_ = p["id"] if not previas else f"{p['id']}-{len(previas) + 1}"
        txt = _texto(crudo)
        paginas = txt.count("\f") + (0 if txt.endswith("\f") else 1)
        caracteres = len(txt)
        TEXTOS_DIR.mkdir(parents=True, exist_ok=True)
        ruta_texto(id_).write_text(txt, encoding="utf-8")
        escaneado = caracteres / max(paginas, 1) < MIN_CARACTERES_PAGINA
        entrada = {
            "id": id_, "base": p["id"], "eleccion": p["eleccion"], "fecha_eleccion": p["fecha_eleccion"],
            "cuerpo": p["cuerpo"], "partido": p["partido"], "titulo": p["titulo"], "origen": p["origen"],
            "url": p["url"], "url_oficial": p["url_oficial"], "descargado": date.today().isoformat(),
            "sha256": sha, "formato": _formato(crudo), "paginas": paginas, "caracteres": caracteres,
            "estado": "error" if escaneado else "pendiente",
            "motivo": "sin capa de texto (escaneado): decidir aparte si merece la pena el OCR" if escaneado else None,
        }
        entradas.append(entrada)
        nuevos.append(entrada)
        log(f"  {id_}: registrado ({paginas} páginas, {caracteres:_} caracteres, {entrada['estado']})".replace("_", "."))
    if nuevos:  # se vuelve a leer el registro: otra lectura en marcha puede haberlo actualizado mientras tanto
        guardar_registro(leer_registro() + nuevos)
    log(f"Programas nuevos en el registro: {len(nuevos)}")
    return len(nuevos)


# ---------------------------------------------------------------- estado

# Precio orientativo de DeepSeek en dólares por millón de tokens (entrada, salida con el razonamiento). Solo
# sirve para estimar el gasto con los tokens anotados en el registro; el real es el de la factura. Ajustado a la
# factura del 29-09-2026 (unos 50 $ por 15,3 M de entrada y 28,2 M de salida): la referencia anterior
# (0,28 y 0,42) se quedaba en un tercio.
PRECIO_ENTRADA, PRECIO_SALIDA = 0.55, 1.50


def estado(log=print):
    entradas = leer_registro()
    if not entradas:
        log("El registro está vacío: `python -m escrutinio programas-descargar`")
        return
    from .emparejar import leer_emparejamientos

    pares = leer_emparejamientos()
    log(f"{'Programa':26} {'Estado':10} {'Págs.':>5} {'Compr.':>6} {'Verif.':>6} {'Pares':>6} {'Tokens':>10}  Leído / motivo")
    t_in = t_out = 0
    for e in entradas:
        entrada = e.get("tokens_entrada", 0) + e.get("tokens_emparejar_entrada", 0)
        salida = e.get("tokens_salida", 0) + e.get("tokens_emparejar_salida", 0)
        t_in, t_out = t_in + entrada, t_out + salida
        n_pares = sum(1 for (c, _i) in pares if c.startswith(e["id"] + ":"))
        detalle = e.get("motivo") or (f"{e.get('leido')} · {e.get('modelo')} · {e.get('version_prompt')}" if e.get("leido") else "")
        log(f"{e['id']:26} {e['estado']:10} {e.get('paginas', 0):5} {e.get('compromisos', 0) or 0:6} "
            f"{e.get('verificables', 0) or 0:6} {n_pares:6} {entrada + salida:10}  {detalle}")
    coste = t_in / 1e6 * PRECIO_ENTRADA + t_out / 1e6 * PRECIO_SALIDA
    log(f"Tokens: {t_in:_} de entrada y {t_out:_} de salida; gasto estimado: {coste:.2f} $".replace("_", "."))
    pendientes = [e["id"] for e in vigentes(entradas) if e["estado"] == "pendiente"]
    if pendientes:
        log(f"Pendientes de leer: {', '.join(pendientes)} (`python -m escrutinio programas-leer`)")
