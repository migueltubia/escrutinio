"""Agregados que se precalculan porque son caros de hacer en cada petición."""

from .texto import es_debate_general

# Votaciones «de fondo»: se excluyen enmiendas parciales y trámites internos, que inflarían
# la afinidad con cientos de votaciones de Presupuestos.
TIPOS_FONDO = ("pnl", "mocion", "toma_consideracion", "totalidad", "conjunto", "convalidacion",
               "tramitacion_ley", "tratado", "enmiendas_senado", "veto_senado", "investidura", "control")


def debates_generales(con):
    """Asuntos votados que son debates de política general (texto.es_debate_general): (legislatura, expediente)."""
    return {(r[0], r[1]) for r in con.execute(
        """SELECT i.legislatura, i.expediente, i.titulo FROM iniciativa i
           WHERE EXISTS (SELECT 1 FROM votacion v WHERE v.legislatura=i.legislatura AND v.expediente=i.expediente)"""
    ) if es_debate_general(r[2])}


def afinidad(con, log=print):
    con.execute("DELETE FROM afinidad")
    marcas = ",".join("?" * len(TIPOS_FONDO))
    # Las propuestas de resolución de los debates de política general no tienen el tema del debate:
    # cuentan en la afinidad global, pero en ningún tema.
    con.execute("DROP TABLE IF EXISTS temp.debate_general")
    con.execute("CREATE TEMP TABLE debate_general(legislatura INTEGER, expediente TEXT, PRIMARY KEY(legislatura, expediente))")
    con.executemany("INSERT INTO temp.debate_general VALUES (?,?)", sorted(debates_generales(con)))
    con.execute("DROP TABLE IF EXISTS temp.base")
    con.execute(
        f"""CREATE TEMP TABLE base AS
            SELECT v.id, v.legislatura, CASE WHEN dg.expediente IS NULL THEN COALESCE(f.tema_principal, '?') ELSE '?' END AS tema,
                   g.grupo, g.sentido
            FROM votacion v
            JOIN voto_grupo g ON g.votacion_id = v.id
            LEFT JOIN ficha_llm f ON f.legislatura = v.legislatura AND f.expediente = v.expediente
            LEFT JOIN temp.debate_general dg ON dg.legislatura = v.legislatura AND dg.expediente = v.expediente
            WHERE v.asentimiento = 0 AND v.tipo_votacion IN ({marcas})
              AND g.sentido IN ('si', 'no', 'abstencion') AND g.grupo NOT IN ('?', '')""",
        TIPOS_FONDO,
    )
    con.execute("CREATE INDEX temp.ix_base ON base(id)")
    con.execute(
        """INSERT INTO afinidad(legislatura, tema, grupo_a, grupo_b, coinciden, total)
           SELECT a.legislatura, a.tema, a.grupo, b.grupo, SUM(a.sentido = b.sentido), COUNT(*)
           FROM base a JOIN base b ON a.id = b.id AND a.grupo <> b.grupo
           GROUP BY a.legislatura, a.tema, a.grupo, b.grupo"""
    )
    con.execute(
        """INSERT INTO afinidad(legislatura, tema, grupo_a, grupo_b, coinciden, total)
           SELECT legislatura, '*', grupo_a, grupo_b, SUM(coinciden), SUM(total)
           FROM afinidad GROUP BY legislatura, grupo_a, grupo_b"""
    )
    con.commit()
    log(f"Afinidades calculadas: {con.execute('SELECT COUNT(*) FROM afinidad').fetchone()[0]} pares")


def analizar(con, log=print):
    afinidad(con, log)


def importar_informe(con, ruta, modelo, log=print):
    """Guarda un informe en Markdown: cada sección «## Título» es una entrada de informe_ia."""
    import re
    from datetime import datetime, timezone
    from pathlib import Path

    texto = Path(ruta).read_text(encoding="utf-8")
    partes = re.split(r"^## +(.+)$", texto, flags=re.M)
    secciones = [(f"{n:02d}", partes[i].strip(), partes[i + 1].strip(), modelo)
                 for n, i in enumerate(range(1, len(partes), 2), 1)]
    previas = [tuple(r) for r in con.execute("SELECT clave, titulo, contenido, modelo FROM informe_ia ORDER BY clave")]
    if previas == secciones:
        log(f"Informe sin cambios: {len(secciones)} secciones")
        return
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    con.execute("DELETE FROM informe_ia")
    con.executemany("INSERT INTO informe_ia(clave, titulo, contenido, modelo, creado) VALUES (?,?,?,?,?)",
                    [(*s, ahora) for s in secciones])
    con.commit()
    log(f"Informe importado: {len(partes) // 2} secciones")
