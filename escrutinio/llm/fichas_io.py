"""Intercambio de fichas IA en JSONL.

`exportar` escribe lotes de iniciativas votadas que aún no tienen ficha (o la tienen con otra
versión del prompt). Cualquier LLM puede procesarlos siguiendo data/llm/INSTRUCCIONES.md y
escribir un JSONL de fichas, que `importar` valida contra la lista cerrada de temas y guarda
en ficha_llm con el modelo y la versión del prompt.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import LLM_DIR
from .prompt import FICHA_SCHEMA, SYSTEM, VERSION_PROMPT, VERSION_TAXONOMIA, validar


def _contexto_leg(con):
    """id de legislatura -> datos que acompañan a cada iniciativa: legislatura y, fuera del Congreso, cámara."""
    out = {}
    for r in con.execute("SELECT l.id, l.romano, l.cuerpo, c.nombre FROM legislatura l LEFT JOIN cuerpo c ON c.codigo=l.cuerpo"):
        out[r[0]] = {"legislatura": r[1]} if r[2] == "congreso" else {"legislatura": r[1], "camara": r[3] or r[2]}
    return out


def items_en_tramite(con):
    """Iniciativas legislativas abiertas (datos abiertos de la legislatura actual) sin ficha IA."""
    items, legs = [], _contexto_leg(con)
    for r in con.execute(
        """SELECT i.legislatura, i.expediente, i.titulo, i.autor, i.extra_json, i.fecha_presentacion,
                  COALESCE(t.nombre, i.tipo) AS tipo
           FROM iniciativa i
           LEFT JOIN tipo_expediente t ON t.prefijo=i.prefijo
           LEFT JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
           WHERE i.situacion IS NOT NULL AND i.situacion <> 'Cerrado' AND f.expediente IS NULL
           ORDER BY i.legislatura DESC, i.fecha_presentacion DESC"""
    ):
        extra = json.loads(r["extra_json"] or "{}")
        item = {"id": f"{r['legislatura']}:{r['expediente']}", **legs.get(r["legislatura"], {}),
                "fecha": r["fecha_presentacion"], "tipo": r["tipo"], "autor": r["autor"], "titulo": r["titulo"]}
        if extra.get("COMISIONCOMPETENTE"):
            item["comision"] = extra["COMISIONCOMPETENTE"].strip()
        items.append(item)
    return items


def items_pendientes(con, prefijos=None, limite=None):
    sql = """
      SELECT i.legislatura, i.expediente, i.prefijo, i.titulo, i.autor, i.extra_json,
             COALESCE(t.nombre, i.tipo) AS tipo, MIN(v.fecha) AS fecha,
             GROUP_CONCAT(DISTINCT substr(v.texto_expediente, 1, 400)) AS textos
      FROM iniciativa i
      JOIN votacion v ON v.legislatura=i.legislatura AND v.expediente=i.expediente
      LEFT JOIN tipo_expediente t ON t.prefijo=i.prefijo
      LEFT JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
      WHERE (f.expediente IS NULL OR f.version_prompt <> ?)
    """
    args = [VERSION_PROMPT]
    if prefijos:
        sql += f" AND i.prefijo IN ({','.join('?' * len(prefijos))})"
        args += prefijos
    # Primero el Congreso (lo nuevo de cada semana) y después el atraso territorial (legislaturas >= 100).
    sql += " GROUP BY i.legislatura, i.expediente ORDER BY i.legislatura >= 100, i.legislatura DESC, fecha DESC"
    if limite:
        sql += f" LIMIT {int(limite)}"
    items, legs = [], _contexto_leg(con)
    for r in con.execute(sql, args):
        item = {
            "id": f"{r['legislatura']}:{r['expediente']}",
            **legs.get(r["legislatura"], {}),
            "fecha": r["fecha"],
            "tipo": r["tipo"],
            "autor": r["autor"],
            "titulo": r["titulo"],
        }
        textos = [t.split("\n")[0].strip() for t in (r["textos"] or "").split(",") if t.strip()]
        otros = [t for t in dict.fromkeys(textos) if t and t != r["titulo"] and len(t) > 25][:2]
        if otros and r["expediente"].startswith("SIN/"):
            item["texto_votado"] = otros
        if r["extra_json"]:
            extra = json.loads(r["extra_json"])
            if isinstance(extra, dict) and extra.get("COMISIONCOMPETENTE"):
                item["comision"] = extra["COMISIONCOMPETENTE"].strip()
        items.append(item)
    return items


def escribir_instrucciones():
    LLM_DIR.mkdir(parents=True, exist_ok=True)
    ruta = LLM_DIR / "INSTRUCCIONES.md"
    ruta.write_text(
        f"# Instrucciones para generar fichas ({VERSION_PROMPT}, {VERSION_TAXONOMIA})\n\n"
        f"{SYSTEM}\n\n"
        "## Entrada\n\nCada línea de un lote `pendientes/lote_NNNN.jsonl` es una iniciativa con `id`, "
        "`legislatura`, `fecha`, `tipo`, `autor`, `titulo` y, a veces, `comision` o `texto_votado`.\n\n"
        "## Salida\n\nUn fichero `resultados/lote_NNNN.jsonl` con una línea JSON por iniciativa, "
        "con el mismo `id` y exactamente este esquema:\n\n```json\n"
        + json.dumps(FICHA_SCHEMA, ensure_ascii=False, indent=1)
        + "\n```\n",
        encoding="utf-8",
    )
    return ruta


def exportar(con, tam=250, prefijos=None, en_tramite=False, log=print):
    items = items_en_tramite(con) if en_tramite else items_pendientes(con, prefijos)
    carpeta = LLM_DIR / "pendientes"
    carpeta.mkdir(parents=True, exist_ok=True)
    for f in carpeta.glob("lote_*.jsonl"):
        f.unlink()
    n = 0
    for i in range(0, len(items), tam):
        n += 1
        with open(carpeta / f"lote_{n:04d}.jsonl", "w", encoding="utf-8") as fh:
            for it in items[i : i + tam]:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    escribir_instrucciones()
    log(f"{len(items)} iniciativas pendientes en {n} lotes en {carpeta}")


def guardar_fichas(con, fichas, modelo, fuente_texto="titulo"):
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok, malas = 0, []
    for f in fichas:
        ficha, errores = validar(f)
        if not ficha:
            malas.append((f.get("id") if isinstance(f, dict) else None, errores))
            continue
        leg, exp = ficha["id"].split(":", 1)
        valores = (
            ficha["resumen"].strip(),
            json.dumps(ficha["bloques"], ensure_ascii=False),
            ficha["tema_principal"],
            json.dumps(ficha["temas_secundarios"]),
            json.dumps(ficha["etiquetas"], ensure_ascii=False),
            ficha["ambito"],
            json.dumps(ficha["marcas"]),
            json.dumps(ficha["leyes_afectadas"], ensure_ascii=False),
            ficha["confianza"], fuente_texto, modelo, VERSION_PROMPT, VERSION_TAXONOMIA,
        )
        # Si ya está igual, no se toca (así no cambia la fecha ni los ficheros troceados).
        previa = con.execute(
            """SELECT resumen, bloques, tema_principal, temas_secundarios, etiquetas, ambito, marcas, leyes_afectadas,
                      confianza, fuente_texto, modelo, version_prompt, version_taxonomia
               FROM ficha_llm WHERE legislatura=? AND expediente=?""",
            (int(leg), exp),
        ).fetchone()
        if previa is None or tuple(previa) != valores:
            con.execute(
                """INSERT OR REPLACE INTO ficha_llm(legislatura, expediente, resumen, bloques, tema_principal,
                     temas_secundarios, etiquetas, ambito, marcas, leyes_afectadas, confianza, fuente_texto,
                     modelo, version_prompt, version_taxonomia, creado)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (int(leg), exp, *valores, ahora),
            )
        ok += 1
    con.commit()
    return ok, malas


def validar_lote(numero, log=print):
    """Comprueba los resultados de un lote: JSON válido, esquema, ids completos y sin sobrantes."""
    lote = LLM_DIR / "pendientes" / f"lote_{int(numero):04d}.jsonl"
    esperados = [json.loads(l)["id"] for l in lote.read_text(encoding="utf-8").splitlines() if l.strip()]
    vistos, problemas = {}, []
    for ruta in sorted((LLM_DIR / "resultados").glob(f"lote_{int(numero):04d}*.jsonl")):
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if not linea.strip():
                continue
            try:
                f = json.loads(linea)
            except json.JSONDecodeError as e:
                problemas.append(f"{ruta.name}:{n} JSON inválido: {e}")
                continue
            ficha, errores = validar(dict(f))
            if errores:
                problemas.append(f"{ruta.name}:{n} ({f.get('id')}): {'; '.join(errores)}")
            if not f.get("resumen", "").strip():
                problemas.append(f"{ruta.name}:{n} ({f.get('id')}): resumen vacío")
            vistos[f.get("id")] = vistos.get(f.get("id"), 0) + 1
    faltan = [i for i in esperados if i not in vistos]
    sobran = [i for i in vistos if i not in esperados]
    repetidos = [i for i, c in vistos.items() if c > 1]
    log(f"Lote {int(numero):04d}: {len(esperados)} esperadas, {len(vistos)} distintas escritas")
    log(f"  faltan: {len(faltan)} {faltan[:10]}")
    log(f"  sobran: {len(sobran)} {sobran[:10]}")
    log(f"  repetidas: {len(repetidos)} {repetidos[:10]}")
    log(f"  errores: {len(problemas)}")
    for p in problemas[:30]:
        log(f"    {p}")
    return not (faltan or sobran or problemas)


def _leer_jsonl(ruta, errores):
    fichas = []
    for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
        linea = linea.strip()
        if not linea:
            continue
        try:
            fichas.append(json.loads(linea))
        except json.JSONDecodeError as e:
            errores.append((f"{ruta.name}:{n}", [str(e)]))
    return fichas


def _guardar_por_modelo(con, fichas, modelo_defecto):
    """Cada línea puede traer su propio «_modelo» (así lo escribe el generador automático)."""
    grupos = {}
    for f in fichas:
        m = f.pop("_modelo", None) if isinstance(f, dict) else None
        grupos.setdefault(m or modelo_defecto, []).append(f)
    ok, malas = 0, []
    for modelo, fs in grupos.items():
        o, m = guardar_fichas(con, fs, modelo or "desconocido")
        ok += o
        malas += m
    return ok, malas


def importar(con, ficheros, modelo=None, log=print):
    total, errores = 0, []
    for patron in ficheros:
        rutas = sorted(Path().glob(patron)) if any(c in patron for c in "*?") else [Path(patron)]
        for ruta in rutas:
            ok, malas = _guardar_por_modelo(con, _leer_jsonl(ruta, errores), modelo)
            total += ok
            errores += malas
    log(f"Fichas importadas: {total}; con errores: {len(errores)}")
    for e in errores[:20]:
        log(f"  ! {e}")


def importar_todo(con, log=print):
    """Carga en la base de datos todas las fichas guardadas en el repositorio (data/llm/resultados).

    Las fichas son la fuente de verdad de la parte IA: la base de datos se puede reconstruir desde
    cero y recuperar todo lo que ya se generó. modelos.json dice qué modelo generó cada carpeta o
    fichero cuando las líneas no lo llevan dentro. Se cargan en orden, así que lo más reciente gana.
    """
    raiz = LLM_DIR / "resultados"
    mapa = json.loads((raiz / "modelos.json").read_text(encoding="utf-8")) if (raiz / "modelos.json").exists() else {}
    total, errores = 0, []
    for ruta in sorted(raiz.rglob("*.jsonl")):
        rel = ruta.relative_to(raiz).as_posix()
        modelo = mapa.get(rel) or next((m for pre, m in sorted(mapa.items(), key=lambda kv: -len(kv[0])) if rel.startswith(pre)), None)
        ok, malas = _guardar_por_modelo(con, _leer_jsonl(ruta, errores), modelo)
        total += ok
        errores += malas
    log(f"Fichas cargadas desde el repositorio: {total}; con errores: {len(errores)}")
    for e in errores[:10]:
        log(f"  ! {e}")
