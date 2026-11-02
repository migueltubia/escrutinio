"""Antecedentes de las promesas de unas elecciones por celebrar: lo que se votó antes sobre lo mismo (sin IA).

Un programa se cruza con las votaciones de la legislatura que empieza tras su elección. Antes de votar todavía
no hay legislatura, así que sus promesas se cruzan con las votaciones de legislaturas anteriores, de dos maneras y
sin LLM:

1. Herencia: si la promesa es casi igual a una de un programa anterior, de cualquier partido (mismo tema, mismo
   tipo de medida, verbos que no se oponen y la mayor parte de las palabras en común en los dos sentidos), se toman
   las iniciativas que ya se relacionaron con aquella y su dirección (en la línea de la promesa o en contra), que sí
   se decidió en su día.
2. Parecidas: las iniciativas votadas más parecidas de las últimas legislaturas (BM25 sobre su ficha, con el mismo
   tema), sin dirección: tratan el mismo asunto. Se dejan fuera las que tocan de todo (los Presupuestos, los
   objetivos de estabilidad, las votaciones sin expediente), que se parecen a cualquier promesa económica.

Van a compromiso_iniciativa con estado «antecedente» y origen «heredado» o «parecido». No cuentan para el estado
de la promesa ni salen en la ficha de la iniciativa: en la web se muestran aparte, avisando de que son relaciones
automáticas, sin analizar una a una. Se recalculan en cada carga (es rápido) y dejan de calcularse en cuanto la
legislatura de la elección empieza y el cruce normal toma el relevo.
"""

import json

from .emparejar import Indice, _raices

LEGISLATURAS = 2  # las últimas con fichas en las que se buscan iniciativas parecidas
PARECIDAS = 2  # como mucho, por promesa
# Para heredar: palabras en común sobre la promesa más corta y sobre la más larga, y cuántas como mínimo. Con solo la
# primera, una promesa corta («Recuperar el delito de referéndum ilegal en el Código Penal») casaba con cualquier
# otra sobre el Código Penal.
MIN_PARECIDO, MIN_PARECIDO_LARGA, MIN_COMUNES = 0.6, 0.35, 3
MIN_PUNTOS = 0.75  # BM25 de una parecida, relativo a la mejor de la promesa
MIN_PUNTOS_ABS = 10.0  # y en absoluto: por debajo, coincidencias sueltas de palabras corrientes
# Verbos que dicen lo contrario: con ellos no se hereda la dirección aunque el resto de la frase coincida.
OPUESTOS = [{"prohibir", "permitir", "autorizar", "legalizar"}, {"bajar", "subir", "reducir", "rebajar", "aumentar",
            "incrementar", "elevar"}, {"eliminar", "suprimir", "derogar", "crear", "aprobar", "introducir", "implantar"}]
GENERICAS = ("presupuestos generales del estado", "objetivos de estabilidad", "techo de gasto")


def _verbo(texto):
    return (texto or "").split(" ", 1)[0].lower()


def _hereda(a, b, verbo_a, verbo_b):
    """Si dos promesas son casi la misma: (parecido, sí o no)."""
    comunes = len(a & b)
    if not a or not b or comunes < MIN_COMUNES:
        return 0.0, False
    if verbo_a != verbo_b and any(verbo_a in g and verbo_b in g for g in OPUESTOS):
        return 0.0, False
    corta, larga = comunes / min(len(a), len(b)), comunes / max(len(a), len(b))
    return corta, corta >= MIN_PARECIDO and larga >= MIN_PARECIDO_LARGA


def calcular(con, log=print):
    """Rellena los antecedentes de las promesas concretas de los programas sin legislatura. Devuelve cuántos."""
    con.execute("DELETE FROM compromiso_iniciativa WHERE estado='antecedente'")
    futuras = con.execute(
        """SELECT c.id, c.texto, c.tema, c.tipo_accion, c.etiquetas, p.cuerpo, p.partido
           FROM compromiso c JOIN programa p ON p.id=c.programa
           WHERE p.legislatura IS NULL AND p.estado='leido' AND c.verificable=1""").fetchall()
    if not futuras:
        return 0
    # Promesas anteriores con alguna iniciativa relacionada en una dirección: las únicas que se pueden heredar.
    anteriores = {}
    for r in con.execute(
            """SELECT c.id, c.texto, c.tema, c.tipo_accion, p.partido, p.eleccion, ci.legislatura, ci.expediente, ci.sentido
               FROM compromiso c JOIN programa p ON p.id=c.programa
               JOIN compromiso_iniciativa ci ON ci.compromiso=c.id
               WHERE p.legislatura IS NOT NULL AND ci.estado<>'rechazado' AND ci.sentido IN ('misma','contraria')"""):
        a = anteriores.setdefault(r["id"], {"texto": r["texto"], "tema": r["tema"], "accion": r["tipo_accion"],
                                            "verbo": _verbo(r["texto"]), "raices": set(_raices(r["texto"])),
                                            "origen": f"{r['partido']}, {r['eleccion']}", "pares": []})
        a["pares"].append((r["legislatura"], r["expediente"], r["sentido"]))
    por_tema = {}
    for a in anteriores.values():
        por_tema.setdefault(a["tema"], []).append(a)

    legs = [r[0] for r in con.execute(
        """SELECT l.id FROM legislatura l WHERE l.cuerpo=? AND EXISTS
             (SELECT 1 FROM ficha_llm f WHERE f.legislatura=l.id AND f.resumen IS NOT NULL)
           ORDER BY l.inicio DESC LIMIT ?""", (futuras[0]["cuerpo"], LEGISLATURAS))]
    indices = [Indice(con, leg) for leg in legs]
    votadas = {f"{r[0]}:{r[1]}" for r in con.execute(
        f"SELECT DISTINCT legislatura, expediente FROM votacion WHERE decisiva=1 AND legislatura IN ({','.join('?' * len(legs))})",
        legs)} if legs else set()

    filas = {}
    heredadas = parecidas = 0
    for c in futuras:
        raices, verbo = set(_raices(c["texto"])), _verbo(c["texto"])
        # 1. Herencia: la promesa anterior más parecida que cumpla todas las condiciones.
        opciones = [(p, a) for a in por_tema.get(c["tema"], []) if a["accion"] == c["tipo_accion"]
                    for p, vale in [_hereda(raices, a["raices"], verbo, a["verbo"])] if vale]
        if opciones:
            a = max(opciones, key=lambda x: x[0])[1]
            for leg, exp, sentido in a["pares"]:
                if (c["id"], leg, exp) not in filas:
                    filas[(c["id"], leg, exp)] = (sentido, f"Heredada de una promesa parecida ({a['origen']}): «{a['texto']}»",
                                                  "heredado")
                    heredadas += 1
        # 2. Parecidas: las mejores de las últimas legislaturas, ya votadas.
        consulta = c["texto"] + " " + " ".join(json.loads(c["etiquetas"] or "[]"))
        candidatas = sorted(((s, d) for ind in indices for s, d in ind.buscar(consulta, c["tema"], k=PARECIDAS * 3)
                             if d["id"] in votadas and d["tipo"] != "Asunto sin expediente identificado"
                             and not any(g in d["titulo"].lower() for g in GENERICAS)), key=lambda x: -x[0])
        tope = candidatas[0][0] if candidatas else 0
        for s, d in candidatas[:PARECIDAS]:
            leg, exp = d["id"].split(":", 1)
            clave = (c["id"], int(leg), exp)
            if s >= max(MIN_PUNTOS * tope, MIN_PUNTOS_ABS) and clave not in filas:
                filas[clave] = ("relacionada", None, "parecido")
                parecidas += 1
    con.executemany(
        """INSERT INTO compromiso_iniciativa(compromiso, legislatura, expediente, sentido, justificacion, origen, estado)
           VALUES (?,?,?,?,?,?,'antecedente')""",
        [(cid, leg, exp, sentido, just, origen) for (cid, leg, exp), (sentido, just, origen) in filas.items()])
    con.commit()
    log(f"Antecedentes de las promesas de elecciones por celebrar: {heredadas} heredados y {parecidas} parecidos "
        f"({len(futuras)} promesas concretas)")
    return heredadas + parecidas
