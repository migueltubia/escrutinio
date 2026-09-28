import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "escrutinio.sqlite"
LLM_DIR = DATA_DIR / "llm"
WEB_DIR = ROOT / "web"

CONGRESO = "https://www.congreso.es"
VOTACIONES_URL = CONGRESO + "/es/opendata/votaciones"
BUSCADOR_INICIATIVAS_URL = (
    CONGRESO
    + "/es/busqueda-de-iniciativas?p_p_id=iniciativas&p_p_lifecycle=2&p_p_state=normal"
    "&p_p_mode=view&p_p_resource_id=filtrarListado&p_p_cacheability=cacheLevelPage"
)

USER_AGENT = "escrutinio/0.1 (analisis local de datos abiertos del Congreso)"

# Legislaturas con votaciones nominales en datos abiertos (la IX y anteriores no tienen).
LEGISLATURAS = {
    10: ("X", "2011-12-13", "2016-01-13"),
    11: ("XI", "2016-01-13", "2016-07-19"),
    12: ("XII", "2016-07-19", "2019-05-21"),
    13: ("XIII", "2019-05-21", "2019-12-03"),
    14: ("XIV", "2019-12-03", "2023-08-17"),
    15: ("XV", "2023-08-17", None),
}

MAYORIA_ABSOLUTA_CONGRESO = 176


def _cargar_env(ruta=ROOT / ".env"):
    """Carga en el entorno las variables de un fichero .env (CLAVE=valor, una por línea) que no estén ya.

    Es donde va la clave de DeepSeek al actualizar desde un equipo (copiar .env.ejemplo); en GitHub
    Actions llegan como secretos y variables del repositorio, que tienen prioridad. El fichero está en
    .gitignore. Sin bibliotecas: se ignoran las líneas en blanco y los comentarios con #, y se quitan
    las comillas alrededor del valor.
    """
    try:
        lineas = ruta.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for linea in lineas:
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave = clave.strip().removeprefix("export ").strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if clave and valor:
            os.environ.setdefault(clave, valor)


_cargar_env()
