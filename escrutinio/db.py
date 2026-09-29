import sqlite3

from .config import DATA_DIR, DB_PATH, LEGISLATURAS

SCHEMA = """
-- Legislaturas (o mandatos) de todas las instituciones: id = num del cuerpo * 100 + número.
-- El Congreso es el cuerpo 0, así que sus ids son los números de legislatura (10 a 15).
CREATE TABLE IF NOT EXISTS legislatura(
  id INTEGER PRIMARY KEY,
  romano TEXT NOT NULL,
  inicio TEXT,
  fin TEXT,
  cuerpo TEXT NOT NULL DEFAULT 'congreso',
  numero INTEGER,
  escanos INTEGER
);

-- Instituciones con votaciones y árbol de ámbitos para filtrar (catálogo en territorio.py).
CREATE TABLE IF NOT EXISTS cuerpo(
  codigo TEXT PRIMARY KEY,
  num INTEGER NOT NULL UNIQUE,
  nombre TEXT NOT NULL,
  corto TEXT,
  nivel TEXT NOT NULL,
  ccaa TEXT,
  escanos INTEGER,
  web TEXT
);
CREATE TABLE IF NOT EXISTS ambito(
  codigo TEXT PRIMARY KEY,
  padre TEXT,
  nombre TEXT NOT NULL,
  nivel TEXT,
  cuerpo TEXT,
  orden INTEGER
);

-- Estado de la descarga: un registro por día con votaciones en el Pleno.
CREATE TABLE IF NOT EXISTS dia_pleno(
  legislatura INTEGER NOT NULL,
  fecha TEXT NOT NULL,
  urls_json TEXT,
  descargado INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(legislatura, fecha)
);

-- Catálogo de prefijos de expediente (121 proyecto de ley, 162 PNL...).
CREATE TABLE IF NOT EXISTS tipo_expediente(
  prefijo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  familia TEXT NOT NULL,
  fuerza_ley INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS iniciativa(
  legislatura INTEGER NOT NULL,
  expediente TEXT NOT NULL,
  prefijo TEXT,
  tipo TEXT,
  titulo TEXT NOT NULL,
  titulo_norm TEXT,
  autor TEXT,
  grupo_autor TEXT,
  fecha_presentacion TEXT,
  fecha_calificacion TEXT,
  resultado_tramitacion TEXT,
  situacion TEXT,
  resultado_final TEXT,
  sintetica INTEGER NOT NULL DEFAULT 0,
  fuente TEXT,
  extra_json TEXT,
  PRIMARY KEY(legislatura, expediente)
);
CREATE INDEX IF NOT EXISTS ix_iniciativa_prefijo ON iniciativa(legislatura, prefijo);

CREATE TABLE IF NOT EXISTS votacion(
  id INTEGER PRIMARY KEY,
  camara TEXT NOT NULL DEFAULT 'Congreso',
  legislatura INTEGER NOT NULL,
  sesion INTEGER NOT NULL,
  numero INTEGER NOT NULL,
  fecha TEXT NOT NULL,
  seccion TEXT,
  texto_expediente TEXT,
  titulo_subgrupo TEXT,
  texto_subgrupo TEXT,
  votaciones_conjuntas TEXT,
  asentimiento INTEGER NOT NULL DEFAULT 0,
  presentes INTEGER,
  a_favor INTEGER,
  en_contra INTEGER,
  abstenciones INTEGER,
  no_votan INTEGER,
  expediente TEXT,
  enlace_metodo TEXT,
  enlace_score REAL,
  prefijo TEXT,
  tipo_votacion TEXT,
  tipo_votacion_fuente TEXT,
  mayoria TEXT,
  resultado TEXT,
  margen INTEGER,
  decisiva INTEGER NOT NULL DEFAULT 0,
  aviso TEXT,
  url TEXT,
  UNIQUE(legislatura, fecha, sesion, numero)
);
CREATE INDEX IF NOT EXISTS ix_votacion_fecha ON votacion(fecha);
CREATE INDEX IF NOT EXISTS ix_votacion_exp ON votacion(legislatura, expediente);

-- Diputados, parlamentarios, junteros o concejales: el nombre es único dentro de cada institución.
CREATE TABLE IF NOT EXISTS diputado(
  id INTEGER PRIMARY KEY,
  nombre TEXT NOT NULL,
  cuerpo TEXT NOT NULL DEFAULT 'congreso',
  UNIQUE(cuerpo, nombre)
);

-- El grupo se guarda en cada voto: es el que tenía el diputado en esa votación.
CREATE TABLE IF NOT EXISTS voto(
  votacion_id INTEGER NOT NULL,
  diputado_id INTEGER NOT NULL,
  grupo TEXT NOT NULL,
  sentido TEXT NOT NULL,
  asiento TEXT,
  PRIMARY KEY(votacion_id, diputado_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_voto_diputado ON voto(diputado_id);

-- Agregado por grupo de cada votación (derivado de voto).
CREATE TABLE IF NOT EXISTS voto_grupo(
  votacion_id INTEGER NOT NULL,
  grupo TEXT NOT NULL,
  si INTEGER NOT NULL,
  no INTEGER NOT NULL,
  abstencion INTEGER NOT NULL,
  no_vota INTEGER NOT NULL,
  sentido TEXT,
  PRIMARY KEY(votacion_id, grupo)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS ix_voto_grupo_grupo ON voto_grupo(grupo);

CREATE TABLE IF NOT EXISTS grupo(
  legislatura INTEGER NOT NULL,
  codigo TEXT NOT NULL,
  nombre TEXT,
  siglas TEXT,
  color TEXT,
  diputados INTEGER,
  PRIMARY KEY(legislatura, codigo)
);

-- Grupos cuyo cambio de voto habría dado la vuelta al resultado.
CREATE TABLE IF NOT EXISTS grupo_decisivo(
  votacion_id INTEGER NOT NULL,
  grupo TEXT NOT NULL,
  modo TEXT NOT NULL,
  PRIMARY KEY(votacion_id, grupo)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS tema(
  codigo TEXT PRIMARY KEY,
  nombre TEXT NOT NULL,
  subtemas TEXT
);

-- Salidas del LLM, siempre separadas de los datos oficiales y con su procedencia.
CREATE TABLE IF NOT EXISTS ficha_llm(
  legislatura INTEGER NOT NULL,
  expediente TEXT NOT NULL,
  resumen TEXT,
  bloques TEXT,
  tema_principal TEXT,
  temas_secundarios TEXT,
  etiquetas TEXT,
  ambito TEXT,
  marcas TEXT,
  leyes_afectadas TEXT,
  confianza REAL,
  fuente_texto TEXT,
  modelo TEXT,
  version_prompt TEXT,
  version_taxonomia TEXT,
  creado TEXT,
  PRIMARY KEY(legislatura, expediente)
);
CREATE INDEX IF NOT EXISTS ix_ficha_tema ON ficha_llm(tema_principal);

-- Tema provisional por reglas (comisión competente), sin IA. La web lo usa si no hay ficha IA.
CREATE TABLE IF NOT EXISTS tema_provisional(
  legislatura INTEGER NOT NULL,
  expediente TEXT NOT NULL,
  comision TEXT,
  tema_principal TEXT,
  temas_secundarios TEXT,
  regla TEXT,
  version TEXT,
  creado TEXT,
  PRIMARY KEY(legislatura, expediente)
);

-- Afinidad precalculada entre grupos (global y por tema).
CREATE TABLE IF NOT EXISTS afinidad(
  legislatura INTEGER NOT NULL,
  tema TEXT NOT NULL,
  grupo_a TEXT NOT NULL,
  grupo_b TEXT NOT NULL,
  coinciden INTEGER NOT NULL,
  total INTEGER NOT NULL,
  PRIMARY KEY(legislatura, tema, grupo_a, grupo_b)
) WITHOUT ROWID;

-- Textos de análisis redactados por la IA a partir de las estadísticas.
CREATE TABLE IF NOT EXISTS informe_ia(
  clave TEXT PRIMARY KEY,
  titulo TEXT,
  contenido TEXT,
  modelo TEXT,
  creado TEXT
);
"""

# Solo en la base de trabajo: se reconstruyen desde data/llm/programas/ y no van en los ficheros de data/bd/
# (añadirlas a su esquema cambiaría la huella de todos y se reescribirían enteros).
SCHEMA_PROGRAMAS = """
-- Programas electorales y sus compromisos: se reconstruyen desde data/llm/programas/ (escrutinio/programas).
CREATE TABLE IF NOT EXISTS programa(
  id TEXT PRIMARY KEY,
  eleccion TEXT,
  fecha_eleccion TEXT,
  cuerpo TEXT,
  legislatura INTEGER,
  partido TEXT,
  titulo TEXT,
  origen TEXT,
  url TEXT,
  url_oficial TEXT,
  descargado TEXT,
  paginas INTEGER,
  estado TEXT,
  leido TEXT,
  version_prompt TEXT,
  compromisos INTEGER,
  verificables INTEGER
);
CREATE TABLE IF NOT EXISTS compromiso(
  id TEXT PRIMARY KEY,
  programa TEXT NOT NULL,
  orden INTEGER,
  texto TEXT,
  cita TEXT,
  pagina INTEGER,
  tema TEXT,
  etiquetas TEXT,
  tipo_accion TEXT,
  responsable TEXT,
  verificable INTEGER
);
-- Sentido de la iniciativa respecto al compromiso: misma, contraria o relacionada. Estado: propuesto (primera
-- pasada) o verificado (segunda revisión, programas/verificar.py).
CREATE TABLE IF NOT EXISTS compromiso_iniciativa(
  compromiso TEXT NOT NULL,
  legislatura INTEGER NOT NULL,
  expediente TEXT NOT NULL,
  sentido TEXT,
  justificacion TEXT,
  origen TEXT,
  estado TEXT,
  rango INTEGER,
  PRIMARY KEY(compromiso, legislatura, expediente)
);
-- Derivada: lo que votó el partido en lo relacionado con cada compromiso (programas/cargar.py).
CREATE TABLE IF NOT EXISTS compromiso_estado(
  compromiso TEXT PRIMARY KEY,
  partido TEXT,
  legislatura INTEGER,
  estado TEXT,
  impulsa INTEGER,
  coherentes INTEGER,
  incoherentes INTEGER,
  abstenciones INTEGER,
  aprobada INTEGER,
  gobierno INTEGER
);
"""


def connect(path=DB_PATH):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=120, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=OFF")
    return con


def _migrar(con):
    """Pone al día bases creadas con versiones anteriores del esquema."""
    columnas = {r[1] for r in con.execute("PRAGMA table_info(votacion)")}
    for columna, tipo in (("aviso", "TEXT"), ("enmienda_grupo", "TEXT"), ("enmienda_autor", "TEXT"),
                          ("enmiendas_n", "INTEGER"), ("transaccional", "INTEGER"),
                          # Votaciones territoriales: resultado que publica la fuente y cómo se obtuvo el dato.
                          ("resultado_oficial", "TEXT"), ("fuente", "TEXT")):
        if columna not in columnas:
            con.execute(f"ALTER TABLE votacion ADD COLUMN {columna} {tipo}")
    columnas = {r[1] for r in con.execute("PRAGMA table_info(legislatura)")}
    for columna, tipo in (("cuerpo", "TEXT NOT NULL DEFAULT 'congreso'"), ("numero", "INTEGER"), ("escanos", "INTEGER")):
        if columna not in columnas:
            con.execute(f"ALTER TABLE legislatura ADD COLUMN {columna} {tipo}")
    # Antes el nombre del diputado era único en toda la base (solo había Congreso).
    if "cuerpo" not in {r[1] for r in con.execute("PRAGMA table_info(diputado)")}:
        con.executescript("""
            ALTER TABLE diputado RENAME TO diputado_viejo;
            CREATE TABLE diputado(id INTEGER PRIMARY KEY, nombre TEXT NOT NULL,
              cuerpo TEXT NOT NULL DEFAULT 'congreso', UNIQUE(cuerpo, nombre));
            INSERT INTO diputado(id, nombre) SELECT id, nombre FROM diputado_viejo;
            DROP TABLE diputado_viejo;""")


def legislaturas_congreso():
    return sorted(LEGISLATURAS)


def cargar_catalogo_territorial(con):
    """Instituciones, sus legislaturas y el árbol de ámbitos (territorio.py y los conectores)."""
    from . import territorio

    cuerpos = territorio.cuerpos()
    con.execute("DELETE FROM cuerpo")
    con.executemany(
        "INSERT INTO cuerpo(codigo, num, nombre, corto, nivel, ccaa, escanos, web) VALUES (?,?,?,?,?,?,?,?)",
        [(c.codigo, c.num, c.nombre, c.corto, c.nivel, c.ccaa, c.escanos, c.web) for c in cuerpos],
    )
    con.executemany(
        "INSERT OR REPLACE INTO legislatura(id, romano, inicio, fin, cuerpo, numero, escanos) VALUES (?,?,?,?,?,?,?)",
        [(c.id_leg(n), t[0], t[1], t[2], c.codigo, n, c.escanos_de(n)) for c in cuerpos for n, t in c.legislaturas.items()],
    )
    con.execute("DELETE FROM ambito")
    con.executemany("INSERT INTO ambito(codigo, padre, nombre, nivel, cuerpo, orden) VALUES (?,?,?,?,?,?)",
                    territorio.arbol())


def init(con, catalogos=True):
    con.executescript(SCHEMA)
    _migrar(con)
    if not catalogos:
        con.commit()
        return
    con.executescript(SCHEMA_PROGRAMAS)
    from .catalogos import TIPOS_EXPEDIENTE, TEMAS
    from .territorial.modelo import TIPOS_INICIATIVA

    con.executemany(
        "INSERT OR REPLACE INTO tipo_expediente(prefijo, nombre, familia, fuerza_ley) VALUES (?,?,?,?)",
        TIPOS_EXPEDIENTE + [(k, n, f, int(f in ("ley", "decreto_ley"))) for k, (n, f) in TIPOS_INICIATIVA.items()],
    )
    con.executemany("INSERT OR REPLACE INTO tema(codigo, nombre, subtemas) VALUES (?,?,?)", TEMAS)
    cargar_catalogo_territorial(con)
    con.commit()
