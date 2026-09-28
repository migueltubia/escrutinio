"""Mitad determinista del sistema: sin IA.

1. Tipo de cada votación (reglas sobre la sección y los textos del asunto).
2. Mayoría requerida y resultado calculado a partir de los totales.
3. Cruce votación -> iniciativa por título normalizado (el fichero de votación no trae expediente).
4. Votación decisiva y resultado final de cada iniciativa.
5. Grupos decisivos: los que habrían cambiado el resultado votando distinto.
"""

import hashlib
import json
import re
from collections import defaultdict

from .catalogos import TIPOS_VOTACION
from .config import LEGISLATURAS, LLM_DIR, MAYORIA_ABSOLUTA_CONGRESO
from .texto import GRUPOS, grupo_de_autor, info_grupo, normalizar, tokens

# Todo lo de este módulo es del Congreso: las votaciones territoriales se procesan en territorial/procesar.py.
_LEGS = ",".join(str(l) for l in sorted(LEGISLATURAS))
EN_CONGRESO = f"legislatura IN ({_LEGS})"
V_EN_CONGRESO = f"v.legislatura IN ({_LEGS})"

# ---------------------------------------------------------------- tipo de votación


def _primera_linea(texto):
    return (texto or "").strip().split("\n")[0].strip()


def tipo_votacion(seccion, texto, subgrupo, texto_subgrupo):
    s = normalizar(seccion)
    t = normalizar(_primera_linea(texto))
    sg = normalizar(subgrupo)
    ts = normalizar(texto_subgrupo)
    todo = " ".join((s, t, sg, ts))

    if "investidura" in todo or "mocion de censura" in todo or "cuestion de confianza" in todo:
        return "investidura"
    if "proposiciones no de ley" in s or t.startswith("proposicion no de ley"):
        return "pnl"
    if "mociones consecuencia" in s or t.startswith("mocion consecuencia"):
        return "mocion"
    # La sección a veces está mal en origen (hay reformas del Reglamento archivadas como convalidaciones):
    # solo cuenta si el texto habla de un real decreto.
    if ("real decreto" in s or "convalidacion" in s) and ("real decreto" in t or "real decreto" in ts):
        if "tramitacion como proyecto" in t or "tramitacion como proyecto" in ts:
            return "tramitacion_ley"
        return "convalidacion"
    if "convenios internacionales" in s or "tratados internacionales" in s:
        return "tratado"
    if "estado de alarma" in s or "estados de alarma" in s:
        return "control"
    if "toma en consideracion" in s or "toma en consideracion" in t:
        return "toma_consideracion"
    if "avocacion" in t or "avocacion" in ts:
        return "organizacion"
    if "debates de totalidad" in s or "debate de totalidad" in s:
        return "totalidad"
    if "veto" in s or "veto" in sg or "veto" in ts:
        return "veto_senado"
    if "enmiendas del senado" in s or sg.startswith("enmiendas del senado"):
        return "enmiendas_senado"
    if "propuestas de resolucion" in s or "propuestas de resolucion" in sg:
        return "control"
    if (
        "objetivo de estabilidad" in s
        or "objetivos de estabilidad" in s
        or "cuenta general" in s
        or "comunicacion del gobierno" in s
        or "informe" in s
        or "estado de la nacion" in s
        or "dacion de cuentas" in s
        or "135 4 de la constitucion" in s
        or "defensa nacional" in s
    ):
        return "control"
    if any(k in s for k in ("eleccion", "designacion", "nombramiento", "propuesta de candidatos", "renovacion")):
        return "nombramiento"
    if any(
        k in s
        for k in ("subcomision", "comision de investigacion", "comisiones de investigacion", "estatuto de los diputados",
                  "suplicatorio", "creacion de comision", "calendario", "comision no permanente",
                  "comisiones no permanentes", "conflicto de atribuciones")
    ):
        return "organizacion"

    # Leyes: dictámenes, lectura única, Presupuestos, etc.
    if "conjunto" in sg or "conjunto" in ts or "conjunto" in t:
        return "conjunto"
    if sg.startswith("texto del dictamen") or ts.startswith("votacion del dictamen"):
        return "articulado"
    if "totalidad" in sg or "totalidad" in ts or "devolucion" in sg or "devolucion" in ts:
        return "totalidad"
    if "enmienda" in sg or "enmienda" in ts or "enmiendas" in t:
        return "enmiendas"
    if "tramitacion directa y en lectura unica" in t or "lectura unica" in t and t.startswith("tramitacion"):
        return "organizacion"
    if "presupuestos generales" in s:
        return "enmiendas" if (sg or ts) else "articulado"
    if any(k in sg + " " + ts for k in ("votacion separada", "por puntos", "articulo", "disposicion", "dictamen", "texto")):
        return "articulado"
    if "dictamen" in s or "lectura unica" in s or "iniciativas legislativas" in s:
        # Una votación sin subgrupo en un dictamen o lectura única suele ser el texto completo.
        return "conjunto" if not (sg or ts) else "articulado"
    return "otro"


def mayoria_requerida(tipo, texto, texto_subgrupo):
    t = normalizar(texto)
    ts = normalizar(texto_subgrupo)
    if tipo == "conjunto" and ("ley organica" in t or "caracter organico" in ts or "estatuto de autonomia" in t):
        return "absoluta"
    if tipo == "investidura" and "primera votacion" in ts:
        return "absoluta"
    return "simple"


def resultado(asentimiento, a_favor, en_contra, mayoria):
    if asentimiento:
        return "aprobada", None
    a_favor, en_contra = a_favor or 0, en_contra or 0
    if mayoria == "absoluta":
        margen = a_favor - MAYORIA_ABSOLUTA_CONGRESO
        return ("aprobada" if margen >= 0 else "rechazada"), margen
    margen = a_favor - en_contra
    # Los empates que persisten tras repetir la votación se entienden rechazados.
    return ("aprobada" if margen > 0 else "rechazada"), margen


# ---------------------------------------------------------------- enlace con iniciativas

PREFIJOS_POR_TIPO = {
    "pnl": ["162"],
    "mocion": ["173"],
    "convalidacion": ["130"],
    "tramitacion_ley": ["130"],
    "tratado": ["110"],
    "toma_consideracion": ["122", "123", "124", "125", "120", "410", "127"],
}
PREFIJOS_LEY = ["121", "122", "123", "124", "125", "120", "127", "410"]

RDL_RE = re.compile(r"real decreto ley (\d+) (\d{4})")
PGE_RE = re.compile(r"presupuestos generales del estado para (?:el ano )?(\d{4})")
# Cláusula de autor dentro del texto votado: «Proposición no de Ley del Grupo Parlamentario X, sobre…».
# Termina en la primera coma seguida de minúscula (los nombres de grupo llevan comas seguidas de mayúscula).
_AUTOR = r"(?i:del|de los|de la|de las)\s+(?i:grupos?|asamblea|cortes|parlamento|junta|diputad|senado|comisi[oó]n promotora).*?,\s+(?=[a-záéíóúñ]|General\b|Org[aá]nica\b)"
AUTOR_TRAS_PREFIJO = re.compile(
    r"^((?i:proposici[oó]n no de ley|proposici[oó]n de ley(?: org[aá]nica)?|moci[oó]n consecuencia de interpelaci[oó]n(?: urgente)?))\s+" + _AUTOR
)
AUTOR_INICIAL = re.compile(r"^" + _AUTOR)


def limpiar_asunto(texto, tipo=None):
    """Deja solo el título de la iniciativa dentro del texto de una votación."""
    t = re.sub(r"\s+", " ", _primera_linea(texto))
    t = re.split(r"\s+(?i:se vota)\b", t)[0]
    t = re.sub(r"^(?i:(?:segunda )?votaci[oó]n(?: conjunta)? de (?:la|las|los|el))\s+", "", t)
    t = re.sub(r"^(?i:enmiendas? a la totalidad(?: de devoluci[oó]n| de texto alternativo)?)\s+(?i:al|a la|del|de la)\s+", "", t)
    t = re.sub(
        r"^(?i:solicitud(?:es)?\b.*?\bavocaci[oó]n por el pleno(?: de la c[aá]mara)?"
        r"(?: del debate y votaci[oó]n final| de la deliberaci[oó]n y votaci[oó]n final)?)\s+(?i:del|de la)\s+",
        "", t)
    t = re.sub(r"^(?i:(?:acuerdo de )?tramitaci[oó]n directa y en lectura [uú]nica (?:del|de la))\s+", "", t)
    t = re.sub(r",\s+(?i:presentadas? por|formuladas? por)\s.*$", "", t)
    t = re.sub(r"^(?i:tramitaci[oó]n como proyecto de ley(?: por el procedimiento de urgencia)? del)\s+", "", t)
    t = AUTOR_TRAS_PREFIJO.sub(r"\1 ", t)
    t = AUTOR_INICIAL.sub("", t)
    n = normalizar(t)
    if tipo == "mocion" and not n.startswith("mocion"):
        t = "Moción consecuencia de interpelación urgente " + t
    elif tipo == "pnl" and not n.startswith("proposicion no de ley"):
        t = "Proposición no de Ley " + t
    return t


def _tokens_asunto(texto, tipo=None):
    return set(tokens(limpiar_asunto(texto, tipo)))


class Indice:
    def __init__(self, con, leg):
        self.por_prefijo = defaultdict(list)
        self.rdl = {}
        self.pge = {}
        for r in con.execute(
            "SELECT expediente, prefijo, titulo, fecha_presentacion FROM iniciativa WHERE legislatura=? AND sintetica=0",
            (leg,),
        ):
            toks = _tokens_asunto(r["titulo"])
            self.por_prefijo[r["prefijo"]].append((r["expediente"], toks, r["fecha_presentacion"] or ""))
            n = normalizar(r["titulo"])
            m = RDL_RE.search(n)
            if r["prefijo"] == "130" and m:
                self.rdl[(m.group(1), m.group(2))] = r["expediente"]
            m = PGE_RE.search(n)
            if r["prefijo"] == "121" and m:
                self.pge[m.group(1)] = r["expediente"]

    def buscar(self, toks, prefijos, fecha):
        mejor, puntos = None, 0.0
        for p in prefijos:
            for exp, ct, fpres in self.por_prefijo.get(p, ()):
                if not ct or (fpres and fecha and fpres > fecha):
                    continue
                comun = len(toks & ct)
                if not comun:
                    continue
                precision, recall = comun / len(toks), comun / len(ct)
                dice = 2 * precision * recall / (precision + recall)
                if recall >= 0.9 and precision >= 0.5:
                    dice = max(dice, 0.8)
                # A igual parecido, gana la iniciativa presentada más cerca de la votación.
                if dice > puntos + 1e-9 or (abs(dice - puntos) < 1e-9 and mejor and fpres > mejor[1]):
                    mejor, puntos = (exp, fpres), dice
        return (mejor[0], puntos) if mejor else (None, 0.0)


def _prefijo_sintetico(tipo, texto):
    t = normalizar(texto)
    if t.startswith("proyecto de ley"):
        return "121"
    if t.startswith("proposicion de ley"):
        return "122"
    if t.startswith("real decreto"):
        return "130"
    return {"pnl": "162", "mocion": "173", "tratado": "110", "investidura": "180"}.get(tipo, "SIN")


def enlazar(con, log=print):
    # Las sintéticas se regeneran en cada pasada (su id es un hash estable del texto).
    con.execute(f"DELETE FROM iniciativa WHERE sintetica=1 AND {EN_CONGRESO}")
    creadas = 0
    for leg in sorted(LEGISLATURAS):
        indice = Indice(con, leg)
        filas = con.execute(
            """SELECT id, sesion, fecha, seccion, texto_expediente, titulo_subgrupo, tipo_votacion
               FROM votacion WHERE legislatura=? ORDER BY fecha, sesion, numero""",
            (leg,),
        ).fetchall()
        # PGE: las votaciones por secciones no llevan el título del proyecto; se toma el último
        # proyecto de Presupuestos presentado antes de la votación.
        pge_exps = set(indice.pge.values())
        pges = sorted((f, e) for e, _toks, f in indice.por_prefijo.get("121", ()) if e in pge_exps)

        def pge_vigente(fecha):
            previos = [e for f, e in pges if f <= fecha]
            return previos[-1] if previos else None

        cache = {}
        cambios = []
        for r in filas:
            texto = r["texto_expediente"] or ""
            tipo = r["tipo_votacion"]
            n = normalizar(_primera_linea(texto))
            clave = (n, tipo in ("pnl", "mocion"))
            exp, score, metodo = None, 0.0, None
            m = RDL_RE.search(n)
            if m and (m.group(1), m.group(2)) in indice.rdl and not n.startswith("proyecto de ley"):
                exp, score, metodo = indice.rdl[(m.group(1), m.group(2))], 1.0, "rdl"
            elif (m2 := PGE_RE.search(n)) and m2.group(1) in indice.pge:
                exp, score, metodo = indice.pge[m2.group(1)], 1.0, "pge"
            elif normalizar(r["seccion"]).startswith("presupuestos generales"):
                exp = pge_vigente(r["fecha"])
                if exp:
                    score, metodo = 1.0, "pge_fecha"
            if not exp and clave in cache:
                exp, score, metodo = cache[clave]
            elif not exp:
                prefijos = PREFIJOS_POR_TIPO.get(tipo)
                if not prefijos:
                    if n.startswith(("proyecto de ley", "proposicion de ley", "propuesta de reforma")):
                        prefijos = PREFIJOS_LEY
                    elif tipo in ("conjunto", "enmiendas", "articulado", "totalidad", "enmiendas_senado",
                                  "veto_senado", "organizacion"):
                        prefijos = PREFIJOS_LEY + ["110", "130"]
                    else:
                        prefijos = ["162", "173", "200", "250", "276", "410", "430", "152", "155", "156", "157", "158", "240"]
                toks = _tokens_asunto(texto, tipo)
                if toks:
                    exp, score = indice.buscar(toks, prefijos, r["fecha"])
                    metodo = "titulo"
                if score < 0.72:
                    exp = None
                cache[clave] = (exp, score, metodo)
            if not exp:
                titulo = _primera_linea(texto) or (r["seccion"] or "Asunto sin título")
                exp = "SIN/" + hashlib.sha1(normalizar(titulo).encode()).hexdigest()[:10]
                metodo, score = "sintetica", 0.0
                creadas += con.execute(
                    """INSERT OR IGNORE INTO iniciativa(legislatura, expediente, prefijo, tipo, titulo, titulo_norm,
                         fecha_presentacion, sintetica, fuente)
                       VALUES (?,?,?,?,?,?,?,1,'votacion')""",
                    (leg, exp, _prefijo_sintetico(tipo, titulo), r["seccion"], titulo, normalizar(titulo), r["fecha"]),
                ).rowcount
            cambios.append((exp, metodo, round(score, 3), exp.split("/")[0], r["id"]))
        con.executemany(
            "UPDATE votacion SET expediente=?, enlace_metodo=?, enlace_score=?, prefijo=? WHERE id=?", cambios
        )
        con.commit()
        enlazadas = sum(1 for c in cambios if c[1] != "sintetica")
        log(f"Legislatura {LEGISLATURAS[leg][0]}: {enlazadas}/{len(cambios)} votaciones enlazadas a un expediente")
    log(f"Iniciativas sintéticas creadas: {creadas}")


# ---------------------------------------------------------------- resultado de las iniciativas

def _elegir_decisivas(vs):
    """Qué votación decide cada asunto. Solo las leyes orgánicas tienen votación de conjunto en el
    Congreso; en las ordinarias se toma la toma en consideración o la totalidad (y el resultado
    final lo da el estado oficial de tramitación)."""
    por_tipo = defaultdict(list)
    for v in vs:
        por_tipo[v["tipo_votacion"]].append(v)
    for t in ("conjunto", "convalidacion", "veto_senado"):
        if por_tipo[t]:
            return t, por_tipo[t][-1:]
    for t in ("pnl", "mocion", "tratado", "investidura"):
        if por_tipo[t]:
            return t, por_tipo[t]
    devueltas = [v for v in por_tipo["totalidad"] if v["resultado"] == "aprobada"]
    if devueltas:
        return "totalidad", devueltas[-1:]
    for t in ("toma_consideracion", "totalidad"):
        if por_tipo[t]:
            return t, por_tipo[t][-1:]
    for t in ("control", "nombramiento", "organizacion"):
        if por_tipo[t]:
            return t, por_tipo[t]
    for t in ("enmiendas_senado", "articulado", "tramitacion_ley", "enmiendas", "otro"):
        if por_tipo[t]:
            return t, por_tipo[t][-1:]
    return None, vs[-1:]


def _mapear_oficial(texto):
    t = normalizar(texto)
    if not t:
        return None
    # Sin la vocal final: el Congreso escribe «Aprobado…» y otras fuentes «Aprobada».
    if t.startswith("convalidad"):
        return "convalidada"
    if t.startswith("derogad"):
        return "derogada"
    if t.startswith("aprobad"):
        return "aprobada"
    if t.startswith(("rechazad", "desestimad")):
        return "rechazada"
    if t.startswith(("caducad", "decaid", "trasladad")):
        return "caducada"
    if t.startswith("retirad"):
        return "retirada"
    if t.startswith(("subsumid", "convertid")):
        return "subsumida"
    if t.startswith("inadmitid"):
        return "inadmitida"
    return "otra"


def resultados_iniciativas(con, log=print):
    con.execute(f"UPDATE votacion SET decisiva=0 WHERE {EN_CONGRESO}")
    votos = defaultdict(list)
    for r in con.execute(
        f"SELECT id, legislatura, expediente, tipo_votacion, resultado, fecha, numero FROM votacion WHERE {EN_CONGRESO} ORDER BY fecha, sesion, numero"
    ):
        votos[(r["legislatura"], r["expediente"])].append(r)
    marcadas, finales = [], []
    for (leg, exp), vs in votos.items():
        elegido, decisivas = _elegir_decisivas(vs)
        marcadas.extend((v["id"],) for v in decisivas)
        aprobadas = sum(1 for v in decisivas if v["resultado"] == "aprobada")
        if elegido == "totalidad":
            # Si prospera una enmienda de devolución, la iniciativa muere ahí.
            calc = "rechazada" if aprobadas else "en_tramite"
        elif elegido == "toma_consideracion":
            calc = "en_tramite" if aprobadas else "rechazada"
        elif elegido == "convalidacion":
            calc = "convalidada" if aprobadas else "derogada"
        elif len(decisivas) > 1 and 0 < aprobadas < len(decisivas):
            calc = "aprobada_en_parte"
        else:
            calc = "aprobada" if aprobadas else "rechazada"
        finales.append((calc, leg, exp))
    con.executemany("UPDATE votacion SET decisiva=1 WHERE id=?", marcadas)
    con.execute(f"UPDATE iniciativa SET resultado_final=NULL WHERE {EN_CONGRESO}")
    con.executemany("UPDATE iniciativa SET resultado_final=? WHERE legislatura=? AND expediente=?", finales)
    # El estado oficial de tramitación manda para las leyes (el Pleno no es el último paso).
    for r in con.execute(
        f"SELECT legislatura, expediente, resultado_tramitacion, resultado_final, prefijo FROM iniciativa WHERE resultado_tramitacion IS NOT NULL AND {EN_CONGRESO}"
    ).fetchall():
        oficial = _mapear_oficial(r["resultado_tramitacion"])
        if (r["prefijo"] in PREFIJOS_LEY or r["prefijo"] == "130") and oficial and oficial != "otra":
            con.execute(
                "UPDATE iniciativa SET resultado_final=? WHERE legislatura=? AND expediente=?",
                (oficial, r["legislatura"], r["expediente"]),
            )
    # Contraste con el resultado oficial: si no cuadra, es un dato que hay que revisar a mano.
    con.execute(f"UPDATE votacion SET aviso=NULL WHERE {EN_CONGRESO}")
    con.execute(
        f"""UPDATE votacion SET aviso='Empate: el Reglamento obliga a repetir la votación y, si el empate persiste, se rechaza. '
                  || 'Las repeticiones no siempre están en los datos abiertos.'
           WHERE asentimiento=0 AND mayoria='simple' AND margen=0 AND {EN_CONGRESO}"""
    )
    discrepan = con.execute(
        f"""UPDATE votacion SET aviso=COALESCE(aviso || ' ', '') ||
             'El resultado calculado con los totales no coincide con el oficial de la iniciativa (' ||
             (SELECT i.resultado_tramitacion FROM iniciativa i WHERE i.legislatura=votacion.legislatura
                AND i.expediente=votacion.expediente) || '): revisar.'
           WHERE decisiva=1 AND {EN_CONGRESO} AND (
             (tipo_votacion='convalidacion' AND resultado='rechazada' AND EXISTS (SELECT 1 FROM iniciativa i
                WHERE i.legislatura=votacion.legislatura AND i.expediente=votacion.expediente AND i.resultado_final='convalidada'))
             OR (tipo_votacion='convalidacion' AND resultado='aprobada' AND EXISTS (SELECT 1 FROM iniciativa i
                WHERE i.legislatura=votacion.legislatura AND i.expediente=votacion.expediente AND i.resultado_final='derogada'))
             OR (tipo_votacion='conjunto' AND resultado='rechazada' AND EXISTS (SELECT 1 FROM iniciativa i
                WHERE i.legislatura=votacion.legislatura AND i.expediente=votacion.expediente AND i.resultado_final='aprobada')))"""
    ).rowcount
    con.commit()
    log(f"Votaciones decisivas marcadas: {len(marcadas)} en {len(finales)} iniciativas votadas")
    log(f"Votaciones cuyo resultado calculado no coincide con el oficial (para revisar): {discrepan}")


# ---------------------------------------------------------------- grupos


def grupos_decisivos(con, log=print):
    con.execute(f"DELETE FROM grupo_decisivo WHERE votacion_id IN (SELECT id FROM votacion WHERE {EN_CONGRESO})")
    filas = []
    por_votacion = defaultdict(list)
    for r in con.execute(
        f"""SELECT g.votacion_id, g.grupo, g.si, g.no, g.abstencion FROM voto_grupo g
           JOIN votacion v ON v.id=g.votacion_id WHERE v.asentimiento=0 AND g.grupo NOT IN ('?', '') AND {V_EN_CONGRESO}"""
    ):
        por_votacion[r["votacion_id"]].append(r)
    for v in con.execute(f"SELECT id, a_favor, en_contra, mayoria, resultado FROM votacion WHERE asentimiento=0 AND {EN_CONGRESO}"):
        si, no = v["a_favor"] or 0, v["en_contra"] or 0
        aprobada = v["resultado"] == "aprobada"
        for g in por_votacion.get(v["id"], ()):
            if v["mayoria"] == "absoluta":
                if aprobada and si - g["si"] < MAYORIA_ABSOLUTA_CONGRESO:
                    filas.append((v["id"], g["grupo"], "absteniendose"))
                elif not aprobada and si + g["no"] + g["abstencion"] >= MAYORIA_ABSOLUTA_CONGRESO:
                    filas.append((v["id"], g["grupo"], "cambiando"))
                continue
            if aprobada and g["si"]:
                if si - g["si"] <= no:
                    filas.append((v["id"], g["grupo"], "absteniendose"))
                elif si - g["si"] <= no + g["si"]:
                    filas.append((v["id"], g["grupo"], "cambiando"))
            elif not aprobada:
                if g["no"] and si > no - g["no"]:
                    filas.append((v["id"], g["grupo"], "absteniendose"))
                elif g["no"] + g["abstencion"] and si + g["no"] + g["abstencion"] > no - g["no"]:
                    filas.append((v["id"], g["grupo"], "cambiando"))
    con.executemany("INSERT OR REPLACE INTO grupo_decisivo(votacion_id, grupo, modo) VALUES (?,?,?)", filas)
    con.commit()
    log(f"Grupos decisivos: {len(filas)} casos")


def tabla_grupos(con, log=print):
    con.execute(f"DELETE FROM grupo WHERE {EN_CONGRESO}")
    for leg in sorted(LEGISLATURAS):
        for r in con.execute(
            """SELECT vo.grupo, COUNT(DISTINCT vo.diputado_id) AS n FROM voto vo
               JOIN votacion v ON v.id=vo.votacion_id WHERE v.legislatura=? GROUP BY vo.grupo""",
            (leg,),
        ).fetchall():
            nombre, siglas, color = info_grupo(r["grupo"], leg)
            con.execute(
                "INSERT INTO grupo(legislatura, codigo, nombre, siglas, color, diputados) VALUES (?,?,?,?,?,?)",
                (leg, r["grupo"], nombre, siglas, color, r["n"]),
            )
    con.commit()
    # Autor de las iniciativas -> código de grupo tal como aparece en las votaciones de esa legislatura.
    codigos = defaultdict(set)
    for r in con.execute("SELECT legislatura, codigo FROM grupo"):
        codigos[r["legislatura"]].add(r["codigo"])
    cambios = [
        (grupo_de_autor(r["autor"], r["legislatura"], codigos[r["legislatura"]]), r["legislatura"], r["expediente"])
        for r in con.execute(f"SELECT legislatura, expediente, autor FROM iniciativa WHERE autor IS NOT NULL AND {EN_CONGRESO}")
    ]
    con.executemany("UPDATE iniciativa SET grupo_autor=? WHERE legislatura=? AND expediente=?", cambios)
    con.commit()
    log(f"Grupos por legislatura: {con.execute(f'SELECT COUNT(*) FROM grupo WHERE {EN_CONGRESO}').fetchone()[0]}")


# ---------------------------------------------------------------- enmiendas

_GRUPO_EN_TEXTO = re.compile(r"(?i)\bgrupos?\s+parlamentarios?\b.*$")


def contar_enmiendas(texto):
    """Número de enmiendas que agrupa una votación («Enmiendas 130, 133 y 1010 a 1012» -> 5)."""
    t = normalizar(texto)
    if not t.startswith(("enmienda", "voto particular")) or "resto" in t:
        return None
    n = sum(int(b) - int(a) + 1 for a, b in re.findall(r"\b(\d+) a (\d+)\b", t) if int(b) >= int(a))
    n += len(re.findall(r"\b\d+\b", re.sub(r"\b\d+ a \d+\b", " ", t)))
    return n or 1


def enmiendas(con, log=print):
    """Quién presentó lo que se vota en enmiendas, totalidades y propuestas de resolución (sale del texto
    de la votación). En los debates con propuestas de resolución cada votación es de un grupo, no del
    autor del asunto (el Gobierno que pide el debate, por ejemplo)."""
    codigos = defaultdict(set)
    for r in con.execute("SELECT legislatura, codigo FROM grupo"):
        codigos[r[0]].add(r[1])
    cambios = []
    for r in con.execute(
        f"""SELECT id, legislatura, seccion, tipo_votacion, titulo_subgrupo, texto_subgrupo FROM votacion
           WHERE tipo_votacion IN ('enmiendas', 'enmiendas_senado', 'totalidad', 'control') AND {EN_CONGRESO}"""
    ).fetchall():
        sg, ts = (r["titulo_subgrupo"] or "").strip(), (r["texto_subgrupo"] or "").strip()
        nsg, nts = normalizar(sg), normalizar(ts)
        grupo = autor = None
        if r["tipo_votacion"] == "enmiendas_senado" or nsg.startswith("enmiendas del senado"):
            grupo = "Senado"
        elif nsg.startswith("enmiendas transaccionales") or (not sg and nts.startswith("enmienda transaccional")):
            grupo = "Transaccional"
        else:
            for texto in (sg, ts):
                m = _GRUPO_EN_TEXTO.search(texto)
                if m and any(k in normalizar(texto) for k in ("enmienda", "propuesta", "voto particular", "votos particulares")):
                    autor = m.group(0).strip(" .")
                    grupo = grupo_de_autor(autor, r["legislatura"], codigos[r["legislatura"]])
                    break
            # «Se votan de forma conjunta las enmiendas de devolución presentadas por los Grupos X, Y y Z»
            if not grupo and "grupos" in nts:
                grupo = "Varios"
        trans = int("transaccional" in nsg or "transaccional" in nts) if r["tipo_votacion"] != "control" else None
        cambios.append((grupo, autor, contar_enmiendas(ts), trans, r["id"]))
    con.execute(f"UPDATE votacion SET enmienda_grupo=NULL, enmienda_autor=NULL, enmiendas_n=NULL, transaccional=NULL WHERE {EN_CONGRESO}")
    con.executemany(
        "UPDATE votacion SET enmienda_grupo=?, enmienda_autor=?, enmiendas_n=?, transaccional=? WHERE id=?", cambios
    )
    con.commit()
    con_grupo = sum(1 for c in cambios if c[0])
    log(f"Votaciones de enmiendas y propuestas con autor identificado: {con_grupo}/{len(cambios)}")


# ---------------------------------------------------------------- orquestación


TIPOS_LLM = LLM_DIR / "tipos_votacion.jsonl"


def tipos_llm():
    """Tipos de votación decididos por un LLM cuando las reglas no bastaban (fichero versionado)."""
    if not TIPOS_LLM.exists():
        return {}
    out = {}
    for linea in TIPOS_LLM.read_text(encoding="utf-8").splitlines():
        if linea.strip():
            d = json.loads(linea)
            if d.get("tipo") in TIPOS_VOTACION:
                out[(d["legislatura"], d["fecha"], d["sesion"], d["numero"])] = d["tipo"]
    return out


def clasificar(con, log=print):
    decididos = tipos_llm()
    cambios = []
    for r in con.execute(
        f"""SELECT id, legislatura, fecha, sesion, numero, seccion, texto_expediente, titulo_subgrupo, texto_subgrupo,
                  asentimiento, a_favor, en_contra FROM votacion WHERE {EN_CONGRESO}"""
    ):
        clave = (r["legislatura"], r["fecha"], r["sesion"], r["numero"])
        if clave in decididos:
            tipo, fuente = decididos[clave], "llm"
        else:
            tipo, fuente = tipo_votacion(r["seccion"], r["texto_expediente"], r["titulo_subgrupo"], r["texto_subgrupo"]), "regla"
        mayoria = mayoria_requerida(tipo, r["texto_expediente"], r["texto_subgrupo"])
        res, margen = resultado(r["asentimiento"], r["a_favor"], r["en_contra"], mayoria)
        cambios.append((tipo, fuente, mayoria, res, margen, r["id"]))
    con.executemany(
        "UPDATE votacion SET tipo_votacion=?, tipo_votacion_fuente=?, mayoria=?, resultado=?, margen=? WHERE id=?",
        cambios,
    )
    con.commit()
    otros = con.execute(f"SELECT COUNT(*) FROM votacion WHERE tipo_votacion='otro' AND {EN_CONGRESO}").fetchone()[0]
    log(f"Votaciones clasificadas: {len(cambios)} ({otros} sin tipo claro por reglas)")


def procesar(con, log=print):
    clasificar(con, log)
    tabla_grupos(con, log)
    enlazar(con, log)
    resultados_iniciativas(con, log)
    grupos_decisivos(con, log)
    enmiendas(con, log)
    from .tema_provisional import calcular as tema_provisional

    tema_provisional(con, log)


def estado(con, log=print):
    q = lambda sql: con.execute(sql).fetchall()
    for r in q("""SELECT legislatura, COUNT(*) n, MIN(fecha) desde, MAX(fecha) hasta,
                  SUM(expediente NOT LIKE 'SIN/%') enlazadas FROM votacion GROUP BY legislatura"""):
        log(f"Leg {r['legislatura']}: {r['n']} votaciones ({r['desde']} a {r['hasta']}), {r['enlazadas']} enlazadas")
    log(f"Votos individuales: {q('SELECT COUNT(*) FROM voto')[0][0]}")
    log(f"Iniciativas: {q('SELECT COUNT(*) FROM iniciativa')[0][0]} (votadas: {q('SELECT COUNT(DISTINCT legislatura||expediente) FROM votacion')[0][0]})")
    log(f"Fichas IA: {q('SELECT COUNT(*) FROM ficha_llm')[0][0]}")
    for r in q("SELECT tipo_votacion, COUNT(*) FROM votacion GROUP BY 1 ORDER BY 2 DESC"):
        log(f"  {r[0]}: {r[1]}")
