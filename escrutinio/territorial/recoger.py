"""Recogida de votaciones autonómicas y locales: todos los conectores, de forma incremental.

Cada conector pide solo lo publicado desde la última votación que ya está en la base (con un
margen de días, por si algo se publicó tarde). Un conector que falla (web caída, cambio de
formato) no para a los demás: se anota y se sigue. Al final se procesa todo con reglas.
"""

import time

from .. import plazo, territorio
from . import estado as estado_fuente  # con alias: la función estado() de abajo taparía el módulo
from .cargar import Cargador, borrar_cuerpo, ultimas_fechas
from .contexto import Contexto
from .fuentes import ERRORES, MODULOS
from .procesar import procesar


def _por_turno(con, modulos):
    """Primero los conectores que llevan más días sin ejecutarse: si se acaba el tiempo, los que se quedan
    sin turno hoy van los primeros en la próxima ejecución."""
    try:
        ultima = dict(con.execute("SELECT conector, MIN(fecha) FROM estado_fuente GROUP BY conector"))
    except Exception:  # aún no existe la tabla
        ultima = {}
    return sorted(modulos.items(), key=lambda kv: ultima.get(kv[0]) or "")


def recoger(con, fuentes=None, completo=False, incluir_inactivos=False, minutos_max=10, borrar=False, log=print):
    """Ejecuta los conectores con `descargar` y carga lo nuevo. Devuelve {conector: resumen}.

    `borrar` (solo con `fuentes`) vacía antes esas instituciones y las recarga enteras.
    Cada conector tiene como mucho `minutos_max` (salvo con `completo`), y todos juntos, el tramo de tiempo en
    curso (ver plazo.py). Lo cargado se queda y el conector sigue desde ahí en la próxima ejecución.
    """
    cuerpos = {c.codigo: c for c in territorio.cuerpos()}
    if borrar:
        if not fuentes:
            raise ValueError("Borrar exige elegir los conectores")
        completo = True
        for nombre in fuentes:
            for c in getattr(MODULOS.get(nombre), "CUERPOS", []):
                borrar_cuerpo(con, c.codigo, log)
    ctx = Contexto(desde=ultimas_fechas(con), completo=completo, log=log)
    for nombre, error in ERRORES.items():
        log(f"  ! {nombre}: no se pudo cargar el conector ({error})")
    resumen, sin_turno = {}, []
    for nombre, m in _por_turno(con, MODULOS):
        if fuentes and nombre not in fuentes:
            continue
        if not fuentes and not incluir_inactivos and not getattr(m, "ACTIVO", True):
            continue
        if not hasattr(m, "descargar"):
            continue
        if plazo.agotado(60):
            sin_turno.append(nombre)
            continue
        cargador = Cargador(con, cuerpos, nombre)
        errores, inicio, cortado, fallo, sin_tiempo = 0, time.time(), False, None, False
        log(f"== {nombre}: " + ", ".join(c.codigo for c in m.CUERPOS)
            + "".join(f" (desde {ctx.desde(c.codigo)})" for c in m.CUERPOS[:1] if ctx.desde(c.codigo)))
        with plazo.tramo(f"conector {nombre}", minutos=None if completo else minutos_max):
            try:
                for i, obj in enumerate(m.descargar(ctx), 1):
                    try:
                        cargador.guardar(obj)
                    except Exception as e:  # dato raro de la fuente: se salta y se sigue
                        errores += 1
                        if errores <= 5:
                            log(f"  ! {nombre}: {type(e).__name__}: {e}")
                    if i % 500 == 0:
                        con.commit()
                        log(f"  {nombre}: {i} registros")
                    if plazo.agotado():
                        raise plazo.TiempoAgotado("tope de tiempo del conector")
                if plazo.agotado():  # el conector se tragó el corte de alguna descarga y terminó antes de tiempo
                    raise plazo.TiempoAgotado("tope de tiempo del conector")
            except plazo.TiempoAgotado:  # no es un fallo de la web: lo ya cargado se queda y se sigue otro día
                cortado = sin_tiempo = True
                log(f"  ! {nombre}: se ha acabado su tiempo ({round(time.time() - inicio)} s); "
                    "se sigue en la próxima ejecución")
            except Exception as e:  # la web ha fallado: lo ya cargado se queda
                errores += 1
                cortado = True
                fallo = e
                log(f"  ! {nombre}: la recogida se ha interrumpido: {type(e).__name__}: {e}")
        if not cortado:
            cargador.limpiar_sesiones()
        for c in m.CUERPOS:  # para avisar en la web de las instituciones que se quedan sin actualizar
            motivo, detalle = (estado_fuente.motivo(fallo), str(fallo)) if fallo else ctx.avisos.get(c.codigo, (None, None))
            if sin_tiempo and isinstance(motivo, str) and "tiempo" in (detalle or ""):
                motivo = detalle = None  # el aviso venía del corte por tiempo, no de la web
            estado_fuente.anotar(con, nombre, [c.codigo], motivo, detalle)
        con.commit()
        resumen[nombre] = {**cargador.n, "errores": errores, "segundos": round(time.time() - inicio), "cortado": cortado}
        log(f"  {nombre}: {dict(cargador.n) or 'nada nuevo'}; {errores} errores; {resumen[nombre]['segundos']} s")
    if sin_turno:
        log(f"  Sin tiempo para {len(sin_turno)} conectores (van los primeros en la próxima ejecución): "
            + ", ".join(sin_turno))
    return resumen


def recoger_y_procesar(con, log=print, **kw):
    resumen = recoger(con, log=log, **kw)
    procesar(con, log)
    return resumen


def estado(con, log=print):
    """Cobertura: conectores, instituciones y lo que hay guardado de cada una."""
    guardado = {r[0]: r[1:] for r in con.execute(
        """SELECT l.cuerpo, COUNT(DISTINCT v.legislatura), COUNT(*), MIN(v.fecha), MAX(v.fecha),
                  SUM(v.a_favor IS NOT NULL), SUM(EXISTS (SELECT 1 FROM voto_grupo g WHERE g.votacion_id=v.id)),
                  SUM(EXISTS (SELECT 1 FROM voto vo WHERE vo.votacion_id=v.id))
           FROM votacion v JOIN legislatura l ON l.id=v.legislatura GROUP BY l.cuerpo""")}
    for nombre, error in ERRORES.items():
        log(f"{nombre}: NO CARGA ({error})")
    for nombre, m in MODULOS.items():
        modos = [x for x in ("descargar", "documentos") if hasattr(m, x)]
        log(f"{nombre} [{'activo' if getattr(m, 'ACTIVO', True) else 'inactivo'}; {', '.join(modos)}]")
        for c in m.CUERPOS:
            g = guardado.get(c.codigo)
            if g:
                legs, n, desde, hasta, tot, grp, nom = g
                log(f"  {c.codigo}: {n} votaciones en {legs} legislaturas, {desde} a {hasta} "
                    f"(con totales {tot}, por grupo {grp}, nominal {nom})")
            else:
                log(f"  {c.codigo}: sin datos guardados")
