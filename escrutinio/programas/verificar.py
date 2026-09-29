"""Segunda revisión, más exigente, de las relaciones que cuentan en las cifras.

La primera pasada (emparejar.py, modelo rápido) decide la relación de cada compromiso con sus candidatas
viendo solo el compromiso resumido. A veces da por «misma dirección» dos cosas que solo se llaman
parecido: una «ley de protección integral de la familia» y una «ley de familias» pueden proponer cosas
opuestas. Las relaciones con dirección (misma o contraria), que son las que deciden el estado de cada
compromiso, se vuelven a revisar con el modelo Pro y más contexto: la cita literal del programa, sin
nombres de partido, y el título, el resumen y las etiquetas de la iniciativa. Tampoco aquí se ven el
partido, el autor ni los votos.

Lo revisado va a data/llm/programas/verificaciones/<programa>.jsonl, una línea por par, y manda sobre la
primera pasada; un par ya revisado no se vuelve a preguntar salvo que se pida (`programas-verificar --rehacer`).
"""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..llm import deepseek
from . import registro
from .emparejar import HILOS, RELACIONES, _sin_autor, leer_emparejamientos
from .leer import MODELO, leer_compromisos

# v2: la v1 exigía «el mismo enfoque» y dejaba sin dirección más de la mitad de las relaciones; ahora cuenta
# también lo que avanza en parte o con otro alcance. Solo queda fuera lo que coincide en el nombre y no en el fondo.
VERSION_PROMPT = "verificar-v2"
VERIFICACIONES_DIR = registro.PROGRAMAS_DIR / "verificaciones"
POR_LLAMADA = 5

SISTEMA = """Eres un analista parlamentario neutral. Recibes pares formados por un compromiso de un programa electoral
(resumido y con su cita literal) y una iniciativa del Congreso de los Diputados (tipo, título, resumen y etiquetas).
No se dice qué partido hizo la promesa ni quién presentó la iniciativa, ni cómo se votó. Para cada par, decide la
relación:
- misma: si la iniciativa saliera adelante, se avanzaría en lo que promete el compromiso, aunque sea en parte o con
  otro alcance o enfoque (por ejemplo, el compromiso promete una jornada de 37,5 horas y la iniciativa la baja a 38; o
  promete reforzar la sanidad pública y la iniciativa amplía una prestación concreta de la sanidad pública).
- contraria: la iniciativa iría en sentido opuesto a lo que promete el compromiso (deroga lo que promete mantener,
  amplía lo que promete derogar, sube lo que promete bajar…), aunque sea en parte.
- relacionada: tratan la misma medida, pero con lo que se sabe no se puede decir si avanza o retrocede en lo
  prometido; o solo coinciden en el nombre o el tema y el contenido va por otro lado (dos «leyes de familias» o dos
  «planes de choque» pueden proponer cosas distintas u opuestas).
- ninguna: no tratan la misma medida.
Ante una duda razonable entre misma o contraria y relacionada, elige relacionada. Justifica en una o dos frases
neutras qué propone cada uno y por qué eliges esa relación. Responde SOLO con un objeto json:
{"pares": [{"id": "p1", "relacion": "relacionada", "justificacion": "…"}]}"""

# Los programas se nombran a sí mismos («desde el PSOE…»): se quita antes de enseñárselo al modelo.
_PARTIDOS = re.compile(r"\b(PSOE|Partido Socialista(?: Obrero Español)?|Partido Popular|PP|VOX|Vox|Sumar|ERC|"
                       r"Esquerra(?: Republicana)?|Junts(?: per Catalunya)?|EH Bildu|Bildu|EAJ-PNV|PNV|EAJ)\b")


def leer_verificaciones():
    """{(compromiso, «leg:expediente»): línea}; si un par está repetido, gana la última."""
    pares = {}
    for ruta in sorted(VERIFICACIONES_DIR.glob("*.jsonl")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                d = json.loads(linea)
                pares[(d["compromiso"], d["iniciativa"])] = d
    return pares


def _iniciativa(con, clave):
    leg, exp = clave.split(":", 1)
    r = con.execute(
        """SELECT i.titulo, COALESCE(te.nombre, i.tipo) AS tipo, f.resumen, f.etiquetas FROM iniciativa i
           LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
           LEFT JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
           WHERE i.legislatura=? AND i.expediente=?""", (int(leg), exp)).fetchone()
    if not r:
        return None
    return {"tipo": r["tipo"], "titulo": _sin_autor(r["titulo"]), "resumen": r["resumen"],
            "etiquetas": json.loads(r["etiquetas"] or "[]")}


def verificar(con, ids=None, limite=None, modelo=None, rehacer=False, log=print):
    """Revisa los pares con dirección (misma o contraria) de la primera pasada que aún no se han revisado.

    Un cambio de prompt no repite nada por sí solo: con rehacer=True (orden explícita) se vuelven a revisar los
    pares revisados con una versión anterior; la revisión nueva se añade y manda sobre la vieja.
    """
    if not deepseek.disponible():
        raise SystemExit("Falta DEEPSEEK_API_KEY (en .env o como variable de entorno)")
    pares, hechos = leer_emparejamientos(), leer_verificaciones()
    VERIFICACIONES_DIR.mkdir(parents=True, exist_ok=True)
    modelo = modelo or MODELO
    total = 0
    for e in registro.vigentes(registro.leer_registro()):
        if e["estado"] != "leido" or (ids and e["id"] not in ids and e["base"] not in ids):
            continue
        compromisos = {c["id"]: c for c in leer_compromisos(e["id"])}
        cola = []
        for (cid, ini), p in sorted(pares.items()):
            hecho = hechos.get((cid, ini))
            pendiente = not hecho or (rehacer and hecho.get("version_prompt") != VERSION_PROMPT)
            if cid in compromisos and p["relacion"] in ("misma", "contraria") and pendiente:
                info = _iniciativa(con, ini)
                if info:
                    cola.append((cid, ini, p["relacion"], info))
        if limite is not None:
            cola = cola[: max(0, limite - total)]
        log(f"  {e['id']}: {len(cola)} relaciones con dirección por revisar")
        lotes = [cola[i : i + POR_LLAMADA] for i in range(0, len(cola), POR_LLAMADA)]

        def preguntar(lote):
            entrada = [{"id": f"p{k + 1}", "compromiso": compromisos[cid]["texto"],
                        "cita": _PARTIDOS.sub("[partido]", compromisos[cid]["cita"]), "iniciativa": info}
                       for k, (cid, _ini, _rel, info) in enumerate(lote)]
            return deepseek.chat_json(SISTEMA, json.dumps(entrada, ensure_ascii=False), modelo, max_tokens=64_000)

        salida = VERIFICACIONES_DIR / f"{e['id']}.jsonl"
        t_in = t_out = 0
        with ThreadPoolExecutor(HILOS) as hilos:
            futuros = [hilos.submit(preguntar, lote) for lote in lotes]
            for j, (lote, futuro) in enumerate(zip(lotes, futuros)):
                try:
                    datos, modelo_real, uso = futuro.result()
                except deepseek.ErrorIA as err:  # se volverá a preguntar en la próxima pasada
                    log(f"    ! lote {j + 1}: {err}")
                    continue
                t_in += uso.get("prompt_tokens", 0)
                t_out += uso.get("completion_tokens", 0)
                respuestas = {r.get("id"): r for r in datos.get("pares") or [] if isinstance(r, dict)}
                ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
                lineas = []
                for k, (cid, ini, rel, _info) in enumerate(lote):
                    r = respuestas.get(f"p{k + 1}")
                    if r and r.get("relacion") in RELACIONES:
                        lineas.append({"compromiso": cid, "iniciativa": ini, "antes": rel, "relacion": r["relacion"],
                                       "justificacion": (r.get("justificacion") or "").strip() or None,
                                       "modelo": f"deepseek:{modelo_real}", "version_prompt": VERSION_PROMPT, "creado": ahora})
                with open(salida, "a", encoding="utf-8") as fh:
                    fh.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in lineas)
                log(f"    {min((j + 1) * POR_LLAMADA, len(cola))}/{len(cola)}")
        total += len(cola)
        if t_in or t_out:
            e = next(x for x in registro.leer_registro() if x["id"] == e["id"])  # el registro puede haber cambiado
            e["tokens_emparejar_entrada"] = e.get("tokens_emparejar_entrada", 0) + t_in
            e["tokens_emparejar_salida"] = e.get("tokens_emparejar_salida", 0) + t_out
            registro.actualizar_entrada(e)
        if limite is not None and total >= limite:
            break
    return total
