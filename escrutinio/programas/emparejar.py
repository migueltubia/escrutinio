"""Emparejar compromisos con iniciativas: candidatas con BM25 y relación decidida por DeepSeek.

1. Candidatas (sin LLM): para cada compromiso verificable, las 10 iniciativas más parecidas de la
   legislatura que cubre el programa, entre las que tienen ficha y comparten tema (principal o
   secundario). BM25 sobre el título, el resumen y las etiquetas, con las palabras recortadas a seis
   letras para que «vivienda» y «viviendas» cuenten igual.
2. Relación (DeepSeek, modelo rápido): recibe el compromiso y sus candidatas sin autor, sin votos y sin
   resultado, y dice de cada una si va en la misma dirección, en la contraria, si trata lo mismo sin
   dirección clara o si no tiene que ver. Nunca sabe de qué partido es el compromiso.

Cada par decidido se guarda en data/llm/programas/emparejamientos/<programa>.jsonl, también los que no
tienen que ver, y no se vuelve a preguntar: cuando se votan iniciativas nuevas, solo se deciden las
candidatas nuevas.
"""

import json
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from ..analisis import debates_generales
from ..llm import deepseek
from ..texto import tokens
from . import registro
from .leer import leer_compromisos

# v2: la v1 marcaba como «relacionada» cualquier iniciativa del mismo ámbito (pensiones, empleo) aunque su propia
# justificación dijera que trataba otra cuestión.
VERSION_PROMPT = "emparejar-v2"
EMPAREJAMIENTOS_DIR = registro.PROGRAMAS_DIR / "emparejamientos"
CANDIDATAS = 10
POR_LLAMADA = 5
HILOS = 4  # lotes que se piden a la vez
RELACIONES = ("misma", "contraria", "relacionada", "ninguna")

SISTEMA = """Eres un analista parlamentario neutral. Recibes compromisos concretos tomados de programas electorales
(sin decir de qué partido son) y, para cada uno, una lista de iniciativas del Congreso de los Diputados candidatas
(sin autor ni resultado). Para cada candidata decide su relación con el compromiso:
- misma: si la iniciativa saliera adelante, se avanzaría en lo que el compromiso promete.
- contraria: va en sentido opuesto al compromiso (por ejemplo, el compromiso promete derogar la ley X y la iniciativa
  la amplía o la refuerza; el compromiso promete bajar un impuesto y la iniciativa lo sube).
- relacionada: trata EXACTAMENTE la misma medida concreta que el compromiso (la misma ley, el mismo impuesto, la misma
  prestación, el mismo organismo, el mismo colectivo y la misma cuestión), pero no se puede decir si va a favor o en
  contra. Es un caso raro.
- ninguna: todo lo demás. Compartir el ámbito general no basta: si el compromiso trata del Fondo de Reserva de las
  pensiones y la iniciativa de la revalorización de las pensiones, o el compromiso de un pacto por el empleo y la
  iniciativa de la inclusión laboral de las personas con discapacidad, la relación es «ninguna».
Sé estricto: ante la duda entre misma o contraria y relacionada, elige relacionada; ante la duda entre relacionada y
ninguna, elige ninguna. Si al justificar tienes que decir que la iniciativa trata otra cuestión, otra medida u otro
aspecto, la relación es «ninguna». La mayoría de las candidatas no tienen que ver con el compromiso: lo normal es que
casi todas sean «ninguna». Justifica cada relación que no sea «ninguna» en una frase neutra y descriptiva.
Responde SOLO con un objeto json: {"compromisos": [{"id": "c1", "candidatas": [{"n": 1, "relacion": "misma",
"justificacion": "La proposición deroga la ley que el compromiso promete derogar."}]}]}"""

# El autor sale en el título («… presentada por el Grupo Parlamentario X, sobre…»): se quita antes de enseñárselo al modelo.
_GRUPO = re.compile(r"(?i)(presentad[ao]s? por |de los |del |el |los )?grupos? parlamentarios? [^,]*,?")


def _sin_autor(titulo):
    return re.sub(r"\s+", " ", _GRUPO.sub("", titulo or "")).strip()


def _raices(texto):
    return [t[:6] for t in tokens(texto)]


def leer_emparejamientos():
    """{(compromiso, «leg:expediente»): línea}; si un par está repetido, gana la última."""
    pares = {}
    for ruta in sorted(EMPAREJAMIENTOS_DIR.glob("*.jsonl")):
        for linea in ruta.read_text(encoding="utf-8").splitlines():
            if linea.strip():
                d = json.loads(linea)
                pares[(d["compromiso"], d["iniciativa"])] = d
    return pares


class Indice:
    """BM25 sobre las fichas de una legislatura, con el tema de cada una para filtrar."""

    def __init__(self, con, legislatura):
        debates = debates_generales(con)
        self.docs = []
        for r in con.execute(
            """SELECT i.legislatura, i.expediente, i.titulo, i.prefijo, COALESCE(te.nombre, i.tipo) AS tipo, te.familia,
                      f.resumen, f.etiquetas, f.tema_principal, f.temas_secundarios
               FROM iniciativa i JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
               LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
               WHERE i.legislatura=? AND f.resumen IS NOT NULL""", (legislatura,)):
            if (r["legislatura"], r["expediente"]) in debates:
                continue
            temas = {r["tema_principal"], *json.loads(r["temas_secundarios"] or "[]")}
            texto = " ".join([r["titulo"] or "", r["resumen"] or "", " ".join(json.loads(r["etiquetas"] or "[]"))])
            self.docs.append({"id": f"{r['legislatura']}:{r['expediente']}", "temas": temas, "tf": Counter(_raices(texto)),
                              "tipo": r["tipo"], "familia": r["familia"], "titulo": _sin_autor(r["titulo"]),
                              "resumen": r["resumen"]})
        self.n = len(self.docs) or 1
        self.media = sum(sum(d["tf"].values()) for d in self.docs) / self.n
        df = Counter(t for d in self.docs for t in d["tf"])
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def buscar(self, consulta, tema, k=CANDIDATAS, k1=1.5, b=0.75):
        terminos = set(_raices(consulta))
        puntos = []
        for d in self.docs:
            if tema not in d["temas"]:
                continue
            largo = sum(d["tf"].values())
            s = sum(self.idf.get(t, 0) * d["tf"][t] * (k1 + 1) / (d["tf"][t] + k1 * (1 - b + b * largo / self.media))
                    for t in terminos if t in d["tf"])
            if s > 0:
                puntos.append((s, d))
        puntos.sort(key=lambda x: -x[0])
        return puntos[:k]


def _legislatura(con, e):
    """La legislatura que empieza tras la elección del programa en su institución."""
    r = con.execute("SELECT id FROM legislatura WHERE cuerpo=? AND inicio>=? ORDER BY inicio LIMIT 1",
                    (e["cuerpo"], e["fecha_eleccion"])).fetchone()
    return r[0] if r else None


def emparejar(con, ids=None, limite=None, modelo=None, log=print):
    """Decide las candidatas nuevas de cada compromiso verificable de los programas leídos."""
    if not deepseek.disponible():
        raise SystemExit("Falta DEEPSEEK_API_KEY (en .env o como variable de entorno)")
    hechos = leer_emparejamientos()
    entradas = [e for e in registro.vigentes(registro.leer_registro())
                if e["estado"] == "leido" and (not ids or e["id"] in ids or e["base"] in ids)]
    EMPAREJAMIENTOS_DIR.mkdir(parents=True, exist_ok=True)
    indices, total = {}, 0
    for e in entradas:
        leg = _legislatura(con, e)
        if leg is None:
            log(f"  {e['id']}: aún no hay legislatura tras la elección de {e['fecha_eleccion']}")
            continue
        indice = indices.setdefault(leg, Indice(con, leg))
        pendientes = []
        for c in leer_compromisos(e["id"]):
            if not c["verificable"]:
                continue
            nuevas = [(s, d) for s, d in indice.buscar(c["texto"] + " " + " ".join(c["etiquetas"]), c["tema"])
                      if (c["id"], d["id"]) not in hechos]
            if nuevas:
                pendientes.append((c, nuevas))
        if limite is not None:
            pendientes = pendientes[: max(0, limite - total)]
        log(f"  {e['id']}: {len(pendientes)} compromisos con candidatas nuevas (legislatura {leg})")
        t_in = t_out = 0
        salida = EMPAREJAMIENTOS_DIR / f"{e['id']}.jsonl"
        lotes = [pendientes[i : i + POR_LLAMADA] for i in range(0, len(pendientes), POR_LLAMADA)]

        def preguntar(lote):
            entrada = [{"id": f"c{k + 1}", "compromiso": c["texto"],
                        "candidatas": [{"n": n + 1, "tipo": d["tipo"], "titulo": d["titulo"], "resumen": d["resumen"]}
                                       for n, (_s, d) in enumerate(nuevas)]}
                       for k, (c, nuevas) in enumerate(lote)]
            return deepseek.chat_json(SISTEMA, json.dumps(entrada, ensure_ascii=False), modelo)

        # Los lotes se piden a la vez (HILOS) y se guardan en orden.
        with ThreadPoolExecutor(HILOS) as hilos:
            futuros = [hilos.submit(preguntar, lote) for lote in lotes]
            for j, (lote, futuro) in enumerate(zip(lotes, futuros)):
                i = j * POR_LLAMADA
                try:
                    datos, modelo_real, uso = futuro.result()
                except deepseek.ErrorIA as err:
                    log(f"    ! lote {j + 1}: {err}")
                    continue
                _guardar(lote, datos, modelo_real, salida, hechos)
                t_in += uso.get("prompt_tokens", 0)
                t_out += uso.get("completion_tokens", 0)
                log(f"    {min(i + POR_LLAMADA, len(pendientes))}/{len(pendientes)}")
        total += len(pendientes)
        if t_in or t_out:
            e["tokens_emparejar_entrada"] = e.get("tokens_emparejar_entrada", 0) + t_in
            e["tokens_emparejar_salida"] = e.get("tokens_emparejar_salida", 0) + t_out
            registro.actualizar_entrada(e)
        if limite is not None and total >= limite:
            break
    return total


def _guardar(lote, datos, modelo_real, salida, hechos):
    """Escribe los pares decididos de un lote (también los «ninguna»); lo que no vino se volverá a preguntar."""
    respuestas = {r.get("id"): r for r in datos.get("compromisos") or [] if isinstance(r, dict)}
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lineas = []
    for k, (c, nuevas) in enumerate(lote):
        decididas = {x.get("n"): x for x in (respuestas.get(f"c{k + 1}") or {}).get("candidatas") or []
                     if isinstance(x, dict) and x.get("relacion") in RELACIONES}
        for n, (s, d) in enumerate(nuevas):
            x = decididas.get(n + 1)
            if not x:
                continue
            lineas.append({"compromiso": c["id"], "iniciativa": d["id"], "relacion": x["relacion"],
                           "justificacion": (x.get("justificacion") or "").strip() or None, "rango": n + 1,
                           "bm25": round(s, 2), "modelo": f"deepseek:{modelo_real}", "version_prompt": VERSION_PROMPT,
                           "creado": ahora})
    with open(salida, "a", encoding="utf-8") as fh:
        fh.writelines(json.dumps(l, ensure_ascii=False) + "\n" for l in lineas)
    for l in lineas:
        hechos[(l["compromiso"], l["iniciativa"])] = l
