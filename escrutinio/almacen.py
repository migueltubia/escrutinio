"""Almacenamiento troceado: una SQLite por institución y legislatura, más una común.

La base de trabajo (data/escrutinio.sqlite) es un fichero temporal que no se versiona: es cómoda
para procesar, pero ocupa casi 400 MB por los casi 7 millones de filas de voto nominal. Lo que se
guarda y versiona es data/bd/:

- comun.sqlite: legislaturas, catálogos, diputados e informe.
- <institución>/legNN.sqlite: todo lo de una legislatura de una institución (congreso/leg15.sqlite,
  parl-AS/leg12.sqlite, ayto-gijon/leg12.sqlite…): días, votaciones, agregados por grupo,
  iniciativas, fichas IA, afinidades… El voto nominal va compacto en voto_compacto: por cada
  votación, una cadena con el sentido de cada diputado de la plantilla (S sí, N no, A abstención,
  - no vota, . no pertenecía a la Cámara) y otra con su grupo (índice en grupo_idx). Los ficheros no
  llevan índices: solo guardan, y `unir` los vuelve a crear en la base de trabajo.

Trocear así mantiene cada fichero muy por debajo del límite de GitHub y hace que cada semana solo
cambien las legislaturas en curso: las cerradas no se reescriben nunca.

`partir` genera los ficheros desde la base de trabajo y solo reescribe los que han cambiado (lo
comprueba con un hash del contenido), así que las legislaturas cerradas no cambian nunca en git.
`unir` reconstruye la base de trabajo desde los ficheros.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict

from . import db
from .config import DATA_DIR, DB_PATH

BD_DIR = DATA_DIR / "bd"
MANIFIESTO = BD_DIR / "manifiesto.json"
LIMITE_AVISO = 45_000_000  # GitHub avisa desde 50 MB por fichero y rechaza desde 100 MB

TABLAS_COMUN = ["legislatura", "tipo_expediente", "tema", "diputado", "informe_ia"]
# (tabla, cláusula para quedarse con las filas de una legislatura)
TABLAS_LEG = [
    ("dia_pleno", "legislatura=?"),
    ("grupo", "legislatura=?"),
    ("iniciativa", "legislatura=?"),
    ("votacion", "legislatura=?"),
    ("voto_grupo", "votacion_id IN (SELECT id FROM votacion WHERE legislatura=?)"),
    ("grupo_decisivo", "votacion_id IN (SELECT id FROM votacion WHERE legislatura=?)"),
    ("ficha_llm", "legislatura=?"),
    ("tema_provisional", "legislatura=?"),
    ("afinidad", "legislatura=?"),
]
SENTIDO_A_LETRA = {"si": "S", "no": "N", "abstencion": "A", "no_vota": "-"}
LETRA_A_SENTIDO = {v: k for k, v in SENTIDO_A_LETRA.items()}

ESQUEMA_COMPACTO = """
CREATE TABLE plantilla(pos INTEGER PRIMARY KEY, diputado_id INTEGER NOT NULL);
CREATE TABLE grupo_idx(idx INTEGER PRIMARY KEY, codigo TEXT NOT NULL);
CREATE TABLE voto_compacto(votacion_id INTEGER PRIMARY KEY, sentidos TEXT NOT NULL, grupos TEXT NOT NULL);
"""


def _columnas(con, tabla, esquema="main"):
    return [r[1] for r in con.execute(f"PRAGMA {esquema}.table_info({tabla})")]


def _crear(ruta):
    if ruta.exists():
        ruta.unlink()
    con = sqlite3.connect(ruta)
    db.init(con, catalogos=False)
    con.execute("DROP TABLE voto")
    # Sin índices: aquí solo se guarda; `unir` los crea en la base de trabajo y la web lleva los suyos.
    for (indice,) in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall():
        con.execute(f"DROP INDEX {indice}")
    con.executescript(ESQUEMA_COMPACTO)
    return con


def _esquema(con):
    """Esquema tal como queda en el fichero (si cambia, la huella también)."""
    return "\n".join(r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name"))


def _pk(con, tabla):
    pk = [r[1] for r in sorted(con.execute(f"PRAGMA table_info({tabla})"), key=lambda r: r[5]) if r[5]]
    return ", ".join(pk) if pk else "rowid"


def _copiar(origen, destino, tabla, where="1=1", args=()):
    """Copia filas de origen a destino en orden de clave primaria, con las columnas comunes."""
    cols = [c for c in _columnas(origen, tabla) if c in set(_columnas(destino, tabla))]
    lista = ", ".join(cols)
    filas = origen.execute(f"SELECT {lista} FROM {tabla} WHERE {where} ORDER BY {_pk(origen, tabla)}", args).fetchall()
    destino.executemany(f"INSERT INTO {tabla} ({lista}) VALUES ({','.join('?' * len(cols))})", filas)
    return filas


def _huella(h, filas):
    for f in filas:
        h.update(repr(tuple(f)).encode())


def _compacto(con, leg):
    """Plantilla, índice de grupos y cadenas de voto de una legislatura."""
    ids = [r[0] for r in con.execute(
        """SELECT d.id FROM diputado d WHERE d.id IN (SELECT DISTINCT vo.diputado_id FROM voto vo
             JOIN votacion v ON v.id=vo.votacion_id WHERE v.legislatura=?) ORDER BY d.nombre, d.id""", (leg,))]
    pos = {d: i for i, d in enumerate(ids)}
    grupos = sorted({r[0] for r in con.execute(
        "SELECT DISTINCT vo.grupo FROM voto vo JOIN votacion v ON v.id=vo.votacion_id WHERE v.legislatura=?", (leg,))})
    gidx = {g: i for i, g in enumerate(grupos)}
    sentidos = defaultdict(lambda: bytearray(b"." * len(ids)))
    grupos_v = defaultdict(lambda: bytearray(b"." * len(ids)))
    for vid, did, grupo, sentido in con.execute(
        "SELECT vo.votacion_id, vo.diputado_id, vo.grupo, vo.sentido FROM voto vo JOIN votacion v ON v.id=vo.votacion_id WHERE v.legislatura=?",
        (leg,),
    ):
        sentidos[vid][pos[did]] = ord(SENTIDO_A_LETRA.get(sentido, "-"))
        grupos_v[vid][pos[did]] = 48 + gidx[grupo]  # '0', '1', …
    votos = [(vid, sentidos[vid].decode(), grupos_v[vid].decode()) for vid in sorted(sentidos)]
    return list(enumerate(ids)), list(enumerate(grupos)), votos


def nombre_trozo(cuerpo, numero):
    """Nombre del fichero de una legislatura: «congreso/leg15», «parl-AS/leg12»…"""
    return f"{cuerpo}/leg{numero}"


def partir(con=None, log=print):
    """Genera data/bd/ desde la base de trabajo; solo reescribe los ficheros que cambian."""
    con = con or db.connect()
    BD_DIR.mkdir(parents=True, exist_ok=True)
    manifiesto = json.loads(MANIFIESTO.read_text(encoding="utf-8")) if MANIFIESTO.exists() else {}
    nuevo = {}

    def escribir(nombre, rellenar):
        final = BD_DIR / f"{nombre}.sqlite"
        tmp = BD_DIR / f"{nombre}.sqlite.tmp"
        final.parent.mkdir(parents=True, exist_ok=True)
        destino = _crear(tmp)
        h = hashlib.sha256(_esquema(destino).encode())  # si cambia el esquema, el fichero también tiene que cambiar
        resumen = rellenar(destino, h)
        destino.commit()
        destino.close()
        huella = h.hexdigest()
        if manifiesto.get(nombre, {}).get("huella") == huella and final.exists():
            tmp.unlink()
            estado = "sin cambios"
        else:
            tmp.replace(final)
            estado = "actualizado"
        nuevo[nombre] = {"huella": huella, **resumen, "bytes": final.stat().st_size}
        log(f"  {nombre}.sqlite: {estado} ({final.stat().st_size / 1e6:.1f} MB)")
        if final.stat().st_size > LIMITE_AVISO:
            log(f"  ! {final.name} supera {LIMITE_AVISO / 1e6:.0f} MB: GitHub avisa a partir de 50 MB y rechaza más de 100 MB")

    def comun(destino, h):
        for t in TABLAS_COMUN:
            _huella(h, _copiar(con, destino, t))
        return {}

    escribir("comun", comun)
    legs = [(r[0], r[1], r[2]) for r in con.execute(
        """SELECT u.legislatura, COALESCE(l.cuerpo, 'congreso'), COALESCE(l.numero, u.legislatura)
           FROM (SELECT legislatura FROM votacion UNION SELECT legislatura FROM iniciativa) u
           LEFT JOIN legislatura l ON l.id=u.legislatura ORDER BY 1""")]
    for leg, cuerpo, numero in legs:
        def rellenar(destino, h, leg=leg):
            n = {}
            for t, where in TABLAS_LEG:
                filas = _copiar(con, destino, t, where, (leg,))
                _huella(h, filas)
                n[t] = len(filas)
            plantilla, grupos, votos = _compacto(con, leg)
            destino.executemany("INSERT INTO plantilla VALUES (?,?)", plantilla)
            destino.executemany("INSERT INTO grupo_idx VALUES (?,?)", grupos)
            destino.executemany("INSERT INTO voto_compacto VALUES (?,?,?)", votos)
            _huella(h, plantilla)
            _huella(h, grupos)
            _huella(h, votos)
            return {"votaciones": n["votacion"], "iniciativas": n["iniciativa"], "fichas": n["ficha_llm"]}

        escribir(nombre_trozo(cuerpo, numero), rellenar)
    # Ficheros de antes que ya no corresponden a nada (p. ej. los legNN.sqlite de la raíz, de cuando solo
    # había Congreso).
    vigentes = {BD_DIR / f"{n}.sqlite" for n in nuevo}
    for viejo in BD_DIR.rglob("*.sqlite"):
        if viejo not in vigentes:
            viejo.unlink()
            log(f"  {viejo.relative_to(BD_DIR).as_posix()}: borrado")
    for carpeta in sorted((d for d in BD_DIR.rglob("*") if d.is_dir()), reverse=True):
        if not any(carpeta.iterdir()):
            carpeta.rmdir()
    MANIFIESTO.write_text(json.dumps(nuevo, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(v["bytes"] for v in nuevo.values())
    log(f"Base troceada en {BD_DIR}: {len(nuevo)} ficheros, {total / 1e6:.1f} MB en total")


def unir(ruta=DB_PATH, log=print):
    """Reconstruye la base de trabajo desde data/bd/ (el voto nominal se expande a filas)."""
    if MANIFIESTO.exists():
        ficheros = [BD_DIR / f"{n}.sqlite" for n in json.loads(MANIFIESTO.read_text(encoding="utf-8")) if n != "comun"]
    else:
        ficheros = sorted(BD_DIR.rglob("leg*.sqlite"))
    if not (BD_DIR / "comun.sqlite").exists() or not ficheros:
        raise SystemExit(f"No hay base troceada en {BD_DIR}")
    for sufijo in ("", "-wal", "-shm"):
        p = ruta.with_name(ruta.name + sufijo)
        if p.exists():
            p.unlink()
    con = db.connect(ruta)
    db.init(con)
    con.execute("DELETE FROM legislatura")
    con.execute("DELETE FROM tipo_expediente")
    con.execute("DELETE FROM tema")

    def adjuntar(fichero, alias):
        con.execute(f"ATTACH DATABASE ? AS {alias}", (str(fichero),))

    adjuntar(BD_DIR / "comun.sqlite", "c")
    for t in TABLAS_COMUN:
        cols = ", ".join(c for c in _columnas(con, t, "c") if c in set(_columnas(con, t)))
        con.execute(f"INSERT INTO main.{t} ({cols}) SELECT {cols} FROM c.{t}")
    con.commit()
    con.execute("DETACH DATABASE c")
    for fichero in ficheros:
        adjuntar(fichero, "l")
        for t, _ in TABLAS_LEG:
            cols = ", ".join(c for c in _columnas(con, t, "l") if c in set(_columnas(con, t)))
            con.execute(f"INSERT INTO main.{t} ({cols}) SELECT {cols} FROM l.{t}")
        plantilla = dict(con.execute("SELECT pos, diputado_id FROM l.plantilla"))
        grupos = dict(con.execute("SELECT idx, codigo FROM l.grupo_idx"))
        filas = []
        for vid, sentidos, gs in con.execute("SELECT votacion_id, sentidos, grupos FROM l.voto_compacto").fetchall():
            for i, (s, g) in enumerate(zip(sentidos, gs)):
                if s != ".":
                    filas.append((vid, plantilla[i], grupos[ord(g) - 48], LETRA_A_SENTIDO[s], None))
            if len(filas) > 200_000:
                con.executemany("INSERT INTO voto VALUES (?,?,?,?,?)", filas)
                filas = []
        con.executemany("INSERT INTO voto VALUES (?,?,?,?,?)", filas)
        con.commit()
        con.execute("DETACH DATABASE l")
        log(f"  {fichero.relative_to(BD_DIR).as_posix()} cargado")
    n = con.execute("SELECT COUNT(*) FROM votacion").fetchone()[0]
    m = con.execute("SELECT COUNT(*) FROM voto").fetchone()[0]
    log(f"Base de trabajo reconstruida en {ruta}: {n} votaciones, {m} votos")
    return con
