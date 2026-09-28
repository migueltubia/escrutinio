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
import io
import json
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
# tras la elección. Si la web del partido no deja descargar (psoe.es está tras una protección contra
# robots, que no se intenta saltar), se usa la copia que publicó un medio y se guarda también la oficial.
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

def _pdf_a_texto(pdf):
    """Texto en orden de lectura, con \\f entre páginas (pdftotext; si no está, pypdf)."""
    from ..territorial.contexto import _pdftotext

    exe = _pdftotext()
    if exe:
        with tempfile.TemporaryDirectory() as tmp:
            entrada = Path(tmp) / "doc.pdf"
            entrada.write_bytes(pdf)
            r = subprocess.run([exe, "-enc", "UTF-8", str(entrada), "-"], capture_output=True, timeout=300)
            if r.returncode == 0:
                return r.stdout.decode("utf-8", "replace")
    from pypdf import PdfReader

    return "\f".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf)).pages)


def descargar(ids=None, forzar=False, log=print):
    """Descarga y registra los programas del catálogo. Lo que ya está registrado con el mismo sha256 no cambia."""
    entradas = leer_registro()
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    nuevos = 0
    for p in catalogo(ids):
        cache = PDF_DIR / f"{p['id']}.pdf"
        if forzar or not cache.exists():
            try:
                pdf = http_util.fetch(p["url"], timeout=180)
            except Exception as e:
                log(f"  ! {p['id']}: no se pudo descargar: {e}")
                continue
            if not pdf.startswith(b"%PDF-"):
                log(f"  ! {p['id']}: la URL no devuelve un PDF (¿página de protección contra robots?)")
                continue
            cache.write_bytes(pdf)
        pdf = cache.read_bytes()
        sha = hashlib.sha256(pdf).hexdigest()
        previas = [e for e in entradas if e["base"] == p["id"]]
        if any(e["sha256"] == sha for e in previas):
            igual = next(e for e in previas if e["sha256"] == sha)
            if not ruta_texto(igual["id"]).exists():  # clon nuevo sin el texto: se regenera, el registro no cambia
                ruta_texto(igual["id"]).write_text(_pdf_a_texto(pdf), encoding="utf-8")
            log(f"  {igual['id']}: ya registrado ({igual['estado']}), sin cambios")
            continue
        id_ = p["id"] if not previas else f"{p['id']}-{len(previas) + 1}"
        txt = _pdf_a_texto(pdf)
        paginas = txt.count("\f") + (0 if txt.endswith("\f") else 1)
        caracteres = len(txt)
        TEXTOS_DIR.mkdir(parents=True, exist_ok=True)
        ruta_texto(id_).write_text(txt, encoding="utf-8")
        escaneado = caracteres / max(paginas, 1) < MIN_CARACTERES_PAGINA
        entrada = {
            "id": id_, "base": p["id"], "eleccion": p["eleccion"], "fecha_eleccion": p["fecha_eleccion"],
            "cuerpo": p["cuerpo"], "partido": p["partido"], "titulo": p["titulo"], "origen": p["origen"],
            "url": p["url"], "url_oficial": p["url_oficial"], "descargado": date.today().isoformat(),
            "sha256": sha, "paginas": paginas, "caracteres": caracteres,
            "estado": "error" if escaneado else "pendiente",
            "motivo": "sin capa de texto (escaneado): decidir aparte si merece la pena el OCR" if escaneado else None,
        }
        entradas.append(entrada)
        nuevos += 1
        log(f"  {id_}: registrado ({paginas} páginas, {caracteres:_} caracteres, {entrada['estado']})".replace("_", "."))
    guardar_registro(entradas)
    log(f"Programas nuevos en el registro: {nuevos}")
    return nuevos


# ---------------------------------------------------------------- estado

# Precio orientativo de DeepSeek en dólares por millón de tokens (entrada sin caché, salida). Solo sirve
# para estimar el gasto con los tokens anotados en el registro; el real es el de la factura.
PRECIO_ENTRADA, PRECIO_SALIDA = 0.28, 0.42


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
