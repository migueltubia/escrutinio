"""Programas de las próximas elecciones: se buscan solos en las webs de los partidos.

En data/programas.json, «vigilar» dice a qué elección se presenta cada partido y en qué páginas de su web suele
publicar el programa (la portada vale). Hasta unos días después de la votación, cada actualización lee esas
páginas y las de su mismo sitio que enlazan con «programa» en el texto o en la dirección, y apunta cada PDF nuevo
cuyo enlace hable de programa (o de lo que diga «patron») y del año de la elección en
data/llm/programas/encontrados.json. Ese fichero se suma al catálogo, así que programas-descargar y
programas-leer lo tratan como uno más.

Para no leer dos veces lo mismo (cada lectura se paga): si un PDF nuevo se llama igual que uno ya encontrado de ese
partido, es el mismo documento en otra dirección o corregido, y solo se cambia la dirección del que ya estaba (el
registro decide por el contenido si hay que volver a leerlo); si solo cambia el idioma del nombre («PROGRAMA-EUS.pdf»
junto a «PROGRAMA-CAS.pdf») o lleva marca de otro idioma («/eu/…») y el partido ya tiene programa, es una traducción y
no entra.

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
MAX_SUBPAGINAS = 8  # páginas del mismo sitio (o de sus subdominios) que se siguen desde cada página vigilada
# Lo que tiene que decir el enlace (o su dirección) para tomarlo por el programa. Es estrecho a propósito: en campaña
# los partidos cuelgan muchos PDF y leer uno que no es el programa cuesta dinero. Un documento con otro nombre
# («Contrato con España») se pone con «patron» en su línea de «vigilar». Un partido nuevo que no pone el año en sus
# documentos lleva «anio»: false.
PATRON = r"program[ae]|egitarau"  # programa, programes, programme
# Programas de otras elecciones que el partido cuelga a la vez (el BNG publicó en 2026 el de las municipales de
# 2027, en una carpeta de 2026). Se puede cambiar con «excluir» en la línea de «vigilar».
# Tampoco los documentos internos del partido: estatutos, código ético, reglamentos, cuentas, transparencia.
EXCLUIR = (r"municipa|autonomic|europe|foral|insular|cabild|concell|ajuntament|udal|"
           r"estatut|cod\w*[- _]etic|reglament|cuentas|comptes|transparen")

MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
# Marcas de idioma en el nombre de un fichero: dos nombres que solo se diferencian en esto son traducciones.
IDIOMAS = r"eus|eu|cas|cast|es|cat|ca|gal|gl|val|va|en|eng"
OTROS_IDIOMAS = r"eus|eu|cat|ca|gal|gl|val|va|en|eng"  # en una carpeta («/eu/») o en el nombre: no es la versión en castellano

_ENLACE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def _plano(s):
    s = unicodedata.normalize("NFKD", html.unescape(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip().lower()


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "-", _plano(s)).strip("-")


def _es_pdf(url):
    return bool(re.search(r"\.pdf(?:$|[?#])|/pdf/", url, re.I))


def _dia_eleccion(fecha):
    """Cómo se suele escribir el día de la votación en un enlace: «29n», «29-n», «29nov»."""
    d = date.fromisoformat(fecha)
    mes = MESES[d.month - 1]
    return re.compile(rf"(?<!\d){d.day}[-_ ]?(?:{mes[0]}(?![a-z])|{mes})")


def _mismo_sitio(host, sitios):
    """Si ese servidor es uno de los vigilados o un subdominio suyo (posibleegin.ehbildu.eus con ehbildu.eus)."""
    for s in sitios:
        base = (s or "").removeprefix("www.")
        if host and base and (host == s or host == base or host.endswith("." + base)):
            return True
    return False


def _nombre(url):
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].lower()


def _sin_idioma(nombre):
    return re.sub(rf"(?<![a-z0-9])(?:{IDIOMAS})(?![a-z0-9])", "", nombre)


def _otro_idioma(url):
    return bool(re.search(rf"(?<![a-z0-9])(?:{OTROS_IDIOMAS})(?![a-z0-9])", urlsplit(url).path.lower()))


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
    dia = _dia_eleccion(v["fecha_eleccion"])
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
            if "mailto:" in href or "{" in href or "%7b" in href.lower():  # enlaces rotos de plantilla
                continue
            dice = f"{_plano(href)} {texto}"
            if _es_pdf(href):
                # El año de la elección, en el enlace o en la dirección de la página que lo enlaza (el PNV lo colgó en
                # «/programa-elecciones-generales-2026/» como «programa-electoral-29n»); también vale el día de la
                # votación («29n»). Si en el nombre del fichero o en el texto del enlace sale otro año y no el de la
                # elección, es otro documento aunque esté en una carpeta de este año.
                propio = f"{_plano(urlsplit(href).path.rsplit('/', 1)[-1])} {texto}"
                anios = set(re.findall(r"20\d\d", propio))
                con_anio = v.get("anio", True)  # false: partido nuevo, todo lo que publica es para esta elección
                de_esta = anio in dice or dia.search(dice) or anio in _plano(urlsplit(url).path)
                if (patron.search(dice) and (not con_anio or (de_esta and (not anios or anio in anios)))
                        and not excluir.search(dice) and href not in salida):
                    salida.append(href)
            elif (_mismo_sitio(urlsplit(href).hostname, sitios) and re.search(PATRON, dice)
                  and seguidas < MAX_SUBPAGINAS and href not in vistas and href.startswith("http")):
                pendientes.append(href)
                seguidas += 1
    return salida


def buscar(log=print):
    """Apunta en encontrados.json los programas nuevos de las elecciones vigiladas. Devuelve los ids que hay que
    bajar: los nuevos y los que han cambiado de dirección."""
    vigilar = vigilados()
    if not vigilar:
        return []
    datos = leer_encontrados()
    catalogo = registro.catalogo()
    conocidas = {u for p in catalogo for u in (p["url"], p.get("url_oficial")) if u}
    conocidas |= set(datos["descartar"]) | {u for p in datos["programas"] for u in p.get("otras_urls", [])}
    ids = {p["id"] for p in catalogo}
    nuevos, movidos = [], []
    for v in vigilar:
        # Primero los que no llevan marca de otro idioma: si el programa está en castellano y en euskera, entra el primero.
        for url in sorted(candidatos(v, log), key=_otro_idioma):
            if url in conocidas:
                continue
            fichero = _nombre(url)
            hermanos = [p for p in catalogo if p["eleccion"] == v["eleccion"] and p["partido"] == v["partido"]]
            igual = next((p for p in hermanos if _nombre(p["url"]) == fichero), None)
            propio = igual and next((d for d in datos["programas"] if d["id"] == igual["id"]), None)
            if propio:  # el mismo fichero en otra dirección: sigue siendo ese documento
                propio.setdefault("otras_urls", []).append(propio["url"])
                propio["url"] = igual["url"] = url
                conocidas.add(url)
                movidos.append(propio["id"])
                log(f"  {propio['id']}: ahora está en {url}")
                continue
            if not igual and hermanos and (_otro_idioma(url)
                                           or any(_sin_idioma(_nombre(p["url"])) == _sin_idioma(fichero) for p in hermanos)):
                log(f"  {v['partido']}: {url} es el mismo programa en otro idioma; no se añade")
                continue
            base = f"{v['eleccion']}-{_slug(v['partido'])}"
            id_ = next(i for i in [base] + [f"{base}-doc{n}" for n in range(2, 50)] if i not in ids)
            nombre = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
            p = {"id": id_, "eleccion": v["eleccion"], "fecha_eleccion": v["fecha_eleccion"],
                 "cuerpo": v.get("cuerpo", "congreso"), "partido": v["partido"],
                 "titulo": v.get("titulo") or f"Programa electoral ({nombre})", "url": url,
                 "origen": "web-partido", "url_oficial": None, "encontrado": date.today().isoformat()}
            datos["programas"].append(p)
            catalogo.append(p)
            conocidas.add(url)
            ids.add(id_)
            nuevos.append(id_)
            log(f"  {id_}: encontrado {url}")
    if nuevos or movidos:
        _guardar(datos)
    log(f"Programas nuevos encontrados en las webs de los partidos: {len(nuevos)}"
        + (f" (y {len(movidos)} que han cambiado de dirección)" if movidos else ""))
    return nuevos + movidos
