"""Procesado determinista de las votaciones territoriales (sin IA).

Lo mismo que procesar.py hace para el Congreso, pero sin depender de sus prefijos ni de sus 350
escaños: tipo de votación, mayoría y resultado (el oficial si la fuente lo da; si no, calculado con
los totales), votación decisiva y resultado de cada iniciativa, tamaño de los grupos, grupo autor y
grupos decisivos. Solo toca legislaturas territoriales (id >= 100; el Congreso usa 10 a 15).
"""

from collections import defaultdict

from ..procesar import _elegir_decisivas, _mapear_oficial, tipo_votacion
from ..texto import normalizar
from .partidos import codigo_grupo

EN_TERRITORIAL = "legislatura >= 100"


def tipo_territorial(prefijo, titulo, subtitulo):
    """Tipo de votación a partir del tipo de iniciativa y de los textos."""
    t, s = normalizar(titulo), normalizar(subtitulo)
    todo = f"{t} {s}"
    if prefijo == "pnl" or t.startswith("proposicion no de ley"):
        return "pnl"
    if prefijo == "mocion" or t.startswith("mocion"):
        return "mocion"
    if prefijo == "investidura" or "investidura" in todo or "mocion de censura" in todo or "cuestion de confianza" in todo:
        return "investidura"
    if prefijo == "dl" or ("decreto ley" in t and "convalidacion" in todo):
        return "tramitacion_ley" if "tramitacion como proyecto" in todo else "convalidacion"
    if prefijo in ("pl", "ppl", "ilp", "presupuesto", "ordenanza") or t.startswith(("proyecto de ley", "proposicion de ley")):
        if "toma en consideracion" in todo:
            return "toma_consideracion"
        if "totalidad" in todo or "devolucion" in todo:
            return "totalidad"
        if "enmienda" in s or "voto particular" in s or "votos particulares" in s:
            return "enmiendas"
        if any(k in s for k in ("articulo", "disposicion", "anexo", "exposicion de motivos", "seccion")):
            return "articulado"
        if prefijo in ("presupuesto", "ordenanza") or "conjunto" in todo or "votacion final" in todo or "dictamen" in todo or not s:
            return "conjunto"
        return "articulado"
    if prefijo == "organizacion":
        return "nombramiento" if any(k in t for k in ("eleccion", "designacion", "nombramiento")) else "organizacion"
    if prefijo == "control":
        return "control"
    if prefijo == "acuerdo":
        # Propuestas de acuerdo y dictámenes municipales: decisión final sobre el asunto.
        return "conjunto"
    tipo = tipo_votacion("", titulo, subtitulo, "")
    return tipo


def _resultado(asentimiento, a_favor, en_contra, mayoria, umbral):
    if asentimiento:
        return "aprobada", None
    if a_favor is None:
        return None, None
    en_contra = en_contra or 0
    if mayoria == "absoluta":
        return ("aprobada" if a_favor >= umbral else "rechazada"), a_favor - umbral
    margen = a_favor - en_contra
    return ("aprobada" if margen > 0 else "rechazada"), margen


def clasificar(con, log=print):
    umbral = {r[0]: (r[1] or 0) // 2 + 1 for r in con.execute(f"SELECT id, escanos FROM legislatura WHERE id >= 100")}
    cambios, avisos = [], 0
    for r in con.execute(
        f"""SELECT id, legislatura, prefijo, texto_expediente, titulo_subgrupo, tipo_votacion, tipo_votacion_fuente,
                   mayoria, asentimiento, a_favor, en_contra, resultado_oficial FROM votacion WHERE {EN_TERRITORIAL}"""
    ):
        tipo, fuente = r["tipo_votacion"], r["tipo_votacion_fuente"]
        if fuente != "fuente" or not tipo:
            tipo, fuente = tipo_territorial(r["prefijo"], r["texto_expediente"], r["titulo_subgrupo"]), "regla"
        mayoria = r["mayoria"] or "simple"
        calc, margen = _resultado(r["asentimiento"], r["a_favor"], r["en_contra"], mayoria, umbral.get(r["legislatura"], 0))
        oficial = r["resultado_oficial"]
        aviso = None
        # Un empate que la fuente da por aprobado es el voto de calidad (alcaldía, presidencia): no es un error.
        empate = r["a_favor"] is not None and r["a_favor"] == (r["en_contra"] or 0)
        if oficial and calc and oficial != calc and not r["asentimiento"] and not empate:
            aviso = (f"La fuente da la votación por {oficial} y con los totales publicados saldría {calc} "
                     "(puede ser una mayoría cualificada o un error en los totales): revisar.")
            avisos += 1
        cambios.append((tipo, fuente, mayoria, oficial or calc, margen, aviso, r["id"]))
    con.executemany(
        "UPDATE votacion SET tipo_votacion=?, tipo_votacion_fuente=?, mayoria=?, resultado=?, margen=?, aviso=? WHERE id=?",
        cambios)
    con.commit()
    log(f"Territorial: {len(cambios)} votaciones clasificadas; {avisos} con resultado oficial distinto del calculado")


def resultados_iniciativas(con, log=print):
    con.execute(f"UPDATE votacion SET decisiva=0 WHERE {EN_TERRITORIAL}")
    votos = defaultdict(list)
    for r in con.execute(
        f"""SELECT id, legislatura, expediente, tipo_votacion, resultado, fecha, numero FROM votacion
            WHERE {EN_TERRITORIAL} ORDER BY fecha, sesion, numero"""
    ):
        votos[(r["legislatura"], r["expediente"])].append(r)
    marcadas, finales = [], []
    for (leg, exp), vs in votos.items():
        elegido, decisivas = _elegir_decisivas(vs)
        marcadas.extend((v["id"],) for v in decisivas)
        aprobadas = sum(1 for v in decisivas if v["resultado"] == "aprobada")
        conocidas = sum(1 for v in decisivas if v["resultado"])
        if not conocidas:
            calc = None
        elif elegido == "totalidad":
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
    con.execute(f"UPDATE iniciativa SET resultado_final=NULL WHERE {EN_TERRITORIAL}")
    con.executemany("UPDATE iniciativa SET resultado_final=? WHERE legislatura=? AND expediente=?", finales)
    # Resultado oficial de tramitación (catálogo de la fuente) para las leyes.
    for r in con.execute(
        f"""SELECT i.legislatura, i.expediente, i.resultado_tramitacion FROM iniciativa i
            JOIN tipo_expediente t ON t.prefijo=i.prefijo
            WHERE i.resultado_tramitacion IS NOT NULL AND t.familia IN ('ley', 'decreto_ley') AND i.{EN_TERRITORIAL}"""
    ).fetchall():
        oficial = _mapear_oficial(r["resultado_tramitacion"])
        if oficial and oficial != "otra":
            con.execute("UPDATE iniciativa SET resultado_final=? WHERE legislatura=? AND expediente=?",
                        (oficial, r["legislatura"], r["expediente"]))
    con.commit()
    log(f"Territorial: {len(marcadas)} votaciones decisivas en {len(finales)} asuntos")


def grupos(con, log=print):
    """Tamaño de cada grupo (el máximo que llega a votar, o los diputados distintos si hay voto nominal)."""
    con.execute(
        f"""UPDATE grupo SET diputados = COALESCE(
              (SELECT COUNT(DISTINCT vo.diputado_id) FROM voto vo JOIN votacion v ON v.id=vo.votacion_id
               WHERE v.legislatura=grupo.legislatura AND vo.grupo=grupo.codigo),
              0)
            WHERE {EN_TERRITORIAL}""")
    con.execute(
        f"""UPDATE grupo SET diputados = (
              SELECT MAX(g.si + g.no + g.abstencion + g.no_vota) FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
              WHERE v.legislatura=grupo.legislatura AND g.grupo=grupo.codigo)
            WHERE {EN_TERRITORIAL} AND diputados = 0""")
    # Grupos que no llegan a aparecer en ninguna votación (nombres mal escritos en la fuente…).
    con.execute(
        f"""DELETE FROM grupo WHERE {EN_TERRITORIAL} AND NOT EXISTS (
              SELECT 1 FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
              WHERE v.legislatura=grupo.legislatura AND g.grupo=grupo.codigo)""")
    # Autor de la iniciativa -> código de grupo de esa legislatura.
    codigos = defaultdict(set)
    for r in con.execute(f"SELECT legislatura, codigo FROM grupo WHERE {EN_TERRITORIAL}"):
        codigos[r[0]].add(r[1])
    cambios = []
    for r in con.execute(f"SELECT legislatura, expediente, autor FROM iniciativa WHERE {EN_TERRITORIAL} AND autor IS NOT NULL"):
        a = normalizar(r["autor"])
        codigo = codigo_grupo(r["autor"])[0]
        if codigo in codigos[r["legislatura"]]:
            g = codigo
        elif any(k in a for k in ("gobierno", "consejo de gobierno", "consell", "junta de gobierno", "alcald", "diputacion foral")):
            g = "Gobierno"
        elif "iniciativa legislativa popular" in a or "comision promotora" in a:
            g = "ILP"
        elif "grupos" in a or "," in r["autor"] or " y " in a:
            g = "Varios"
        else:
            g = None
        cambios.append((g, r["legislatura"], r["expediente"]))
    con.executemany("UPDATE iniciativa SET grupo_autor=? WHERE legislatura=? AND expediente=?", cambios)
    con.commit()
    log(f"Territorial: {con.execute(f'SELECT COUNT(*) FROM grupo WHERE {EN_TERRITORIAL}').fetchone()[0]} grupos")


def grupos_decisivos(con, log=print):
    """Grupos cuyo voto cambiaba el resultado (solo donde se conoce el recuento por grupo)."""
    con.execute(f"DELETE FROM grupo_decisivo WHERE votacion_id IN (SELECT id FROM votacion WHERE {EN_TERRITORIAL})")
    umbral = {r[0]: (r[1] or 0) // 2 + 1 for r in con.execute("SELECT id, escanos FROM legislatura WHERE id >= 100")}
    por_votacion = defaultdict(list)
    for r in con.execute(
        f"""SELECT g.votacion_id, g.grupo, g.si, g.no, g.abstencion FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
            WHERE v.asentimiento=0 AND v.{EN_TERRITORIAL} AND g.grupo NOT IN ('?', '') AND g.si + g.no + g.abstencion > 0"""
    ):
        por_votacion[r["votacion_id"]].append(r)
    filas = []
    for v in con.execute(
        f"""SELECT id, legislatura, a_favor, en_contra, mayoria, resultado FROM votacion
            WHERE asentimiento=0 AND {EN_TERRITORIAL} AND a_favor IS NOT NULL AND resultado IS NOT NULL
              AND aviso IS NULL"""  # con aviso, los totales no son de fiar
    ):
        si, no = v["a_favor"] or 0, v["en_contra"] or 0
        aprobada = v["resultado"] == "aprobada"
        mayoria = umbral.get(v["legislatura"], 0)
        for g in por_votacion.get(v["id"], ()):
            if v["mayoria"] == "absoluta":
                if aprobada and si - g["si"] < mayoria:
                    filas.append((v["id"], g["grupo"], "absteniendose"))
                elif not aprobada and si + g["no"] + g["abstencion"] >= mayoria:
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
    log(f"Territorial: {len(filas)} casos de grupo decisivo")


def procesar(con, log=print):
    clasificar(con, log)
    resultados_iniciativas(con, log)
    grupos(con, log)
    grupos_decisivos(con, log)
