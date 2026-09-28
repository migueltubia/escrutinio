"""Exporta una SQLite compacta para la web local (sin servidor).

La página se abre con doble clic (file://). Los navegadores no dejan leer ficheros locales con
fetch, así que la base de datos va comprimida con gzip y en base64 dentro de ficheros .js que se
cargan con <script>. En el navegador, sql.js (SQLite en WebAssembly) la abre en memoria y la web
hace sus consultas SQL directamente sobre ella.

Igual que data/bd/, va troceada: web/datos/comun.js (catálogos, instituciones y árbol de ámbitos,
diputados, informe) y un <institución>/legNN.js por legislatura de cada institución, más indice.js
con la lista, la institución y la huella de cada uno. La web solo descarga los ficheros del ámbito
elegido. Solo se reescriben los que cambian, así que cada semana en git solo cambian las
legislaturas en curso y el índice.

Para que quepa, el voto nominal (casi 6 millones de filas) se guarda como una cadena por votación:
un carácter por diputado de la plantilla de la legislatura (S sí, N no, A abstención, - no vota,
. no pertenecía a la Cámara ese día). El grupo de cada diputado en cada fecha sale de sus tramos.
"""

import base64
import gzip
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .analisis import debates_generales
from .config import WEB_DIR
from .gobiernos import GOBIERNOS
from .llm.etiquetas import VERSION as VERSION_ETIQUETAS
from .llm.etiquetas import canonicas, leyes_canonicas
from .llm.prompt import VERSION_TAXONOMIA

CODIGO = {"si": "S", "no": "N", "abstencion": "A", "no_vota": "-"}
DEBATE_GENERAL = "debate general"

ESQUEMA = """
CREATE TABLE meta(clave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE legislatura(id INTEGER PRIMARY KEY, romano TEXT, inicio TEXT, fin TEXT, cuerpo TEXT, numero INTEGER,
  escanos INTEGER, votaciones INTEGER, desde TEXT, hasta TEXT, nominal INTEGER, por_grupo INTEGER, totales INTEGER);
CREATE TABLE cuerpo(codigo TEXT PRIMARY KEY, num INTEGER, nombre TEXT, corto TEXT, nivel TEXT, ccaa TEXT, escanos INTEGER,
  web TEXT);
CREATE TABLE ambito(codigo TEXT PRIMARY KEY, padre TEXT, nombre TEXT, nivel TEXT, cuerpo TEXT, orden INTEGER);
CREATE TABLE tema(codigo TEXT PRIMARY KEY, nombre TEXT, subtemas TEXT);
CREATE TABLE tipo_expediente(prefijo TEXT PRIMARY KEY, nombre TEXT, familia TEXT, fuerza_ley INTEGER);
CREATE TABLE grupo(legislatura INTEGER, codigo TEXT, nombre TEXT, siglas TEXT, color TEXT, diputados INTEGER,
  PRIMARY KEY(legislatura, codigo));
CREATE TABLE votacion(id INTEGER PRIMARY KEY, legislatura INTEGER, sesion INTEGER, numero INTEGER, fecha TEXT,
  seccion TEXT, texto_expediente TEXT, titulo_subgrupo TEXT, texto_subgrupo TEXT, asentimiento INTEGER,
  presentes INTEGER, a_favor INTEGER, en_contra INTEGER, abstenciones INTEGER, no_votan INTEGER,
  expediente TEXT, prefijo TEXT, tipo_votacion TEXT, tipo_votacion_fuente TEXT, mayoria TEXT, resultado TEXT,
  margen INTEGER, decisiva INTEGER, aviso TEXT, enmienda_grupo TEXT, enmienda_autor TEXT, enmiendas_n INTEGER,
  transaccional INTEGER, fuente TEXT, url TEXT);
CREATE INDEX ix_votacion_fecha ON votacion(fecha);
CREATE INDEX ix_votacion_exp ON votacion(legislatura, expediente);
CREATE TABLE voto_grupo(votacion_id INTEGER, grupo TEXT, si INTEGER, no INTEGER, abstencion INTEGER,
  no_vota INTEGER, sentido TEXT, PRIMARY KEY(votacion_id, grupo)) WITHOUT ROWID;
CREATE TABLE grupo_decisivo(votacion_id INTEGER, grupo TEXT, modo TEXT, PRIMARY KEY(votacion_id, grupo)) WITHOUT ROWID;
CREATE TABLE iniciativa(legislatura INTEGER, expediente TEXT, prefijo TEXT, tipo TEXT, titulo TEXT, autor TEXT,
  grupo_autor TEXT, fecha_presentacion TEXT, resultado_tramitacion TEXT, situacion TEXT, resultado_final TEXT,
  sintetica INTEGER, comision TEXT, bocg TEXT, boe TEXT, url TEXT, PRIMARY KEY(legislatura, expediente));
CREATE TABLE ficha_llm(legislatura INTEGER, expediente TEXT, resumen TEXT, bloques TEXT, tema_principal TEXT,
  temas_secundarios TEXT, etiquetas TEXT, ambito TEXT, marcas TEXT, leyes_afectadas TEXT, confianza REAL,
  fuente_texto TEXT, modelo TEXT, version_prompt TEXT, version_taxonomia TEXT, creado TEXT,
  PRIMARY KEY(legislatura, expediente));
CREATE TABLE afinidad(legislatura INTEGER, tema TEXT, grupo_a TEXT, grupo_b TEXT, coinciden INTEGER, total INTEGER,
  PRIMARY KEY(legislatura, tema, grupo_a, grupo_b)) WITHOUT ROWID;
CREATE TABLE informe_ia(clave TEXT PRIMARY KEY, titulo TEXT, contenido TEXT, modelo TEXT, creado TEXT);
CREATE TABLE diputado(id INTEGER PRIMARY KEY, nombre TEXT);
CREATE TABLE plantilla(legislatura INTEGER, pos INTEGER, diputado_id INTEGER, PRIMARY KEY(legislatura, pos));
CREATE INDEX ix_plantilla_dip ON plantilla(diputado_id);
CREATE TABLE diputado_grupo(legislatura INTEGER, diputado_id INTEGER, grupo TEXT, desde TEXT, hasta TEXT,
  votaciones INTEGER, ausencias INTEGER);
CREATE INDEX ix_dg ON diputado_grupo(diputado_id, legislatura);
CREATE TABLE voto_nominal(votacion_id INTEGER PRIMARY KEY, sentidos TEXT);
-- Iniciativas legislativas abiertas de la legislatura actual (datos abiertos): fase y plazos.
CREATE TABLE en_tramite(legislatura INTEGER, expediente TEXT, prefijo TEXT, tipo TEXT, titulo TEXT, autor TEXT,
  grupo_autor TEXT, fecha_presentacion TEXT, organo TEXT, fase TEXT, comision TEXT, plazo_hasta TEXT, plazo_tipo TEXT,
  primer_plazo TEXT, ampliaciones INTEGER, votada INTEGER, bocg TEXT, PRIMARY KEY(legislatura, expediente));
"""
# Tablas que solo van en comun.js. Van aparte para que añadirlas no cambie el esquema (ni la huella)
# de los ficheros de legislatura, que si no se reescribirían todos.
ESQUEMA_COMUN = """
CREATE TABLE gobierno(cuerpo TEXT, desde TEXT, hasta TEXT, presidente TEXT, partido TEXT, socios TEXT,
  PRIMARY KEY(cuerpo, desde));
-- Programas electorales, sus compromisos, las iniciativas relacionadas y el estado de cada compromiso.
CREATE TABLE programa(id TEXT PRIMARY KEY, eleccion TEXT, fecha_eleccion TEXT, cuerpo TEXT, legislatura INTEGER,
  partido TEXT, titulo TEXT, origen TEXT, url TEXT, url_oficial TEXT, descargado TEXT, paginas INTEGER, estado TEXT,
  leido TEXT, compromisos INTEGER, verificables INTEGER);
CREATE TABLE compromiso(id TEXT PRIMARY KEY, programa TEXT, orden INTEGER, texto TEXT, cita TEXT, pagina INTEGER,
  tema TEXT, etiquetas TEXT, tipo_accion TEXT, responsable TEXT, verificable INTEGER);
CREATE INDEX ix_compromiso_programa ON compromiso(programa);
CREATE TABLE compromiso_iniciativa(compromiso TEXT, legislatura INTEGER, expediente TEXT, sentido TEXT,
  justificacion TEXT, origen TEXT, estado TEXT, PRIMARY KEY(compromiso, legislatura, expediente));
CREATE TABLE compromiso_estado(compromiso TEXT PRIMARY KEY, estado TEXT, impulsa INTEGER, coherentes INTEGER,
  incoherentes INTEGER, abstenciones INTEGER, aprobada INTEGER, gobierno INTEGER);
"""


def _enlaces(texto):
    return "\n".join(u.strip() for u in (texto or "").split("\n") if u.strip().startswith("http"))


def construir(con, destino, log=print):
    if destino.exists():
        destino.unlink()
    web = sqlite3.connect(destino)
    web.executescript(ESQUEMA + ESQUEMA_COMUN)

    def copiar(tabla, sql, args=()):
        filas = con.execute(sql, args).fetchall()
        if filas:
            marcas = ",".join("?" * len(filas[0]))
            web.executemany(f"INSERT INTO {tabla} VALUES ({marcas})", [tuple(f) for f in filas])
        return len(filas)

    # Con lo que hay de cada legislatura: la web lo enseña al elegir ámbito sin tener que cargarla.
    copiar("legislatura", """SELECT l.id, l.romano, l.inicio, l.fin, l.cuerpo, COALESCE(l.numero, l.id), l.escanos,
                                    COUNT(*), MIN(v.fecha), MAX(v.fecha),
                                    SUM(EXISTS (SELECT 1 FROM voto vo WHERE vo.votacion_id=v.id)),
                                    SUM(EXISTS (SELECT 1 FROM voto_grupo g WHERE g.votacion_id=v.id)),
                                    SUM(v.a_favor IS NOT NULL)
                             FROM legislatura l JOIN votacion v ON v.legislatura=l.id GROUP BY l.id""")
    con_datos = {r[0] for r in con.execute(
        "SELECT DISTINCT l.cuerpo FROM legislatura l WHERE l.id IN (SELECT DISTINCT legislatura FROM votacion)")}
    copiar("cuerpo", f"""SELECT codigo, num, nombre, corto, nivel, ccaa, escanos, web FROM cuerpo
                        WHERE codigo IN ({','.join('?' * len(con_datos))})""", tuple(con_datos))
    from .territorio import arbol

    web.executemany("INSERT INTO ambito VALUES (?,?,?,?,?,?)", arbol(con_datos))
    web.executemany("INSERT INTO gobierno VALUES (?,?,?,?,?,?)", [g for g in GOBIERNOS if g[0] in con_datos])
    copiar("programa", """SELECT id, eleccion, fecha_eleccion, cuerpo, legislatura, partido, titulo, origen, url, url_oficial,
                                 descargado, paginas, estado, leido, compromisos, verificables FROM programa""")
    n = copiar("compromiso", """SELECT id, programa, orden, texto, cita, pagina, tema, etiquetas, tipo_accion, responsable,
                                   verificable FROM compromiso""")
    copiar("compromiso_iniciativa", """SELECT compromiso, legislatura, expediente, sentido, justificacion, origen, estado
                                      FROM compromiso_iniciativa WHERE estado<>'rechazado'""")
    copiar("compromiso_estado", """SELECT compromiso, estado, impulsa, coherentes, incoherentes, abstenciones, aprobada, gobierno
                                  FROM compromiso_estado""")
    if n:
        log(f"  compromisos de programas electorales: {n}")
    copiar("tema", "SELECT codigo, nombre, subtemas FROM tema")
    copiar("tipo_expediente", "SELECT prefijo, nombre, familia, fuerza_ley FROM tipo_expediente")
    copiar("grupo", "SELECT legislatura, codigo, nombre, siglas, color, diputados FROM grupo")
    n = copiar(
        "votacion",
        """SELECT id, legislatura, sesion, numero, fecha, seccion, texto_expediente, titulo_subgrupo, texto_subgrupo,
                  asentimiento, presentes, a_favor, en_contra, abstenciones, no_votan, expediente, prefijo,
                  tipo_votacion, tipo_votacion_fuente, mayoria, resultado, margen, decisiva, aviso, enmienda_grupo,
                  enmienda_autor, enmiendas_n, transaccional, fuente,
                  url FROM votacion""",
    )
    log(f"  votaciones: {n}")
    copiar("voto_grupo", "SELECT votacion_id, grupo, si, no, abstencion, no_vota, sentido FROM voto_grupo")
    copiar("grupo_decisivo", "SELECT votacion_id, grupo, modo FROM grupo_decisivo")
    filas = []
    for r in con.execute(
        """SELECT i.* FROM iniciativa i
           JOIN (SELECT DISTINCT legislatura, expediente FROM votacion) vv USING (legislatura, expediente)"""
    ):
        extra = json.loads(r["extra_json"]) if r["extra_json"] else {}
        filas.append((
            r["legislatura"], r["expediente"], r["prefijo"], r["tipo"], r["titulo"], r["autor"], r["grupo_autor"],
            r["fecha_presentacion"], r["resultado_tramitacion"], r["situacion"], r["resultado_final"], r["sintetica"],
            (extra.get("COMISIONCOMPETENTE") or "").strip() or None,
            _enlaces(extra.get("ENLACESBOCG")) or None, _enlaces(extra.get("ENLACESBOE")) or None,
            extra.get("url") if isinstance(extra, dict) else None,  # ficha en la fuente (territoriales)
        ))
    web.executemany(f"INSERT INTO iniciativa VALUES ({','.join('?' * 16)})", filas)
    log(f"  iniciativas votadas: {len(filas)}")
    # Debates de política general: lo que se vota son propuestas de resolución de cualquier tema, así que
    # el asunto se queda sin tema (y sus votaciones fuera del análisis por tema), con la marca «debate general».
    debates = debates_generales(con)
    fichas = []
    for r in con.execute(
        """SELECT f.* FROM ficha_llm f
           WHERE EXISTS (SELECT 1 FROM votacion v WHERE v.legislatura=f.legislatura AND v.expediente=f.expediente)
              OR EXISTS (SELECT 1 FROM iniciativa i WHERE i.legislatura=f.legislatura AND i.expediente=f.expediente
                         AND i.situacion IS NOT NULL AND i.situacion <> 'Cerrado')"""
    ):
        f = dict(r)
        f["etiquetas"] = json.dumps(canonicas(json.loads(f["etiquetas"] or "[]")), ensure_ascii=False)
        f["leyes_afectadas"] = json.dumps(leyes_canonicas(json.loads(f["leyes_afectadas"] or "[]")), ensure_ascii=False)
        if (f["legislatura"], f["expediente"]) in debates:
            f["tema_principal"], f["temas_secundarios"] = None, "[]"
            f["marcas"] = json.dumps(json.loads(f["marcas"] or "[]") + [DEBATE_GENERAL], ensure_ascii=False)
        fichas.append(tuple(f.values()))
    web.executemany(f"INSERT INTO ficha_llm VALUES ({','.join('?' * 16)})", fichas)
    log(f"  fichas IA: {len(fichas)} (etiquetas normalizadas con {VERSION_ETIQUETAS})")
    # Sin ficha IA todavía: tema provisional por comisión (sin resumen ni etiquetas), marcado como tal.
    # Un debate general no lleva: no tiene tema.
    provisionales = [
        (r["legislatura"], r["expediente"], None, "[]", r["tema_principal"], r["temas_secundarios"], "[]", "estatal", "[]", "[]",
         None, f"comisión competente: {r['comision']}", "reglas (comisión competente)", r["version"], VERSION_TAXONOMIA, r["creado"])
        for r in con.execute(
            """SELECT p.* FROM tema_provisional p
               LEFT JOIN ficha_llm f ON f.legislatura=p.legislatura AND f.expediente=p.expediente
               WHERE f.expediente IS NULL AND (
                 EXISTS (SELECT 1 FROM votacion v WHERE v.legislatura=p.legislatura AND v.expediente=p.expediente)
                 OR EXISTS (SELECT 1 FROM iniciativa i WHERE i.legislatura=p.legislatura AND i.expediente=p.expediente
                            AND i.situacion IS NOT NULL AND i.situacion <> 'Cerrado'))"""
        )
        if (r["legislatura"], r["expediente"]) not in debates
    ]
    web.executemany(f"INSERT INTO ficha_llm VALUES ({','.join('?' * 16)})", provisionales)
    log(f"  temas provisionales por comisión (sin ficha IA): {len(provisionales)}")
    n = en_tramite(con, web)
    log(f"  iniciativas en trámite: {n}")
    copiar("afinidad", "SELECT legislatura, tema, grupo_a, grupo_b, coinciden, total FROM afinidad")
    copiar("informe_ia", "SELECT clave, titulo, contenido, modelo, creado FROM informe_ia")
    copiar("diputado", "SELECT id, nombre FROM diputado")

    # Plantilla por legislatura: todos los diputados que votaron alguna vez en ella.
    plantilla = {}
    for leg, in con.execute("SELECT DISTINCT legislatura FROM votacion").fetchall():
        ids = [r[0] for r in con.execute(
            """SELECT d.id FROM diputado d WHERE d.id IN (
                 SELECT DISTINCT vo.diputado_id FROM voto vo JOIN votacion v ON v.id=vo.votacion_id WHERE v.legislatura=?)
               ORDER BY d.nombre""",
            (leg,),
        )]
        plantilla[leg] = {did: pos for pos, did in enumerate(ids)}
        web.executemany("INSERT INTO plantilla VALUES (?,?,?)", [(leg, pos + 1, did) for did, pos in plantilla[leg].items()])

    # Voto nominal compacto y tramos de grupo (en orden cronológico).
    leg_de = dict(con.execute("SELECT id, legislatura FROM votacion").fetchall())
    fecha_de = dict(con.execute("SELECT id, fecha FROM votacion").fetchall())
    cadenas = {vid: bytearray(b"." * len(plantilla[leg])) for vid, leg in leg_de.items()}
    tramos = defaultdict(list)  # (leg, diputado) -> [[grupo, desde, hasta, n, ausencias]]
    for vid, did, grupo, sentido in con.execute(
        """SELECT vo.votacion_id, vo.diputado_id, vo.grupo, vo.sentido FROM voto vo
           JOIN votacion v ON v.id=vo.votacion_id ORDER BY v.fecha, v.sesion, v.numero"""
    ):
        leg = leg_de[vid]
        cadenas[vid][plantilla[leg][did]] = ord(CODIGO.get(sentido, "-"))
        t = tramos[(leg, did)]
        f = fecha_de[vid]
        if t and t[-1][0] == grupo:
            t[-1][2] = f
        else:
            t.append([grupo, f, f, 0, 0])
        t[-1][3] += 1
        t[-1][4] += sentido == "no_vota"
    web.executemany("INSERT INTO voto_nominal VALUES (?,?)", [(vid, c.decode()) for vid, c in cadenas.items()])
    web.executemany(
        "INSERT INTO diputado_grupo VALUES (?,?,?,?,?,?,?)",
        [(leg, did, *t) for (leg, did), ts in tramos.items() for t in ts],
    )

    # La fecha de generación va en indice.js, para que comun.js no cambie si no cambian los datos.
    meta = {
        "votos": con.execute("SELECT COUNT(*) FROM voto").fetchone()[0],
        "diputados": con.execute("SELECT COUNT(DISTINCT diputado_id) FROM voto").fetchone()[0],
    }
    web.executemany("INSERT INTO meta VALUES (?,?)", [(k, str(v)) for k, v in meta.items()])
    web.commit()
    web.execute("VACUUM")
    web.close()


_PLAZO = re.compile(r"Hasta:\s*(\d{2})/(\d{2})/(\d{4})\s*\([\d:]+\)\s*(.+?)(?=\s*Hasta:|$)", re.S)


def en_tramite(con, web):
    filas = []
    for r in con.execute(
        """SELECT i.*, EXISTS (SELECT 1 FROM votacion v WHERE v.legislatura=i.legislatura AND v.expediente=i.expediente) AS votada
           FROM iniciativa i WHERE i.situacion IS NOT NULL AND i.situacion <> 'Cerrado'"""
    ):
        extra = json.loads(r["extra_json"] or "{}")
        # La situación viene en pares «órgano / fase» (a veces varios a la vez).
        partes = [p.strip() for p in (r["situacion"] or "").split("\n") if p.strip()]
        organos = list(dict.fromkeys(partes[0::2]))
        fases = list(dict.fromkeys(partes[1::2]))
        plazos = [(f"{y}-{m}-{d}", re.sub(r"\s+", " ", t).strip()) for d, m, y, t in _PLAZO.findall(extra.get("PLAZOS") or "")]
        ultimo = max(plazos) if plazos else (None, None)
        filas.append((
            r["legislatura"], r["expediente"], r["prefijo"], r["tipo"], r["titulo"], r["autor"], r["grupo_autor"],
            r["fecha_presentacion"], " / ".join(organos) or None, " + ".join(fases) or None,
            (extra.get("COMISIONCOMPETENTE") or "").strip() or None, ultimo[0], ultimo[1],
            min(plazos)[0] if plazos else None, sum(1 for _, t in plazos if t.lower().startswith("ampliaci")),
            r["votada"], _enlaces(extra.get("ENLACESBOCG")) or None,
        ))
    web.executemany(f"INSERT INTO en_tramite VALUES ({','.join('?' * 17)})", filas)
    return len(filas)


DATOS_DIR = WEB_DIR / "datos"
INDICE = DATOS_DIR / "indice.js"
TABLAS_COMUN = ("meta", "legislatura", "cuerpo", "ambito", "gobierno", "tema", "tipo_expediente", "informe_ia", "diputado",
                "programa", "compromiso", "compromiso_iniciativa", "compromiso_estado")
_POR_VOTACION = "votacion_id IN (SELECT id FROM votacion WHERE legislatura=?)"
TABLAS_LEG = (
    ("grupo", "legislatura=?"), ("votacion", "legislatura=?"), ("voto_grupo", _POR_VOTACION),
    ("grupo_decisivo", _POR_VOTACION), ("iniciativa", "legislatura=?"), ("ficha_llm", "legislatura=?"),
    ("afinidad", "legislatura=?"), ("plantilla", "legislatura=?"), ("diputado_grupo", "legislatura=?"),
    ("voto_nominal", _POR_VOTACION), ("en_tramite", "legislatura=?"),
)
# Los ficheros de legislatura solo llevan datos: los índices ya están en comun.js.
_ESQUEMA_SIN_INDICES = "\n".join(l for l in ESQUEMA.splitlines() if not l.startswith("CREATE INDEX"))


def _leer_indice():
    if not INDICE.exists():
        return {}
    texto = INDICE.read_text(encoding="utf-8")
    return json.loads(texto[texto.index("{"):texto.rindex("}") + 1])


def _trocear(completa, tmp):
    """Parte la SQLite web en comun + una por legislatura. Devuelve [(nombre, cuerpo, ruta, huella)]."""
    web = sqlite3.connect(completa)
    trozos = []

    def trozo(nombre, esquema, tablas, args=()):
        ruta = tmp / f"{nombre.replace('/', '__')}.sqlite"
        web.execute("ATTACH DATABASE ? AS d", (str(ruta),))
        web.executescript(esquema.replace("CREATE TABLE ", "CREATE TABLE d.").replace("CREATE INDEX ", "CREATE INDEX d."))
        h = hashlib.sha256(esquema.encode())  # si cambia el esquema, el fichero también tiene que cambiar
        for tabla, where in tablas:
            pk = ", ".join(r[1] for r in sorted(web.execute(f"PRAGMA table_info({tabla})"), key=lambda r: r[5]) if r[5]) or "rowid"
            for fila in web.execute(f"SELECT * FROM main.{tabla} WHERE {where} ORDER BY {pk}", args):
                h.update(repr(fila).encode())
            web.execute(f"INSERT INTO d.{tabla} SELECT * FROM main.{tabla} WHERE {where} ORDER BY {pk}", args)
        web.commit()
        web.execute("DETACH DATABASE d")
        destino = sqlite3.connect(ruta)
        destino.execute("VACUUM")
        destino.close()
        trozos.append((nombre, cuerpo, ruta, h.hexdigest()[:16]))

    cuerpo = None
    trozo("comun", ESQUEMA + ESQUEMA_COMUN, [(t, "1=1") for t in TABLAS_COMUN])
    for leg, cuerpo, numero in web.execute("SELECT id, cuerpo, numero FROM legislatura ORDER BY id").fetchall():
        trozo(f"{cuerpo}/leg{numero}", _ESQUEMA_SIN_INDICES, TABLAS_LEG, (leg,))
    web.close()
    return trozos


def exportar(con, log=print):
    log("Construyendo la base de datos para la web…")
    DATOS_DIR.mkdir(parents=True, exist_ok=True)
    anterior = {f["nombre"]: f for f in _leer_indice().get("ficheros", [])}
    ficheros, cambios = [], 0
    with tempfile.TemporaryDirectory() as tmp:
        completa = Path(tmp) / "escrutinio-web.sqlite"
        construir(con, completa, log)
        for nombre, cuerpo, ruta, huella in _trocear(completa, Path(tmp)):
            js = DATOS_DIR / f"{nombre}.js"
            js.parent.mkdir(parents=True, exist_ok=True)
            if anterior.get(nombre, {}).get("huella") == huella and js.exists():
                estado = "sin cambios"
            else:
                # mtime=0: el mismo contenido da siempre el mismo fichero.
                comprimido = gzip.compress(ruta.read_bytes(), 9, mtime=0)
                js.write_text(
                    "// Generado por `python -m escrutinio web`. SQLite comprimida con gzip, en base64.\n"
                    f"(window.ESCRUTINIO_DATOS = window.ESCRUTINIO_DATOS || {{}})[\"{nombre}\"] =\n"
                    f"\"{base64.b64encode(comprimido).decode()}\";\n",
                    encoding="ascii",
                )
                estado, cambios = "actualizado", cambios + 1
            ficheros.append({"nombre": nombre, **({"cuerpo": cuerpo} if cuerpo else {}), "huella": huella,
                             "bytes": js.stat().st_size})
            log(f"  {nombre}.js: {estado} ({js.stat().st_size / 1e6:.1f} MB)")
    # Restos de exportaciones anteriores (legislaturas que ya no están, los legNN.js de la raíz…).
    vigentes = {DATOS_DIR / f"{f['nombre']}.js" for f in ficheros} | {INDICE}
    for viejo in DATOS_DIR.rglob("*.js"):
        if viejo not in vigentes:
            viejo.unlink()
            log(f"  {viejo.relative_to(DATOS_DIR).as_posix()}: borrado")
    for carpeta in sorted((d for d in DATOS_DIR.rglob("*") if d.is_dir()), reverse=True):
        if not any(carpeta.iterdir()):
            carpeta.rmdir()
    previo = _leer_indice()
    generado = previo.get("generado") if not cambios and previo.get("ficheros") == ficheros else None
    indice = {"generado": generado or datetime.now(timezone.utc).isoformat(timespec="seconds"), "ficheros": ficheros}
    # Instituciones que no respondieron en la última recogida: la web lo avisa. Van aquí y no en comun.js
    # para que este cambie solo si cambian los datos. Sin recogida en esta base, se quedan los de antes.
    from .territorial import estado

    avisos = estado.avisos(con)
    indice["avisos"] = previo.get("avisos", {}) if avisos is None else avisos
    INDICE.write_text(
        "// Generado por `python -m escrutinio web`. Ficheros de datos que carga la web, en orden.\n"
        f"window.ESCRUTINIO_INDICE = {json.dumps(indice, indent=1, ensure_ascii=False)};\n",
        encoding="utf-8",
    )
    total = sum(f["bytes"] for f in ficheros)
    log(f"Web: {len(ficheros)} ficheros de datos, {total / 1e6:.1f} MB en total ({cambios} actualizados) -> {DATOS_DIR}")
    log(f"Abre {WEB_DIR / 'index.html'} en el navegador (doble clic, sin servidor).")
