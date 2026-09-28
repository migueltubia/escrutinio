"""IA con DeepSeek (API compatible con OpenAI) para la actualización automática.

Solo usa la biblioteca estándar. Variables de entorno (o del fichero .env de la raíz, que carga
escrutinio/config.py; en GitHub Actions son secretos y variables del repositorio):
  DEEPSEEK_API_KEY   (obligatoria)
  DEEPSEEK_MODEL     (por defecto deepseek-flash)
  DEEPSEEK_BASE_URL  (por defecto https://api.deepseek.com)

Todo lo que genera se valida contra los catálogos cerrados y se guarda en ficheros versionados
(data/llm/...), que son la fuente de verdad: la base de datos se puede reconstruir sin volver a
llamar a la IA.
"""

import http.client
import io
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from ..catalogos import TIPOS_VOTACION
from ..config import LLM_DIR
from .fichas_io import guardar_fichas, items_en_tramite, items_pendientes
from .prompt import FICHA_SCHEMA, SYSTEM, validar

POR_LLAMADA = 15


class ErrorIA(RuntimeError):
    pass


class RespuestaTruncada(ErrorIA):
    """La respuesta no cabe en max_tokens: hay que pedir menos de una vez (partir el lote o el texto)."""


def disponible():
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def modelo_por_defecto():
    return os.environ.get("DEEPSEEK_MODEL") or "deepseek-flash"


# Se añade a todas las peticiones: los textos se publican en una web española.
IDIOMA = ("Escribe siempre en español de España (castellano peninsular): ortografía, vocabulario y "
          "expresiones de España, no de Hispanoamérica, aunque el texto original esté en otra lengua.")


def _salida(uso):
    """«8000 tokens de salida, 5210 de razonamiento»: para saber por qué no cupo una respuesta."""
    uso = uso or {}
    razonamiento = (uso.get("completion_tokens_details") or {}).get("reasoning_tokens")
    return f"{uso.get('completion_tokens', '?')} tokens de salida" + (f", {razonamiento} de razonamiento" if razonamiento else "")


def chat_json(sistema, usuario, modelo=None, max_tokens=32_000, reintentos=5):
    """Una llamada en modo JSON. Devuelve (objeto, modelo_real, uso).

    max_tokens cuenta también el razonamiento previo del modelo (modo thinking): con 8.000 se agotaba
    pensando y no escribía nada, de ahí el defecto de 32.000 (la API admite hasta 384K).
    """
    base = (os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    cuerpo = {
        "model": modelo or modelo_por_defecto(),
        "messages": [{"role": "system", "content": f"{sistema}\n\n{IDIOMA}"}, {"role": "user", "content": usuario}],
        "response_format": {"type": "json_object"},
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": False,
    }
    peticion = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(cuerpo).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}"},
    )
    ultimo = None
    for intento in range(reintentos):
        try:
            with urllib.request.urlopen(peticion, timeout=600) as r:
                d = json.loads(r.read().decode("utf-8"))
            eleccion = d["choices"][0]
            contenido = (eleccion.get("message") or {}).get("content") or ""
            if eleccion.get("finish_reason") == "length":
                raise RespuestaTruncada(f"respuesta truncada por max_tokens ({_salida(d.get('usage'))})")
            if not contenido.strip():
                ultimo = ErrorIA("respuesta vacía")  # la documentación avisa de que puede pasar en modo JSON
            else:
                return json.loads(contenido), d.get("model") or cuerpo["model"], d.get("usage") or {}
        except urllib.error.HTTPError as e:
            detalle = e.read().decode("utf-8", "replace")[:300]
            if e.code in (429, 500, 502, 503, 504):
                ultimo = ErrorIA(f"HTTP {e.code}: {detalle}")
            else:
                raise ErrorIA(f"HTTP {e.code}: {detalle}") from e
        except json.JSONDecodeError as e:
            ultimo = ErrorIA(f"JSON inválido en la respuesta: {e}")
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException) as e:
            ultimo = ErrorIA(f"red: {e}")  # también respuestas cortadas (IncompleteRead, RemoteDisconnected)
        time.sleep(min(60, 5 * 2 ** intento))
    raise ultimo or ErrorIA("sin respuesta")


# ---------------------------------------------------------------- fichas

SISTEMA_FICHAS = (
    SYSTEM
    + "\nFormato de salida: responde SOLO con un objeto json con la clave «fichas», una lista con una ficha por "
    "iniciativa, en el mismo orden y con el mismo «id». Cada ficha sigue exactamente este esquema json:\n"
    + json.dumps(FICHA_SCHEMA, ensure_ascii=False)
    + '\nEjemplo de salida json: {"fichas": [{"id": "15:162/000001", "resumen": "Insta al Gobierno a ampliar el parque '
    'público de vivienda en alquiler.", "bloques": [], "tema_principal": "VIV", "temas_secundarios": [], "etiquetas": '
    '["vivienda pública", "alquiler"], "ambito": "estatal", "marcas": [], "leyes_afectadas": [], "confianza": 0.8}]}'
)


def generar_fichas(con, limite=400, modelo=None, log=print):
    """Genera fichas para iniciativas votadas o en trámite que aún no la tienen."""
    vistos, items = set(), []
    for it in items_pendientes(con) + items_en_tramite(con):
        if it["id"] not in vistos:
            vistos.add(it["id"])
            items.append(it)
    if not items:
        log("No hay iniciativas pendientes de ficha")
        return 0
    items = items[:limite]
    log(f"Fichas con DeepSeek: {len(items)} iniciativas pendientes (límite {limite})")
    carpeta = LLM_DIR / "resultados" / "deepseek"
    carpeta.mkdir(parents=True, exist_ok=True)
    salida = carpeta / f"{datetime.now(timezone.utc):%Y-%m-%d}.jsonl"
    hechas, fallidas, tokens = 0, [], 0
    for i in range(0, len(items), POR_LLAMADA):
        lote = i // POR_LLAMADA + 1
        # (iniciativas, ronda): la segunda ronda, solo con las que faltaron o salieron mal. Si la respuesta no
        # cabe en max_tokens, el grupo se parte en dos y se piden por separado.
        cola = [(items[i : i + POR_LLAMADA], 0)]
        while cola:
            pendientes, ronda = cola.pop(0)
            ids = {it["id"] for it in pendientes}
            try:
                datos, modelo_real, uso = chat_json(SISTEMA_FICHAS, "Genera las fichas en json para estas iniciativas:\n"
                                                    + "\n".join(json.dumps(it, ensure_ascii=False) for it in pendientes), modelo)
            except RespuestaTruncada as e:
                if len(pendientes) > 1:
                    mitad = len(pendientes) // 2
                    log(f"  · lote {lote}: {e}; se parte en {mitad} + {len(pendientes) - mitad}")
                    cola[:0] = [(pendientes[:mitad], ronda), (pendientes[mitad:], ronda)]
                else:
                    log(f"  ! lote {lote}: la ficha de {pendientes[0]['id']} no cabe: {e}")
                    fallidas += [it["id"] for it in pendientes]
                continue
            except ErrorIA as e:
                log(f"  ! lote {lote}: {e}")
                fallidas += [it["id"] for it in pendientes]
                continue
            tokens += uso.get("total_tokens", 0)
            buenas = []
            for f in datos.get("fichas") or []:
                if not isinstance(f, dict) or f.get("id") not in ids:
                    continue
                ficha, errores = validar(dict(f))
                if ficha and ficha.get("resumen", "").strip():
                    buenas.append(ficha)
            etiqueta = f"deepseek:{modelo_real}"
            ok, _ = guardar_fichas(con, [dict(b) for b in buenas], etiqueta)
            with open(salida, "a", encoding="utf-8") as fh:
                for b in buenas:
                    fh.write(json.dumps({**b, "_modelo": etiqueta}, ensure_ascii=False) + "\n")
            hechas += ok
            hechos = {b["id"] for b in buenas}
            faltan = [it for it in pendientes if it["id"] not in hechos]
            if faltan and ronda == 0:
                cola.append((faltan, 1))
            else:
                fallidas += [it["id"] for it in faltan]
        log(f"  {min(i + POR_LLAMADA, len(items))}/{len(items)}")
    log(f"Fichas generadas: {hechas}; sin ficha tras dos intentos: {len(fallidas)}; tokens: {tokens}")
    return hechas


# ---------------------------------------------------------------- tipos de votación

def clasificar_tipos(con, modelo=None, log=print):
    """Tipo de las votaciones que las reglas dejan como «otro», con lista cerrada."""
    from ..procesar import EN_CONGRESO, TIPOS_LLM

    filas = con.execute(
        f"""SELECT legislatura, fecha, sesion, numero, seccion, texto_expediente, titulo_subgrupo, texto_subgrupo
            FROM votacion WHERE tipo_votacion='otro' AND {EN_CONGRESO}"""
    ).fetchall()
    if not filas:
        return 0
    tipos = {k: v for k, v in TIPOS_VOTACION.items() if k != "otro"}
    sistema = ("Clasificas votaciones del Pleno del Congreso de los Diputados. Para cada votación elige un único tipo de "
               "esta lista cerrada (clave: descripción):\n" + json.dumps(tipos, ensure_ascii=False)
               + '\nResponde SOLO con un objeto json: {"tipos": [{"id": "...", "tipo": "clave"}]}. Si ninguno encaja, usa "otro".')
    nuevos = 0
    for i in range(0, len(filas), 30):
        lote = filas[i : i + 30]
        entrada = [{"id": f"{r['legislatura']}|{r['fecha']}|{r['sesion']}|{r['numero']}", "seccion": r["seccion"],
                    "texto": (r["texto_expediente"] or "")[:400], "subgrupo": r["titulo_subgrupo"], "detalle": (r["texto_subgrupo"] or "")[:200]}
                   for r in lote]
        try:
            datos, modelo_real, _ = chat_json(sistema, json.dumps(entrada, ensure_ascii=False), modelo, max_tokens=4000)
        except ErrorIA as e:
            log(f"  ! tipos de votación: {e}")
            continue
        with open(TIPOS_LLM, "a", encoding="utf-8") as fh:
            for t in datos.get("tipos") or []:
                if t.get("tipo") in TIPOS_VOTACION and t.get("tipo") != "otro" and t.get("id", "").count("|") == 3:
                    leg, fecha, sesion, numero = t["id"].split("|")
                    fh.write(json.dumps({"legislatura": int(leg), "fecha": fecha, "sesion": int(sesion), "numero": int(numero),
                                         "tipo": t["tipo"], "_modelo": f"deepseek:{modelo_real}"}, ensure_ascii=False) + "\n")
                    nuevos += 1
    log(f"Tipos de votación decididos por DeepSeek: {nuevos} de {len(filas)}")
    return nuevos


# ---------------------------------------------------------------- informe

SISTEMA_INFORME = """Eres un analista parlamentario neutral. Con las estadísticas que se te dan (calculadas sobre las
votaciones oficiales del Congreso), redacta en español un análisis en Markdown con 5 a 7 secciones que empiecen por
«## », con viñetas breves y cifras concretas. Reglas: usa solo cifras que aparezcan en las estadísticas; no valores
a los partidos ni atribuyas intenciones; explica las cautelas cuando un dato pueda malinterpretarse (por ejemplo, que
una PNL aprobada no tiene fuerza de ley). Incluye siempre una sección final «## Calidad de la clasificación y
limitaciones». No menciones la inteligencia artificial, los modelos de lenguaje ni cómo se han generado las
fichas, los temas o este texto. Responde SOLO con un objeto json: {"markdown": "..."}."""


def redactar_informe(con, modelo=None, log=print):
    from ..analisis import importar_informe
    from ..estadisticas import imprimir

    buf = io.StringIO()
    imprimir(con, log=lambda *a: print(*a, file=buf))
    # El razonamiento previo cuenta dentro de max_tokens: con 8.000 la respuesta llegaba cortada.
    datos, modelo_real, _ = chat_json(SISTEMA_INFORME, buf.getvalue(), modelo, max_tokens=32_000)
    md = (datos.get("markdown") or "").strip()
    if md.count("## ") < 3:
        raise ErrorIA("el informe no tiene el formato esperado")
    ruta = LLM_DIR / "informe.md"
    ruta.write_text(md + "\n", encoding="utf-8")
    (LLM_DIR / "informe_modelo.txt").write_text(f"deepseek:{modelo_real}\n", encoding="utf-8")
    importar_informe(con, ruta, f"deepseek:{modelo_real}", log)
    return ruta
