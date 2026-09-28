"""Tema provisional por reglas, sin IA, a partir de la comisión competente.

Los proyectos y proposiciones de ley se tramitan en una comisión que casi siempre indica la
materia (Comisión de Sanidad -> Sanidad). En las comisiones que abarcan varias materias, unas
palabras del título afinan el tema. El resultado va a la tabla tema_provisional, separada de las
fichas IA; la web lo usa solo cuando una iniciativa aún no tiene ficha IA.
"""

import json
import re
from .texto import normalizar

VERSION = "comision-v1"

# (patrón de la comisión, tema por defecto, secundario, [(patrón del título, tema que lo sustituye)]).
# Se prueban en orden: van primero los patrones más específicos.
_ECONOMIA_URGENTE = (r"consecuencias economicas|materia economica|reactivacion economica", "ECO")

REGLAS = [
    (r"derechos sociales", "SOC", "ECO", [(r"consum|clientela|contrat", "ECO")]),
    (r"juventud|infancia", "SOC", None, []),
    (r"igualdad", "IGU", None, []),
    (r"justicia", "JUS", None, [
        (r"arrendamiento|alquiler|vivienda|desahucio|ocupacion|propiedad horizontal", "VIV"),
        (r"rectificacion|medios de comunicacion", "CUL"),
        (r"consumidor|empresarial|mercantil|concursal|sociedades de capital", "ECO"),
    ]),
    (r"presupuestos", "PRE", None, []),
    (r"hacienda", "FIS", "PRE", [
        (r"presupuestos generales|techo de gasto|estabilidad presupuestaria|credito extraordinario|sostenibilidad financiera", "PRE"),
        (r"funcion publica|empleo publico|empleados publicos|integridad|transparencia|grupos de interes|procedimiento administrativo", "INS"),
        (r"financiacion autonomica|financiacion territorial|sistemas de financiacion|haciendas locales|cesion de tributos", "TER"),
        (r"jubilacion|pension", "PEN"),
        (r"celiac|sanitari|salud", "SAN"),
        _ECONOMIA_URGENTE,
    ]),
    (r"funcion publica", "INS", None, []),
    (r"trabajo|empleo|inclusion|seguridad social|migraciones", "EMP", None, [
        (r"pension|jubilacion|ingreso minimo|revalorizacion", "PEN"),
        (r"extranjer|inmigra|migrante|asilo|refugiad", "MIG"),
        (r"donante|sanitari|salud", "SAN"),
    ]),
    (r"sanidad|salud", "SAN", None, []),
    (r"constitucional", "INS", None, [
        (r"informacion clasificada|secretos oficiales", "SEG"),
        (r"tribunal constitucional|poder judicial", "JUS"),
        (r"radio|television|medios de comunicacion|lengua|simbolos", "CUL"),
        (r"igualdad|discriminacion|lgtbi|memoria democratica|libertad|derechos fundamentales|honor|intimidad|asociacion", "IGU"),
        (r"estatuto de autonomia|comunidad autonoma", "TER"),
    ]),
    (r"transicion ecologica|medio ambiente|reto demografico", "MED", "ENE", [
        (r"energ|electric|hidrocarburo|nuclear|renovable|gas natural|combustible", "ENE"),
        (r"despoblacion|reto demografico|medio rural", "AGR"),
    ]),
    (r"interior|seguridad vial", "SEG", None, [
        (r"ocupacion|okupa|vivienda", "VIV"),
        (r"discapacidad", "SOC"),
    ]),
    (r"economia|asuntos economicos|industria|turismo|comercio", "ECO", None, [
        (r"digital|inteligencia artificial|telecomunicacion|ciberseguridad|datos|algoritm", "DIG"),
        (r"energ|electric", "ENE"),
    ]),
    (r"transportes|movilidad|fomento", "TRA", None, []),
    (r"politica territorial", "TER", None, []),
    (r"vivienda", "VIV", None, []),
    (r"agricultura|pesca|alimentacion", "AGR", None, []),
    (r"\bcultura\b", "CUL", None, []),
    (r"educacion|ciencia|universidades", "EDU", None, [(r"deport", "CUL")]),
    (r"defensa", "DEF", None, []),
    (r"asuntos exteriores|cooperacion internacional|union europea", "EXT", None, []),
    (r"reglamento|estatuto de los diputados|peticiones", "INS", None, []),
]

# Asuntos cuyo título manda sobre la comisión, sea cual sea.
REFINOS_GLOBALES = [(r"oriente medio|gaza|ucrania|guerra de", "EXT")]


def tema_por_comision(comision, titulo=""):
    """Devuelve (tema, secundarios, regla aplicada) o None si la comisión no está en las reglas."""
    c, t = normalizar(comision), normalizar(titulo)
    if not c:
        return None
    for patron_t, tema_t in REFINOS_GLOBALES:
        if re.search(patron_t, t):
            return tema_t, [], f"título «{patron_t}»"
    for patron, tema, secundario, refinos in REGLAS:
        if re.search(patron, c):
            for patron_t, tema_t in refinos:
                if re.search(patron_t, t):
                    secundarios = [x for x in (tema, secundario) if x and x != tema_t][:1]
                    return tema_t, secundarios, f"{patron} + título «{patron_t}»"
            return tema, [secundario] if secundario else [], patron
    return None


def calcular(con, log=print):
    filas = []
    for r in con.execute("SELECT legislatura, expediente, titulo, extra_json FROM iniciativa WHERE extra_json IS NOT NULL"):
        comision = (json.loads(r["extra_json"]).get("COMISIONCOMPETENTE") or "").strip()
        res = tema_por_comision(comision, r["titulo"])
        if res:
            tema, secundarios, regla = res
            filas.append((r["legislatura"], r["expediente"], comision, tema, json.dumps(secundarios), regla, VERSION, None))
    con.execute("DELETE FROM tema_provisional")
    con.executemany("INSERT INTO tema_provisional VALUES (?,?,?,?,?,?,?,?)", filas)
    con.commit()
    # Contraste con las fichas IA cuando existen ambas.
    coinciden, total, cerca = 0, 0, 0
    for r in con.execute(
        """SELECT p.tema_principal AS p, f.tema_principal AS ia, f.temas_secundarios AS sec
           FROM tema_provisional p JOIN ficha_llm f USING (legislatura, expediente)"""
    ):
        total += 1
        coinciden += r["p"] == r["ia"]
        cerca += r["p"] == r["ia"] or r["p"] in json.loads(r["sec"] or "[]")
    sin_ficha = con.execute(
        """SELECT COUNT(*) FROM tema_provisional p LEFT JOIN ficha_llm f USING (legislatura, expediente)
           WHERE f.expediente IS NULL"""
    ).fetchone()[0]
    log(f"Tema provisional por comisión: {len(filas)} iniciativas ({sin_ficha} sin ficha IA)")
    if total:
        log(f"  coincide con la IA en el tema principal: {coinciden}/{total} ({100 * coinciden / total:.0f}%); "
            f"con el principal o un secundario: {cerca}/{total} ({100 * cerca / total:.0f}%)")
