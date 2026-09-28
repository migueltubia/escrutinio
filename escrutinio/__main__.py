import argparse
import sys
import time

from . import db
from .config import LEGISLATURAS


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def _legs(valor):
    if not valor:
        return sorted(LEGISLATURAS)
    return [int(x) for x in valor.split(",")]


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    p = argparse.ArgumentParser(prog="escrutinio", description="Votaciones parlamentarias en SQLite + fichas de las iniciativas")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("actualizar", help="Actualización completa (lo que ejecuta GitHub Actions)")
    s.add_argument("--limite-fichas", type=int, default=400, help="Máximo de fichas IA nuevas por ejecución")
    s.add_argument("--sin-ia", action="store_true", help="No llamar a la IA aunque haya clave")
    s.add_argument("--informe", action="store_true", help="Regenerar el informe de análisis con DeepSeek")
    s.add_argument("--sin-territorial", action="store_true", help="Solo el Congreso: no recoger votaciones autonómicas y locales")
    s.add_argument("--limite-actas", type=int, default=40, help="Máximo de diarios y actas que leer con IA por ejecución")

    sub.add_parser("unir", help="Reconstruye la base de trabajo desde data/bd/ (una SQLite por legislatura)")
    sub.add_parser("partir", help="Guarda la base de trabajo troceada por legislatura en data/bd/")

    sub.add_parser("init", help="Crea la base de datos y los catálogos")

    s = sub.add_parser("votaciones", help="Descarga las votaciones del Pleno")
    s.add_argument("--leg", help="Legislaturas separadas por comas (por defecto 10-15)")
    s.add_argument("--workers", type=int, default=6)

    s = sub.add_parser("iniciativas", help="Descarga el catálogo de iniciativas del buscador del Congreso")
    s.add_argument("--leg")
    s.add_argument("--workers", type=int, default=4)

    sub.add_parser("procesar", help="Enlaza votaciones e iniciativas, clasifica y calcula resultados")

    s = sub.add_parser("fichas-exportar", help="Exporta a JSONL las iniciativas sin ficha IA, en lotes")
    s.add_argument("--tam", type=int, default=250)
    s.add_argument("--prefijos", help="Filtra por prefijos de expediente, p. ej. 121,122,130")
    s.add_argument("--en-tramite", action="store_true", help="Iniciativas abiertas (aún no votadas) de la legislatura actual")

    s = sub.add_parser("fichas-importar", help="Importa fichas IA desde ficheros JSONL")
    s.add_argument("ficheros", nargs="+")
    s.add_argument("--modelo", help="Modelo que generó las fichas (si las líneas no traen «_modelo»)")

    s = sub.add_parser("fichas-validar", help="Valida los resultados de un lote de fichas")
    s.add_argument("lote", type=int)

    s = sub.add_parser("fichas-deepseek", help="Genera fichas con DeepSeek (requiere DEEPSEEK_API_KEY)")
    s.add_argument("--limite", type=int, default=400)

    s = sub.add_parser("territorial", help="Recoge votaciones autonómicas y locales (todos los conectores activos)")
    s.add_argument("--fuente", help="Conectores separados por comas (por defecto, todos los activos)")
    s.add_argument("--completo", action="store_true", help="Recorre todo el histórico, no solo lo nuevo")
    s.add_argument("--incluir-inactivos", action="store_true", help="Incluye los conectores marcados ACTIVO = False")
    s.add_argument("--borrar", action="store_true", help="Vacía antes las instituciones de --fuente y las recarga enteras")

    s = sub.add_parser("territorial-probar", help="Prueba un conector territorial sin tocar la base de datos")
    s.add_argument("fuente")
    s.add_argument("--limite", type=int, default=50, help="Máximo de votaciones (0: sin límite)")
    s.add_argument("--desde", help="Fecha AAAA-MM-DD desde la que pedir (simula una recogida incremental)")
    s.add_argument("--completo", action="store_true")
    s.add_argument("--salida", help="Escribe lo recogido en este JSONL")

    sub.add_parser("territorial-estado", help="Cobertura de los conectores territoriales y de lo guardado")

    s = sub.add_parser("actas-deepseek", help="Extrae con DeepSeek las votaciones de diarios y actas pendientes")
    s.add_argument("--limite", type=int, default=40, help="Máximo de documentos")
    s.add_argument("--fuente", help="Conectores separados por comas")

    s = sub.add_parser("actas-exportar", help="Deja el texto de diarios y actas pendientes para que los procese otro LLM o agente")
    s.add_argument("--limite", type=int, default=20, help="Máximo de documentos (0: todos)")
    s.add_argument("--limpiar", action="store_true", help="Borra antes lo exportado que quede")
    s.add_argument("--fuente", help="Conectores separados por comas")

    s = sub.add_parser("actas-validar", help="Comprueba las respuestas de diarios y actas antes de importarlas")
    s.add_argument("ficheros", nargs="+")

    s = sub.add_parser("actas-importar", help="Carga las votaciones extraídas de diarios y actas por otro LLM o agente")
    s.add_argument("ficheros", nargs="+")
    s.add_argument("--modelo", required=True)

    s = sub.add_parser("programas-descargar", help="Descarga y registra los programas electorales del catálogo")
    s.add_argument("--id", help="Programas separados por comas (por defecto, todos)")
    s.add_argument("--forzar", action="store_true", help="Vuelve a descargar aunque esté en la caché (si cambió, entra como documento nuevo)")

    sub.add_parser("programas-estado", help="Registro de programas: qué está leído, qué falta, qué falló y el gasto")

    s = sub.add_parser("programas-leer", help="Extrae con DeepSeek los compromisos de los programas pendientes (una sola vez)")
    s.add_argument("--id", help="Programas separados por comas")
    s.add_argument("--limite", type=int, help="Máximo de programas")
    s.add_argument("--reintentar", action="store_true", help="Reintenta también los que fallaron")
    s.add_argument("--modelo", help="Modelo de DeepSeek (por defecto, el Pro)")

    s = sub.add_parser("programas-releer", help="Vuelve a leer un programa ya leído con una versión nueva del prompt")
    s.add_argument("--id", required=True)
    s.add_argument("--version", required=True, help="Versión del prompt con la que releer (tiene que ser la actual)")
    s.add_argument("--modelo")

    s = sub.add_parser("programas-emparejar", help="Relaciona con DeepSeek los compromisos con sus iniciativas candidatas nuevas")
    s.add_argument("--id", help="Programas separados por comas")
    s.add_argument("--limite", type=int, help="Máximo de compromisos")
    s.add_argument("--modelo", help="Modelo de DeepSeek (por defecto, DEEPSEEK_MODEL)")

    sub.add_parser("programas-calcular", help="Recarga programas, emparejamientos y validaciones y recalcula el estado (sin DeepSeek)")

    sub.add_parser("analizar", help="Recalcula afinidades y agregados")

    s = sub.add_parser("informe-importar", help="Guarda el informe de análisis (Markdown con secciones ##)")
    s.add_argument("fichero")
    s.add_argument("--modelo", required=True)

    sub.add_parser("informe-deepseek", help="Redacta el informe de análisis con DeepSeek a partir de las estadísticas")
    sub.add_parser("estadisticas", help="Estadísticas en texto para redactar el informe de análisis")
    sub.add_parser("web", help="Exporta la base de datos para la web local (web/index.html, sin servidor)")
    sub.add_parser("estado", help="Resumen de lo que hay en la base de datos")

    a = p.parse_args(argv)

    # Estos dos gestionan su propia base de datos.
    if a.cmd == "actualizar":
        from .actualizar import actualizar

        actualizar(limite_fichas=a.limite_fichas, ia=not a.sin_ia, informe=a.informe, territorial=not a.sin_territorial,
                   limite_actas=a.limite_actas, log=log)
        return
    if a.cmd == "unir":
        from .almacen import unir

        unir(log=log).close()
        return
    if a.cmd == "actas-validar":
        from .territorial.actas_llm import validar

        sys.exit(0 if validar(a.ficheros, log=print) else 1)
    if a.cmd == "territorial-probar":
        from .territorial.probar import probar

        _n, malos, repetidas = probar(a.fuente, limite=a.limite or None, desde=a.desde, completo=a.completo,
                                      salida=a.salida, log=log)
        sys.exit(1 if (malos or repetidas) else 0)
    if a.cmd == "fichas-validar":
        # Solo compara ficheros: no abre la base (así no espera a una carga que la tenga bloqueada).
        from .llm.fichas_io import validar_lote

        sys.exit(0 if validar_lote(a.lote) else 1)
    if a.cmd in ("programas-descargar", "programas-estado"):
        # Solo el registro y los textos: no hace falta la base.
        from .programas import registro

        if a.cmd == "programas-descargar":
            registro.descargar(ids=a.id.split(",") if a.id else None, forzar=a.forzar, log=log)
        else:
            registro.estado()
        return

    con = db.connect()
    db.init(con)
    if a.cmd == "init":
        print("Base de datos lista")
    elif a.cmd == "partir":
        from .almacen import partir

        partir(con, log=log)
    elif a.cmd == "votaciones":
        from .congreso_votaciones import descargar

        descargar(con, _legs(a.leg), workers=a.workers, log=log)
    elif a.cmd == "iniciativas":
        from .congreso_iniciativas import descargar

        descargar(con, _legs(a.leg), workers=a.workers, log=log)
    elif a.cmd == "procesar":
        from .procesar import procesar

        procesar(con, log=log)
    elif a.cmd == "fichas-exportar":
        from .llm.fichas_io import exportar

        exportar(con, tam=a.tam, prefijos=a.prefijos.split(",") if a.prefijos else None, en_tramite=a.en_tramite)
    elif a.cmd == "fichas-importar":
        from .llm.fichas_io import importar

        importar(con, a.ficheros, modelo=a.modelo)
    elif a.cmd == "fichas-validar":
        from .llm.fichas_io import validar_lote

        sys.exit(0 if validar_lote(a.lote) else 1)
    elif a.cmd == "fichas-deepseek":
        from .llm import deepseek

        if not deepseek.disponible():
            sys.exit("Falta DEEPSEEK_API_KEY")
        deepseek.generar_fichas(con, limite=a.limite, log=log)
    elif a.cmd == "territorial":
        from .territorial.recoger import recoger_y_procesar

        recoger_y_procesar(con, fuentes=a.fuente.split(",") if a.fuente else None, completo=a.completo,
                           incluir_inactivos=a.incluir_inactivos, borrar=a.borrar, log=log)
    elif a.cmd in ("actas-deepseek", "actas-exportar", "actas-importar"):
        from .territorial import actas_llm
        from .territorial.procesar import procesar as procesar_territorial

        if a.cmd == "actas-deepseek":
            actas_llm.procesar_deepseek(con, limite=a.limite, fuentes=a.fuente.split(",") if a.fuente else None, log=log)
        elif a.cmd == "actas-exportar":
            actas_llm.exportar(con, fuentes=a.fuente.split(",") if a.fuente else None, limite=a.limite, limpiar=a.limpiar, log=log)
        else:
            actas_llm.importar(con, a.ficheros, a.modelo, log=log)
        if a.cmd != "actas-exportar":
            procesar_territorial(con, log)
    elif a.cmd == "territorial-estado":
        from .territorial.recoger import estado

        estado(con, log=log)
    elif a.cmd.startswith("programas-"):
        from .programas import emparejar, leer
        from .programas.cargar import cargar

        ids = a.id.split(",") if getattr(a, "id", None) else None
        if a.cmd == "programas-leer":
            leer.leer(ids=ids, reintentar=a.reintentar, limite=a.limite, modelo=a.modelo, log=log)
        elif a.cmd == "programas-releer":
            leer.releer(a.id, a.version, modelo=a.modelo, log=log)
        elif a.cmd == "programas-emparejar":
            emparejar.emparejar(con, ids=ids, limite=a.limite, modelo=a.modelo, log=log)
        cargar(con, log)
        log("Para verlo en la web: python -m escrutinio web")
    elif a.cmd == "analizar":
        from .analisis import analizar

        analizar(con, log=log)
    elif a.cmd == "informe-importar":
        from .analisis import importar_informe

        importar_informe(con, a.fichero, a.modelo)
    elif a.cmd == "informe-deepseek":
        from .llm import deepseek

        if not deepseek.disponible():
            sys.exit("Falta DEEPSEEK_API_KEY")
        deepseek.redactar_informe(con, log=log)
    elif a.cmd == "estadisticas":
        from .estadisticas import imprimir

        imprimir(con)
    elif a.cmd == "web":
        from .exportar_web import exportar
        from .programas.cargar import cargar

        cargar(con, log)  # lo último de data/llm/programas/
        exportar(con, log=log)
    elif a.cmd == "estado":
        from .procesar import estado

        estado(con)


if __name__ == "__main__":
    main()
