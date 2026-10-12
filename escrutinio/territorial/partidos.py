"""Partido, siglas y color de un grupo a partir del nombre que publica cada fuente.

Las fuentes escriben el mismo grupo de mil maneras («Grupo Parlamentario Socialista», «G.P.S.»,
«PSOE», «Socialistas de Gijón»). Aquí se reconoce el partido para que las siglas sean las mismas en
todas las instituciones (así la web puede sumar «el PSOE» del Congreso, de un parlamento y de un
ayuntamiento) y el color, el habitual del partido.
"""

import hashlib
import json
import re
import sqlite3

from ..config import DATA_DIR
from ..texto import normalizar

# Partidos dados de alta a mano, fuera del código, para no tener que editar y desplegar por cada partido
# nuevo. El proceso diario lee este fichero al arrancar. Formato y ejemplos: en el propio fichero.
RUTA_ALTAS = DATA_DIR / "partidos.json"

# (patrón sobre el nombre normalizado, siglas, color). Se prueban en orden: primero lo específico. Las
# altas de data/partidos.json se insertan justo después de «Mixto», antes de los partidos de aquí.
PARTIDOS_BASE = [
    (r"\bno adscrit|\bsin adscripcion|\bno inscrit|\bdiputad[oa]s? no adscrit|\bconcejal(es)? no adscrit", "No adscritos", "#b4b4b4"),
    (r"\bmixto\b|\bmixt\b|\btalde mistoa\b", "Mixto", "#8a8f98"),
    (r"\bvox\b", "VOX", "#63be21"),
    (r"navarra suma|\bna\+", "NA+", "#1d4f9c"),
    (r"\bupn\b|union del pueblo navarro", "UPN", "#1d4f9c"),
    (r"\bcup\b|unitat popular|unidad popular", "CUP", "#ffed00"),
    (r"agrupacion socialista gomera|\basg\b", "ASG", "#2f8f3a"),
    (r"\bpartido popular\b|\bpopular(es)?\b|\bpp\b|\bgpp\b", "PP", "#1d84ce"),
    (r"\bpsc\b|socialistes de catalunya", "PSOE", "#e30613"),
    (r"socialista|\bpsoe\b|\bpsd?e\b|\bpse ee\b|\bfsa\b|\bpsib\b|\bpspv\b|\bpsdeg\b|\bpsn\b|\bgps\b|\bsocialistas?\b", "PSOE", "#e30613"),
    (r"ciudadanos|\bciutadans\b|\bcs\b|\bc s\b", "Cs", "#eb6109"),
    (r"union progreso y democracia|\bupyd\b", "UPyD", "#e2007a"),
    (r"eh bildu|\bbildu\b", "Bildu", "#00a19a"),
    (r"eaj pnv|\bpnv\b|\beaj\b|nacionalistas vascos|euzko abertzaleak", "PNV", "#008000"),
    (r"geroa bai", "Geroa Bai", "#e0301e"),
    (r"compromis", "Compromís", "#f18a00"),
    (r"mas madrid|mas pais|\bmes madrid", "Más Madrid", "#00c19d"),
    (r"\bsumar\b|movimiento sumar", "Sumar", "#e5007d"),
    (r"adelante andalucia", "Adelante Andalucía", "#00a650"),
    (r"elkarrekin|unidas podemos|unidos podemos|unidas por|unides podem|\bpodemos\b|\bpodem\b|\bpodemos\b|en comu podem", "Podemos", "#6c3483"),
    (r"\bcomuns\b|en comu|catalunya en comu|comuns sumar", "Comuns", "#c3113b"),
    (r"extremadura unida|juntos por extremadura", "EU-Ext", "#2e7d32"),
    (r"izquierda unida|\biu\b|esquerra unida|\beu\b|ezker batua|\bgeup\b", "IU", "#a31c2c"),
    (r"por andalucia", "Por Andalucía", "#6c3483"),
    (r"esquerra republicana|\berc\b|republicano", "ERC", "#ffb232"),
    (r"junts|junts per catalunya|\bjxcat\b|\bjxc\b|convergencia", "Junts", "#20c0b2"),
    (r"alianca catalana", "Aliança Catalana", "#0a2a5e"),
    (r"\bbng\b|bloque nacionalista galego", "BNG", "#76b3dd"),
    (r"coalicion canaria|\bcc\b|\bcc pnc\b|\bcc an\b", "CC", "#f7c600"),
    (r"nueva canarias|\bnc\b|\bnc bc\b", "NC", "#8fbe00"),
    (r"foro asturias|\bforo\b|\bfac\b", "Foro", "#0071bc"),
    (r"partido regionalista de cantabria|\bprc\b|regionalista", "PRC", "#a2c73b"),
    (r"chunta|\bcha\b", "CHA", "#9e1a2c"),
    (r"partido aragones|\bpar\b", "PAR", "#f7b500"),
    (r"teruel existe", "Teruel Existe", "#00833e"),
    (r"soria ya", "Soria Ya", "#2e8b57"),
    (r"union del pueblo leones|\bupl\b", "UPL", "#b5163c"),
    (r"por avila|\bxav\b", "Por Ávila", "#1f5ea8"),
    (r"mes per mallorca|\bmes per menorca\b|\bmes\b", "Més", "#c5d300"),
    (r"\bel pi\b|proposta per les illes", "El Pi", "#7a4d9c"),
    (r"coalicion por melilla|\bcpm\b", "CpM", "#1b8a3a"),
    (r"movimiento por la dignidad|\bmdyc\b", "MDyC", "#7cb342"),
    (r"caballas", "Caballas", "#3a7d44"),
]


def _altas():
    """Lee data/partidos.json: lista de (patrón, siglas, color). Si falta o está mal, no pasa nada."""
    try:
        datos = json.loads(RUTA_ALTAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = datos.get("partidos", []) if isinstance(datos, dict) else datos
    salida = []
    for it in items:
        if isinstance(it, dict):
            patron, siglas, color = it.get("patron"), it.get("siglas"), it.get("color")
        elif isinstance(it, (list, tuple)) and len(it) >= 3:
            patron, siglas, color = it[0], it[1], it[2]
        else:
            continue
        if patron and siglas and color:
            try:
                re.compile(patron)
            except re.error:
                continue
            salida.append((patron, siglas, color))
    return salida


def _construir():
    """Tabla efectiva: las altas van tras «Mixto» (índice 2), antes que los partidos base, que son más genéricos."""
    altas = _altas()
    return PARTIDOS_BASE[:2] + altas + PARTIDOS_BASE[2:]


# La tabla que usa reconocer(). Se arma al importar; el proceso diario arranca de cero en cada ejecución.
PARTIDOS = _construir()


# Palabras de relleno del nombre de un grupo, para quedarse con lo que lo identifica.
_GENERICO = re.compile(
    r"(?i)^\s*(el\s+|la\s+)?(grupos?|g\.?\s*p\.?|g\.?\s*m\.?|talde|grup)\s+((parlamentari[oa]?|municipal|pol[ií]tico|"
    r"de\s+junteros|de\s+procuradores|juntero|mixto(?=\s+-))\s*)?(de\s+|del\s+|d')?")
_MINUSCULAS = {"de", "del", "la", "las", "los", "el", "y", "e", "i", "por", "para", "en", "a", "per", "da", "do"}


def _limpio(nombre):
    return normalizar(nombre).replace("-", " ")


def reconocer(nombre):
    """(siglas, color) del partido de un grupo, o (None, None) si no se reconoce.

    Un grupo mixto con un solo partido en el nombre («G.P. Mixto-Adelante Andalucía») es ese partido.
    """
    n = _limpio(nombre)
    if re.search(PARTIDOS[1][0], n):
        resto = re.sub(PARTIDOS[1][0], " ", n)
        for patron, siglas, color in PARTIDOS[2:]:
            if re.search(patron, resto):
                return siglas, color
        return PARTIDOS[1][1], PARTIDOS[1][2]
    for patron, siglas, color in PARTIDOS:
        if re.search(patron, n):
            return siglas, color
    return None, None


def color_neutro(texto):
    """Color estable (gris azulado variado) para grupos locales sin partido conocido."""
    tonos = ["#6b7b8c", "#7a8f6a", "#8c7b6b", "#6b8c86", "#86738c", "#8c8a6b", "#5f7f9e", "#9e7f5f"]
    return tonos[int(hashlib.md5(texto.encode()).hexdigest(), 16) % len(tonos)]


def _nombre_propio(texto):
    """«VECINOS POR GIJÓN» -> «Vecinos por Gijón»; respeta siglas cortas y lo que ya viene con mayúsculas."""
    palabras = texto.split()
    if texto.upper() != texto:
        return " ".join(palabras)
    out = []
    for i, w in enumerate(palabras):
        if i and w.lower() in _MINUSCULAS:
            out.append(w.lower())
        elif len(w) <= 3 and w.isalpha():
            out.append(w)  # probablemente unas siglas
        else:
            out.append(w.capitalize())
    return " ".join(out)


def codigo_grupo(nombre):
    """(código, siglas, color) de un grupo. El código es único por legislatura y estable."""
    nombre = re.sub(r"\s+", " ", (nombre or "").strip())
    if not nombre:
        return "?", "?", "#9aa0a6"
    siglas, color = reconocer(nombre)
    if siglas:
        return siglas, siglas, color
    # Grupo local o sin partido reconocido: el propio nombre, sin «Grupo Municipal» y demás.
    corto = _nombre_propio(_GENERICO.sub("", nombre).strip(" .-–:()")) or nombre
    corto = corto[:40]
    return corto, corto, color_neutro(normalizar(corto))


# ---------------------------------------------------------------- radar de partidos nuevos

def grupos_pendientes(bd_dir=None):
    """Grupos de todas las bases troceadas (data/bd/) que reconocer() NO identifica: posibles partidos nuevos.

    Devuelve {clave: {codigo, grupos, cuerpos, ejemplo}} agrupando por el código del grupo. Lee de lo
    versionado en el repositorio, así que no necesita la base de trabajo y da igual en el equipo o en Actions.
    Un grupo puramente local (sin partido nacional) también sale aquí: lo que distingue a un partido nuevo de
    verdad es que aparezca en varias instituciones, de ahí que se cuenten los «cuerpos».
    """
    bd_dir = bd_dir or (DATA_DIR / "bd")
    agg = {}
    for ruta in sorted(bd_dir.rglob("*.sqlite")):
        cuerpo = ruta.parent.name  # data/bd/<cuerpo>/legN.sqlite: el código de la institución es la carpeta
        try:
            con = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
        except sqlite3.Error:
            continue
        try:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='grupo'").fetchone():
                continue
            filas = con.execute("SELECT nombre, codigo FROM grupo").fetchall()
        except sqlite3.Error:
            continue
        finally:
            con.close()
        for nombre, codigo in filas:
            if not nombre or codigo == "?" or reconocer(nombre)[0]:
                continue  # «?» es el marcador de un grupo sin nombre, no un partido
            clave = normalizar(codigo or nombre)
            e = agg.setdefault(clave, {"codigo": codigo or nombre, "grupos": 0, "cuerpos": set(), "ejemplo": nombre})
            e["grupos"] += 1
            e["cuerpos"].add(cuerpo)
    return agg


def anunciar_pendientes(log=print, bd_dir=None, limite=20, min_cuerpos=1):
    """Lista los grupos sin reconocer, los más repartidos primero. En GitHub Actions avisa de los que
    aparecen en varias instituciones (los candidatos más claros a ser un partido nuevo)."""
    import os

    agg = grupos_pendientes(bd_dir)
    orden = sorted(agg.values(), key=lambda e: (len(e["cuerpos"]), e["grupos"]), reverse=True)
    orden = [e for e in orden if len(e["cuerpos"]) >= min_cuerpos]
    if not orden:
        log("No hay grupos sin partido reconocido.")
        return []
    log(f"Grupos sin partido reconocido (posibles partidos nuevos): {len(orden)}")
    log(f"  {'Código':42} {'Grupos':>6} {'Insts.':>6}  Instituciones")
    for e in orden[:limite]:
        cuerpos = ", ".join(sorted(e["cuerpos"]))
        log(f"  {e['codigo'][:42]:42} {e['grupos']:6} {len(e['cuerpos']):6}  {cuerpos[:70]}")
    if len(orden) > limite:
        log(f"  … y {len(orden) - limite} más.")
    log("Para dar uno de alta: añade una entrada en data/partidos.json (ver la cabecera del fichero).")

    # En GitHub Actions, los que aparecen en 2+ instituciones salen como aviso del resumen de la ejecución.
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for e in orden:
            if len(e["cuerpos"]) < 2:
                continue
            titulo = f"Grupo sin reconocer: {e['codigo']}".replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
            msg = (f"Aparece en {len(e['cuerpos'])} instituciones ({', '.join(sorted(e['cuerpos']))}) y no se "
                   f"reconoce. Si es un partido, dalo de alta en data/partidos.json.").replace("%", "%25").replace("\n", " ")
            print(f"::warning title={titulo}::{msg}", flush=True)
    return orden
