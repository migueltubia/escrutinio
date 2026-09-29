"""Programas electorales frente a votos: lo que dicen los partidos y lo que votan.

Plan completo en «Programas y votos lo que dicen frente a lo que votan.md». Cada programa se descarga,
se lee y se guarda una sola vez; lo leído (data/llm/programas/) es la fuente de verdad y la base se
reconstruye desde ahí:

- registro.py: catálogo de programas, descarga, texto extraído y registro de lo hecho (fase 0).
- leer.py: compromisos de cada programa con su cita literal y su página (DeepSeek, una vez).
- emparejar.py: iniciativas candidatas para cada compromiso (BM25, sin LLM) y relación con cada una
  (DeepSeek, sin saber de qué partido es el compromiso).
- verificar.py: segunda revisión, más exigente (modelo Pro y la cita literal), de las relaciones con
  dirección, que son las que cuentan en las cifras.
- cargar.py: tablas de la base desde los JSONL y estado de cada compromiso según lo que votó el partido
  (con reglas, sin LLM). Todo es automático: no hay revisión a mano.
"""


def actualizar(con, ia=True, limite_compromisos=300, log=print):
    """Lo de cada día: leer los programas registrados pendientes, decidir y revisar las candidatas nuevas y recalcular."""
    from ..llm import deepseek
    from .cargar import cargar
    from .emparejar import emparejar
    from .leer import leer
    from .verificar import verificar

    if ia and deepseek.disponible():
        try:
            leer(log=log)
            emparejar(con, limite=limite_compromisos, log=log)
            verificar(con, log=log)
        except Exception as e:  # lo ya leído y decidido está guardado; el resto de la actualización sigue
            log(f"  ! Programas: {type(e).__name__}: {e}")
    cargar(con, log)
