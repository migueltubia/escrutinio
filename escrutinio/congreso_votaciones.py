"""Descarga de votaciones del Pleno del Congreso (datos abiertos) a SQLite.

Flujo: página de la legislatura -> lista de días con votaciones (diasVotaciones)
-> página de cada día -> enlaces a los JSON de cada votación -> descarga y carga.
"""

import gzip
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from .config import CONGRESO, LEGISLATURAS, RAW_DIR, VOTACIONES_URL
from .http_util import fetch

DIAS_RE = re.compile(r"diasVotaciones\s*=\s*\[([^\]]*)\]")
JSON_RE = re.compile(
    r"/webpublica/opendata/votaciones/Leg(\d+)/Sesion(\d+)/(\d{8})/Votacion(\d+)/[^\"'\s]+?\.json"
)

SENTIDOS = {"sí": "si", "si": "si", "no": "no", "abstención": "abstencion", "abstencion": "abstencion", "no vota": "no_vota"}


def _url_legislatura(leg):
    romano = LEGISLATURAS[leg][0]
    return (
        f"{VOTACIONES_URL}?p_p_id=votaciones&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view"
        f"&targetLegislatura={romano}"
    )


def listar_dias(leg):
    html = fetch(_url_legislatura(leg)).decode("utf-8", "replace")
    m = DIAS_RE.search(html)
    if not m:
        return []
    dias = sorted({d for d in re.findall(r"\d{8}", m.group(1))})
    return [f"{d[:4]}-{d[4:6]}-{d[6:]}" for d in dias]


def urls_dia(leg, fecha):
    y, m, d = fecha.split("-")
    html = fetch(_url_legislatura(leg) + f"&targetDate={d}/{m}/{y}").decode("utf-8", "replace")
    compacta = f"{y}{m}{d}"
    vistos = {}
    for match in JSON_RE.finditer(html):
        lg, ses, dia, num = match.groups()
        if int(lg) != leg or dia != compacta:
            continue
        vistos.setdefault((int(ses), int(num)), CONGRESO + match.group(0))
    return [vistos[k] for k in sorted(vistos)]


def _fecha_iso(texto):
    return datetime.strptime(texto.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")


def _ruta_raw(url):
    m = JSON_RE.search(url)
    lg, ses, dia, num = m.groups()
    return RAW_DIR / "votaciones" / f"Leg{lg}" / dia / f"Sesion{int(ses):03d}_Votacion{int(num):03d}.json.gz"


def descargar_json(url):
    ruta = _ruta_raw(url)
    if ruta.exists():
        return url, gzip.decompress(ruta.read_bytes())
    raw = fetch(url)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(gzip.compress(raw))
    return url, raw


def _sentido_grupo(si, no, abst):
    votos = {"si": si, "no": no, "abstencion": abst}
    orden = sorted(votos.items(), key=lambda kv: kv[1], reverse=True)
    if orden[0][1] == 0:
        return None
    if orden[0][1] == orden[1][1]:
        return "dividido"
    return orden[0][0]


class Cargador:
    def __init__(self, con):
        self.con = con
        self.dip = {r["nombre"]: r["id"] for r in con.execute("SELECT id, nombre FROM diputado WHERE cuerpo='congreso'")}

    def diputado_id(self, nombre):
        if nombre not in self.dip:
            cur = self.con.execute("INSERT INTO diputado(nombre, cuerpo) VALUES (?, 'congreso')", (nombre,))
            self.dip[nombre] = cur.lastrowid
        return self.dip[nombre]

    def guardar(self, leg, url, raw):
        d = json.loads(raw.decode("utf-8-sig"))
        info, tot = d["informacion"], d["totales"]
        m = JSON_RE.search(url)
        fecha = _fecha_iso(info["fecha"]) if info.get("fecha") else None
        if not fecha:
            dia = m.group(3)
            fecha = f"{dia[:4]}-{dia[4:6]}-{dia[6:]}"
        fila = (
            leg,
            int(info.get("sesion") or m.group(2)),
            int(info.get("numeroVotacion") or m.group(4)),
            fecha,
            (info.get("titulo") or "").strip(),
            (info.get("textoExpediente") or "").strip(),
            (info.get("tituloSubGrupo") or "").strip(),
            (info.get("textoSubGrupo") or "").strip(),
            json.dumps(info.get("votacionesConjuntas") or [], ensure_ascii=False),
            1 if str(tot.get("asentimiento", "")).lower().startswith("s") else 0,
            tot.get("presentes"),
            tot.get("afavor"),
            tot.get("enContra"),
            tot.get("abstenciones"),
            tot.get("noVotan"),
            url,
        )
        cur = self.con.execute(
            """INSERT INTO votacion(legislatura, sesion, numero, fecha, seccion, texto_expediente,
                 titulo_subgrupo, texto_subgrupo, votaciones_conjuntas, asentimiento, presentes,
                 a_favor, en_contra, abstenciones, no_votan, url)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(legislatura, fecha, sesion, numero) DO UPDATE SET url=excluded.url
               RETURNING id""",
            fila,
        )
        vid = cur.fetchone()[0]
        self.con.execute("DELETE FROM voto WHERE votacion_id=?", (vid,))
        self.con.execute("DELETE FROM voto_grupo WHERE votacion_id=?", (vid,))
        grupos = {}
        filas = []
        for v in d.get("votaciones") or []:
            sentido = SENTIDOS.get((v.get("voto") or "").strip().lower(), "no_vota")
            grupo = (v.get("grupo") or "").strip() or "?"
            nombre = (v.get("diputado") or "").strip()
            if not nombre:
                continue
            filas.append((vid, self.diputado_id(nombre), grupo, sentido, v.get("asiento")))
            g = grupos.setdefault(grupo, {"si": 0, "no": 0, "abstencion": 0, "no_vota": 0})
            g[sentido] += 1
        self.con.executemany(
            "INSERT OR REPLACE INTO voto(votacion_id, diputado_id, grupo, sentido, asiento) VALUES (?,?,?,?,?)",
            filas,
        )
        self.con.executemany(
            "INSERT INTO voto_grupo(votacion_id, grupo, si, no, abstencion, no_vota, sentido) VALUES (?,?,?,?,?,?,?)",
            [
                (vid, g, c["si"], c["no"], c["abstencion"], c["no_vota"], _sentido_grupo(c["si"], c["no"], c["abstencion"]))
                for g, c in grupos.items()
            ],
        )
        return vid


def descargar(con, legislaturas, workers=6, log=print):
    cargador = Cargador(con)
    for leg in legislaturas:
        dias = listar_dias(leg)
        log(f"Legislatura {LEGISLATURAS[leg][0]}: {len(dias)} días con votaciones")
        con.executemany(
            "INSERT OR IGNORE INTO dia_pleno(legislatura, fecha) VALUES (?,?)", [(leg, f) for f in dias]
        )
        con.commit()
        pendientes = [
            r["fecha"]
            for r in con.execute(
                "SELECT fecha FROM dia_pleno WHERE legislatura=? AND urls_json IS NULL ORDER BY fecha", (leg,)
            )
        ]
        with ThreadPoolExecutor(workers) as ex:
            futs = {ex.submit(urls_dia, leg, f): f for f in pendientes}
            for i, fut in enumerate(as_completed(futs), 1):
                fecha = futs[fut]
                try:
                    urls = fut.result()
                except Exception as e:
                    log(f"  ! {fecha}: {e}")
                    continue
                con.execute(
                    "UPDATE dia_pleno SET urls_json=? WHERE legislatura=? AND fecha=?",
                    (json.dumps(urls), leg, fecha),
                )
                con.commit()
                if i % 50 == 0:
                    log(f"  páginas de día {i}/{len(pendientes)}")

        dias_pend = con.execute(
            "SELECT fecha, urls_json FROM dia_pleno WHERE legislatura=? AND descargado=0 AND urls_json IS NOT NULL ORDER BY fecha",
            (leg,),
        ).fetchall()
        total = sum(len(json.loads(r["urls_json"])) for r in dias_pend)
        log(f"  {total} votaciones por descargar en {len(dias_pend)} días")
        hechas = 0
        # Las descargas van en paralelo; la escritura en SQLite es por día y en una transacción corta.
        with ThreadPoolExecutor(workers) as ex:
            por_dia = [(r["fecha"], [ex.submit(descargar_json, u) for u in json.loads(r["urls_json"])]) for r in dias_pend]
            for fecha, futs in por_dia:
                resultados, errores = [], 0
                for fut in futs:
                    try:
                        resultados.append(fut.result())
                    except Exception as e:
                        errores += 1
                        log(f"  ! {fecha}: {e}")
                for url, raw in resultados:
                    try:
                        cargador.guardar(leg, url, raw)
                    except Exception as e:
                        errores += 1
                        log(f"  ! {fecha} {url}: {e}")
                if not errores:
                    con.execute("UPDATE dia_pleno SET descargado=1 WHERE legislatura=? AND fecha=?", (leg, fecha))
                con.commit()
                antes, hechas = hechas, hechas + len(futs)
                if hechas // 500 != antes // 500:
                    log(f"  votaciones {hechas}/{total}")
        log(f"  Legislatura {LEGISLATURAS[leg][0]} completada")
        sys.stdout.flush()
