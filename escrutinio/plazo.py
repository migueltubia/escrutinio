"""Tiempo máximo de una actualización, para que termine sola antes de que GitHub la corte.

Si GitHub corta el trabajo, se pierde todo lo hecho en él (fichas, actas leídas, la web del día) y la
ejecución siguiente vuelve a empezar desde el mismo sitio. Por eso la actualización se da un plazo
(`iniciar`) algo menor que el de GitHub y lo reparte en tramos (`tramo`): cada fase deja de pedir cosas
nuevas cuando se le acaba su tramo, y lo que queda se hace en la próxima ejecución.

Las descargas (territorial/contexto.py) y las llamadas a DeepSeek (llm/deepseek.py) consultan `quedan()`
antes de cada intento: así se para también una fase que está atascada esperando a una web lenta.
Sin `iniciar` (uso desde la línea de órdenes para una sola cosa) no hay límite.
"""

import math
import os
import time
from contextlib import contextmanager

_fin = None    # fin de toda la actualización (time.monotonic)
_tramo = None  # fin del tramo en curso, si es antes
_duraciones = []  # (nombre, segundos, cortado) de cada tramo, para el resumen final


class TiempoAgotado(Exception):
    """Se ha acabado el tiempo de esta fase: lo que falta queda para la próxima ejecución."""


def iniciar(minutos):
    global _fin, _tramo
    _fin = time.monotonic() + minutos * 60 if minutos else None
    _tramo = None
    _duraciones.clear()


def quedan():
    """Segundos que le quedan al tramo en curso (infinito si no hay límite)."""
    fines = [f for f in (_fin, _tramo) if f is not None]
    return min(fines) - time.monotonic() if fines else math.inf


def agotado(margen=0):
    return quedan() <= margen


def comprobar(que=""):
    if agotado():
        raise TiempoAgotado(f"se ha acabado el tiempo de esta ejecución{f' ({que})' if que else ''}")


@contextmanager
def tramo(nombre, minutos=None, reserva=0, log=None):
    """Fase con límite propio: como mucho `minutos`, y siempre dejando `reserva` minutos antes del final
    (para las fases que van detrás). Los tramos se pueden anidar: manda el límite más cercano."""
    global _tramo
    anterior, inicio = _tramo, time.monotonic()
    fines = [f for f in (anterior, _fin - reserva * 60 if _fin is not None else None,
                         inicio + minutos * 60 if minutos else None) if f is not None]
    _tramo = min(fines) if fines else None
    try:
        yield
    finally:
        cortado = _tramo is not None and time.monotonic() >= _tramo
        _tramo = anterior
        segundos = round(time.monotonic() - inicio)
        _duraciones.append((nombre, segundos, cortado))
        if log:
            log(f"  [{nombre}: {_mmss(segundos)}{', cortado por tiempo' if cortado else ''}]")


def _mmss(s):
    return f"{s // 60} min {s % 60:02d} s"


def resumen(log=print):
    """Duración de cada fase; en GitHub Actions, además, como aviso visible en la ejecución."""
    if not _duraciones:
        return
    lineas = [f"{n}: {_mmss(s)}{' (cortado por tiempo)' if c else ''}" for n, s, c in _duraciones]
    log("Tiempo por fase: " + "; ".join(lineas))
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print("::notice title=Tiempo por fase::" + "%0A".join(lineas), flush=True)
