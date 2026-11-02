"""Programas de las próximas elecciones: se buscan solos en las webs de los partidos.

En data/programas.json, «vigilar» dice a qué elección se presenta cada partido y en qué páginas de su web suele
publicar el programa (la portada vale). Hasta unos días después de la votación, cada actualización lee esas
páginas y las de su mismo sitio que enlazan con «programa» en el texto o en la dirección, y apunta cada PDF nuevo
cuyo enlace hable de programa (o de lo que diga «patron») y del año de la elección en
data/llm/programas/encontrados.json. Ese fichero se suma al catálogo, así que programas-descargar y
programas-leer lo tratan como uno más.

Para añadir un partido o una elección basta una línea en «vigilar»: no hay que tocar el código. Lo que se
encuentra solo se puede corregir a mano en encontrados.json (borrar la línea de un PDF que no es el programa y
ponerlo en «descartar» para que no vuelva a entrar).
"""

import html
import json
import re
import unicodedata
from datetime import date, timedelta
from urllib.parse import urljoin, urlsplit

from .. import http_util
from . import registro

ENCONTRADOS = registro.PROGRAMAS_DIR / "encontrados.json"
DIAS_DESPUES = 7  # tras la votación ya no se publican programas: se deja de mirar
MAX_SUBPAGINAS = 6  # páginas del mismo sitio que se siguen desde cada página vigilada
# Lo que tiene que decir el enlace (o su dirección) para tomarlo por el programa. Es estrecho a propósito: en campaña
# los partidos cuelgan muchos PDF y leer uno que no es el programa cuesta dinero. Un documento con otro nombre
# («Contrato con España») se pone con «patron» en su línea de «vigilar». Un partido nuevo que no pone el año en sus
# documentos lleva «anio»: false.
PATRON = r"programa|programme|egitarau"
# Programas de otras elecciones que el partido cuelga a la vez (el BNG publicó en 2026 el de las municipales de
# 2027, en una carpeta de 2026). Se puede cambiar con «excluir» en la línea de «vigilar».
# Tampoco los documentos internos del partido: estatutos, código ético, reglamentos, cuentas, transparencia.
EXCLUIR = (r"municipa|autonomic|europe|foral|insular|cabild|concell|ajuntament|udal|"
           r"estatut|cod\w*[- _]etic|reglament|cuentas|comptes|transparen")

_ENLACE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _plano(s):
    s = unicodedata.normalize("NFKD", html.unescape(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip().lower()


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", _plano(s)).strip("-")


def _es_pdf(url):
    return bool(re.search(r"\.pdf(?:$|[?#])|/pdf/", url, re.I))


def vigilados(hoy=None):
    """Las entradas de «vigilar» de data/programas.json cuya elección no ha pasado hace más de DIAS_DESPUES días."""
    try:
        datos = json.loads(registro.RUTA_ALTAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    hoy = hoy or date.today()
    salida = []
    for v in datos.get("vigilar", []) if isinstance(datos, dict) else []:
        if not (isinstance(v, dict) and v.get("eleccion") and v.get("partido") and v.get("paginas")):
            continue
        try:
            if date.fromisoformat(v["fecha_eleccion"]) + timedelta(days=DIAS_DESPUES) < hoy:
                continue
        except (KeyError, TypeError, ValueError):
            continue
        salida.append(v)
    return salida


def leer_encontrados():
    try:
        datos = json.loads(ENCONTRADOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {}
    return {"programas": datos.get("programas", []), "descartar": datos.get("descartar", [])}


def _guardar(datos):
    ENCONTRADOS.parent.mkdir(parents=True, exist_ok=True)
    ENCONTRADOS.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _enlaces(url):
    """[(url absoluta, texto del enlace en minúsculas y sin tildes)] de una página, o [] si no se puede leer."""
    crudo = http_util.fetch(url, retries=2, timeout=30)
    pagina = crudo.decode("utf-8", "replace")
    return [(urljoin(url, html.unescape(h.strip())), _plano(t)) for h, t in _ENLACE.findall(pagina)]


def candidatos(v, log=print):
    """URLs de PDF que parecen el programa de esa entrada de «vigilar», en el orden en que aparecen."""
    anio = v["fecha_eleccion"][:4]
    patron = re.compile(v.get("patron") or PATRON)
    excluir = re.compile(v.get("excluir") or EXCLUIR)
    vistas, salida = set(), []
    pendientes = list(v["paginas"])
    sitios = {urlsplit(p).hostname for p in v["paginas"]}
    seguidas = 0
    while pendientes:
        url = pendientes.pop(0)
        if url in vistas:
            continue
        vistas.add(url)
        try:
            enlaces = _enlaces(url)
        except Exception as e:
            log(f"  ! {v['partido']}: no se pudo leer {url}: {type(e).__name__}: {e}")
            continue
        for href, texto in enlaces:
            dice = f"{_plano(href)} {texto}"
            if _es_pdf(href):
                # El año, en el nombre del fichero o en el enlace; si ahí sale otro año y no el de la elección, es otro
                # documento aunque esté en una carpeta de este año.
                propio = f"{_plano(urlsplit(href).path.rsplit('/', 1)[-1])} {texto}"
                anios = set(re.findall(r"20\d\d", propio))
                con_anio = v.get("anio", True)  # false: partido nuevo, todo lo que publica es para esta elección
                if (patron.search(dice) and (not con_anio or (anio in dice and (not anios or anio in anios)))
                        and not excluir.search(dice) and href not in salida):
                    salida.append(href)
            elif (urlsplit(href).hostname in sitios and re.search(r"programa|programme|egitarau", dice)
                  and seguidas < MAX_SUBPAGINAS and href not in vistas and href.startswith("http")):
                pendientes.append(href)
                seguidas += 1
    return salida


def buscar(log=print):
    """Apunta en encontrados.json los programas nuevos de las elecciones vigiladas. Devuelve sus ids."""
    vigilar = vigilados()
    if not vigilar:
        return []
    datos = leer_encontrados()
    conocidas = {u for p in registro.catalogo() for u in (p["url"], p.get("url_oficial")) if u}
    conocidas |= set(datos["descartar"])
    ids = {p["id"] for p in registro.catalogo()}
    nuevos = []
    for v in vigilar:
        for url in candidatos(v, log):
            if url in conocidas:
                continue
            base = f"{v['eleccion']}-{_slug(v['partido'])}"
            id_ = next(i for i in [base] + [f"{base}-doc{n}" for n in range(2, 50)] if i not in ids)
            nombre = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
            p = {"id": id_, "eleccion": v["eleccion"], "fecha_eleccion": v["fecha_eleccion"],
                 "cuerpo": v.get("cuerpo", "congreso"), "partido": v["partido"],
                 "titulo": v.get("titulo") or f"Programa electoral ({nombre})", "url": url,
                 "origen": "web-partido", "url_oficial": None, "encontrado": date.today().isoformat()}
            datos["programas"].append(p)
            conocidas.add(url)
            ids.add(id_)
            nuevos.append(id_)
            log(f"  {id_}: encontrado {url}")
    if nuevos:
        _guardar(datos)
    log(f"Programas nuevos encontrados en las webs de los partidos: {len(nuevos)}")
    return nuevos
