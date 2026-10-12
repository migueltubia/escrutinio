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
6. Programas electorales: con DeepSeek, se leen los programas registrados pendientes y se relacionan
   los compromisos con las iniciativas nuevas; con o sin clave, se recalcula su estado con los votos.
7. Se recalculan agregados, se regenera la web y se vuelve a trocear la base en data/bd/.

Con un tiempo máximo (MINUTOS_MAX o --minutos; en GitHub Actions, algo menos que el límite del trabajo), cada
fase tiene su tramo (plazo.py): deja de pedir cosas nuevas cuando se le acaba y lo que falta se hace en la
próxima ejecución. El cierre (paso 7) siempre tiene su tiempo reservado, para que se guarde y se publique lo hecho.
"""

import os
import shutil

from . import almacen, analisis, congreso_iniciativas, congreso_votaciones, db, exportar_web, plazo, programas
from .config import DB_PATH, LEGISLATURAS, LLM_DIR, RAW_DIR
from .llm import deepseek, fichas_io
from .procesar import procesar

MODELO_INFORME_POR_DEFECTO = "lote inicial"

# Reparto del tiempo cuando hay límite (MINUTOS_MAX o --minutos; ver plazo.py). Cada fase deja libres los minutos
# de las que van detrás; lo que no da tiempo a hacer queda para la próxima ejecución.
RESERVA_CIERRE = 15        # agregados, web y base troceada: siempre tienen que caber
RESERVA_PROGRAMAS = 10     # programas electorales con IA
RESERVA_ACTAS = 10         # diarios de sesiones y actas autonómicas y locales con IA
MINUTOS_CONECTORES = 35    # todos los conectores autonómicos y locales juntos
MINUTOS_POR_CONECTOR = 10


def actualizar(limite_fichas=400, ia=True, informe=False, territorial=True, limite_actas=None, minutos=None, log=print):
    minutos = minutos or int(os.environ.get("MINUTOS_MAX") or 0) or None
    plazo.iniciar(minutos)
    if minutos:
        log(f"Tiempo máximo de esta actualización: {minutos} min")
    try:
        _actualizar(limite_fichas, ia, informe, territorial, limite_actas, log)
    finally:
        plazo.resumen(log)


def _actualizar(limite_fichas, ia, informe, territorial, limite_actas, log):
    actual = max(LEGISLATURAS)
    con_ia = ia and deepseek.disponible()
    tras_ia_congreso = RESERVA_CIERRE + RESERVA_PROGRAMAS + (RESERVA_ACTAS + 15 if territorial else 0)
    with plazo.tramo("Congreso: descargas y procesado", log=log):
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

    # Antes que lo territorial: las fichas del Congreso son lo principal de la web.
    if con_ia:
        log(f"== IA: DeepSeek ({deepseek.modelo_por_defecto()})")
        with plazo.tramo("Congreso: IA", reserva=tras_ia_congreso, log=log):
            if deepseek.clasificar_tipos(con, log=log):
                procesar(con, log)
            if informe:  # antes que las fichas: es semanal y, si no da tiempo, la portada se queda con el anterior
                try:
                    deepseek.redactar_informe(con, log=log)
                except Exception as e:  # el informe no debe tirar la actualización: se queda el anterior
                    log(f"  ! Informe no redactado: {type(e).__name__}: {e}")
            deepseek.generar_fichas(con, limite=limite_fichas, log=log)
    elif ia:
        log("== IA: sin DEEPSEEK_API_KEY; se omite. Las leyes nuevas quedan con el tema provisional por comisión.")

    if territorial:
        log("== Votaciones autonómicas y locales")
        try:
            actualizar_territorial(con, ia=ia, limite_actas=limite_actas, log=log)
        except Exception as e:  # lo territorial nunca debe impedir que se actualice el Congreso
            log(f"  ! La parte territorial ha fallado: {type(e).__name__}: {e}")
            con.rollback()

    log("== Agregados, web y base troceada")
    with plazo.tramo("Agregados y programas electorales", reserva=RESERVA_CIERRE, log=log):
        analisis.analizar(con, log)
        programas.actualizar(con, ia=ia, log=log)
    with plazo.tramo("Cierre: web y base troceada", log=log):
        exportar_web.exportar(con, log)
        almacen.partir(con, log)
    pendientes = len(fichas_io.items_pendientes(con)) + len(fichas_io.items_en_tramite(con))
    log(f"Hecho. Iniciativas que siguen sin ficha IA: {pendientes}")
    if territorial:
        from .territorial import estado
        from .territorial.partidos import anunciar_pendientes

        estado.anunciar(con, log)  # en Actions, además, como avisos de la ejecución
        anunciar_pendientes(log)   # grupos sin partido reconocido: posibles partidos nuevos para dar de alta


def actualizar_territorial(con, ia=True, limite_actas=None, log=print):
    """`limite_actas`: máximo de diarios y actas que leer con IA; None, sin límite (hasta que se acabe el tiempo de
    la fase); 0, ninguno."""
    from .territorial import actas_llm
    from .territorial.procesar import procesar as procesar_territorial
    from .territorial.recoger import recoger

    with plazo.tramo("Autonómicas y locales: conectores", minutos=MINUTOS_CONECTORES,
                     reserva=RESERVA_CIERRE + RESERVA_PROGRAMAS + RESERVA_ACTAS, log=log):
        recoger(con, minutos_max=MINUTOS_POR_CONECTOR, log=log)
    # Después de los conectores: lo leído de actas puede completar votaciones que acaban de volver a guardarse.
    actas_llm.cargar_guardadas(con, log)
    if ia and limite_actas != 0:
        with plazo.tramo("Autonómicas y locales: actas con IA", reserva=RESERVA_CIERRE + RESERVA_PROGRAMAS, log=log):
            try:
                actas_llm.procesar_deepseek(con, limite=limite_actas, log=log)
            except Exception as e:  # lo ya leído está guardado en data/llm; el procesado territorial sigue
                log(f"  ! Lectura de actas interrumpida: {type(e).__name__}: {e}")
                con.rollback()
    with plazo.tramo("Autonómicas y locales: procesado", log=log):
        procesar_territorial(con, log)
