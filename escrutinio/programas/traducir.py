"""Traducción al castellano de las citas que están en otra lengua (catalán, euskera, gallego).

La cita de cada compromiso se guarda tal como aparece en el programa, sin traducir, para que se pueda comprobar
en el PDF. Para quien no lee esa lengua, aquí se traduce una sola vez con DeepSeek (el modelo rápido, sin
razonamiento) y se guarda en data/llm/programas/traducciones/<programa>.jsonl, una línea por cita: {id, cita_es}.
La traducción acompaña a la cita en la web; nunca la sustituye.

La actualización diaria traduce con DeepSeek lo que falte. También se puede traducir fuera, con Claude o a mano:
programas-traducciones-pendientes saca las citas a un JSON y programas-importar-traducciones mete las traducciones
(lo importado ya no se vuelve a pedir a DeepSeek).

Qué cita está en otra lengua se decide con palabras que solo existen en cada una (sin LLM). Lo que ya está
traducido no se vuelve a pedir; si la cita cambia (programas-releer, programas-rehacer-citas), se traduce otra vez.
"""

import hashlib
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor

from ..llm import deepseek
from . import registro
from .leer import leer_compromisos

TRADUCCIONES_DIR = registro.PROGRAMAS_DIR / "traducciones"
LOTE = 50  # citas por petición (unos 300 caracteres cada una)
HILOS = 6  # peticiones a la vez

# Palabras corrientes que no existen en castellano: con dos o más, y más que de castellano, la cita va en esa lengua.
_PROPIAS = {
    "catalán": r"amb|els|dels|pels|pel|aquest|aquesta|aquests|aquestes|seva|seus|també|més|perquè|mitjançant|així|"
               r"garantirem|impulsarem|farem|crearem|serà|seran|aquells|llur|cal|caldrà|nostre|nostra|per|i|dret|drets|"
               r"[ldsmn]'[a-zàèéíòóú]\w*",  # l'Estat, d'un: el apóstrofo solo lo usa el catalán
    "euskera": r"eta|dira|dute|bat|izango|ditu|ere|euskal|herria|beharko|egingo|bidez|gure|baita|behar",
    "gallego": r"unha|coa|xa|tamén|polo|pola|nunha|galiza|mellorar|cidadanía|dereito|dereitos",
}
# Solo palabras que no existen en las otras tres («el», «del», «una», «para» o «con» sí existen y no sirven).
_CASTELLANO = r"los|las|y|sus|más|también|será|serán|mediante|ley|leyes|nuestro|nuestra|hacia|hasta|garantizar|ciudadanía"
_PATRONES = {k: re.compile(rf"(?<![\w'+]){'(?:' + v + ')'}(?![\w+])", re.I) for k, v in _PROPIAS.items()}  # no «I+D+i»
_ES = re.compile(rf"(?<![\w']){'(?:' + _CASTELLANO + ')'}(?!\w)", re.I)

SISTEMA = """Eres traductor. Recibes citas literales de programas electorales españoles escritas en catalán, euskera,
gallego u otra lengua. Tradúcelas al castellano con fidelidad: el mismo sentido, el mismo registro y la misma
longitud aproximada, sin resumir, sin añadir nada y sin valorar. Respeta cifras, siglas, nombres propios y nombres
de leyes (traduce el nombre de la ley si tiene uno habitual en castellano). Si una cita ya está en castellano,
devuélvela igual.

Responde SOLO con un objeto json: {"traducciones": [{"id": "…", "cita_es": "…"}]}, una por cita, con el mismo id."""


def lengua(cita):
    """«catalán», «euskera», «gallego» o None (castellano o no se sabe)."""
    es = len(_ES.findall(cita or ""))
    cuentas = {k: len(p.findall(cita or "")) for k, p in _PATRONES.items()}
    k, n = max(cuentas.items(), key=lambda x: x[1])
    return k if n >= 2 and n > es else None


def por_traducir(compromisos):
    """Las citas que hay que traducir. Las frases sueltas engañan («Proposem la condonació del FLA» no tiene ninguna
    palabra de la lista), así que se mira el programa entero: si al menos un 30 % de sus citas está en otra lengua,
    va todo lo que no sea claramente castellano; si no, nada (una palabra suelta en un programa en castellano).
    Si alguna resulta estar en castellano, el modelo la devuelve igual y la web no la muestra."""
    otras = sum(1 for c in compromisos if lengua(c["cita"]))
    if not compromisos or otras < 0.3 * len(compromisos):
        return []
    return [c for c in compromisos if lengua(c["cita"]) or len(_ES.findall(c["cita"])) < 2]


def _huella(cita):
    return hashlib.sha1((cita or "").encode("utf-8")).hexdigest()[:12]


def ruta(id_):
    return TRADUCCIONES_DIR / f"{id_}.jsonl"


def leer_traducciones(id_):
    """{id del compromiso: cita_es} de las traducciones que corresponden a la cita actual."""
    if not ruta(id_).exists():
        return {}
    salida = {}
    for l in ruta(id_).read_text(encoding="utf-8").splitlines():
        if l.strip():
            t = json.loads(l)
            salida[t["id"]] = t
    return salida


def vigentes(id_, compromisos):
    """{id: cita_es} solo de las traducciones hechas sobre la misma cita que hay ahora."""
    hechas = leer_traducciones(id_)
    igual = lambda a, b: re.sub(r"\W+", "", a).lower() == re.sub(r"\W+", "", b).lower()  # ya estaba en castellano
    return {c["id"]: hechas[c["id"]]["cita_es"] for c in compromisos
            if c["id"] in hechas and hechas[c["id"]].get("huella") == _huella(c["cita"])
            and not igual(hechas[c["id"]]["cita_es"], c["cita"])}


def traducir(ids=None, modelo=None, log=print):
    """Traduce las citas en otra lengua de los programas leídos que aún no lo estén. Devuelve cuántas tradujo."""
    if not deepseek.disponible():
        log("  Traducciones: falta DEEPSEEK_API_KEY")
        return 0
    modelo = modelo or deepseek.modelo_por_defecto()
    total = 0
    for e in registro.vigentes(registro.leer_registro()):
        if e["estado"] != "leido" or (ids and e["id"] not in ids):
            continue
        compromisos = leer_compromisos(e["id"])
        hechas = vigentes(e["id"], compromisos)
        faltan = [c for c in por_traducir(compromisos) if c["id"] not in hechas]
        if not faltan:
            continue
        log(f"  {e['id']}: {len(faltan)} citas por traducir")
        TRADUCCIONES_DIR.mkdir(parents=True, exist_ok=True)
        cerrojo = threading.Lock()

        def pedir(lote, e=e):
            usuario = json.dumps({"citas": [{"id": c["id"], "cita": c["cita"]} for c in lote]}, ensure_ascii=False)
            datos, modelo_real, _uso = deepseek.chat_json(SISTEMA, usuario, modelo=modelo, max_tokens=16_000, razonar=False)
            por_id = {c["id"]: c for c in lote}
            nuevas = []
            for t in datos.get("traducciones", []):
                c = por_id.get(t.get("id"))
                if c and isinstance(t.get("cita_es"), str) and t["cita_es"].strip():
                    nuevas.append({"id": c["id"], "cita_es": t["cita_es"].strip(), "lengua": lengua(c["cita"]),
                                   "huella": _huella(c["cita"]), "modelo": modelo_real})
            with cerrojo, ruta(e["id"]).open("a", encoding="utf-8", newline="\n") as f:  # lo pagado se guarda ya
                f.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in nuevas)
            return len(nuevas)

        with ThreadPoolExecutor(HILOS) as hilos:
            total += sum(hilos.map(pedir, [faltan[i:i + LOTE] for i in range(0, len(faltan), LOTE)]))
    log(f"Citas traducidas al castellano: {total}")
    return total


def importar(ficheros, modelo, log=print):
    """Añade traducciones hechas fuera de DeepSeek (con Claude o a mano): ficheros JSON {id del compromiso: cita_es}.
    Para no gastar DeepSeek: se sacan las citas pendientes (pendientes()), se traducen y se importan aquí. Solo entra
    lo que corresponde a una cita que existe y está sin traducir; la huella se calcula con la cita actual."""
    nuevas = {}
    for f in ficheros:
        with open(f, encoding="utf-8") as fh:
            nuevas.update(json.load(fh))
    por_programa = {}
    for cid, cita_es in nuevas.items():
        if isinstance(cita_es, str) and cita_es.strip():
            por_programa.setdefault(cid.split(":", 1)[0], {})[cid] = cita_es.strip()
    total = 0
    for id_, trads in por_programa.items():
        compromisos = {c["id"]: c for c in leer_compromisos(id_)}
        hechas = leer_traducciones(id_)
        filas = [{"id": cid, "cita_es": t, "lengua": lengua(compromisos[cid]["cita"]),
                  "huella": _huella(compromisos[cid]["cita"]), "modelo": modelo}
                 for cid, t in trads.items() if cid in compromisos and cid not in hechas]
        if filas:
            TRADUCCIONES_DIR.mkdir(parents=True, exist_ok=True)
            with ruta(id_).open("a", encoding="utf-8", newline="\n") as fh:
                fh.writelines(json.dumps(t, ensure_ascii=False) + "\n" for t in filas)
        log(f"  {id_}: {len(filas)} traducciones importadas")
        total += len(filas)
    log(f"Traducciones importadas: {total}")
    return total


def pendientes(ids=None):
    """[{id, cita}] de las citas que faltan por traducir, para traducirlas fuera (importar())."""
    salida = []
    for e in registro.vigentes(registro.leer_registro()):
        if e["estado"] != "leido" or (ids and e["id"] not in ids):
            continue
        compromisos = leer_compromisos(e["id"])
        hechas = leer_traducciones(e["id"])
        salida += [{"id": c["id"], "cita": c["cita"]} for c in por_traducir(compromisos) if c["id"] not in hechas]
    return salida
