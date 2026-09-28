"""Catálogo de iniciativas del Congreso.

- Buscador de iniciativas (endpoint JSON de la web): expediente, título, autor y resultado
  para todas las legislaturas y todos los tipos que se votan en el Pleno.
- Datos abiertos de iniciativas legislativas (solo legislatura actual): situación, tramitación
  y enlaces al BOCG, que se guardan en extra_json.
"""

import gzip
import json
import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .catalogos import PREFIJOS_BUSCADOR
from .config import BUSCADOR_INICIATIVAS_URL, CONGRESO, LEGISLATURAS, RAW_DIR
from .http_util import fetch
from .texto import grupo_de_autor, normalizar

POR_PAGINA = 25


def _pagina(leg, prefijo, pagina):
    raw = fetch(
        BUSCADOR_INICIATIVAS_URL,
        data={
            "_iniciativas_legislatura": str(leg),
            "_iniciativas_tipo": prefijo,
            "_iniciativas_paginaActual": str(pagina),
        },
    )
    return json.loads(raw.decode("utf-8"))


def _fecha(texto):
    try:
        return datetime.strptime((texto or "").strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def catalogo(leg, prefijo, workers=4):
    ruta = RAW_DIR / "iniciativas" / f"Leg{leg}" / f"{prefijo}.json.gz"
    if ruta.exists():
        return json.loads(gzip.decompress(ruta.read_bytes()))
    primera = _pagina(leg, prefijo, 1)
    total = int(primera.get("iniciativas_encontradas") or 0)
    items = list((primera.get("lista_iniciativas") or {}).values())
    paginas = math.ceil(total / POR_PAGINA)
    if paginas > 1:
        with ThreadPoolExecutor(workers) as ex:
            for d in ex.map(lambda n: _pagina(leg, prefijo, n), range(2, paginas + 1)):
                items.extend((d.get("lista_iniciativas") or {}).values())
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(gzip.compress(json.dumps(items, ensure_ascii=False).encode()))
    return items


def _guardar(con, leg, items):
    filas = []
    for it in items:
        exp = (it.get("id_iniciativa") or "").strip()
        if not exp:
            continue
        titulo = (it.get("titulo") or "").strip()
        autor = (it.get("autor") or "").strip()
        filas.append(
            (
                leg,
                exp,
                exp.split("/")[0],
                (it.get("tipo") or "").strip().rstrip("."),
                titulo,
                normalizar(titulo),
                autor,
                grupo_de_autor(autor, leg),
                _fecha(it.get("fecha_presentado")),
                _fecha(it.get("fecha_calificado")),
                (it.get("resultado_tram") or "").strip() or None,
            )
        )
    con.executemany(
        """INSERT INTO iniciativa(legislatura, expediente, prefijo, tipo, titulo, titulo_norm, autor, grupo_autor,
             fecha_presentacion, fecha_calificacion, resultado_tramitacion, fuente)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,'buscador')
           ON CONFLICT(legislatura, expediente) DO UPDATE SET
             prefijo=excluded.prefijo, tipo=excluded.tipo, titulo=excluded.titulo, titulo_norm=excluded.titulo_norm,
             autor=excluded.autor, grupo_autor=excluded.grupo_autor, fecha_presentacion=excluded.fecha_presentacion,
             fecha_calificacion=excluded.fecha_calificacion, resultado_tramitacion=excluded.resultado_tramitacion,
             sintetica=0, fuente='buscador'""",
        filas,
    )
    return len(filas)


def enriquecer_opendata(con, log=print):
    """Añade situación, tramitación y enlaces BOCG de la legislatura actual (datos abiertos)."""
    html = fetch(CONGRESO + "/es/opendata/iniciativas").decode("utf-8", "replace")
    urls = sorted(set(re.findall(r"/webpublica/opendata/iniciativas/[A-Za-z]+__\d+\.json", html)))
    n = 0
    for u in urls:
        datos = json.loads(fetch(CONGRESO + u).decode("utf-8-sig"))
        for it in datos:
            leg = int(re.sub(r"\D", "", it.get("LEGISLATURA", "")) or 0)
            exp = "/".join((it.get("NUMEXPEDIENTE") or "").split("/")[:2])
            if not leg or not exp:
                continue
            extra = {
                k: it.get(k)
                for k in ("TIPOTRAMITACION", "COMISIONCOMPETENTE", "TRAMITACIONSEGUIDA", "ENLACESBOCG",
                          "ENLACESBOE", "INICIATIVASRELACIONADAS", "RESULTADOTRAMITACION", "SITUACIONACTUAL",
                          "PLAZOS", "FECHAPRESENTACION", "FECHACALIFICACION")
                if it.get(k)
            }
            n += con.execute(
                """UPDATE iniciativa SET situacion=?, extra_json=?,
                     resultado_tramitacion=COALESCE(resultado_tramitacion, ?)
                   WHERE legislatura=? AND expediente=?""",
                (
                    (it.get("SITUACIONACTUAL") or "").strip() or None,
                    json.dumps(extra, ensure_ascii=False),
                    (it.get("RESULTADOTRAMITACION") or "").strip() or None,
                    leg,
                    exp,
                ),
            ).rowcount
        con.commit()
    log(f"Datos abiertos de iniciativas: {n} iniciativas enriquecidas")


def descargar(con, legislaturas, workers=4, log=print):
    for leg in legislaturas:
        total = 0
        for prefijo in PREFIJOS_BUSCADOR:
            try:
                items = catalogo(leg, prefijo, workers)
            except Exception as e:
                log(f"  ! Leg {leg} {prefijo}: {e}")
                continue
            total += _guardar(con, leg, items)
            con.commit()
        log(f"Legislatura {LEGISLATURAS[leg][0]}: {total} iniciativas")
    enriquecer_opendata(con, log)
