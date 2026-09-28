"""Actualización completa, pensada para ejecutarse sin intervención (GitHub Actions o local).

1. Si no hay base de trabajo, se reconstruye desde data/bd/ (lo versionado en el repositorio).
2. Se descargan las votaciones nuevas (y se revisan los últimos días de la legislatura actual) y el
   catálogo de iniciativas de la legislatura actual, con sus plazos y fases.
3. Se cargan las fichas IA versionadas en data/llm/ y se procesa todo con reglas (sin IA).
4. Si hay DEEPSEEK_API_KEY: DeepSeek decide el tipo de las votaciones que las reglas no reconocen
   y genera las fichas de las iniciativas nuevas (con un límite por ejecución). Sin clave, las
   leyes nuevas quedan con el tema provisional por comisión.
5. Votaciones autonómicas y locales: cada conector territorial trae lo nuevo desde su última
   votación guardada; con DeepSeek, además, se leen los diarios de sesiones y actas pendientes (con
   un límite por ejecución). Un conector que falla no para a los demás ni al resto del ciclo.
6. Se recalculan agregados, se regenera la web y se vuelve a trocear la base en data/bd/.
"""

import shutil

from . import almacen, analisis, congreso_iniciativas, congreso_votaciones, db, exportar_web
from .config import DB_PATH, LEGISLATURAS, LLM_DIR, RAW_DIR
from .llm import deepseek, fichas_io
from .procesar import procesar

MODELO_INFORME_POR_DEFECTO = "lote inicial"


def actualizar(limite_fichas=400, ia=True, informe=False, territorial=True, limite_actas=40, log=print):
    actual = max(LEGISLATURAS)
    if not DB_PATH.exists() and (almacen.BD_DIR / "comun.sqlite").exists():
        log("Reconstruyendo la base de trabajo desde data/bd/…")
        almacen.unir(DB_PATH, log).close()
    con = db.connect()
    db.init(con)

    log("== Votaciones")
    # Los días recientes pueden publicarse incompletos: se vuelven a revisar (los JSON ya descargados salen de la caché).
    con.execute(
        "UPDATE dia_pleno SET urls_json=NULL, descargado=0 WHERE legislatura=? AND fecha >= date('now', '-14 day')", (actual,)
    )
    con.commit()
    congreso_votaciones.descargar(con, sorted(LEGISLATURAS), log=log)

    log("== Iniciativas")
    shutil.rmtree(RAW_DIR / "iniciativas" / f"Leg{actual}", ignore_errors=True)  # el catálogo de la actual cambia
    faltan = [l for l in sorted(LEGISLATURAS)
              if l == actual or not con.execute("SELECT 1 FROM iniciativa WHERE legislatura=? AND sintetica=0 LIMIT 1", (l,)).fetchone()]
    congreso_iniciativas.descargar(con, faltan, log=log)

    log("== Fichas IA versionadas")
    fichas_io.importar_todo(con, log)
    ruta_informe = LLM_DIR / "informe.md"
    if ruta_informe.exists():
        modelo_inf = (LLM_DIR / "informe_modelo.txt")
        analisis.importar_informe(con, ruta_informe, modelo_inf.read_text(encoding="utf-8").strip()
                                  if modelo_inf.exists() else MODELO_INFORME_POR_DEFECTO, log)

    log("== Procesado con reglas")
    procesar(con, log)

    if territorial:
        log("== Votaciones autonómicas y locales")
        try:
            actualizar_territorial(con, ia=ia, limite_actas=limite_actas, log=log)
        except Exception as e:  # lo territorial nunca debe impedir que se actualice el Congreso
            log(f"  ! La parte territorial ha fallado: {type(e).__name__}: {e}")
            con.rollback()

    if ia and deepseek.disponible():
        log(f"== IA: DeepSeek ({deepseek.modelo_por_defecto()})")
        if deepseek.clasificar_tipos(con, log=log):
            procesar(con, log)
        deepseek.generar_fichas(con, limite=limite_fichas, log=log)
        if informe:
            try:
                deepseek.redactar_informe(con, log=log)
            except Exception as e:  # el informe no debe tirar la actualización: se queda el anterior
                log(f"  ! Informe no redactado: {type(e).__name__}: {e}")
    elif ia:
        log("== IA: sin DEEPSEEK_API_KEY; se omite. Las leyes nuevas quedan con el tema provisional por comisión.")

    log("== Agregados, web y base troceada")
    analisis.analizar(con, log)
    exportar_web.exportar(con, log)
    almacen.partir(con, log)
    pendientes = len(fichas_io.items_pendientes(con)) + len(fichas_io.items_en_tramite(con))
    log(f"Hecho. Iniciativas que siguen sin ficha IA: {pendientes}")
    if territorial:
        from .territorial import estado

        estado.anunciar(con, log)  # en Actions, además, como avisos de la ejecución


def actualizar_territorial(con, ia=True, limite_actas=40, log=print):
    from .territorial import actas_llm
    from .territorial.procesar import procesar as procesar_territorial
    from .territorial.recoger import recoger

    recoger(con, log=log)
    # Después de los conectores: lo leído de actas puede completar votaciones que acaban de volver a guardarse.
    actas_llm.cargar_guardadas(con, log)
    if ia and limite_actas:
        try:
            actas_llm.procesar_deepseek(con, limite=limite_actas, log=log)
        except Exception as e:  # lo ya leído está guardado en data/llm; el procesado territorial sigue
            log(f"  ! Lectura de actas interrumpida: {type(e).__name__}: {e}")
            con.rollback()
    procesar_territorial(con, log)
