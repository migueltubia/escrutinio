"""Recogida de votaciones autonómicas y locales: todos los conectores, de forma incremental.

Cada conector pide solo lo publicado desde la última votación que ya está en la base (con un
margen de días, por si algo se publicó tarde). Van varios a la vez (CONECTORES_A_LA_VEZ), cada uno
con su tope de tiempo. Un conector que falla (web caída, cambio de formato) no para a los demás:
se anota y se sigue. Al final se procesa todo con reglas.
"""

import queue
import time
from concurrent.futures import ThreadPoolExecutor

from .. import plazo, territorio
from . import estado as estado_fuente  # con alias: la función estado() de abajo taparía el módulo
from .cargar import Cargador, borrar_cuerpo, ultimas_fechas
from .contexto import Contexto
from .fuentes import ERRORES, MODULOS
from .procesar import procesar

CONECTORES_A_LA_VEZ = 6

def _por_turno(con, modulos):
    """Primero los conectores que llevan más días sin ejecutarse: si se acaba el tiempo, los que se quedan
    sin turno hoy van los primeros en la próxima ejecución."""
    try:
        ultima = dict(con.execute("SELECT conector, MIN(fecha) FROM estado_fuente GROUP BY conector"))
    except Exception:  # aún no existe la tabla
        ultima = {}
    return sorted(modulos.items(), key=lambda kv: ultima.get(kv[0]) or "")


def _descargar(nombre, m, ctx, cola, minutos, log):
    """Hilo de un conector: deja en la cola («inicio»), cada objeto («obj») y cómo acaba («fin», «tiempo» con los
    segundos o «fallo» con la excepción); «sin_turno» si ya no queda tiempo para empezar. Siempre acaba con uno de
    esos avisos, para que el hilo principal no se quede esperando."""
    if plazo.agotado(60):
        cola.put((nombre, "sin_turno", None))
        return
    cola.put((nombre, "inicio", (m, ctx)))
    log(f"== {nombre}: " + ", ".join(c.codigo for c in m.CUERPOS)
        + "".join(f" (desde {ctx.desde(c.codigo)})" for c in m.CUERPOS[:1] if ctx.desde(c.codigo)))
    inicio = time.time()
    try:
        with plazo.limite_hilo(minutos):
            for obj in m.descargar(ctx):
                cola.put((nombre, "obj", obj))
                if plazo.agotado():
                    raise plazo.TiempoAgotado("tope de tiempo del conector")
            if plazo.agotado():  # el conector se tragó el corte de alguna descarga y terminó antes de tiempo
                raise plazo.TiempoAgotado("tope de tiempo del conector")
        cola.put((nombre, "fin", None))
    except plazo.TiempoAgotado:  # no es un fallo de la web: lo ya cargado se queda y se sigue otro día
        cola.put((nombre, "tiempo", round(time.time() - inicio)))
    except BaseException as e:  # la web ha fallado: lo ya cargado se queda
        cola.put((nombre, "fallo", e))


def _cerrar(con, nombre, m, ctx, cargador, errores, inicio, como, dato, log):
    """Cierra la recogida de un conector (en el hilo principal) y devuelve su resumen."""
    cortado = como != "fin"
    fallo = dato if como == "fallo" else None
    if como == "tiempo":
        log(f"  ! {nombre}: se ha acabado su tiempo ({dato} s); se sigue en la próxima ejecución")
    elif fallo:
        errores += 1
        log(f"  ! {nombre}: la recogida se ha interrumpido: {type(fallo).__name__}: {fallo}")
    if not cortado:
        cargador.limpiar_sesiones()
    for c in m.CUERPOS:  # para avisar en la web de las instituciones que se quedan sin actualizar
        motivo, detalle = (estado_fuente.motivo(fallo), str(fallo)) if fallo else ctx.avisos.get(c.codigo, (None, None))
        if como == "tiempo" and isinstance(motivo, str) and "tiempo" in (detalle or ""):
            motivo = detalle = None  # el aviso venía del corte por tiempo, no de la web
        estado_fuente.anotar(con, nombre, [c.codigo], motivo, detalle)
    con.commit()
    resumen = {**cargador.n, "errores": errores, "segundos": round(time.time() - inicio), "cortado": cortado}
    log(f"  {nombre}: {dict(cargador.n) or 'nada nuevo'}; {errores} errores; {resumen['segundos']} s")
    return resumen


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
    desde = ultimas_fechas(con)
    for nombre, error in ERRORES.items():
        log(f"  ! {nombre}: no se pudo cargar el conector ({error})")
    elegidos = [(nombre, m) for nombre, m in _por_turno(con, MODULOS)
                if (not fuentes or nombre in fuentes) and hasattr(m, "descargar")
                and (fuentes or incluir_inactivos or getattr(m, "ACTIVO", True))]
    resumen, sin_turno = {}, []
    # Cada conector espera a una web distinta: van a la vez, cada uno en su hilo y con su tope de tiempo, y dejan
    # lo que traen en una cola. La base solo se toca desde este hilo (SQLite no admite escribir desde varios).
    cola = queue.Queue()
    with ThreadPoolExecutor(CONECTORES_A_LA_VEZ) as hilos:
        for nombre, m in elegidos:
            ctx = Contexto(desde=desde, completo=completo, log=log)
            hilos.submit(_descargar, nombre, m, ctx, cola, None if completo else minutos_max, log)
        en_marcha = {}  # nombre -> [módulo, contexto, cargador, errores, inicio, registros]
        terminados = 0
        while terminados < len(elegidos):
            nombre, que, dato = cola.get()
            if que == "sin_turno":
                sin_turno.append(nombre)
                terminados += 1
            elif que == "inicio":
                m, ctx = dato
                en_marcha[nombre] = [m, ctx, Cargador(con, cuerpos, nombre), 0, time.time(), 0]
            elif que == "obj":
                e = en_marcha[nombre]
                e[5] += 1
                try:
                    e[2].guardar(dato)
                except Exception as ex:  # dato raro de la fuente: se salta y se sigue
                    e[3] += 1
                    if e[3] <= 5:
                        log(f"  ! {nombre}: {type(ex).__name__}: {ex}")
                if e[5] % 500 == 0:
                    con.commit()
                    log(f"  {nombre}: {e[5]} registros")
            else:  # «fin», «tiempo» o «fallo»: el conector ha terminado
                m, ctx, cargador, errores, inicio, _n = en_marcha.pop(nombre)
                resumen[nombre] = _cerrar(con, nombre, m, ctx, cargador, errores, inicio, que, dato, log)
                terminados += 1
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
