"""Estado de cada fuente en la última recogida: si respondió o por qué no.

Algunas webs no aceptan conexiones desde fuera de España (o desde centros de datos), y la
actualización diaria se hace en servidores de GitHub que están fuera: esas instituciones se quedan
sin actualizar. Aquí se anota por institución, la web lo avisa (va en web/datos/indice.js) y en
GitHub Actions sale como aviso en el resumen de la ejecución.

La tabla estado_fuente solo vive en la base de trabajo (no se trocea en data/bd): cada recogida la
rellena de nuevo.
"""

import os
import socket
import ssl
import urllib.error
from datetime import date

# motivo -> explicación (la web tiene los mismos textos en ambito.js)
MOTIVOS = {
    "sin_respuesta": "su web no ha respondido",
    "rechaza": "su web ha rechazado la conexión",
    "certificado": "su web tiene un certificado de seguridad incompleto",
    "copia": "su web no ha respondido y se ha usado la copia del Internet Archive, que puede ir con retraso",
    "error": "ha fallado la descarga (puede ser pasajero o un cambio en su web)",
}
EXTRANJERO = ("Varias webs de instituciones no aceptan conexiones desde fuera de España, y la actualización "
              "diaria se hace en servidores de GitHub que están fuera.")


def motivo(e):
    """Clasifica la excepción de una descarga fallida."""
    cadena = [e, e.__cause__]
    cadena += [getattr(x, "reason", None) for x in cadena]  # URLError guarda ahí el error de red o TLS
    for x in cadena:
        if isinstance(x, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(x or ""):
            return "certificado"
        if isinstance(x, urllib.error.HTTPError):
            return "rechaza" if x.code in (401, 403, 451) else "error"
        if isinstance(x, (TimeoutError, socket.timeout, ConnectionError)) or any(
                t in str(x or "") for t in ("timed out", "closed connection", "Connection refused", "Connection reset",
                                           "Name or service not known", "getaddrinfo failed")):
            return "sin_respuesta"
    return "error"


def _tabla(con):
    con.execute("""CREATE TABLE IF NOT EXISTS estado_fuente(
        cuerpo TEXT PRIMARY KEY, conector TEXT, fecha TEXT, motivo TEXT, detalle TEXT)""")


def anotar(con, conector, cuerpos, motivo_=None, detalle=None):
    """Resultado de un conector para sus instituciones: sin motivo, respondió bien."""
    _tabla(con)
    hoy = date.today().isoformat()
    con.executemany("INSERT OR REPLACE INTO estado_fuente VALUES (?,?,?,?,?)",
                    [(c, conector, hoy, motivo_, (detalle or "")[:300] or None) for c in cuerpos])


def avisos(con):
    """{cuerpo: {fecha, motivo, detalle, hasta}} de las instituciones que no respondieron bien; None si
    en esta base no se ha hecho ninguna recogida (entonces se mantienen los avisos anteriores)."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='estado_fuente'").fetchone():
        return None
    out = {}
    for cuerpo, fecha, motivo_, detalle in con.execute(
            "SELECT cuerpo, fecha, motivo, detalle FROM estado_fuente WHERE motivo IS NOT NULL ORDER BY cuerpo"):
        hasta = con.execute("SELECT MAX(fecha) FROM votacion WHERE camara=?", (cuerpo,)).fetchone()[0]
        out[cuerpo] = {"fecha": fecha, "motivo": motivo_, "detalle": detalle, "hasta": hasta}
    return out


def anunciar(con, log=print):
    """Resume los avisos en el registro y, en GitHub Actions, como avisos de la ejecución."""
    from .. import territorio

    lista = avisos(con) or {}
    if not lista:
        return
    nombres = {c.codigo: c.nombre for c in territorio.cuerpos()}
    log(f"Fuentes sin actualizar en esta ejecución: {len(lista)}")
    lineas = []
    for cuerpo, a in lista.items():
        nombre = nombres.get(cuerpo, cuerpo)
        texto = f"{MOTIVOS.get(a['motivo'], a['motivo'])}; datos hasta {a['hasta'] or '—'}"
        log(f"  ! {nombre}: {texto} ({a['detalle']})")
        lineas.append((nombre, texto, a["detalle"]))
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for nombre, texto, detalle in lineas:
        # Comandos de flujo de GitHub: salen en el resumen de la ejecución como avisos.
        mensaje = f"{texto[0].upper()}{texto[1:]}. {detalle or ''}".replace("%", "%25").replace("\r", "").replace("\n", " ")
        titulo = f"{nombre} sin actualizar".replace("%", "%25").replace(":", "%3A").replace(",", "%2C")
        print(f"::warning title={titulo}::{mensaje}", flush=True)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as fh:
            fh.write("### Fuentes sin actualizar\n\n" + EXTRANJERO + " La web lo avisa.\n\n"
                     "| Institución | Qué ha pasado | Detalle |\n| --- | --- | --- |\n")
            for nombre, texto, detalle in lineas:
                fh.write(f"| {nombre} | {texto} | {(detalle or '').replace('|', '/')} |\n")
