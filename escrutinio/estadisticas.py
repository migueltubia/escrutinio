"""Resumen estadístico en texto: es la entrada con la que la IA redacta el informe de análisis.

Todo lo que se imprime sale de SQL sobre los datos oficiales y las fichas; la IA solo lo interpreta.
"""

import json
from collections import Counter, defaultdict

from .analisis import TIPOS_FONDO
from .catalogos import TEMAS
from .config import LEGISLATURAS
from .llm.etiquetas import canonicas, leyes_canonicas
from .texto import info_grupo

TEMA = dict((c, n) for c, n, _ in TEMAS)
SALE = ("aprobada", "aprobada_en_parte", "convalidada")


def _siglas(codigo, leg):
    return info_grupo(codigo, leg)[1]


def imprimir(con, log=print):
    q = lambda sql, *a: con.execute(sql, a).fetchall()
    for leg, (rom, ini, fin) in LEGISLATURAS.items():
        n = q("SELECT COUNT(*) FROM votacion WHERE legislatura=?", leg)[0][0]
        if n < 100:
            continue
        log(f"\n=== Legislatura {rom} ({ini} a {fin or 'hoy'}): {n} votaciones")
        for r in q(
            """SELECT te.familia, COUNT(*) n, SUM(i.resultado_final IN ('aprobada','aprobada_en_parte','convalidada')) ok,
                      SUM(i.resultado_final IN ('rechazada','derogada')) ko
               FROM iniciativa i JOIN (SELECT DISTINCT legislatura, expediente FROM votacion) vv USING (legislatura, expediente)
               LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo WHERE i.legislatura=? GROUP BY 1 ORDER BY 2 DESC""",
            leg,
        ):
            log(f"  {r['familia']}: {r['n']} votadas, {r['ok']} salen, {r['ko']} rechazadas")
        # Éxito por proponente (PNL, mociones y proposiciones de ley de grupos).
        filas = q(
            """SELECT i.grupo_autor g, te.familia f, COUNT(*) n,
                      SUM(i.resultado_final IN ('aprobada','aprobada_en_parte','convalidada')) ok
               FROM iniciativa i JOIN (SELECT DISTINCT legislatura, expediente FROM votacion) vv USING (legislatura, expediente)
               JOIN tipo_expediente te ON te.prefijo=i.prefijo
               WHERE i.legislatura=? AND te.familia IN ('pnl','mocion','ley') AND i.grupo_autor IS NOT NULL
                 AND i.resultado_final IN ('aprobada','aprobada_en_parte','convalidada','rechazada','derogada')
               GROUP BY 1, 2 HAVING n >= 5 ORDER BY 1, 2""",
            leg,
        )
        log("  Éxito por proponente (votadas con resultado): " + "; ".join(
            f"{_siglas(r['g'], leg)} {r['f']} {r['ok']}/{r['n']}" for r in filas))
        # Ajustadas y grupo decisivo.
        aj = q("SELECT COUNT(*) FROM votacion WHERE legislatura=? AND decisiva=1 AND asentimiento=0 AND ABS(margen)<=5", leg)[0][0]
        log(f"  Votaciones decisivas por 5 votos o menos: {aj}")
        dec = q(
            """SELECT d.grupo, COUNT(*) n FROM grupo_decisivo d JOIN votacion v ON v.id=d.votacion_id
               WHERE v.legislatura=? AND v.decisiva=1 AND d.modo='absteniendose' GROUP BY 1 ORDER BY 2 DESC""",
            leg,
        )
        log("  Decisivo con solo abstenerse (nº votaciones decisivas): " + ", ".join(f"{_siglas(r['grupo'], leg)} {r['n']}" for r in dec))
        # Afinidad global.
        af = q(
            """SELECT grupo_a, grupo_b, coinciden, total FROM afinidad
               WHERE legislatura=? AND tema='*' AND grupo_a < grupo_b AND total >= 30 AND grupo_a<>'?' AND grupo_b<>'?'""",
            leg,
        )
        af = sorted(af, key=lambda r: r["coinciden"] / r["total"], reverse=True)
        fmt = lambda r: f"{_siglas(r['grupo_a'], leg)}-{_siglas(r['grupo_b'], leg)} {round(100 * r['coinciden'] / r['total'])}%"
        log("  Afinidad más alta: " + ", ".join(fmt(r) for r in af[:6]))
        log("  Afinidad más baja: " + ", ".join(fmt(r) for r in af[-6:]))
        # Pares cuya afinidad cambia mucho según el tema.
        por_tema = q(
            """SELECT grupo_a, grupo_b, tema, coinciden, total FROM afinidad
               WHERE legislatura=? AND tema NOT IN ('*','?') AND grupo_a < grupo_b AND total >= 15""",
            leg,
        )
        rango = defaultdict(list)
        for r in por_tema:
            rango[(r["grupo_a"], r["grupo_b"])].append((r["coinciden"] / r["total"], r["tema"], r["total"]))
        difs = sorted(((max(v)[0] - min(v)[0], k, max(v), min(v)) for k, v in rango.items() if len(v) >= 4), reverse=True)[:6]
        for d, (a, b), hi, lo in difs:
            log(f"  {_siglas(a, leg)}-{_siglas(b, leg)}: {round(100 * hi[0])}% en {TEMA[hi[1]]} (n={hi[2]}) frente a {round(100 * lo[0])}% en {TEMA[lo[1]]} (n={lo[2]})")
        # Cohesión: votaciones de fondo en que al menos un 10% del grupo (y 2 o más diputados)
        # se separa del voto mayoritario. Un solo voto distinto suele ser un error al pulsar.
        coh = q(
            f"""SELECT grupo, COUNT(*) n,
                       SUM((si+no+abstencion) - MAX(si, no, abstencion) >= MAX(2, 0.1*(si+no+abstencion))) div
                FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
                WHERE v.legislatura=? AND v.asentimiento=0 AND v.tipo_votacion IN ({','.join('?' * len(TIPOS_FONDO))})
                GROUP BY 1 HAVING n > 50""",
            leg, *TIPOS_FONDO,
        )
        log("  Votaciones de fondo con el grupo partido (>=10% en contra de su mayoría): " + ", ".join(
            f"{_siglas(r['grupo'], leg)} {round(100 * r['div'] / r['n'], 1)}%" for r in sorted(coh, key=lambda r: -r["div"] / r["n"]) if r["grupo"] != "?"))
        # Temas y etiquetas.
        temas = q(
            """SELECT f.tema_principal t, COUNT(*) n FROM ficha_llm f WHERE f.legislatura=? GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", leg)
        log("  Temas más votados: " + ", ".join(f"{TEMA.get(r['t'], r['t'])} {r['n']}" for r in temas))
        et = Counter()
        for r in q(
            """SELECT f.etiquetas FROM ficha_llm f JOIN (SELECT DISTINCT legislatura, expediente FROM votacion) vv
               USING (legislatura, expediente) WHERE f.legislatura=?""",
            leg,
        ):
            et.update(canonicas(json.loads(r["etiquetas"] or "[]")))
        log("  Etiquetas más frecuentes: " + ", ".join(f"{e} {c}" for e, c in et.most_common(20)))
        em = q("SELECT COUNT(*) FROM ficha_llm WHERE legislatura=? AND marcas LIKE '%emergencia%'", leg)[0][0]
        om = q("SELECT COUNT(*) FROM ficha_llm WHERE legislatura=? AND marcas LIKE '%omnibus%'", leg)[0][0]
        log(f"  Asuntos marcados emergencia: {em}; ómnibus: {om}")

    log("\n=== Todas las legislaturas: éxito por tema")
    for r in q(
        """SELECT f.tema_principal t,
                  SUM(te.familia IN ('ley','decreto_ley')) leyes,
                  SUM(te.familia IN ('ley','decreto_ley') AND i.resultado_final IN ('aprobada','aprobada_en_parte','convalidada')) leyes_ok,
                  SUM(te.familia IN ('pnl','mocion')) decl,
                  SUM(te.familia IN ('pnl','mocion') AND i.resultado_final IN ('aprobada','aprobada_en_parte')) decl_ok
           FROM ficha_llm f JOIN iniciativa i USING (legislatura, expediente)
           LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo WHERE f.legislatura < 100
           GROUP BY 1 ORDER BY leyes + decl DESC"""
    ):
        log(f"  {TEMA.get(r['t'], r['t'])}: leyes/decretos {r['leyes_ok']}/{r['leyes']}; PNL+mociones {r['decl_ok']}/{r['decl']}")

    log("\n=== Leyes más citadas como afectadas")
    leyes = Counter()
    for r in q(
        """SELECT f.leyes_afectadas FROM ficha_llm f
           JOIN (SELECT DISTINCT legislatura, expediente FROM votacion) vv USING (legislatura, expediente)
           WHERE f.legislatura < 100"""
    ):
        leyes.update(leyes_canonicas(json.loads(r["leyes_afectadas"] or "[]")))
    for ley, n in leyes.most_common(15):
        log(f"  {n} × {ley}")

    log("\n=== Diputados que más veces votaron distinto a su grupo (votaciones de fondo)")
    for r in q(
        f"""SELECT d.nombre, v.legislatura, vo.grupo, COUNT(*) n FROM voto vo
            JOIN votacion v ON v.id=vo.votacion_id JOIN diputado d ON d.id=vo.diputado_id
            JOIN voto_grupo g ON g.votacion_id=vo.votacion_id AND g.grupo=vo.grupo
            WHERE v.tipo_votacion IN ({','.join('?' * len(TIPOS_FONDO))}) AND v.asentimiento=0 AND v.legislatura < 100
              AND vo.sentido IN ('si','no','abstencion') AND g.sentido IN ('si','no','abstencion')
              AND vo.sentido<>g.sentido AND vo.grupo NOT IN ('GMx','GPlu','?')
            GROUP BY 1, 2, 3 ORDER BY 4 DESC LIMIT 15""",
        *TIPOS_FONDO,
    ):
        log(f"  {r['nombre']} ({_siglas(r['grupo'], r['legislatura'])}, Leg. {LEGISLATURAS[r['legislatura']][0]}): {r['n']}")
