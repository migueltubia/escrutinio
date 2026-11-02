"""Programas electorales frente a votos: lo que dicen los partidos y lo que votan.

Plan completo en «Programas y votos lo que dicen frente a lo que votan.md». Cada programa se descarga,
se lee y se guarda una sola vez; lo leído (data/llm/programas/) es la fuente de verdad y la base se
reconstruye desde ahí:

- registro.py: catálogo de programas, descarga, texto extraído y registro de lo hecho (fase 0).
- buscar.py: programas de las elecciones que vienen, encontrados solos en las webs de los partidos («vigilar» en
  data/programas.json).
- leer.py: compromisos de cada programa con su cita literal y su página (DeepSeek, una vez).
- emparejar.py: iniciativas candidatas para cada compromiso (BM25, sin LLM) y relación con cada una
  (DeepSeek, sin saber de qué partido es el compromiso).
- traducir.py: traducción al castellano de las citas en catalán, euskera o gallego (DeepSeek, una vez).
- verificar.py: segunda revisión, más exigente (modelo Pro y la cita literal), de las relaciones con
  dirección, que son las que cuentan en las cifras.
- antecedentes.py: promesas de elecciones por celebrar frente a lo votado antes (herencia y parecidas, sin LLM).
- cargar.py: tablas de la base desde los JSONL y estado de cada compromiso según lo que votó el partido
  (con reglas, sin LLM). Todo es automático: no hay revisión a mano.
"""


def actualizar(con, ia=True, limite_compromisos=300, log=print):
    """Lo de cada día: buscar y bajar los programas nuevos, leer los pendientes, decidir y revisar las candidatas nuevas,
    traducir las citas que no están en castellano y recalcular."""
    from ..llm import deepseek
    from . import registro
    from .buscar import buscar
    from .cargar import cargar
    from .emparejar import emparejar
    from .leer import leer
    from .traducir import traducir
    from .verificar import verificar

    try:  # sin IA también: encontrar y bajar el PDF no cuesta nada
        buscar(log=log)
        if registro.sin_registrar():
            registro.descargar(ids=registro.sin_registrar(), log=log)
    except Exception as e:
        log(f"  ! Búsqueda de programas: {type(e).__name__}: {e}")
    if ia and deepseek.disponible():
        try:
            leer(log=log)
            emparejar(con, limite=limite_compromisos, log=log)
            verificar(con, modelo=deepseek.modelo_por_defecto(), cifras=True, log=log)  # lo que cuenta, con el modelo rápido
            traducir(log=log)
        except Exception as e:  # lo ya leído y decidido está guardado; el resto de la actualización sigue
            log(f"  ! Programas: {type(e).__name__}: {e}")
    cargar(con, log)
