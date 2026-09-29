"""Tablas de programas y compromisos desde data/llm/programas/, y estado de cada compromiso.

Todo se reconstruye desde los JSONL (registro, compromisos, emparejamientos y verificaciones), como
las fichas, así que no hace falta guardarlo en data/bd/. Todo es automático: las relaciones con dirección
(misma o contraria) de la primera pasada se revisan en una segunda más exigente (verificar.py), que manda
sobre la primera; mientras no se ha revisado, cuenta la primera.

El estado de cada compromiso se calcula con reglas a partir del sentido de cada iniciativa respecto al
compromiso y del apoyo del partido en su votación decisiva (con las enmiendas a la totalidad
invertidas, como en el resto de Escrutinio): apoyar algo en la misma dirección o rechazar algo en la
contraria es coherente; lo inverso, incoherente. Se recalcula en cada actualización, así que cuando se
vota algo relacionado el estado cambia solo, sin volver a leer nada.
"""

import json

from ..analisis import TIPOS_FONDO
from ..gobiernos import GOBIERNOS
from . import registro
from .emparejar import _legislatura, leer_emparejamientos
from .leer import leer_compromisos
from .verificar import leer_verificaciones

SALE = ("aprobada", "aprobada_en_parte", "convalidada")
# Estados en el orden en que se enseñan.
ESTADOS = ("impulsado", "apoyado", "mixto", "contradicho", "abstencion", "sin_votacion", "fuera_parlamento", "generico")


def en_gobierno(cuerpo, partido, fecha):
    for c, desde, hasta, _pres, p, socios in GOBIERNOS:
        if c == cuerpo and desde <= fecha and (not hasta or fecha <= hasta):
            return partido == p or partido in [s.strip() for s in socios.split(",")]
    return False


def _posicion(con, leg, exp, siglas):
    """Apoyo del partido a la iniciativa en sus votaciones decisivas de fondo: si, no, abstencion o None.

    Con varias votaciones decisivas (una PNL votada por puntos), si apoyó unas y rechazó otras queda en
    abstención (ni coherente ni incoherente). Lo aprobado por asentimiento cuenta como apoyo de todos.
    """
    marcas = ",".join("?" * len(TIPOS_FONDO))
    apoyos = set()
    for r in con.execute(
        f"""SELECT v.tipo_votacion, v.asentimiento, g.sentido FROM votacion v
            LEFT JOIN (SELECT g.votacion_id, g.sentido FROM voto_grupo g
                       JOIN grupo gr ON gr.legislatura=? AND gr.codigo=g.grupo WHERE gr.siglas=?) g ON g.votacion_id=v.id
            WHERE v.legislatura=? AND v.expediente=? AND v.decisiva=1 AND v.tipo_votacion IN ({marcas})""",
        (leg, siglas, leg, exp, *TIPOS_FONDO)):
        sentido = "si" if r["asentimiento"] else r["sentido"]
        if r["tipo_votacion"] == "totalidad" and sentido in ("si", "no"):
            sentido = "no" if sentido == "si" else "si"
        if sentido in ("si", "no", "abstencion", "dividido"):
            apoyos.add(sentido)
    if not apoyos:
        return None
    if apoyos <= {"si", "abstencion"} and "si" in apoyos:
        return "si"
    if apoyos <= {"no", "abstencion"} and "no" in apoyos:
        return "no"
    return "abstencion"


def cargar(con, log=print):
    for t in ("programa", "compromiso", "compromiso_iniciativa", "compromiso_estado"):
        con.execute(f"DELETE FROM {t}")
    entradas = registro.vigentes(registro.leer_registro())
    pares = leer_emparejamientos()
    verificaciones = leer_verificaciones()
    n_comp = n_pares = 0
    for e in entradas:
        leg = _legislatura(con, e)
        con.execute(
            """INSERT INTO programa(id, eleccion, fecha_eleccion, cuerpo, legislatura, partido, titulo, origen, url, url_oficial,
                 descargado, paginas, estado, leido, version_prompt, compromisos, verificables, formato)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (e["id"], e["eleccion"], e["fecha_eleccion"], e["cuerpo"], leg, e["partido"], e["titulo"], e["origen"], e["url"],
             e.get("url_oficial"), e["descargado"], e.get("paginas"), e["estado"], e.get("leido"), e.get("version_prompt"),
             e.get("compromisos"), e.get("verificables"), e.get("formato", "pdf")))
        if e["estado"] != "leido":
            continue
        compromisos = leer_compromisos(e["id"])
        con.executemany(
            """INSERT INTO compromiso(id, programa, orden, texto, cita, pagina, tema, etiquetas, tipo_accion, responsable, verificable)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [(c["id"], e["id"], k, c["texto"], c["cita"], c["pagina"], c["tema"], json.dumps(c["etiquetas"], ensure_ascii=False),
              c["tipo_accion"], c["responsable"], int(c["verificable"])) for k, c in enumerate(compromisos, 1)])
        n_comp += len(compromisos)
        ids = {c["id"] for c in compromisos}
        # Lo que no es «ninguna»; si la segunda revisión ya ha visto el par, manda la suya.
        filas = {}
        for (cid, ini), p in pares.items():
            if cid not in ids:
                continue
            fila = [p["relacion"], p.get("justificacion"), "llm", "propuesto", p.get("rango")]
            v = verificaciones.get((cid, ini))
            if v and v["antes"] == p["relacion"]:
                fila[0], fila[1], fila[3] = v["relacion"], v.get("justificacion") or fila[1], "verificado"
            if fila[0] != "ninguna":
                filas[(cid, ini)] = fila
        for (cid, ini), (sentido, just, origen, estado, rango) in filas.items():
            leg_i, exp = ini.split(":", 1)
            if con.execute("SELECT 1 FROM iniciativa WHERE legislatura=? AND expediente=?", (int(leg_i), exp)).fetchone():
                con.execute("INSERT INTO compromiso_iniciativa VALUES (?,?,?,?,?,?,?,?)",
                            (cid, int(leg_i), exp, sentido, just, origen, estado, rango))
                n_pares += 1
        calcular(con, e, leg, compromisos)
    con.commit()
    if entradas:
        log(f"Programas: {len(entradas)} ({sum(e['estado'] == 'leido' for e in entradas)} leídos), "
            f"{n_comp} compromisos y {n_pares} iniciativas relacionadas")


def calcular(con, e, leg, compromisos):
    """Estado de cada compromiso de un programa según lo que votó el partido (tabla compromiso_estado)."""
    partido, cuerpo = e["partido"], e["cuerpo"]
    for c in compromisos:
        if not c["verificable"]:
            con.execute("INSERT INTO compromiso_estado(compromiso, partido, legislatura, estado) VALUES (?,?,?,?)",
                        (c["id"], partido, leg, "generico"))
            continue
        impulsa = coherentes = incoherentes = abstenciones = aprobada = 0
        gobierno = set()
        hay = False
        for r in con.execute(
            """SELECT ci.legislatura, ci.expediente, ci.sentido, i.resultado_final, i.fecha_presentacion, te.familia,
                      CASE WHEN i.grupo_autor='Gobierno' THEN 'Gobierno' ELSE gr.siglas END AS autor,
                      (SELECT MIN(fecha) FROM votacion v WHERE v.legislatura=i.legislatura AND v.expediente=i.expediente) AS fecha
               FROM compromiso_iniciativa ci
               JOIN iniciativa i ON i.legislatura=ci.legislatura AND i.expediente=ci.expediente
               LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
               LEFT JOIN grupo gr ON gr.legislatura=i.legislatura AND gr.codigo=i.grupo_autor
               WHERE ci.compromiso=? AND ci.estado<>'rechazado' AND ci.sentido IN ('misma','contraria')""", (c["id"],)):
            # Lo que depende del Gobierno o de otra Administración solo se comprueba en el Pleno con los decretos-leyes,
            # que se convalidan.
            if c["responsable"] != "parlamento" and r["familia"] != "decreto_ley":
                continue
            hay = True
            fecha = r["fecha"] or r["fecha_presentacion"] or ""
            gob = en_gobierno(cuerpo, partido, fecha) if fecha else False
            # Presentado por el partido o, si gobernaba, por el Gobierno.
            if r["sentido"] == "misma" and (r["autor"] == partido or (r["autor"] == "Gobierno" and gob)):
                impulsa += 1
            pos = _posicion(con, r["legislatura"], r["expediente"], partido)
            if pos:
                gobierno.add(gob)
                coherente = (pos == "si") == (r["sentido"] == "misma")
                if pos == "abstencion":
                    abstenciones += 1
                elif coherente:
                    coherentes += 1
                else:
                    incoherentes += 1
            if r["sentido"] == "misma" and r["resultado_final"] in SALE:
                aprobada = 1
        if not hay:
            estado = "fuera_parlamento" if c["responsable"] != "parlamento" else "sin_votacion"
        elif incoherentes and (coherentes or impulsa):
            estado = "mixto"
        elif incoherentes:
            estado = "contradicho"
        elif impulsa:
            estado = "impulsado"
        elif coherentes:
            estado = "apoyado"
        elif abstenciones:
            estado = "abstencion"
        else:
            estado = "sin_votacion"
        con.execute(
            """INSERT INTO compromiso_estado(compromiso, partido, legislatura, estado, impulsa, coherentes, incoherentes,
                 abstenciones, aprobada, gobierno) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (c["id"], partido, leg, estado, impulsa, coherentes, incoherentes, abstenciones, aprobada,
             None if len(gobierno) != 1 else int(gobierno.pop())))
