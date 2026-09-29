"use strict";

// ------------------------------------------------------------------ utilidades

let META = null;
const $ = (sel, root = document) => root.querySelector(sel);

function el(tag, attrs, ...hijos) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "style") n.setAttribute("style", v);
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (k === "html") n.innerHTML = v; // solo para marcado propio, nunca datos
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const h of hijos.flat(Infinity)) {
    if (h === null || h === undefined || h === false) continue;
    n.appendChild(h instanceof Node ? h : document.createTextNode(String(h)));
  }
  return n;
}

// ------------------------------------------------------------------ móvil
// Se considera móvil una pantalla estrecha o un teléfono girado (táctil y con poca altura).
// La clase «movil» en <html> activa la interfaz para móvil (styles.css) y los gráficos se
// dibujan al ancho de la pantalla para que los textos no encojan.

const MQ_MOVIL = matchMedia("(max-width: 700px), (pointer: coarse) and (max-height: 500px)");
const esMovil = () => MQ_MOVIL.matches;
document.documentElement.classList.toggle("movil", esMovil());

// Ancho del lienzo de un gráfico SVG: en móvil, el de la pantalla (menos márgenes).
const anchoGrafico = (defecto) => (esMovil() ? Math.max(280, Math.min(defecto, window.innerWidth - 40)) : defecto);

// ------------------------------------------------------------------ base de datos local (sql.js)
// La SQLite viaja troceada y comprimida en datos/*.js: comun.js (catálogos, instituciones y árbol de
// ámbitos) y un <institución>/legNN.js por legislatura, listados en datos/indice.js. Se cargan con
// <script> (funciona con file://) y se juntan en una sola base en memoria, que se consulta con SQL.
// Solo se cargan los ficheros de las instituciones del ámbito elegido (ambito.js): al cambiar de
// ámbito se rehace la base con los que tocan, y los ya descargados no se vuelven a pedir.

let DB = null;
let SQL = null;
let COMUN = null;     // comun.js ya descomprimido: es la base de partida de cada montaje
let CATALOGO = null;  // instituciones, árbol de ámbitos, legislaturas y ficheros (de comun e indice)

function b64aBytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

async function descomprimir(b64) {
  const flujo = new Blob([b64aBytes(b64)]).stream().pipeThrough(new DecompressionStream("gzip"));
  return new Uint8Array(await new Response(flujo).arrayBuffer());
}

function cargarScript(src) {
  return new Promise((ok, mal) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => mal(new Error(`no se pudo cargar ${src}`));
    document.head.appendChild(s);
  });
}

// En un servidor (GitHub Pages) la huella en la URL evita servir datos viejos de la caché.
const conVersion = (f) => `datos/${f.nombre}.js${location.protocol.startsWith("http") ? `?v=${f.huella}` : ""}`;
const DATOS = () => (window.ESCRUTINIO_DATOS = window.ESCRUTINIO_DATOS || {});

// Abre comun.js y lee el catálogo: qué instituciones hay, su árbol y qué fichero trae cada legislatura.
async function abrirCatalogo() {
  const indice = window.ESCRUTINIO_INDICE;
  if (!indice) throw new Error("Falta web/datos/indice.js. Genéralo con: python -m escrutinio web");
  SQL = await initSqlJs({ wasmBinary: b64aBytes(window.SQL_WASM_B64) });
  delete window.SQL_WASM_B64;
  const comun = indice.ficheros.find((f) => f.nombre === "comun");
  await cargarScript(conVersion(comun));
  COMUN = await descomprimir(DATOS().comun);
  delete DATOS().comun;
  const base = new SQL.Database(COMUN);
  const filas = (sql) => {
    try {
      const r = base.exec(sql)[0];
      return r ? r.values.map((v) => Object.fromEntries(r.columns.map((c, i) => [c, v[i]]))) : [];
    } catch { return null; } // datos generados con una versión anterior, sin catálogo territorial
  };
  // programas.js no es de ninguna institución: se carga aparte, solo cuando hace falta (programas.js).
  const ficheros = indice.ficheros.filter((f) => f.nombre !== "comun" && f.nombre !== "programas").map((f) => ({ ...f, cuerpo: f.cuerpo || "congreso" }));
  CATALOGO = {
    generado: indice.generado,
    avisos: indice.avisos || {},  // instituciones que no respondieron en la última actualización
    ficheros,
    programas: indice.ficheros.find((f) => f.nombre === "programas") || null,
    ambitos: filas("SELECT * FROM ambito ORDER BY orden, nombre") ||
      [{ codigo: "es", padre: null, nombre: "Toda España" }, { codigo: "congreso", padre: "es", nombre: "Congreso de los Diputados", nivel: "nacional", cuerpo: "congreso" }],
    cuerpos: Object.fromEntries((filas("SELECT * FROM cuerpo") ||
      [{ codigo: "congreso", nombre: "Congreso de los Diputados", corto: "Congreso", nivel: "nacional", escanos: 350 }]).map((c) => [c.codigo, c])),
    legs: filas("SELECT * FROM legislatura ORDER BY id") || [],
  };
  base.close();
}

// Monta en memoria la base con comun y las legislaturas de las instituciones elegidas.
async function montarBD(cuerpos, avisar = () => {}) {
  const ficheros = CATALOGO.ficheros.filter((f) => cuerpos.has(f.cuerpo));
  const faltan = ficheros.filter((f) => !DATOS()[f.nombre]);
  if (faltan.length) {
    const mb = faltan.reduce((a, f) => a + f.bytes, 0) / 1e6;
    const lento = mb * 1e6 > AMBITO_PESADO_BYTES ? " Es mucha información: puede tardar un rato." : "";
    avisar(`Descargando ${faltan.length} fichero${faltan.length === 1 ? "" : "s"} de datos (${mb.toLocaleString("es-ES", { maximumFractionDigits: 1 })} MB)…${lento}`);
    await Promise.all(faltan.map((f) => cargarScript(conVersion(f))));
  }
  if (DB) DB.close();
  DB = new SQL.Database(COMUN);
  for (const f of ficheros) {
    const c = CATALOGO.cuerpos[f.cuerpo];
    avisar(`Abriendo ${c ? c.corto || c.nombre : f.cuerpo} · ${f.nombre.split("/").pop().replace(/^leg(\d+)$/, "legislatura $1")}…`);
    // Los base64 se quedan en memoria (son la versión comprimida): cambiar de ámbito no vuelve a descargarlos.
    // sql.js guarda cada base en su sistema de ficheros en memoria: se adjunta y se copian las filas.
    const trozo = new SQL.Database(await descomprimir(DATOS()[f.nombre]));
    DB.exec(`ATTACH DATABASE '/${trozo.filename}' AS l`);
    DB.exec("BEGIN");
    for (const { name } of q("SELECT name FROM l.sqlite_master WHERE type = 'table'")) {
      DB.exec(`INSERT OR IGNORE INTO main."${name}" SELECT * FROM l."${name}"`);
    }
    DB.exec("COMMIT");
    DB.exec("DETACH DATABASE l");
    trozo.close();
  }
  DB.exec("INSERT OR REPLACE INTO meta VALUES ('generado', ?)", [CATALOGO.generado]);
  crearPesos();
  for (const k of Object.keys(plantillas)) delete plantillas[k];
}

// Peso de cada votación decisiva de fondo para que cada asunto cuente una vez: una PNL votada en
// 8 puntos no pesa 8 veces más que una ley. Los puntos de un asunto se reparten su peso a partes
// iguales. En los debates con propuestas de resolución, las de cada grupo cuentan como un asunto.
function crearPesos() {
  DB.exec(`CREATE TEMP TABLE peso(votacion_id INTEGER PRIMARY KEY, peso REAL);
    INSERT INTO peso SELECT v.id, 1.0 / u.n FROM votacion v
    JOIN (SELECT v.legislatura, v.expediente, ${SQL_PROPONE} AS propone, COUNT(*) AS n FROM votacion v
          WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) GROUP BY 1, 2, 3) u
      ON u.legislatura=v.legislatura AND u.expediente=v.expediente AND u.propone=${SQL_PROPONE}
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL});`);
}

function q(sql, params = []) {
  const st = DB.prepare(sql);
  st.bind(params.map((v) => (v === undefined ? null : v)));
  const filas = [];
  while (st.step()) filas.push(st.getAsObject());
  st.free();
  return filas;
}
const q1 = (sql, params) => q(sql, params)[0];
// ---- filtros con varias opciones: los valores van separados por comas en la URL ----
const lista = (v) => String(v ?? "").split(",").map((s) => s.trim()).filter(Boolean);

// Añade «columna IN (…)» si el filtro tiene valores.
function condIn(w, a, columna, valor, conv = (x) => x) {
  const xs = lista(valor);
  if (!xs.length) return;
  w.push(`${columna} IN (${xs.map(() => "?").join(",")})`);
  a.push(...xs.map(conv));
}
// Igual, pero devuelve el trozo de SQL para intercalarlo en consultas ya escritas.
function enSQL(columna, valor, { conector = "AND", conv = (x) => x } = {}) {
  const xs = lista(valor);
  return xs.length ? [` ${conector} ${columna} IN (${xs.map(() => "?").join(",")})`, xs.map(conv)] : ["", []];
}
// Tema principal (y opcionalmente secundario) igual a cualquiera de los elegidos.
function condTema(w, a, valor, secundarios = true, alias = "f") {
  const xs = lista(valor);
  if (!xs.length) return;
  const partes = xs.map(() => `${alias}.tema_principal=?`);
  const args = [...xs];
  if (secundarios) for (const t of xs) { partes.push(`${alias}.temas_secundarios LIKE ?`); args.push(`%"${t}"%`); }
  w.push(`(${partes.join(" OR ")})`);
  a.push(...args);
}
// Campo JSON (etiquetas, marcas) que contiene cualquiera de los valores.
function condJson(w, a, columna, valor) {
  const xs = lista(valor);
  if (!xs.length) return;
  w.push(`(${xs.map(() => `${columna} LIKE ?`).join(" OR ")})`);
  a.push(...xs.map((x) => `%"${x}"%`));
}
function condFamilia(w, a, valor, columna = "te.familia") {
  const fams = lista(valor).flatMap((f) => (typeof FAMILIAS_AGRUPADAS !== "undefined" && FAMILIAS_AGRUPADAS[f]) || [f]);
  if (!fams.length) return;
  w.push(`${columna} IN (${fams.map(() => "?").join(",")})`);
  a.push(...fams);
}

const jsonDe = (v, d) => { try { return v ? JSON.parse(v) : d; } catch { return d; } };

async function api(ruta, params = {}) {
  const limpio = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== null && v !== undefined).map(([k, v]) => [k, String(v)]));
  return API[ruta](limpio);
}

const TIPOS_VOTACION = {
  pnl: "Proposición no de ley", mocion: "Moción", toma_consideracion: "Toma en consideración",
  totalidad: "Enmienda a la totalidad", enmiendas: "Enmiendas / votos particulares", articulado: "Dictamen (articulado)",
  conjunto: "Votación de conjunto", enmiendas_senado: "Enmiendas del Senado", veto_senado: "Veto del Senado",
  convalidacion: "Convalidación de real decreto-ley", tramitacion_ley: "Tramitación como proyecto de ley",
  tratado: "Convenio internacional", investidura: "Investidura, confianza o censura", nombramiento: "Elección o nombramiento",
  organizacion: "Organización de la Cámara", control: "Control / propuestas de resolución", otro: "Otro",
};
const FAMILIAS = {
  ley: "Leyes", decreto_ley: "Decretos-leyes", pnl: "Proposiciones no de ley", mocion: "Mociones",
  internacional: "Convenios internacionales", organizacion: "Organización", control: "Control", otro: "Otros",
};
const TIPOS_FONDO = ["pnl", "mocion", "toma_consideracion", "totalidad", "conjunto", "convalidacion", "tramitacion_ley",
  "tratado", "enmiendas_senado", "veto_senado", "investidura", "control"];
const LETRA_SENTIDO = { S: "si", N: "no", A: "abstencion", "-": "no_vota" };
// Grupos que reúnen partidos distintos: votar distinto a su mayoría no es romper la disciplina.
const GRUPOS_HETEROGENEOS = new Set(["GMx", "GPlu", "?", "Mixto", "No adscritos"]);
const SQL_HETEROGENEOS = [...GRUPOS_HETEROGENEOS].map((g) => `'${g}'`).join(",");

const API = {};

API.meta = () => {
  const info = Object.fromEntries(q("SELECT * FROM legislatura").map((r) => [r.id, r]));
  const legislaturas = q("SELECT legislatura AS id, COUNT(*) AS votaciones, MIN(fecha) AS desde, MAX(fecha) AS hasta FROM votacion GROUP BY legislatura ORDER BY legislatura")
    .map((l) => {
      const i = info[l.id] || { romano: l.id, cuerpo: "congreso" };
      const c = CATALOGO.cuerpos[i.cuerpo] || { corto: i.cuerpo, nombre: i.cuerpo };
      return { ...l, romano: i.romano, cuerpo: i.cuerpo || "congreso", numero: i.numero || l.id, escanos: i.escanos || 350,
        corto: c.corto || c.nombre, cuerpo_nombre: c.nombre, nivel: c.nivel };
    });
  const cuerpos = [...new Set(legislaturas.map((l) => l.cuerpo))];
  const grupos = {};
  for (const g of q("SELECT * FROM grupo ORDER BY legislatura, diputados DESC")) (grupos[g.legislatura] = grupos[g.legislatura] || []).push(g);
  const meta = Object.fromEntries(q("SELECT clave, valor FROM meta").map((r) => [r.clave, r.valor]));
  return {
    legislaturas, grupos, cuerpos, multi: cuerpos.length > 1, soloCongreso: cuerpos.length === 1 && cuerpos[0] === "congreso",
    temas: q("SELECT codigo, nombre, subtemas FROM tema ORDER BY rowid"),
    gobiernos: q("SELECT * FROM gobierno ORDER BY cuerpo, desde"),
    tipos_votacion: TIPOS_VOTACION, familias: FAMILIAS, tipos_fondo: TIPOS_FONDO,
    totales: {
      votaciones: q1("SELECT COUNT(*) AS n FROM votacion").n,
      // Votos individuales emitidos (o no) y personas distintas, en lo que está cargado.
      votos: q1("SELECT SUM(LENGTH(REPLACE(sentidos, '.', ''))) AS n FROM voto_nominal").n || 0,
      diputados: q1("SELECT COUNT(DISTINCT diputado_id) AS n FROM plantilla").n, generado: meta.generado,
      fichas: q1("SELECT COUNT(*) AS n FROM ficha_llm WHERE modelo NOT LIKE 'reglas%'").n,
      provisionales: q1("SELECT COUNT(*) AS n FROM ficha_llm WHERE modelo LIKE 'reglas%'").n,
      iniciativas: q1("SELECT COUNT(*) AS n FROM iniciativa").n,
    },
    modelos: q("SELECT modelo, version_prompt, COUNT(*) AS n FROM ficha_llm WHERE modelo NOT LIKE 'reglas%' GROUP BY 1, 2"),
  };
};

const BASE_VOTACION = `
  FROM votacion v
  LEFT JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
  LEFT JOIN tipo_expediente te ON te.prefijo=v.prefijo
  LEFT JOIN ficha_llm f ON f.legislatura=v.legislatura AND f.expediente=v.expediente`;
// Derrota del Gobierno: perdió lo que votó el partido del presidente (votó sí y se rechazó, o no y se aprobó).
// No cuenta si el resultado de la fuente no cuadra con los totales (lleva aviso); un empate, sí.
const SQL_DERROTA = `((v.aviso IS NULL OR v.aviso LIKE 'Empate%') AND EXISTS (SELECT 1 FROM gobierno go
    JOIN legislatura lg ON lg.id=v.legislatura AND lg.cuerpo=go.cuerpo
    JOIN voto_grupo gg ON gg.votacion_id=v.id
    JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=gg.grupo AND gr.siglas=go.partido
    WHERE v.fecha>=go.desde AND (go.hasta IS NULL OR v.fecha<=go.hasta)
      AND ((gg.sentido='si' AND v.resultado='rechazada') OR (gg.sentido='no' AND v.resultado='aprobada'))))`;

function filtrosVotacion(p) {
  const w = ["1=1"], a = [];
  condIn(w, a, "v.legislatura", p.leg, Number);
  if (p.desde) { w.push("v.fecha>=?"); a.push(p.desde); }
  if (p.hasta) { w.push("v.fecha<=?"); a.push(p.hasta); }
  condIn(w, a, "v.tipo_votacion", p.tipo);
  condFamilia(w, a, p.familia);
  condTema(w, a, p.tema);
  condIn(w, a, "v.resultado", p.resultado);
  if (p.decisivas === "1") w.push("v.decisiva=1");
  if (p.ajustadas === "1") w.push("v.asentimiento=0 AND ABS(v.margen) <= 10");
  if (p.derrotas === "1") w.push(SQL_DERROTA);
  condIn(w, a, "i.grupo_autor", p.autor);
  if (p.exp) { w.push("v.expediente=?"); a.push(p.exp); }
  for (const palabra of (p.q || "").split(/\s+/).filter(Boolean)) {
    w.push("(v.texto_expediente LIKE ? OR f.resumen LIKE ? OR f.etiquetas LIKE ? OR v.expediente LIKE ?)");
    a.push(...Array(4).fill(`%${palabra}%`));
  }
  return [w.join(" AND "), a];
}

API.votaciones = (p) => {
  const [where, args] = filtrosVotacion(p);
  const pagina = Math.max(1, +(p.pagina || 1));
  const tam = Math.min(200, +(p.tam || 50));
  const orden = p.orden === "asc" ? "v.fecha ASC, v.sesion, v.numero" : "v.fecha DESC, v.sesion DESC, v.numero DESC";
  const total = q1(`SELECT COUNT(*) AS n ${BASE_VOTACION} WHERE ${where}`, args).n;
  const filas = q(`SELECT v.*, te.familia, i.titulo, i.autor, i.grupo_autor, i.sintetica, f.tema_principal, f.resumen,
      ${SQL_DERROTA} AS derrota
    ${BASE_VOTACION} WHERE ${where} ORDER BY ${orden} LIMIT ? OFFSET ?`, [...args, tam, (pagina - 1) * tam]);
  if (filas.length) {
    const ids = filas.map((f) => f.id);
    const marcas = ids.map(() => "?").join(",");
    const grupos = {}, decis = {};
    for (const g of q(`SELECT * FROM voto_grupo WHERE votacion_id IN (${marcas})`, ids)) (grupos[g.votacion_id] = grupos[g.votacion_id] || []).push(g);
    for (const g of q(`SELECT * FROM grupo_decisivo WHERE votacion_id IN (${marcas})`, ids)) (decis[g.votacion_id] = decis[g.votacion_id] || []).push(g);
    for (const f of filas) { f.grupos = grupos[f.id] || []; f.decisivos = decis[f.id] || []; }
  }
  return { total, pagina, tam, votaciones: filas };
};

const plantillas = {};
function plantilla(leg) {
  if (!plantillas[leg]) plantillas[leg] = q("SELECT p.pos, d.id, d.nombre FROM plantilla p JOIN diputado d ON d.id=p.diputado_id WHERE p.legislatura=? ORDER BY p.pos", [leg]);
  return plantillas[leg];
}

function iniciativaDict(i) {
  if (!i) return null;
  const lineas = (t) => (t || "").split("\n").filter(Boolean);
  return { ...i, bocg: lineas(i.bocg), boe: lineas(i.boe) };
}
function fichaDict(f) {
  if (!f) return null;
  return { ...f, bloques: jsonDe(f.bloques, []), temas_secundarios: jsonDe(f.temas_secundarios, []), etiquetas: jsonDe(f.etiquetas, []),
    marcas: jsonDe(f.marcas, []), leyes_afectadas: jsonDe(f.leyes_afectadas, []) };
}

API.votacion = (p) => {
  const v = q1(`SELECT v.*, te.familia, te.nombre AS tipo_iniciativa, ${SQL_DERROTA} AS derrota
    FROM votacion v LEFT JOIN tipo_expediente te ON te.prefijo=v.prefijo WHERE v.id=?`, [+p.id]);
  if (!v) throw new Error("No existe la votación");
  const ini = q1("SELECT * FROM iniciativa WHERE legislatura=? AND expediente=?", [v.legislatura, v.expediente]);
  const ficha = q1("SELECT * FROM ficha_llm WHERE legislatura=? AND expediente=?", [v.legislatura, v.expediente]);
  const grupos = q("SELECT * FROM voto_grupo WHERE votacion_id=? ORDER BY si+no+abstencion+no_vota DESC", [v.id]);
  const decisivos = q("SELECT grupo, modo FROM grupo_decisivo WHERE votacion_id=?", [v.id]);
  // Voto nominal: un carácter por diputado de la plantilla; el grupo sale de sus tramos en esa fecha.
  const cadena = (q1("SELECT sentidos FROM voto_nominal WHERE votacion_id=?", [v.id]) || {}).sentidos || "";
  const grupoDe = {};
  for (const t of q("SELECT diputado_id, grupo FROM diputado_grupo WHERE legislatura=? AND ? BETWEEN desde AND hasta", [v.legislatura, v.fecha])) grupoDe[t.diputado_id] = t.grupo;
  const mayoriaGrupo = Object.fromEntries(grupos.map((g) => [g.grupo, g.sentido]));
  const votos = [];
  for (const d of plantilla(v.legislatura)) {
    const s = LETRA_SENTIDO[cadena[d.pos - 1]];
    if (!s) continue;
    const grupo = grupoDe[d.id] || "?";
    const sg = mayoriaGrupo[grupo];
    votos.push({ id: d.id, nombre: d.nombre, grupo, sentido: s,
      disidente: !GRUPOS_HETEROGENEOS.has(grupo) && ["si", "no", "abstencion"].includes(sg) && ["si", "no", "abstencion"].includes(s) && s !== sg });
  }
  votos.sort((a, b) => a.grupo.localeCompare(b.grupo) || a.nombre.localeCompare(b.nombre));
  const otras = q(`SELECT id, fecha, tipo_votacion, titulo_subgrupo, texto_subgrupo, resultado, a_favor, en_contra, abstenciones, asentimiento, decisiva
    FROM votacion WHERE legislatura=? AND expediente=? ORDER BY fecha, sesion, numero`, [v.legislatura, v.expediente]);
  return { votacion: v, iniciativa: iniciativaDict(ini), ficha: fichaDict(ficha), grupos, decisivos, votos, otras };
};

API.iniciativas = (p) => {
  const w = ["1=1"], a = [];
  condIn(w, a, "i.legislatura", p.leg, Number);
  condTema(w, a, p.tema);
  condFamilia(w, a, p.familia);
  condIn(w, a, "i.grupo_autor", p.autor);
  condIn(w, a, "i.resultado_final", p.resultado);
  condJson(w, a, "f.marcas", p.marca);
  condJson(w, a, "f.etiquetas", p.etiqueta);
  for (const palabra of (p.q || "").split(/\s+/).filter(Boolean)) {
    w.push("(i.titulo LIKE ? OR f.resumen LIKE ? OR f.etiquetas LIKE ? OR i.expediente LIKE ?)");
    a.push(...Array(4).fill(`%${palabra}%`));
  }
  const base = `FROM iniciativa i
    JOIN (SELECT legislatura, expediente, COUNT(*) nvot, MIN(fecha) primera, MAX(fecha) ultima FROM votacion GROUP BY legislatura, expediente) vv
      ON vv.legislatura=i.legislatura AND vv.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    LEFT JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    WHERE ${w.join(" AND ")}`;
  const pagina = Math.max(1, +(p.pagina || 1));
  const tam = Math.min(200, +(p.tam || 50));
  const total = q1(`SELECT COUNT(*) AS n ${base}`, a).n;
  const filas = q(`SELECT i.legislatura, i.expediente, i.titulo, i.autor, i.grupo_autor, i.resultado_final, i.resultado_tramitacion,
      i.sintetica, te.familia, te.nombre AS tipo, vv.nvot, vv.primera, vv.ultima, f.resumen, f.tema_principal,
      f.temas_secundarios, f.etiquetas, f.marcas, f.confianza
    ${base} ORDER BY vv.ultima DESC LIMIT ? OFFSET ?`, [...a, tam, (pagina - 1) * tam]);
  for (const f of filas) for (const k of ["temas_secundarios", "etiquetas", "marcas"]) f[k] = jsonDe(f[k], []);
  return { total, pagina, tam, iniciativas: filas };
};

API.iniciativa = (p) => ({
  iniciativa: iniciativaDict(q1("SELECT * FROM iniciativa WHERE legislatura=? AND expediente=?", [+p.leg, p.exp])),
  ficha: fichaDict(q1("SELECT * FROM ficha_llm WHERE legislatura=? AND expediente=?", [+p.leg, p.exp])),
  votaciones: API.votaciones({ leg: p.leg, exp: p.exp, tam: "200", orden: "asc" }).votaciones,
});

// Legislatura en curso (la última con datos) de cada institución cargada.
function legsActuales() {
  const ultima = new Map();
  for (const l of META.legislaturas) ultima.set(l.cuerpo, l.id);
  return [...ultima.values()];
}
// Legislaturas elegidas en un filtro; si no hay ninguna, la actual de cada institución.
const legsOActual = (valor) => (lista(valor).length ? lista(valor) : legsActuales().map(String))
  .map(Number).sort((a, b) => a - b);
const textoLegs = (legs) => (META.multi ? legs.map(legTexto).join(" + ") : `Leg. ${legs.map(romano).join(" + ")}`);
const textoTemas = (temas) => temas.map(temaNombre).join(" + ");

// Afinidad sumada por siglas en varias legislaturas y temas (sin temas elegidos: todos).
function afinidadSiglas(legs, temas) {
  const w = ["af.grupo_a<>'?'", "af.grupo_b<>'?'"], a = [];
  condIn(w, a, "af.legislatura", legs.join(","), Number);
  if (temas.length) condIn(w, a, "af.tema", temas.join(","));
  else w.push("af.tema='*'");
  return q(`SELECT ga.siglas AS a, gb.siglas AS b, SUM(af.coinciden) AS coinciden, SUM(af.total) AS total
    FROM afinidad af
    JOIN grupo ga ON ga.legislatura=af.legislatura AND ga.codigo=af.grupo_a
    JOIN grupo gb ON gb.legislatura=af.legislatura AND gb.codigo=af.grupo_b
    WHERE ${w.join(" AND ")} GROUP BY 1, 2`, a);
}

// Grupos (por siglas) de unas legislaturas, con nombre, color y diputados de la más reciente.
function gruposDeLegs(legs, minimo = 2) {
  const out = new Map();
  for (const l of [...legs].sort((x, y) => x - y)) {
    for (const g of META.grupos[l] || []) if (g.codigo !== "?") out.set(g.siglas, { ...g, leg: l });
  }
  return [...out.values()].filter((g) => g.diputados >= minimo).sort((a, b) => b.diputados - a.diputados);
}

API.afinidad = (p) => ({ pares: afinidadSiglas(legsOActual(p.leg), lista(p.tema).filter((t) => t !== "*")) });

API.temas = (p) => ({
  filas: q(`SELECT f.tema_principal AS tema, te.familia, i.grupo_autor, i.resultado_final, COUNT(*) AS n
    FROM iniciativa i
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    ${enSQL("i.legislatura", p.leg, { conector: "WHERE", conv: Number })[0]} GROUP BY 1, 2, 3, 4`, enSQL("i.legislatura", p.leg, { conv: Number })[1])
    .filter((r) => r.tema), // los debates de política general no tienen tema
});

API.decisivos = (p) => {
  const [wl, al] = enSQL("v.legislatura", legsOActual(p.leg).join(","), { conv: Number });
  return {
    decisivas_nominales: q1(`SELECT COUNT(*) AS n FROM votacion v WHERE v.decisiva=1 AND v.asentimiento=0 ${wl}`, al).n,
    filas: q(`SELECT gr.siglas, MAX(gr.color) AS color, d.modo, COUNT(*) AS n FROM grupo_decisivo d
      JOIN votacion v ON v.id=d.votacion_id JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=d.grupo
      WHERE v.decisiva=1 AND d.grupo<>'?' ${wl} GROUP BY 1, 3`, al),
    ejemplos: q(`SELECT v.id, v.fecha, v.legislatura, v.texto_expediente, v.tipo_votacion, v.resultado, v.a_favor, v.en_contra,
        v.abstenciones, v.margen, GROUP_CONCAT(d.grupo) AS grupos
      FROM votacion v JOIN grupo_decisivo d ON d.votacion_id=v.id
      WHERE v.decisiva=1 AND d.modo='absteniendose'
        AND v.tipo_votacion IN ('conjunto','convalidacion','toma_consideracion','totalidad') ${wl}
      GROUP BY v.id ORDER BY ABS(v.margen), v.fecha DESC LIMIT 25`, al),
  };
};

API.resumen = () => ({
  decisivas: q(`SELECT i.legislatura, te.familia, i.resultado_final AS resultado, COUNT(*) AS n
    FROM iniciativa i LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo GROUP BY 1, 2, 3`),
  por_tema: q(`SELECT f.legislatura, f.tema_principal AS tema, COUNT(*) AS n
    FROM ficha_llm f JOIN iniciativa i ON i.legislatura=f.legislatura AND i.expediente=f.expediente GROUP BY 1, 2`),
  mensual: q(`SELECT legislatura, substr(fecha,1,7) AS mes, COUNT(*) AS n, SUM(asentimiento=0 AND ABS(margen)<=10) AS ajustadas
    FROM votacion GROUP BY 1, 2 ORDER BY 2`),
});

API.etiquetas = (p) => {
  const cont = new Map(), temas = new Map();
  const [sqlLeg, argsLeg] = enSQL("f.legislatura", p.leg, { conector: "WHERE", conv: Number });
  for (const r of q(`SELECT f.etiquetas, f.tema_principal FROM ficha_llm f
      JOIN iniciativa i ON i.legislatura=f.legislatura AND i.expediente=f.expediente ${sqlLeg}`, argsLeg)) {
    for (const e of jsonDe(r.etiquetas, [])) {
      cont.set(e, (cont.get(e) || 0) + 1);
      const t = temas.get(e) || {};
      t[r.tema_principal] = (t[r.tema_principal] || 0) + 1;
      temas.set(e, t);
    }
  }
  return { etiquetas: [...cont.entries()].sort((a, b) => b[1] - a[1]).slice(0, 80)
    .map(([etiqueta, n]) => ({ etiqueta, n, tema: Object.entries(temas.get(etiqueta)).sort((a, b) => b[1] - a[1])[0][0] })) };
};

API.leyes = () => {
  const cont = new Map(), ejemplos = new Map();
  for (const r of q(`SELECT f.leyes_afectadas, f.legislatura, f.expediente, i.titulo, i.resultado_final, te.familia
      FROM ficha_llm f JOIN iniciativa i ON i.legislatura=f.legislatura AND i.expediente=f.expediente
      LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo`)) {
    for (const ley of jsonDe(r.leyes_afectadas, [])) {
      cont.set(ley, (cont.get(ley) || 0) + 1);
      const ej = ejemplos.get(ley) || [];
      if (ej.length < 40) ej.push({ leg: r.legislatura, exp: r.expediente, titulo: r.titulo, resultado: r.resultado_final, familia: r.familia });
      ejemplos.set(ley, ej);
    }
  }
  return { leyes: [...cont.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40).map(([ley, n]) => ({ ley, n, iniciativas: ejemplos.get(ley) })) };
};

API.diputado = (p) => {
  const id = +p.id;
  return {
    diputado: q1("SELECT * FROM diputado WHERE id=?", [id]),
    grupos: q(`SELECT legislatura, grupo, votaciones AS n, desde, hasta, ausencias FROM diputado_grupo WHERE diputado_id=? ORDER BY desde`, [id]),
    disidencias: q(`SELECT * FROM (
        SELECT v.id, v.fecha, v.texto_expediente, v.tipo_votacion, dg.grupo, g.sentido AS sentido_grupo,
               CASE substr(n.sentidos, p.pos, 1) WHEN 'S' THEN 'si' WHEN 'N' THEN 'no' WHEN 'A' THEN 'abstencion' END AS sentido
        FROM plantilla p
        JOIN votacion v ON v.legislatura=p.legislatura AND v.asentimiento=0
        JOIN voto_nominal n ON n.votacion_id=v.id
        JOIN diputado_grupo dg ON dg.diputado_id=p.diputado_id AND dg.legislatura=v.legislatura AND v.fecha BETWEEN dg.desde AND dg.hasta
        JOIN voto_grupo g ON g.votacion_id=v.id AND g.grupo=dg.grupo
        WHERE p.diputado_id=?)
      WHERE sentido IS NOT NULL AND sentido_grupo IN ('si','no','abstencion') AND sentido<>sentido_grupo
        AND grupo NOT IN (${SQL_HETEROGENEOS})
      ORDER BY fecha DESC LIMIT 100`, [id]),
  };
};

API.informe = () => ({ informes: q("SELECT * FROM informe_ia ORDER BY clave") });

// ---- análisis por tema y por grupo --------------------------------------------------------
// Se usan las votaciones decisivas «de fondo» (una por asunto, o una por punto en PNL y mociones).
// «Apoyo» es el voto respecto a la iniciativa: en las enmiendas a la totalidad, votar sí es
// votar contra el proyecto, así que ahí se invierte.

const SALE_RES = new Set(["aprobada", "aprobada_en_parte", "convalidada"]);
const CAE_RES = new Set(["rechazada", "derogada"]);
const FAMILIAS_AGRUPADAS = { legislativo: ["ley", "decreto_ley"], declarativo: ["pnl", "mocion"] };
const SQL_APOYO = `CASE WHEN v.tipo_votacion='totalidad'
    THEN CASE g.sentido WHEN 'si' THEN 'no' WHEN 'no' THEN 'si' ELSE g.sentido END
    ELSE g.sentido END`;
const FONDO_SQL = TIPOS_FONDO.map((t) => `'${t}'`).join(",");
// Grupo que presenta cada propuesta de resolución de un debate (en el Congreso): ahí lo votado es suyo,
// no del autor del asunto. En el resto de votaciones, cadena vacía.
const SQL_PROPONE = "CASE WHEN v.tipo_votacion='control' THEN COALESCE(v.enmienda_grupo, '') ELSE '' END";

function filtrosAsunto(p, { conTema = true } = {}) {
  const w = [], a = [];
  if (conTema) condTema(w, a, p.tema, p.sec === "1");
  condIn(w, a, "i.legislatura", p.leg, Number);
  condFamilia(w, a, p.familia);
  if (conTema) condJson(w, a, "f.etiquetas", p.etiqueta);
  if (conTema) for (const palabra of (p.q || "").split(/\s+/).filter(Boolean)) {
    w.push("(i.titulo LIKE ? OR f.resumen LIKE ? OR f.etiquetas LIKE ?)");
    a.push(...Array(3).fill(`%${palabra}%`));
  }
  return [w.length ? w.join(" AND ") : "1=1", a];
}

const FROM_ASUNTO = `FROM iniciativa i
  JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
  LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo`;

// Apoyo de cada grupo (por siglas) en las votaciones decisivas de fondo que cumplen el filtro. Cuenta
// asuntos, no votaciones (tabla peso): n es el número de asuntos en que votó el grupo y nv, el de votaciones.
function apoyoPorGrupo(p, { conTema = true, agrupar = "gr.siglas, v.legislatura" } = {}) {
  const [w, a] = filtrosAsunto(p, { conTema });
  return q(`SELECT gr.siglas, MAX(gr.color) AS color, v.legislatura, f.tema_principal AS tema,
      SUM(pe.peso * (${SQL_APOYO}='si')) AS si, SUM(pe.peso * (${SQL_APOYO}='no')) AS no,
      SUM(pe.peso * (${SQL_APOYO}='abstencion')) AS abst, SUM(pe.peso * (${SQL_APOYO}='dividido')) AS div,
      SUM(pe.peso) AS n, COUNT(*) AS nv
    FROM votacion v
    JOIN peso pe ON pe.votacion_id=v.id
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    JOIN voto_grupo g ON g.votacion_id=v.id
    JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) AND g.grupo<>'?'
      AND g.sentido IS NOT NULL AND ${w}
    GROUP BY ${agrupar}`, a);
}

function sumarPor(filas, clave) {
  const out = new Map();
  for (const r of filas) {
    const k = clave(r);
    const o = out.get(k) || { clave: k, siglas: r.siglas, color: r.color, si: 0, no: 0, abst: 0, div: 0, n: 0, nv: 0 };
    for (const c of ["si", "no", "abst", "div", "n", "nv"]) o[c] += r[c];
    out.set(k, o);
  }
  return out;
}

API.tema = (p) => {
  const [w, a] = filtrosAsunto(p);
  const asuntos = q(`SELECT i.legislatura, i.expediente, i.titulo, i.grupo_autor, i.resultado_final, te.familia,
      f.etiquetas, (SELECT MIN(fecha) FROM votacion v WHERE v.legislatura=i.legislatura AND v.expediente=i.expediente) AS fecha
    ${FROM_ASUNTO} WHERE ${w}`, a);
  const apoyo = apoyoPorGrupo(p);
  const media = apoyoPorGrupo(p, { conTema: false });
  const pagina = Math.max(1, +(p.pagina || 1));
  const tam = 30;
  const baseMatriz = `FROM votacion v
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) AND ${w}
      ${p.ajustadas === "1" ? "AND ABS(v.margen) <= 10" : ""}`;
  const totalMatriz = q1(`SELECT COUNT(*) AS n ${baseMatriz}`, a).n;
  const votaciones = q(`SELECT v.id, v.fecha, v.legislatura, v.tipo_votacion, v.resultado, v.a_favor, v.en_contra,
      v.abstenciones, v.margen, v.titulo_subgrupo, v.texto_subgrupo, v.texto_expediente, i.titulo, i.sintetica,
      i.grupo_autor, te.familia
    ${baseMatriz} ORDER BY v.fecha DESC, v.numero DESC LIMIT ? OFFSET ?`, [...a, tam, (pagina - 1) * tam]);
  const celdas = {};
  if (votaciones.length) {
    const ids = votaciones.map((v) => v.id);
    for (const c of q(`SELECT g.votacion_id, gr.siglas, g.sentido, g.si, g.no, g.abstencion, v.tipo_votacion,
          ${SQL_APOYO} AS apoyo
        FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
        JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
        WHERE g.votacion_id IN (${ids.map(() => "?").join(",")}) AND g.grupo<>'?'`, ids)) {
      (celdas[c.votacion_id] = celdas[c.votacion_id] || {})[c.siglas] = c;
    }
  }
  const asentimiento = q1(`SELECT COUNT(*) AS n FROM votacion v
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    WHERE v.decisiva=1 AND v.asentimiento=1 AND ${w}`, a).n;
  // Afinidad en el tema (tema principal), sumada por siglas si abarca varias legislaturas.
  const afinidad = p.tema ? q(`SELECT ga.siglas AS a, gb.siglas AS b, SUM(af.coinciden) AS coinciden, SUM(af.total) AS total
    FROM afinidad af
    JOIN grupo ga ON ga.legislatura=af.legislatura AND ga.codigo=af.grupo_a
    JOIN grupo gb ON gb.legislatura=af.legislatura AND gb.codigo=af.grupo_b
    WHERE 1=1 ${enSQL("af.tema", p.tema)[0]} ${enSQL("af.legislatura", p.leg, { conv: Number })[0]} AND af.grupo_a<>'?' AND af.grupo_b<>'?'
    GROUP BY 1, 2`, [...enSQL("af.tema", p.tema)[1], ...enSQL("af.legislatura", p.leg, { conv: Number })[1]]) : [];
  return { asuntos, apoyo, media, votaciones, celdas, totalMatriz, pagina, tam, asentimiento, afinidad };
};

API.grupoPerfil = (p) => {
  const gs = lista(p.g);
  const enG = (columna) => `${columna} IN (${gs.map(() => "?").join(",")})`;
  const filtro = { leg: p.leg, familia: p.familia };
  const [w, a] = filtrosAsunto(filtro, { conTema: false });
  const [wl, al] = enSQL("v.legislatura", p.leg, { conv: Number });
  const porTema = [...sumarPor(apoyoPorGrupo(filtro, { conTema: false, agrupar: "gr.siglas, f.tema_principal" })
    .filter((r) => gs.includes(r.siglas)), (r) => r.tema).values()].map((o) => ({ ...o, tema: o.clave }));
  const media = apoyoPorGrupo(filtro, { conTema: false, agrupar: "gr.siglas" });
  const propuestas = q(`SELECT f.tema_principal AS tema, i.resultado_final, COUNT(*) AS n ${FROM_ASUNTO}
    JOIN grupo gr ON gr.legislatura=i.legislatura AND gr.codigo=i.grupo_autor
    WHERE ${enG("gr.siglas")} AND ${w} GROUP BY 1, 2`, [...gs, ...a]);
  const afinidad = q(`SELECT gb.siglas AS otro, MAX(gb.color) AS color, af.tema, SUM(af.coinciden) AS coinciden, SUM(af.total) AS total
    FROM afinidad af
    JOIN grupo ga ON ga.legislatura=af.legislatura AND ga.codigo=af.grupo_a
    JOIN grupo gb ON gb.legislatura=af.legislatura AND gb.codigo=af.grupo_b
    WHERE ${enG("ga.siglas")} AND NOT ${enG("gb.siglas")} ${enSQL("af.legislatura", p.leg, { conv: Number })[0]} AND af.grupo_b<>'?'
    GROUP BY 1, 3`, [...gs, ...gs, ...enSQL("af.legislatura", p.leg, { conv: Number })[1]]);
  const decisivo = q(`SELECT v.legislatura, d.modo, COUNT(DISTINCT v.id) AS n FROM grupo_decisivo d
    JOIN votacion v ON v.id=d.votacion_id JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=d.grupo
    WHERE ${enG("gr.siglas")} AND v.decisiva=1 ${wl} GROUP BY 1, 2`, [...gs, ...al]);
  const totalesDecisivas = q(`SELECT legislatura, COUNT(*) AS n FROM votacion WHERE decisiva=1 AND asentimiento=0 GROUP BY 1`);
  const cohesion = q(`SELECT v.legislatura, COUNT(*) AS n,
      SUM((g.si+g.no+g.abstencion) - MAX(g.si, g.no, g.abstencion) >= MAX(2, 0.1*(g.si+g.no+g.abstencion))) AS partidas
    FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
    WHERE ${enG("gr.siglas")} AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) ${wl}
    GROUP BY 1`, [...gs, ...al]);
  const clave = q(`SELECT v.id, v.fecha, v.legislatura, v.texto_expediente, v.tipo_votacion, v.resultado, v.a_favor, v.en_contra,
      v.abstenciones, v.margen, i.titulo, i.sintetica, f.tema_principal
    FROM grupo_decisivo d JOIN votacion v ON v.id=d.votacion_id
    JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=d.grupo
    LEFT JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    LEFT JOIN ficha_llm f ON f.legislatura=v.legislatura AND f.expediente=v.expediente
    WHERE ${enG("gr.siglas")} AND v.decisiva=1 AND d.modo='absteniendose' AND v.tipo_votacion IN (${FONDO_SQL}) ${wl}
    GROUP BY v.id ORDER BY v.fecha DESC LIMIT 20`, [...gs, ...al]);
  const legislaturas = q(`SELECT DISTINCT legislatura FROM grupo WHERE ${enG("siglas")} ORDER BY 1`, gs).map((r) => r.legislatura);
  const programas = q(`SELECT DISTINCT partido FROM programa WHERE ${enG("partido")}`, gs).map((r) => r.partido);
  return { porTema, media, propuestas, afinidad, decisivo, totalesDecisivas, cohesion, clave, legislaturas, programas };
};

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function fecha(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${+d} ${MESES[+m - 1]} ${y}`;
}
const fmt = (n) => (n ?? 0).toLocaleString("es-ES");
// Asuntos contados con peso (un asunto votado por puntos se reparte): puede haber medios asuntos.
const fmtAs = (n) => (n ?? 0).toLocaleString("es-ES", { maximumFractionDigits: 1 });
const pct = (a, b) => (b ? Math.round((100 * a) / b) : 0);
const infoLeg = (leg) => META.legislaturas.find((l) => l.id === +leg) || {};
const romano = (leg) => infoLeg(leg).romano || leg;
// «Leg. XV» si solo hay una institución cargada; si hay varias, con su nombre corto: «Asturias XII».
const legTexto = (leg) => (META.multi ? `${infoLeg(leg).corto || ""} ${romano(leg)}`.trim() : `Leg. ${romano(leg)}`);
// Gobierno de una institución en una fecha (null si no consta) y sus partidos: «PSOE + Sumar».
const gobiernoEn = (cuerpo, fecha) => META.gobiernos.find((g) => g.cuerpo === cuerpo && g.desde <= fecha && (!g.hasta || fecha <= g.hasta)) || null;
const partidosGobierno = (g) => [g.partido, ...lista(g.socios)].join(" + ");
// Quién gobernó mientras se votaba en una legislatura: «PP → PSOE» (vacío si no consta).
const gobiernosLeg = (leg) => {
  const l = infoLeg(leg);
  return META.gobiernos.filter((g) => g.cuerpo === l.cuerpo && g.desde <= l.hasta && (!g.hasta || g.hasta >= l.desde))
    .map(partidosGobierno).filter((t, k, xs) => t !== xs[k - 1]).join(" → ");
};
// Mayoría absoluta de la cámara en esa legislatura.
const mayoriaAbs = (leg) => Math.floor((infoLeg(leg).escanos || 350) / 2) + 1;
// Cómo se llama a los miembros de la cámara: diputados, junteros o concejales.
const miembros = (leg, singular = false) => {
  const nivel = infoLeg(leg).nivel;
  const [uno, varios] = nivel === "municipal" ? ["concejal", "concejales"] : nivel === "provincial" ? ["miembro", "miembros"] : ["diputado", "diputados"];
  return singular ? uno : varios;
};
const temaNombre = (c) => (META.temas.find((t) => t.codigo === c) || {}).nombre || c;

function grupo(leg, codigo) {
  const g = (META.grupos[leg] || []).find((x) => x.codigo === codigo);
  if (g) return g;
  const especiales = { Gobierno: "Gobierno", Senado: "Senado", CCAA: "Comunidades autónomas", ILP: "Iniciativa popular", Otros: "Otros diputados", Varios: "Varios grupos" };
  return { codigo, siglas: codigo || "—", nombre: especiales[codigo] || codigo || "—", color: "#9aa0a6" };
}

const SENTIDO = { si: ["✓", "Sí"], no: ["✗", "No"], abstencion: ["~", "Abstención"], dividido: ["±", "Dividido"], no_vota: ["·", "No vota"] };
const RESULTADOS = {
  aprobada: ["✓", "Aprobada", "ok"], aprobada_en_parte: ["◐", "Aprobada en parte", "ok"], rechazada: ["✗", "Rechazada", "ko"],
  convalidada: ["✓", "Convalidado", "ok"], derogada: ["✗", "Derogado", "ko"], caducada: ["⌛", "Caducada", ""],
  retirada: ["↩", "Retirada", ""], subsumida: ["⤷", "Subsumida en otra", ""], inadmitida: ["⊘", "Inadmitida", ""],
  en_tramite: ["…", "Sigue en trámite", ""], otra: ["·", "Otra", ""],
};

function badgeResultado(r) {
  if (!r) return null;
  const [ic, txt, cls] = RESULTADOS[r] || ["·", r, ""];
  return el("span", { class: `badge ${cls}` }, el("span", { class: "ic" }, ic), txt);
}

function tituloVotacion(v) {
  const t = (v.texto_expediente || "").split("\n")[0].trim();
  return v.titulo && !v.sintetica ? v.titulo : t || v.seccion || "Votación";
}

// Los títulos oficiales son muy largos («Proposición no de Ley relativa a…», «Real Decreto-ley
// 2/2026, de 3 de febrero, por el que se adoptan…»). En listas y tablas se muestra la abreviatura
// del tipo, el número si lo tiene y el asunto, recortado; el título completo queda en el tooltip
// (atributo title) y en el detalle. Los CSV llevan siempre el título completo.
const ABREVIATURAS = [
  [/^real decreto[\s-]*ley (\d+\/\d{4})(,? de \d+ de [a-záéíóú]+( de \d{4})?)?,?\s*/i, "RDL $1"],
  [/^real decreto legislativo (\d+\/\d{4})(,? de \d+ de [a-záéíóú]+( de \d{4})?)?,?\s*/i, "RD Leg. $1"],
  [/^proyecto de ley orgánica\s*/i, "PLO"],
  [/^proyecto de ley\s*/i, "PL"],
  [/^proposición de ley orgánica\s*/i, "PPLO"],
  [/^proposición no de ley\s*/i, "PNL"],
  [/^proposición de ley\s*/i, "PPL"],
  [/^moción consecuencia de interpelación( urgente)?\s*/i, "Moción"],
];
const ARRANQUES = [
  /^(del|presentada por el|de los) grupos? parlamentarios? [^,]+,\s*/i,
  /^(de la asamblea|del parlamento|de las cortes|de la junta general|de la asamblea de madrid|del senado)[^,]*,\s*/i,
  /^(al|a la) (ministr[oa]|gobierno|vicepresident[ae]|presidente).{0,140}?\s(sobre|relativa a|relativo a|acerca de)\s+/i,
  /^por (el|la) que se (adoptan?|aprueban?|establecen?|articulan?|prevén?|dictan?|introducen?|toman?|fijan?|habilitan?)\s+/i,
  /^por (el|la) que se\s+/i,
  /^(sobre|relativa al?|relativo al?|acerca de|de|del)\s+/i,
  /^para (el|la|los|las)\s+/i,
  /^(el|la|los|las)\s+/i,
];
function tituloCorto(titulo, max = 120) {
  let t = String(titulo || "").split("\n")[0].trim().replace(/\.$/, "");
  let sigla = "";
  for (const [re, abr] of ABREVIATURAS) {
    const m = t.match(re);
    if (m) { sigla = m[0].replace(re, abr).trim(); t = t.slice(m[0].length); break; }
  }
  if (sigla) {
    for (const re of ARRANQUES) {
      t = t.replace(re, "");
      // «Proposición de Ley del Grupo X, Orgánica por la que…»: el «orgánica» queda tras el autor.
      if (/^orgánica\b/i.test(t) && /^PP?L$/.test(sigla)) { sigla += "O"; t = t.replace(/^orgánica\s*/i, ""); }
    }
    t = t.replace(/\s*\(corresponde al n[úu]mero[^)]*\)?/i, "");
    t = t.replace(/(\d+\/\d{4}),? de \d+ de [a-záéíóú]+,?/gi, "$1"); // «Ley 37/1992, de 28 de diciembre,» -> «Ley 37/1992»
  }
  t = t.replace(/,? hech[oa] (en|ad) .+$/i, ""); // convenios: «…, hecho en Madrid el 3 de mayo de 2019»
  // «entre el Gobierno del Reino de España y el Gobierno de la República de X» -> «España–X»
  t = t.replace(/ entre el (Gobierno del )?Reino de España y (el Gobierno de )?(la República (Federal |Islámica |Democrática |Oriental )?de |el Reino de |los |las |la |el )?/i, " España–");
  if (t) t = t[0].toUpperCase() + t.slice(1);
  let s = sigla && t ? `${sigla} · ${t}` : sigla || t;
  if (s.length > max) {
    const corte = s.slice(0, max);
    s = corte.slice(0, Math.max(corte.lastIndexOf(" "), max * 0.6)).replace(/[\s,;:(·-]+$/, "") + "…";
  }
  return s;
}
// Texto corto para una celda, con el título completo al pasar el ratón.
const textoCorto = (titulo, max) => {
  const completo = String(titulo || "").split("\n")[0].trim();
  return el("span", { title: completo }, tituloCorto(completo, max));
};

// ------------------------------------------------------------------ tooltip

const TT = () => $("#tooltip");
function tip(evt, valor, etiqueta, extra) {
  const t = TT();
  t.replaceChildren(...[el("div", { class: "tv" }, valor), etiqueta ? el("div", { class: "tl" }, etiqueta) : null,
    extra ? el("div", { class: "tl small" }, extra) : null].filter(Boolean));
  t.style.display = "block";
  const x = Math.min(evt.clientX + 14, window.innerWidth - t.offsetWidth - 8);
  const y = Math.min(evt.clientY + 14, window.innerHeight - t.offsetHeight - 8);
  t.style.left = x + "px";
  t.style.top = y + "px";
}
const tipOff = () => (TT().style.display = "none");
// Con ratón, el tooltip sigue al puntero. En pantallas táctiles no hay «pasar por encima»:
// aparece al tocar y se va al tocar en otro sitio o al desplazarse.
let ocultarTactil = null;
function alPasar(nodo, mostrar, ocultar = tipOff) {
  nodo.addEventListener("pointermove", (e) => { if (e.pointerType === "mouse") mostrar(e); });
  nodo.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") ocultar(); });
  nodo.addEventListener("pointerdown", (e) => { if (e.pointerType !== "mouse") { mostrar(e); ocultarTactil = ocultar; } });
}
function quitarTipTactil() {
  if (ocultarTactil) { ocultarTactil(); ocultarTactil = null; }
}
function conTip(nodo, valor, etiqueta, extra) {
  alPasar(nodo, (e) => tip(e, valor, etiqueta, extra));
  nodo.addEventListener("focus", (e) => { const r = nodo.getBoundingClientRect(); tip({ clientX: r.right, clientY: r.top }, valor, etiqueta, extra); });
  nodo.addEventListener("blur", tipOff);
  return nodo;
}

// ------------------------------------------------------------------ piezas

function barraVotos(v) {
  const si = v.a_favor || 0, no = v.en_contra || 0, ab = v.abstenciones || 0;
  const tot = si + no + ab;
  if (v.asentimiento) {
    return el("div", {}, el("div", { class: "barra" }, el("span", { class: "si", style: "width:100%" })),
      el("div", { class: "totales" }, el("span", {}, "Por asentimiento"), el("span", {})));
  }
  if (v.a_favor === null || v.a_favor === undefined) {
    const cls = v.resultado === "aprobada" ? "si" : v.resultado === "rechazada" ? "no" : "abs";
    return el("div", {}, el("div", { class: "barra", style: "opacity:.45" }, el("span", { class: cls, style: "width:100%" })),
      el("div", { class: "totales" }, el("span", {}, "Sin recuento publicado"), el("span", {})));
  }
  const barra = el("div", { class: "barra", role: "img", "aria-label": `Sí ${si}, abstención ${ab}, no ${no}` },
    si ? el("span", { class: "si", style: `width:${(100 * si) / tot}%` }) : null,
    ab ? el("span", { class: "abs", style: `width:${(100 * ab) / tot}%` }) : null,
    no ? el("span", { class: "no", style: `width:${(100 * no) / tot}%` }) : null);
  return el("div", {}, barra,
    el("div", { class: "totales" },
      el("span", {}, el("i", { class: "key", style: "background:var(--si)" }), "Sí ", el("b", {}, si)),
      el("span", {}, el("i", { class: "key", style: "background:var(--abs)" }), "Abst. ", el("b", {}, ab)),
      el("span", {}, el("i", { class: "key", style: "background:var(--no)" }), "No ", el("b", {}, no))));
}

function chipsGrupos(v) {
  const decis = new Set((v.decisivos || []).map((d) => d.grupo));
  const gs = [...(v.grupos || [])].filter((g) => g.grupo && g.grupo !== "?")
    .sort((a, b) => (b.si + b.no + b.abstencion + b.no_vota) - (a.si + a.no + a.abstencion + a.no_vota));
  return el("div", { class: "chips" }, gs.map((g) => {
    const info = grupo(v.legislatura, g.grupo);
    const [ic, txt] = SENTIDO[g.sentido] || ["·", "Sin voto"];
    const chip = el("span", { class: "chip" + (decis.has(g.grupo) ? " decisivo" : ""), tabindex: 0 },
      el("span", { class: "sw", style: `background:${info.color}` }), info.siglas, el("span", { class: `s ${g.sentido}` }, ic));
    const recuento = g.si + g.no + g.abstencion + g.no_vota ? `Sí ${g.si} · Abst. ${g.abstencion} · No ${g.no} · No vota ${g.no_vota}` : "Voto del grupo según la fuente, sin recuento";
    return conTip(chip, `${info.siglas}: ${txt}`, recuento,
      decis.has(g.grupo) ? "Grupo decisivo: su voto cambiaba el resultado" : null);
  }));
}

function filaVotacion(v) {
  const sub = [v.titulo_subgrupo, v.texto_subgrupo].filter(Boolean).join(" — ");
  const tv = META.tipos_votacion[v.tipo_votacion] || v.tipo_votacion;
  return el("article", { class: "fila", tabindex: 0, onclick: () => abrir(`v:${v.id}`), onkeydown: (e) => e.key === "Enter" && abrir(`v:${v.id}`) },
    el("div", {}, el("div", { class: "fecha" }, fecha(v.fecha)), el("div", { class: "muted small" }, legTexto(v.legislatura))),
    el("div", {},
      el("div", { class: "titulo", title: tituloVotacion(v) }, tituloCorto(tituloVotacion(v), esMovil() ? 110 : 170)),
      sub ? el("div", { class: "detalle" }, sub) : null,
      el("div", { class: "badges" },
        badgeResultado(v.resultado),
        el("span", { class: "badge" }, tv),
        v.decisiva ? el("span", { class: "badge" }, "votación decisiva") : null,
        v.derrota ? el("span", { class: "badge", title: "Perdió lo que votó el partido del presidente del Gobierno" }, "derrota del Gobierno") : null,
        v.mayoria === "absoluta" ? el("span", { class: "badge" }, "mayoría absoluta") : null,
        v.aviso ? el("span", { class: "badge ko", title: v.aviso }, el("span", { class: "ic" }, "⚠"), v.aviso.includes("revisar") ? "revisar" : "empate") : null,
        v.tema_principal ? el("span", { class: "badge ia", title: "Tema" }, temaNombre(v.tema_principal)) : null,
        // En las propuestas de resolución de un debate, lo votado es del grupo que la presenta.
        v.tipo_votacion === "control" && v.enmienda_grupo ? el("span", { class: "badge" }, "Propone: " + grupo(v.legislatura, v.enmienda_grupo).siglas)
          : v.grupo_autor ? el("span", { class: "badge" }, "Propone: " + grupo(v.legislatura, v.grupo_autor).siglas) : null),
      v.resumen && v.decisiva ? el("div", { class: "resumen" }, v.resumen) : null),
    el("div", {}, barraVotos(v), chipsGrupos(v)));
}

function paginacion(total, pagina, tam, ir) {
  const paginas = Math.max(1, Math.ceil(total / tam));
  return el("div", { class: "paginacion" },
    el("button", { disabled: pagina <= 1, onclick: () => ir(pagina - 1) }, "← Anterior"),
    el("span", { class: "muted small" }, `Página ${pagina} de ${fmt(paginas)} · ${fmt(total)} resultados`),
    el("button", { disabled: pagina >= paginas, onclick: () => ir(pagina + 1) }, "Siguiente →"));
}

// Selects de filtros --------------------------------------------------------

// Con varias instituciones, agrupadas por institución (la más reciente primero dentro de cada una).
const optLegs = () => [...META.legislaturas]
  .sort((a, b) => (a.cuerpo === b.cuerpo ? b.id - a.id : ordenCuerpo(a.cuerpo) - ordenCuerpo(b.cuerpo)))
  .map((l) => [l.id, `${META.multi ? l.corto + " · " : ""}Leg. ${l.romano} (${l.desde.slice(0, 4)}–${l.hasta.slice(0, 4)})`]);
function ordenCuerpo(codigo) {
  const i = META.cuerpos.indexOf(codigo);
  return codigo === "congreso" ? -1 : i;
}
const optTemas = () => META.temas.map((t) => [t.codigo, t.nombre]);
function optAutores(leg) {
  const elegidas = lista(leg).map(Number);
  const legs = elegidas.length ? elegidas : META.legislaturas.map((l) => l.id);
  const vistos = new Map();
  for (const l of legs) for (const g of META.grupos[l] || []) if (g.codigo !== "?") vistos.set(g.codigo, g.siglas + (legs.length === 1 ? "" : ` (${g.codigo})`));
  return [["Gobierno", "Gobierno"], ...[...vistos.entries()]];
}

// Lee un formulario: los selectores múltiples dan «a,b,c» y las casillas sueltas, «1».
function leerFormulario(f) {
  const d = {};
  for (const c of f.elements) {
    if (!c.name) continue;
    if (c.type === "checkbox") {
      if (!c.checked) continue;
      if (c.classList.contains("ms-cb")) d[c.name] = d[c.name] ? `${d[c.name]},${c.value}` : c.value;
      else d[c.name] = "1";
    } else if (c.value) d[c.name] = c.value;
  }
  return d;
}

// En móvil, los formularios con muchos filtros se pliegan tras un botón (el buscador queda a la
// vista). Si se despliegan, siguen desplegados al aplicar un filtro y redibujarse la vista.
let filtrosDesplegados = false;

function formFiltros(campos, estado, onCambio) {
  const f = el("form", { class: "filtros", onsubmit: (e) => { e.preventDefault(); onCambio(leerFormulario(f)); } }, campos);
  // Los selectores múltiples se aplican al cerrarse, no en cada casilla.
  f.addEventListener("change", (e) => { if (e.target.type !== "search" && !e.target.classList.contains("ms-cb")) onCambio(leerFormulario(f)); });
  f.addEventListener("ms-cambio", () => onCambio(leerFormulario(f)));
  const busqueda = new Set([...f.querySelectorAll("input[type=search]")].map((c) => c.name));
  const filtros = new Set([...f.elements].filter((c) => c.name && !busqueda.has(c.name)).map((c) => c.name));
  if (filtros.size >= 3) {
    const activos = Object.keys(leerFormulario(f)).filter((k) => filtros.has(k)).length;
    f.classList.add("plegable");
    f.classList.toggle("desplegado", filtrosDesplegados);
    const boton = el("button", { type: "button", class: "boton filtros-boton", "aria-expanded": String(filtrosDesplegados),
      onclick: () => {
        filtrosDesplegados = f.classList.toggle("desplegado");
        boton.setAttribute("aria-expanded", String(filtrosDesplegados));
      } }, "Filtros", activos ? el("span", { class: "cuenta" }, activos) : null);
    f.prepend(boton);
  }
  return f;
}

// Selector desplegable con varias opciones (casillas). Se aplica al cerrar o con «Aplicar».
function multiSelect(nombre, opciones, valor, etiquetaVacia, plural = "seleccionados") {
  const elegidos = new Set(lista(valor));
  const textoDe = new Map(opciones.map(([v, t]) => [String(v), t]));
  const texto = el("span", { class: "ms-texto" });
  const det = el("details", { class: "ms" }, el("summary", { title: etiquetaVacia }, texto));
  const pintar = () => {
    const xs = opciones.map(([v]) => String(v)).filter((v) => elegidos.has(v));
    texto.textContent = !xs.length ? etiquetaVacia : xs.length === 1 ? textoDe.get(xs[0]) : xs.length === 2 ? xs.map((x) => textoDe.get(x)).join(" + ") : `${xs.length} ${plural}`;
    det.classList.toggle("activo", xs.length > 0);
  };
  const cajas = opciones.map(([v, t]) => el("label", { class: "ms-op" },
    el("input", { type: "checkbox", class: "ms-cb", name: nombre, value: v, checked: elegidos.has(String(v)),
      onchange: (e) => { e.target.checked ? elegidos.add(String(v)) : elegidos.delete(String(v)); pintar(); } }), t));
  det.append(el("div", { class: "ms-panel" },
    el("div", { class: "ms-titulo" }, etiquetaVacia),
    el("div", { class: "ms-acciones" },
      el("button", { type: "button", class: "boton", onclick: () => { for (const c of det.querySelectorAll(".ms-cb")) c.checked = false; elegidos.clear(); pintar(); } }, "Ninguno"),
      el("button", { type: "button", class: "boton", onclick: () => { det.open = false; } }, "Aplicar")),
    el("div", { class: "ms-lista" }, cajas)));
  let aplicado = [...elegidos].sort().join(",");
  det.addEventListener("toggle", () => {
    if (det.open) { for (const o of document.querySelectorAll("details.ms[open]")) if (o !== det) o.open = false; return; }
    const ahora = [...elegidos].sort().join(",");
    if (ahora !== aplicado) { aplicado = ahora; det.dispatchEvent(new CustomEvent("ms-cambio", { bubbles: true })); }
  });
  pintar();
  return det;
}

// ------------------------------------------------------------------ gráficos

// Barras horizontales de una serie (o apiladas con segs). Marca <= 14px, extremo redondeado.
function barrasH(items, { max, formato = fmt, segs = null, normalizar = false } = {}) {
  const m = max || Math.max(1, ...items.map((i) => (segs ? i.segs.reduce((a, s) => a + s.v, 0) : i.v)));
  const cont = el("div", { class: "chart barrash" });
  for (const it of items) {
    const lbl = el("div", { class: "small", style: "color:var(--ink-2);display:flex;gap:6px;align-items:center;min-width:0" },
      it.color ? el("span", { style: `width:10px;height:10px;border-radius:2px;flex:none;background:${it.color}` }) : null,
      el("span", { style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap" }, it.label));
    const total = segs ? it.segs.reduce((a, s) => a + s.v, 0) : it.v;
    const pista = el("div", { style: "display:flex;align-items:center;gap:8px;min-width:0" });
    const barra = el("div", { style: `display:flex;gap:2px;height:14px;width:${normalizar ? 78 : (78 * total) / m}%;min-width:${total ? 3 : 0}px` });
    const partes = segs ? it.segs.filter((s) => s.v) : [{ v: it.v, color: it.barColor || "var(--accent)", nombre: it.label }];
    partes.forEach((s, i) => {
      const ultimo = i === partes.length - 1;
      const seg = el("div", { class: "mark", tabindex: 0, style: `flex:${s.v} 0 0;background:${s.color};height:100%;border-radius:${ultimo ? "0 4px 4px 0" : "0"};cursor:${it.onclick ? "pointer" : "default"}` });
      conTip(seg, formato(s.v), `${it.label}${segs ? " · " + s.nombre : ""}`, it.tip ? it.tip(s) : null);
      if (it.onclick) seg.addEventListener("click", it.onclick);
      barra.appendChild(seg);
    });
    pista.append(barra, el("span", { class: "small", style: "font-weight:600;white-space:nowrap" }, it.valorTexto ?? formato(total)));
    cont.append(lbl, pista);
  }
  return cont;
}

// Columnas finas en el tiempo (una serie) con eje Y limpio y tooltip por columna.
function columnas(datos, { alto = 180, etiqueta = "" } = {}) {
  const W = anchoGrafico(1000), H = alto, ml = 36, mb = 22, mt = 8;
  const max = Math.max(1, ...datos.map((d) => d.y));
  const paso = Math.pow(10, Math.floor(Math.log10(max)));
  const tick = [1, 2, 5, 10].map((k) => k * paso).find((t) => max / t <= 5) || paso;
  const top = Math.ceil(max / tick) * tick;
  const bw = (W - ml) / datos.length;
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", etiqueta);
  const mk = (t, a) => { const n = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) n.setAttribute(k, v); return n; };
  const y = (v) => mt + (H - mt - mb) * (1 - v / top);
  let ultimaEtiqueta = -Infinity;
  for (let v = 0; v <= top; v += tick) {
    svg.appendChild(mk("line", { x1: ml, x2: W, y1: y(v), y2: y(v), class: v === 0 ? "baseline" : "gridline" }));
    const t = mk("text", { x: ml - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = fmt(v); svg.appendChild(t);
  }
  datos.forEach((d, i) => {
    const x = ml + i * bw;
    const h = (H - mt - mb) * (d.y / top);
    const w = Math.max(1, Math.min(24, bw - 2));
    const g = mk("g", {});
    g.appendChild(mk("path", { class: "mark", fill: "var(--accent)", d: barraPath(x + (bw - w) / 2, y(0), w, h) }));
    const hit = mk("rect", { class: "hit", x, y: mt, width: bw, height: H - mt - mb });
    g.appendChild(hit);
    alPasar(hit, (e) => { g.classList.add("hover"); tip(e, fmt(d.y) + " votaciones", d.label, d.extra); }, () => { g.classList.remove("hover"); tipOff(); });
    svg.appendChild(g);
    if (d.tick && x + bw / 2 - ultimaEtiqueta >= 34) {
      ultimaEtiqueta = x + bw / 2;
      const t = mk("text", { x: x + bw / 2, y: H - 6, "text-anchor": "middle" }); t.textContent = d.tick; svg.appendChild(t);
    }
  });
  return el("div", { class: "chart" }, svg);
}
function barraPath(x, base, w, h) {
  if (h <= 0) return "";
  const r = Math.min(4, w / 2, h);
  return `M${x},${base} V${base - h + r} Q${x},${base - h} ${x + r},${base - h} H${x + w - r} Q${x + w},${base - h} ${x + w},${base - h + r} V${base} Z`;
}

// Rampa secuencial azul (un tono, claro -> oscuro).
const RAMPA = ["--seq-100", "--seq-200", "--seq-300", "--seq-400", "--seq-500", "--seq-600", "--seq-700"];
function colorSecuencial(t) {
  const i = Math.max(0, Math.min(RAMPA.length - 1, Math.round(t * (RAMPA.length - 1))));
  return { bg: `var(${RAMPA[i]})`, ink: i >= 3 ? "#ffffff" : "#0b0b0b" };
}

// ------------------------------------------------------------------ router

let estadoRuta = { tab: "", q: {}, clave: "" };

// El ámbito (amb=…) va aparte: no es un filtro de la vista, sino qué datos están cargados (ambito.js).
function leerRuta() {
  const h = location.hash.replace(/^#\/?/, "");
  const [tab, qs] = h.split("?");
  const q = Object.fromEntries(new URLSearchParams(qs || ""));
  const amb = q.amb || null;
  delete q.amb;
  return { tab: tab || "resumen", q, amb };
}
function irA(tab, q) {
  const qs = new URLSearchParams(Object.entries({ ...q, amb: AMBITO.clave }).filter(([, v]) => v !== "" && v != null)).toString().replace(/%2C/g, ",");
  location.hash = `#/${tab}${qs ? "?" + qs : ""}`;
}
function abrir(ver) {
  const { tab, q } = leerRuta();
  irA(tab, { ...q, ver });
}
function cerrarPanel() {
  const { tab, q } = leerRuta();
  delete q.ver;
  irA(tab, q);
}

// Las tablas van dentro de un contenedor con desplazamiento horizontal: en móvil no caben.
function envolverTablas(raiz) {
  for (const t of raiz.querySelectorAll("table.tabla")) {
    if (t.parentElement.classList.contains("tabla-scroll")) continue;
    const caja = el("div", { class: "tabla-scroll" });
    t.before(caja);
    caja.appendChild(t);
  }
}

async function render() {
  const { tab, q } = leerRuta();
  const { ver, ...resto } = q;
  const clave = tab + JSON.stringify(resto) + "|" + AMBITO.clave;
  const padre = { tema: "temas", grupo: "grupos", coaliciones: "analisis", mapa: "analisis", disciplina: "analisis",
    enmiendas: "analisis", causas: "activismo", causa: "activismo", viene: "activismo", programas: "activismo" }[tab] || tab;
  document.querySelectorAll("#tabs a, #barraMovil [data-tab]").forEach((a) => a.classList.toggle("activo",
    a.dataset.tab === padre || (a.dataset.tab === "mas" && ["comparar", "analisis", "activismo", "ayuda"].includes(padre))));
  document.querySelectorAll("#hojaMas a").forEach((a) => a.classList.toggle("activo", a.getAttribute("href") === `#/${tab}`));
  if (clave !== estadoRuta.clave) {
    estadoRuta = { tab, q: resto, clave };
    const vista = $("#vista");
    vista.classList.add("cargando");
    try {
      const nodo = await (VISTAS[tab] || VISTAS.resumen)(resto);
      if (estadoRuta.clave === clave) { vista.replaceChildren(nodo); envolverTablas(vista); botonAyuda(vista, VISTAS[tab] ? tab : "resumen"); }
    } catch (e) {
      vista.replaceChildren(el("div", { class: "vacio" }, "Error: " + e.message));
    }
    vista.classList.remove("cargando");
  }
  if (ver) abrirPanel(ver); else ocultarPanel();
}

// ------------------------------------------------------------------ vistas

const VISTAS = {};

VISTAS.resumen = async (q) => {
  const leg = q.leg || "";
  const legsSel = new Set(lista(leg).map(Number));
  const enLegs = (l) => !legsSel.size || legsSel.has(l);
  const [res, inf] = await Promise.all([api("resumen"), api("informe")]);
  const T = META.totales;
  const cont = el("div", {});
  const desde = META.legislaturas.map((l) => l.desde).sort()[0], hasta = META.legislaturas.map((l) => l.hasta).sort().at(-1);
  if (META.soloCongreso) {
    cont.append(
      el("h2", {}, "Qué se ha votado en el Congreso desde 2012"),
      el("p", { class: "sub" }, `Votaciones nominales del Pleno de la ${META.legislaturas.map((l) => l.romano).join(", ")} legislaturas, `,
        `del ${fecha(desde)} al ${fecha(hasta)}. `,
        "La IX legislatura y anteriores no tienen votaciones nominales en los datos abiertos del Congreso, así que no hay 20 años completos: hay los que existen. ",
        "Los datos (votos, totales, resultados) son oficiales. ",
        "Con el selector de ámbito de arriba puedes añadir parlamentos autonómicos y otras instituciones."));
  } else {
    cont.append(
      el("h2", {}, `Qué se ha votado · ${nombreAmbito()}`),
      el("p", { class: "sub" }, `Votaciones de los plenos de ${META.cuerpos.length === 1 ? "esta institución" : `${META.cuerpos.length} instituciones`}, del ${fecha(desde)} al ${fecha(hasta)}. `,
        "Cada fuente publica un nivel de detalle distinto (voto de cada diputado, voto de cada grupo o solo el recuento o el resultado) y el análisis usa lo que hay: la tabla de abajo lo resume. ",
        "Votos, totales y resultados son los que publica cada fuente, que se enlaza desde cada votación."),
      avisoFuentes(AMBITO.cuerpos) || "",
      tablaCobertura());
  }
  cont.append(el("div", { class: "grid g4" },
    stat("Votaciones", fmt(T.votaciones), META.soloCongreso ? "en el Pleno" : "en los plenos"),
    T.votos ? stat("Votos individuales", fmt(T.votos), `de ${fmt(T.diputados)} ${META.soloCongreso ? "diputados" : "parlamentarios y concejales"}`)
      : stat("Votos individuales", "—", "estas fuentes no publican el voto de cada uno"),
    stat("Asuntos votados", fmt(T.iniciativas), "iniciativas y trámites"),
    stat("Fichas de iniciativas", fmt(T.fichas), "con resumen y tema" + (T.provisionales ? ` · ${fmt(T.provisionales)} con tema provisional por comisión` : ""))));

  // Filtro que gobierna todo lo de abajo.
  cont.append(formFiltros([multiSelect("leg", optLegs(), leg, "Todas las legislaturas", "legislaturas")], q, (d) => irA("resumen", d)));

  // Lo que se vota y lo que se aprueba.
  const SALE = new Set(["aprobada", "aprobada_en_parte", "convalidada"]);
  const CAE = new Set(["rechazada", "derogada"]);
  const fam = {};
  for (const r of res.decisivas) {
    if (!enLegs(r.legislatura)) continue;
    const k = r.familia || "otro";
    fam[k] = fam[k] || { sale: 0, cae: 0, otra: 0 };
    fam[k][SALE.has(r.resultado) ? "sale" : CAE.has(r.resultado) ? "cae" : "otra"] += r.n;
  }
  const orden = ["ley", "decreto_ley", "pnl", "mocion", "internacional", "control", "organizacion", "otro"];
  const itemsFam = orden.filter((k) => fam[k]).map((k) => ({
    label: META.familias[k] || k,
    segs: [
      { v: fam[k].sale, color: "var(--si)", nombre: "salen adelante" },
      { v: fam[k].otra, color: "var(--abs)", nombre: "caducan, se retiran o siguen en trámite" },
      { v: fam[k].cae, color: "var(--no)", nombre: "rechazadas o derogadas" },
    ],
    valorTexto: `${pct(fam[k].sale, fam[k].sale + fam[k].otra + fam[k].cae)}% salen`,
    tip: (s) => `${fmt(s.v)} asuntos votados que ${s.nombre}`,
    onclick: () => irA("iniciativas", { leg, familia: k }),
  }));

  // Temas.
  const temas = {};
  for (const r of res.por_tema) if (r.tema && enLegs(r.legislatura)) temas[r.tema] = (temas[r.tema] || 0) + r.n;
  const itemsTema = Object.entries(temas).sort((a, b) => b[1] - a[1]).map(([t, n]) => ({
    label: temaNombre(t), v: n, onclick: () => irA("tema", { leg, tema: t }), tip: () => "Clic para ver cómo vota cada grupo en este tema",
  }));

  cont.append(el("div", { class: "grid g2" },
    el("div", { class: "card" }, el("h3", {}, "Lo que se vota y lo que se aprueba"),
      el("p", { class: "small muted" }, "Asuntos que llegaron a votarse en el Pleno y cómo acabaron: para leyes y decretos, el resultado oficial de su tramitación; para PNL y mociones, su votación. Una PNL aprobada no cambia ninguna ley."),
      el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--si)" }), "Salen adelante"), el("span", {}, el("i", { style: "background:var(--abs)" }), "Caducan, se retiran o siguen"), el("span", {}, el("i", { style: "background:var(--no)" }), "Rechazadas")),
      barrasH(itemsFam, { segs: true })),
    el("div", { class: "card" }, el("h3", {}, "Asuntos votados por tema"),
      el("p", { class: "small muted" }, "Tema principal de cada asunto, de una lista cerrada de 23 temas."),
      itemsTema.length ? barrasH(itemsTema) : el("div", { class: "vacio" }, "Aún no hay temas asignados."))));

  // Actividad mensual.
  // Eje continuo: los meses sin votaciones (verano, disoluciones) también cuentan, con 0.
  const porMes = {};
  for (const m of res.mensual) {
    if (!enLegs(m.legislatura)) continue;
    const o = (porMes[m.mes] = porMes[m.mes] || { mes: m.mes, n: 0, ajustadas: 0 });
    o.n += m.n;
    o.ajustadas += m.ajustadas;
  }
  const mesesCon = Object.keys(porMes).sort();
  const desdeMes = mesesCon[0] || res.mensual[0].mes;
  const hastaMes = mesesCon.at(-1) || res.mensual.at(-1).mes;
  const meses = [];
  for (let [y, m] = desdeMes.split("-").map(Number); `${y}-${String(m).padStart(2, "0")}` <= hastaMes; m === 12 ? (y++, m = 1) : m++) {
    const mes = `${y}-${String(m).padStart(2, "0")}`;
    meses.push(porMes[mes] || { mes, n: 0, ajustadas: 0 });
  }
  const datos = meses.map((m, i) => ({
    y: m.n, label: `${MESES[+m.mes.slice(5) - 1]} ${m.mes.slice(0, 4)}`, extra: `${fmt(m.ajustadas)} ajustadas (±10 votos)`,
    tick: (m.mes.endsWith("-01") && (meses.length < 80 || +m.mes.slice(0, 4) % 2 === 0)) || (i === 0 && !m.mes.endsWith("-12")) ? m.mes.slice(0, 4) : null,
  }));
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Votaciones por mes"),
    el("p", { class: "small muted" }, "Los picos de otoño son los Presupuestos, con cientos de votaciones de enmiendas."),
    columnas(datos, { etiqueta: "Votaciones por mes" })));

  // Informe (es sobre el Congreso: solo si está en el ámbito).
  if (inf.informes.length && META.cuerpos.includes("congreso")) {
    const box = el("div", { class: "informe", style: "margin-top:16px" });
    for (const i of inf.informes) {
      box.append(el("h3", {}, i.titulo));
      box.append(markdown(i.contenido));
      box.append(el("p", { class: "procedencia" }, `Actualizado el ${fecha(i.creado.slice(0, 10))} a partir de las estadísticas de esta base de datos.`));
    }
    cont.append(el("h2", { style: "margin-top:24px" }, META.soloCongreso ? "Análisis" : "Análisis del Congreso"), box);
  }
  return cont;
};

// Qué hay de cada institución cargada: periodo, votaciones y nivel de detalle de la fuente.
function tablaCobertura() {
  const porCuerpo = new Map();
  for (const l of META.legislaturas) (porCuerpo.get(l.cuerpo) || porCuerpo.set(l.cuerpo, []).get(l.cuerpo)).push(l);
  const filas = [...porCuerpo.entries()].sort((a, b) => ordenCuerpo(a[0]) - ordenCuerpo(b[0])).map(([codigo, legs]) => {
    const c = CATALOGO.cuerpos[codigo] || { nombre: codigo };
    const r = resumenCuerpos([codigo]);
    const quien = c.nivel === "municipal" ? "concejal" : c.nivel === "provincial" ? "miembro" : "diputado";
    const detalle = r.nominal ? `Voto de cada ${quien}` : r.grupo ? "Voto de cada grupo" : r.totales ? "Solo el recuento" : "Solo el resultado";
    return el("tr", {},
      el("td", {}, c.web ? el("a", { href: c.web, target: "_blank", rel: "noopener" }, c.nombre) : c.nombre, marcaAviso(codigo)),
      el("td", {}, legs.map((l) => l.romano).join(", ")),
      el("td", { class: "small" }, `${fecha(legs.map((l) => l.desde).sort()[0])} – ${fecha(legs.map((l) => l.hasta).sort().at(-1))}`),
      el("td", { class: "num" }, fmt(legs.reduce((a, l) => a + l.votaciones, 0))),
      el("td", { class: "small" }, detalle));
  });
  return el("div", { class: "card", style: "margin-bottom:16px" }, el("h3", {}, "Qué hay de cada institución"),
    el("table", { class: "tabla" }, el("thead", {}, el("tr", {}, el("th", {}, "Institución"), el("th", {}, "Legislaturas"), el("th", {}, "Periodo"), el("th", { class: "num" }, "Votaciones"), el("th", {}, "Detalle"))),
      el("tbody", {}, filas)));
}

function stat(label, valor, nota) {
  return el("div", { class: "card stat" }, el("div", { class: "label" }, label), el("div", { class: "value" }, valor), el("div", { class: "nota" }, nota));
}

// Markdown mínimo (###, listas, **negrita**) construido con nodos de texto.
function markdown(texto) {
  const cont = el("div", {});
  let lista = null;
  for (const linea of (texto || "").split("\n")) {
    const l = linea.trim();
    if (!l) { lista = null; continue; }
    if (l.startsWith("### ")) { lista = null; cont.append(el("h3", {}, l.slice(4))); continue; }
    if (l.startsWith("- ")) {
      if (!lista) { lista = el("ul", {}); cont.append(lista); }
      lista.append(el("li", {}, inline(l.slice(2))));
      continue;
    }
    lista = null;
    cont.append(el("p", {}, inline(l)));
  }
  return cont;
}
function inline(t) {
  return t.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\((?:#\/|https:\/\/)[^)\s]+\))/).map((p) => {
    if (p.startsWith("**")) return el("strong", {}, p.slice(2, -2));
    const m = p.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (m) return el("a", m[2].startsWith("#") ? { href: m[2] } : { href: m[2], target: "_blank", rel: "noopener" }, m[1]);
    return p;
  });
}

VISTAS.votaciones = async (q) => {
  const pagina = +(q.pagina || 1);
  const d = await api("votaciones", { ...q, pagina, tam: 40 });
  const tipos = Object.entries(META.tipos_votacion);
  const campos = [
    el("input", { type: "search", name: "q", value: q.q || "", placeholder: "Buscar (vivienda, amnistía, 162/000123…)" }),
    multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
    multiSelect("tipo", tipos, q.tipo, "Cualquier tipo", "tipos"),
    multiSelect("familia", Object.entries(META.familias), q.familia, "Cualquier iniciativa", "categorías"),
    multiSelect("tema", optTemas(), q.tema, "Cualquier tema", "temas"),
    multiSelect("resultado", [["aprobada", "Aprobadas"], ["rechazada", "Rechazadas"]], q.resultado, "Cualquier resultado", "resultados"),
    multiSelect("autor", optAutores(q.leg), q.autor, "Cualquier proponente", "proponentes"),
    el("input", { type: "date", name: "desde", value: q.desde || "", "aria-label": "Desde" }),
    el("input", { type: "date", name: "hasta", value: q.hasta || "", "aria-label": "Hasta" }),
    el("label", { class: "check" }, el("input", { type: "checkbox", name: "decisivas", checked: q.decisivas === "1" }), "Solo decisivas"),
    el("label", { class: "check" }, el("input", { type: "checkbox", name: "ajustadas", checked: q.ajustadas === "1" }), "Ajustadas (±10)"),
    META.gobiernos.some((g) => META.cuerpos.includes(g.cuerpo))
      ? el("label", { class: "check", title: "Votaciones que perdió el partido del presidente del Gobierno" },
        el("input", { type: "checkbox", name: "derrotas", checked: q.derrotas === "1" }), "Derrotas del Gobierno") : null,
  ];
  const cont = el("div", {},
    el("h2", {}, "Votaciones"),
    el("p", { class: "sub" }, "Cada fila es una votación del Pleno. Las etiquetas de colores muestran qué votó cada grupo (✓ sí, ✗ no, ~ abstención); con borde, los grupos cuyo voto decidía el resultado."),
    formFiltros(campos, q, (f) => irA("votaciones", f)),
    el("p", { class: "small" }, el("button", { class: "boton", onclick: () => exportarVotacionesCSV(q) }, "⬇ Exportar estas votaciones a CSV"),
      el("span", { class: "muted" }, ` ${fmt(d.total)} votaciones, con el voto de cada grupo`,
        d.total > MAX_FILAS_CSV ? ` (se exportan las ${fmt(MAX_FILAS_CSV)} más recientes: filtra para exportar el resto)` : "")));
  if (!d.votaciones.length) cont.append(el("div", { class: "vacio" }, "Sin resultados."));
  cont.append(el("div", { class: "lista" }, d.votaciones.map(filaVotacion)));
  cont.append(paginacion(d.total, d.pagina, d.tam, (p) => irA("votaciones", { ...q, pagina: p })));
  return cont;
};

function filaIniciativa(i) {
  return el("article", { class: "fila", style: "grid-template-columns:92px minmax(0,1fr) 200px", tabindex: 0, onclick: () => abrir(`i:${i.legislatura}:${i.expediente}`), onkeydown: (e) => e.key === "Enter" && abrir(`i:${i.legislatura}:${i.expediente}`) },
    el("div", {}, el("div", { class: "fecha" }, fecha(i.ultima)), el("div", { class: "muted small" }, legTexto(i.legislatura))),
    el("div", {},
      el("div", { class: "titulo", title: i.titulo }, tituloCorto(i.titulo, esMovil() ? 110 : 170)),
      el("div", { class: "detalle" }, [i.sintetica ? "Sin expediente identificado" : i.expediente, i.tipo, i.autor].filter(Boolean).join(" · ")),
      i.resumen ? el("div", { class: "resumen" }, i.resumen) : null,
      el("div", { class: "badges" },
        badgeResultado(i.resultado_final),
        i.tema_principal ? el("span", { class: "badge ia" }, temaNombre(i.tema_principal)) : null,
        (i.temas_secundarios || []).map((t) => el("span", { class: "badge ia" }, temaNombre(t))),
        (i.marcas || []).map((m) => el("span", { class: "badge ia" }, m)),
        (i.etiquetas || []).map((e) => el("span", { class: "badge ia" }, "#" + e)))),
    el("div", { class: "small muted" }, `${i.nvot} votaci${i.nvot === 1 ? "ón" : "ones"}`,
      i.resultado_tramitacion ? el("div", {}, "Tramitación: " + i.resultado_tramitacion) : null));
}

VISTAS.iniciativas = async (q) => {
  const pagina = +(q.pagina || 1);
  const d = await api("iniciativas", { ...q, pagina, tam: 40 });
  const campos = [
    el("input", { type: "search", name: "q", value: q.q || "", placeholder: "Buscar en títulos, resúmenes y etiquetas" }),
    multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
    multiSelect("tema", optTemas(), q.tema, "Cualquier tema", "temas"),
    multiSelect("familia", Object.entries(META.familias), q.familia, "Cualquier tipo", "categorías"),
    multiSelect("autor", optAutores(q.leg), q.autor, "Cualquier proponente", "proponentes"),
    multiSelect("resultado", Object.entries(RESULTADOS).map(([k, v]) => [k, v[1]]), q.resultado, "Cualquier resultado", "resultados"),
    multiSelect("marca", [["emergencia", "Emergencia"], ["omnibus", "Ómnibus"]], q.marca, "Cualquier marca", "marcas"),
    q.etiqueta ? el("input", { type: "search", name: "etiqueta", value: q.etiqueta, "aria-label": "Etiqueta" }) : null,
  ];
  const cont = el("div", {},
    el("h2", {}, "Iniciativas votadas"),
    el("p", { class: "sub" }, "Una ficha por asunto: qué es, quién lo propone, de qué trata y cómo acabó. El resultado de las leyes es el oficial de tramitación; el de PNL y mociones, el de su votación."),
    formFiltros(campos, q, (f) => irA("iniciativas", f)));
  if (!d.iniciativas.length) cont.append(el("div", { class: "vacio" }, "Sin resultados."));
  cont.append(el("div", { class: "lista" }, d.iniciativas.map(filaIniciativa)));
  cont.append(paginacion(d.total, d.pagina, d.tam, (p) => irA("iniciativas", { ...q, pagina: p })));
  return cont;
};

VISTAS.temas = async (q) => {
  const leg = q.leg || "";
  const [d, et, leyes] = await Promise.all([api("temas", { leg }), api("etiquetas", { leg }), api("leyes")]);
  const cont = el("div", {}, el("h2", {}, "Temas"),
    el("p", { class: "sub" }, "Tasa de éxito por tema, separando lo que tiene fuerza de ley (leyes y decretos) de lo declarativo (PNL y mociones)."),
    formFiltros([multiSelect("leg", optLegs(), leg, "Todas las legislaturas", "legislaturas")], q, (f) => irA("temas", f)));

  const OK = new Set(["aprobada", "convalidada", "aprobada_en_parte"]);
  const T = {};
  for (const r of d.filas) {
    const t = (T[r.tema] = T[r.tema] || { tema: r.tema, leyV: 0, leyA: 0, declV: 0, declA: 0, total: 0 });
    const esLey = r.familia === "ley" || r.familia === "decreto_ley";
    const esDecl = r.familia === "pnl" || r.familia === "mocion";
    const cuenta = !["caducada", "retirada", "subsumida", "inadmitida", "en_tramite", "otra", null].includes(r.resultado_final);
    t.total += r.n;
    if (esLey && cuenta) { t.leyV += r.n; if (OK.has(r.resultado_final)) t.leyA += r.n; }
    if (esDecl) { t.declV += r.n; if (OK.has(r.resultado_final)) t.declA += r.n; }
  }
  const filas = Object.values(T).sort((a, b) => b.total - a.total);
  const tabla = el("table", { class: "tabla" },
    el("thead", {}, el("tr", {}, el("th", {}, "Tema"), el("th", { class: "num" }, "Asuntos"), el("th", { class: "num" }, "Leyes y decretos votados"), el("th", { class: "num" }, "aprobados"), el("th", { class: "num" }, "PNL y mociones"), el("th", { class: "num" }, "aprobadas"))),
    el("tbody", {}, filas.map((t) => el("tr", { class: "clic", onclick: () => irA("tema", { leg, tema: t.tema }) },
      el("td", {}, temaNombre(t.tema)), el("td", { class: "num" }, fmt(t.total)),
      el("td", { class: "num" }, fmt(t.leyV)), el("td", { class: "num" }, t.leyV ? `${pct(t.leyA, t.leyV)}%` : "—"),
      el("td", { class: "num" }, fmt(t.declV)), el("td", { class: "num" }, t.declV ? `${pct(t.declA, t.declV)}%` : "—")))));
  cont.append(el("div", { class: "card" }, el("h3", {}, "Éxito por tema"),
    el("p", { class: "small muted" }, "Clic en un tema para ver cómo vota cada grupo, quién lo propone, las afinidades y la votación a votación."), tabla));

  // Proponente x tema (PNL, mociones y proposiciones de ley de grupos).
  const P = {};
  const autores = new Map();
  for (const r of d.filas) {
    if (!r.grupo_autor || ["internacional", "organizacion", "control", "otro"].includes(r.familia)) continue;
    if (["caducada", "retirada", "subsumida", "inadmitida", "en_tramite", "otra", null].includes(r.resultado_final)) continue;
    const k = r.tema + "|" + r.grupo_autor;
    P[k] = P[k] || { v: 0, a: 0 };
    P[k].v += r.n;
    if (OK.has(r.resultado_final)) P[k].a += r.n;
    autores.set(r.grupo_autor, (autores.get(r.grupo_autor) || 0) + r.n);
  }
  const cols = [...autores.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12).map(([a]) => a);
  const legRef = leg || META.legislaturas.at(-1).id;
  const heat = el("div", { class: "heat" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}), cols.map((c) => el("th", { class: "rot" }, el("div", {}, grupo(autorLeg(c), c).siglas))))),
    el("tbody", {}, filas.map((t) => el("tr", {}, el("th", { style: "text-align:left" }, temaNombre(t.tema)),
      cols.map((c) => {
        const x = P[t.tema + "|" + c];
        if (!x) return el("td", { class: "self" });
        const p = x.a / x.v;
        const col = colorSecuencial(p);
        // Con menos de 3 iniciativas el porcentaje dice poco: la celda se atenúa.
        return conTip(el("td", { style: `background:${col.bg};color:${col.ink};${x.v < 3 ? "opacity:.35" : ""}`, tabindex: 0 }, `${Math.round(100 * p)}`),
          `${Math.round(100 * p)}% aprobadas`, `${grupo(autorLeg(c), c).siglas} · ${temaNombre(t.tema)}`, `${x.a} de ${x.v} votadas`);
      }))))));
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Quién consigue sacar adelante qué"),
    el("p", { class: "small muted" }, "Porcentaje de iniciativas votadas que salen adelante, por proponente y tema (más oscuro = más éxito). Las celdas atenuadas tienen menos de 3 iniciativas. Pasa el ratón por una celda para ver cuántas son."),
    heat));

  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Etiquetas más frecuentes"),
      el("p", { class: "small muted" }, "Etiquetas más usadas: captan la actualidad que la lista de temas no recoge."),
      el("div", { class: "chips" }, et.etiquetas.map((e) => el("a", { class: "chip", href: `#/iniciativas?${new URLSearchParams({ ...(leg ? { leg } : {}), etiqueta: e.etiqueta })}` }, `#${e.etiqueta}`, el("span", { class: "muted" }, ` ${e.n}`))))),
    el("div", { class: "card" }, el("h3", {}, "Leyes que más se intenta modificar"),
      el("p", { class: "small muted" }, "Normas citadas como afectadas en los títulos de lo votado, todas las legislaturas."),
      barrasH(leyes.leyes.slice(0, 15).map((l) => ({ label: l.ley, v: l.n, tip: () => l.iniciativas.slice(0, 3).map((i) => tituloCorto(i.titulo, 80)).join(" · ") }))))));
  return cont;
};

function autorLeg(codigo) {
  for (const l of [...META.legislaturas].reverse()) if ((META.grupos[l.id] || []).some((g) => g.codigo === codigo)) return l.id;
  return META.legislaturas.at(-1).id;
}

VISTAS.grupos = async (q) => {
  const legs = legsOActual(q.leg);
  const temas = lista(q.tema).filter((t) => t !== "*");
  const leg = legs.join(",");
  const [af, dec] = await Promise.all([api("afinidad", { leg, tema: temas.join(",") }), api("decisivos", { leg })]);
  const cont = el("div", {}, el("h2", {}, "Grupos"),
    el("p", { class: "sub" }, "Afinidad: en qué porcentaje de votaciones de fondo (PNL, mociones, tomas en consideración, totalidades, conjuntos, convalidaciones…) dos grupos votan lo mismo. Se excluyen las enmiendas parciales y lo votado por asentimiento. Con varias legislaturas, cada partido suma las de todas. Para poner dos o más partidos frente a frente tema a tema, usa ",
      el("a", { href: `#/comparar${leg ? "?leg=" + leg : ""}` }, "Comparar"), "."),
    formFiltros([
      multiSelect("leg", optLegs(), leg, "Legislatura", "legislaturas"),
      multiSelect("tema", optTemas(), temas.join(","), "Todos los temas", "temas"),
    ], q, (f) => irA("grupos", f)));

  const gs = gruposDeLegs(legs);
  const mapa = {};
  for (const p of af.pares) mapa[p.a + "|" + p.b] = p;
  const heat = el("div", { class: "heat" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}), gs.map((g) => el("th", { class: "rot" }, el("div", {}, g.siglas))))),
    el("tbody", {}, gs.map((a) => el("tr", {},
      el("th", { style: "text-align:left;white-space:nowrap;cursor:pointer", title: "Ver el perfil del grupo", onclick: () => irA("grupo", { g: a.siglas, leg }) }, swatch(a.color), a.siglas),
      gs.map((b) => {
        if (a.siglas === b.siglas) return el("td", { class: "self" });
        const p = mapa[a.siglas + "|" + b.siglas];
        if (!p || p.total < 5) return el("td", { class: "self" }, el("span", { class: "muted" }, "·"));
        const r = p.coinciden / p.total;
        const c = colorSecuencial(r);
        return conTip(el("td", { style: `background:${c.bg};color:${c.ink}`, tabindex: 0 }, Math.round(100 * r)),
          `${Math.round(100 * r)}% de coincidencia`, `${a.siglas} y ${b.siglas}`, `${fmt(p.coinciden)} de ${fmt(p.total)} votaciones`);
      }))))));
  cont.append(el("div", { class: "card" }, el("h3", {}, `Afinidad entre grupos · ${textoLegs(legs)}${temas.length ? " · " + textoTemas(temas) : ""}`), heat,
    el("p", { class: "small muted" }, "Más oscuro = votan igual más a menudo. El Grupo Mixto reúne partidos distintos y su «voto» es el mayoritario entre sus miembros.")));

  // Grupo decisivo.
  const cuenta = new Map();
  for (const r of dec.filas) {
    const o = cuenta.get(r.siglas) || { color: r.color, abst: 0, camb: 0 };
    o[r.modo === "absteniendose" ? "abst" : "camb"] += r.n;
    cuenta.set(r.siglas, o);
  }
  const items = [...cuenta.entries()].sort((a, b) => (b[1].abst + b[1].camb) - (a[1].abst + a[1].camb)).map(([s, c]) => ({
    label: s, color: c.color,
    segs: [{ v: c.abst, color: "var(--seq-600)", nombre: "bastaba con abstenerse" }, { v: c.camb, color: "var(--seq-300)", nombre: "cambiando el voto" }],
    tip: (x) => `${fmt(x.v)} votaciones decisivas en las que ${s} daba la vuelta al resultado ${x.nombre}`,
    onclick: () => irA("grupo", { g: s, leg }),
  }));
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Grupo decisivo"),
      el("p", { class: "small muted" }, `En cuántas de las ${fmt(dec.decisivas_nominales)} votaciones decisivas nominales de ${legs.length > 1 ? "estas legislaturas" : "la legislatura"} el voto de cada grupo determinaba el resultado. «Abstenerse» es el caso más fuerte: bastaba con no votar lo que votó.`),
      el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--seq-600)" }), "Bastaba con abstenerse"), el("span", {}, el("i", { style: "background:var(--seq-300)" }), "Cambiando el voto")),
      barrasH(items, { segs: true })),
    el("div", { class: "card" }, el("h3", {}, "Las más ajustadas"),
      el("p", { class: "small muted" }, "Leyes, decretos, tomas en consideración y totalidades decididas por menos margen, con los grupos que las decidían."),
      el("table", { class: "tabla" }, el("tbody", {}, dec.ejemplos.map((v) => el("tr", { class: "clic", onclick: () => abrir(`v:${v.id}`) },
        el("td", { class: "small" }, fecha(v.fecha)),
        el("td", {}, textoCorto(v.texto_expediente, 110), el("div", { class: "small muted" }, `${META.tipos_votacion[v.tipo_votacion]} · ${v.resultado} ${v.a_favor}–${v.en_contra}`)),
        el("td", { class: "small" }, (v.grupos || "").split(",").map((g) => grupo(v.legislatura, g).siglas).join(", ")))))))));
  return cont;
};

// ------------------------------------------------------------------ análisis por tema

const optFamiliasAnalisis = () => [
  ["legislativo", "Leyes y decretos-leyes"], ["declarativo", "PNL y mociones"],
  ["ley", "Solo leyes"], ["decreto_ley", "Solo decretos-leyes"], ["pnl", "Solo PNL"], ["mocion", "Solo mociones"],
  ["internacional", "Convenios internacionales"],
];

function colorSiglas(siglas) {
  for (const l of [...META.legislaturas].reverse()) {
    const g = (META.grupos[l.id] || []).find((x) => x.siglas === siglas);
    if (g) return g.color;
  }
  return "#9aa0a6";
}
function todasSiglas() {
  const m = new Map();
  for (const l of META.legislaturas) for (const g of META.grupos[l.id] || []) {
    if (g.codigo === "?") continue;
    m.set(g.siglas, (m.get(g.siglas) || 0) + g.diputados);
  }
  return [...m.entries()].sort((a, b) => b[1] - a[1]).map(([s]) => s);
}
const swatch = (color) => el("span", { style: `display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${color}` });
const leyendaApoyo = () => el("div", { class: "legend" },
  el("span", {}, el("i", { style: "background:var(--si)" }), "A favor"), el("span", {}, el("i", { style: "background:var(--abs)" }), "Abstención"),
  el("span", {}, el("i", { style: "background:var(--novota)" }), "Grupo dividido"), el("span", {}, el("i", { style: "background:var(--no)" }), "En contra"));

function segsApoyo(o) {
  return [
    { v: o.si, color: "var(--si)", nombre: "a favor" }, { v: o.abst, color: "var(--abs)", nombre: "abstención" },
    { v: o.div, color: "var(--novota)", nombre: "grupo dividido" }, { v: o.no, color: "var(--no)", nombre: "en contra" },
  ];
}
const pctFavor = (o) => (o.n ? Math.round((100 * o.si) / o.n) : 0);

// Mapa de calor por siglas (afinidad o apoyo) con celdas atenuadas si hay pocos casos.
function mapaCalor(filas, columnas, valor, { etiquetaFila = (x) => x, etiquetaCol = (x) => x, minimo = 5, tip, alClicarFila } = {}) {
  return el("div", { class: "heat" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}), columnas.map((c) => el("th", { class: "rot" }, el("div", {}, etiquetaCol(c)))))),
    el("tbody", {}, filas.map((f) => el("tr", {},
      el("th", { style: `text-align:left;white-space:nowrap;${alClicarFila ? "cursor:pointer" : ""}`, onclick: alClicarFila ? () => alClicarFila(f) : null }, etiquetaFila(f)),
      columnas.map((c) => {
        const x = valor(f, c);
        if (!x) return el("td", { class: "self" });
        if (x.n < minimo) return conTip(el("td", { class: "self", tabindex: 0 }, el("span", { class: "muted" }, "·")), `${fmtAs(x.n)} casos`, "Demasiado pocos para calcular un porcentaje");
        const col = colorSecuencial(x.p);
        return conTip(el("td", { style: `background:${col.bg};color:${col.ink}`, tabindex: 0 }, Math.round(100 * x.p)), ...tip(f, c, x));
      }))))));
}

VISTAS.tema = async (q) => {
  const tema = q.tema || META.temas[0].codigo;
  const elegidos = lista(tema).map((c) => META.temas.find((t) => t.codigo === c) || { nombre: c, subtemas: "" });
  const info = { nombre: elegidos.map((t) => t.nombre).join(" + "), subtemas: elegidos.map((t) => t.subtemas).join("; ") };
  const d = await api("tema", { ...q, tema });
  const cont = el("div", {});
  const base = { tema, leg: q.leg, familia: q.familia, sec: q.sec };
  cont.append(
    el("p", { class: "small", style: "margin:0" }, el("a", { href: `#/temas${q.leg ? "?leg=" + q.leg : ""}` }, "← Todos los temas")),
    el("h2", {}, info.nombre, q.etiqueta ? el("span", { class: "muted" }, ` · #${q.etiqueta}`) : null),
    el("p", { class: "sub" }, `Incluye, por ejemplo: ${info.subtemas}.`),
    formFiltros([
      multiSelect("tema", META.temas.map((t) => [t.codigo, t.nombre]), tema, "Tema", "temas"),
      multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
      multiSelect("familia", optFamiliasAnalisis(), q.familia, "Todo tipo de asunto", "categorías"),
      el("label", { class: "check" }, el("input", { type: "checkbox", name: "sec", checked: q.sec === "1" }), "Contar también si es tema secundario"),
      q.etiqueta ? el("input", { type: "hidden", name: "etiqueta", value: q.etiqueta }) : null,
      q.etiqueta ? el("a", { class: "chip", href: "#/tema?" + new URLSearchParams(Object.entries(base).filter(([, v]) => v)) }, `#${q.etiqueta} ✕`) : null,
    ], q, (f) => irA("tema", f)));

  if (!d.asuntos.length) {
    cont.append(el("div", { class: "vacio" }, "No hay asuntos votados con estos filtros."));
    return cont;
  }

  // Cifras.
  const sale = d.asuntos.filter((x) => SALE_RES.has(x.resultado_final)).length;
  const cae = d.asuntos.filter((x) => CAE_RES.has(x.resultado_final)).length;
  cont.append(el("div", { class: "grid g4" },
    stat("Asuntos votados", fmt(d.asuntos.length), "iniciativas y trámites"),
    stat("Salen adelante", `${pct(sale, d.asuntos.length)}%`, `${fmt(sale)} salen, ${fmt(cae)} rechazados, ${fmt(d.asuntos.length - sale - cae)} caducan o siguen`),
    stat("Votaciones decisivas nominales", fmt(d.totalMatriz), "las que se analizan abajo"),
    stat("Por asentimiento", fmt(d.asentimiento), "sin votación nominal")));

  // Cómo vota cada grupo.
  const porSiglas = sumarPor(d.apoyo, (r) => r.siglas);
  const medias = sumarPor(d.media, (r) => r.siglas);
  const grupos = [...porSiglas.values()].filter((o) => o.n >= 3).sort((a, b) => pctFavor(b) - pctFavor(a));
  const itemsApoyo = grupos.map((o) => {
    const m = medias.get(o.siglas);
    const delta = m && m.n ? pctFavor(o) - pctFavor(m) : null;
    return {
      label: o.siglas, color: o.color, segs: segsApoyo(o),
      valorTexto: `${pctFavor(o)}%` + (delta === null ? "" : ` (${delta > 0 ? "+" : ""}${delta})`),
      tip: (s) => `${fmtAs(s.v)} de ${fmtAs(o.n)} asuntos (${fmt(o.nv)} votaciones) · su media en todos los temas: ${m ? pctFavor(m) : "—"}% a favor`,
      onclick: () => irA("grupo", { g: o.siglas, leg: q.leg, familia: q.familia }),
    };
  });
  const nombresFamilia = q.familia ? optFamiliasAnalisis().find(([k]) => k === q.familia)?.[1].toLowerCase() : "asuntos";
  const aComparar = grupos.slice().sort((a, b) => b.n - a.n).slice(0, 2).map((o) => o.siglas).join(",");
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Cómo vota cada grupo"),
      el("p", { class: "small muted" }, `Voto de cada grupo en la votación decisiva de cada asunto (${nombresFamilia}). Cada asunto cuenta una vez: si se votó por puntos, sus puntos se reparten el peso. El número es el porcentaje a favor y, entre paréntesis, la diferencia con su media en todos los temas con los mismos filtros. En las enmiendas a la totalidad el voto se invierte: votar sí a la devolución es votar en contra del proyecto. Clic en un grupo para ver su perfil.`),
      leyendaApoyo(), barrasH(itemsApoyo, { segs: true, normalizar: true, formato: fmtAs }),
      el("p", { class: "aviso-lectura small" }, "Cada grupo vota casi siempre a favor de lo que presenta él mismo, y el partido del Gobierno, de lo que presenta el Gobierno. Un porcentaje alto puede deberse a que el grupo presentó muchos asuntos del tema, no a que apoye más ese tema. ",
        el("a", { href: "#/comparar?" + new URLSearchParams(Object.entries({ g: aComparar, tema, leg: q.leg, familia: q.familia }).filter(([, v]) => v)) }, "Compara grupos separando lo propio de lo ajeno →"))),
    tarjetaProponentes(d.asuntos)));

  // Afinidad en el tema.
  const orden = grupos.slice().sort((a, b) => b.n - a.n).map((o) => o.siglas);
  const par = {};
  for (const r of d.afinidad) par[r.a + "|" + r.b] = r;
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Con quién coincide cada grupo en este tema"),
    el("p", { class: "small muted" }, "Porcentaje de votaciones de fondo del tema (tema principal) en que los dos grupos votan lo mismo. Si abarca varias legislaturas, se suman por partido."),
    mapaCalor(orden, orden, (a, b) => {
      if (a === b) return null;
      const r = par[a + "|" + b];
      return r ? { p: r.coinciden / r.total, n: r.total, r } : null;
    }, {
      etiquetaFila: (s) => [swatch(colorSiglas(s)), s],
      tip: (a, b, x) => [`${Math.round(100 * x.p)}% de coincidencia`, `${a} y ${b}`, `${fmt(x.r.coinciden)} de ${fmt(x.n)} votaciones`],
      alClicarFila: (s) => irA("grupo", { g: s, leg: q.leg }),
    })));

  // Evolución por legislatura (si hay más de una en juego).
  if (lista(q.leg).length !== 1) {
    const legs = META.legislaturas.filter((l) => d.asuntos.some((x) => x.legislatura === l.id));
    const porGL = sumarPor(d.apoyo, (r) => r.siglas + "|" + r.legislatura);
    const filasEvo = todasSiglas().filter((s) => legs.some((l) => (porGL.get(s + "|" + l.id) || {}).n >= 3));
    const resumenLeg = legs.map((l) => {
      const xs = d.asuntos.filter((x) => x.legislatura === l.id);
      return `${l.romano}: ${xs.length} asuntos, ${pct(xs.filter((x) => SALE_RES.has(x.resultado_final)).length, xs.length)}% salen`;
    });
    cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cómo ha cambiado el apoyo de cada grupo"),
      el("p", { class: "small muted" }, "Porcentaje de asuntos del tema en que cada grupo votó a favor en la votación decisiva, por legislatura. Ayuda a ver cómo cambia la posición de un partido entre el Gobierno y la oposición. " + resumenLeg.join(" · ")),
      mapaCalor(filasEvo, legs, (s, l) => {
        const o = porGL.get(s + "|" + l.id);
        return o ? { p: o.si / o.n, n: o.n, o } : null;
      }, {
        minimo: 3,
        etiquetaFila: (s) => [swatch(colorSiglas(s)), s], etiquetaCol: (l) => `Leg. ${l.romano}`,
        tip: (s, l, x) => [`${Math.round(100 * x.p)}% a favor`, `${s} · Leg. ${l.romano}`, `de ${fmtAs(x.o.n)} asuntos: a favor ${fmtAs(x.o.si)}, abst. ${fmtAs(x.o.abst)}, en contra ${fmtAs(x.o.no)}, dividido ${fmtAs(x.o.div)}`],
      })));
  }

  // Etiquetas del tema.
  const et = new Map();
  for (const x of d.asuntos) for (const e of jsonDe(x.etiquetas, [])) et.set(e, (et.get(e) || 0) + 1);
  const topEt = [...et.entries()].sort((a, b) => b[1] - a[1]).slice(0, 40);
  if (topEt.length) {
    cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Subtemas (etiquetas)"),
      el("p", { class: "small muted" }, "Clic en una etiqueta para limitar todo el análisis a esos asuntos."),
      el("div", { class: "chips" }, topEt.map(([e, n]) => el("a", {
        class: "chip" + (e === q.etiqueta ? " decisivo" : ""), href: "#/tema?" + new URLSearchParams({ ...Object.fromEntries(Object.entries(base).filter(([, v]) => v)), etiqueta: e }),
      }, `#${e}`, el("span", { class: "muted" }, ` ${n}`))))));
  }

  // Votación a votación.
  cont.append(el("div", { class: "card", style: "margin-top:16px" },
    el("div", { style: "display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap" },
      el("h3", {}, "Votación a votación"),
      el("label", { class: "check small" }, el("input", {
        type: "checkbox", checked: q.ajustadas === "1",
        onchange: (e) => irA("tema", { ...q, tema, ajustadas: e.target.checked ? "1" : "", pagina: "" }),
      }), "Solo ajustadas (±10 votos)")),
    el("p", { class: "small muted" }, "Posición de cada grupo respecto a la iniciativa en su votación decisiva: ✓ a favor, ✗ en contra, ~ abstención, ± grupo dividido. Clic en una fila para ver el voto nominal."),
    matrizVotos(d, grupos.slice().sort((a, b) => b.n - a.n).map((o) => o.siglas).slice(0, 14)),
    paginacion(d.totalMatriz, d.pagina, d.tam, (p) => irA("tema", { ...q, tema, pagina: p }))));
  return cont;
};

function tarjetaProponentes(asuntos) {
  const porAutor = new Map();
  for (const x of asuntos) {
    if (!x.grupo_autor) continue;
    const info = grupo(x.legislatura, x.grupo_autor);
    const o = porAutor.get(info.siglas) || { siglas: info.siglas, color: info.color, sale: 0, cae: 0, otra: 0, n: 0 };
    o[SALE_RES.has(x.resultado_final) ? "sale" : CAE_RES.has(x.resultado_final) ? "cae" : "otra"]++;
    o.n++;
    porAutor.set(info.siglas, o);
  }
  const items = [...porAutor.values()].sort((a, b) => b.n - a.n).slice(0, 14).map((o) => ({
    label: o.siglas, color: o.color, valorTexto: `${o.sale} de ${o.n}`,
    segs: [{ v: o.sale, color: "var(--si)", nombre: "salen adelante" }, { v: o.otra, color: "var(--abs)", nombre: "caducan, se retiran o siguen" }, { v: o.cae, color: "var(--no)", nombre: "rechazadas" }],
    tip: (s) => `${fmt(s.v)} iniciativas de ${o.siglas} que ${s.nombre}`,
  }));
  return el("div", { class: "card" }, el("h3", {}, "Quién propone y quién lo consigue"),
    el("p", { class: "small muted" }, "Asuntos votados según quién los presentó y cómo acabaron (resultado oficial en leyes y decretos; el de su votación en PNL y mociones)."),
    el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--si)" }), "Salen adelante"), el("span", {}, el("i", { style: "background:var(--abs)" }), "Caducan o siguen"), el("span", {}, el("i", { style: "background:var(--no)" }), "Rechazadas")),
    items.length ? barrasH(items, { segs: true }) : el("p", { class: "muted" }, "Sin proponente identificado."));
}

const CELDA = { si: ["si", "✓", "A favor"], no: ["no", "✗", "En contra"], abstencion: ["ab", "~", "Abstención"], dividido: ["dv", "±", "Grupo dividido"] };

function matrizVotos(d, columnas, { marcas = null, alMarcar = null } = {}) {
  if (!d.votaciones.length) return el("div", { class: "vacio" }, "Sin votaciones nominales con estos filtros.");
  const selectorMarca = (v) => el("td", { onclick: (e) => e.stopPropagation() }, el("select", {
    class: "marca", "aria-label": "Voto favorable para tu causa",
    onchange: (e) => alMarcar(v.id, e.target.value),
  }, [["", "—"], ["si", "A favor"], ["no", "En contra"]].map(([k, t]) => el("option", { value: k, selected: (marcas[v.id] || "") === k }, t))));
  return el("div", { class: "matriz" }, el("table", {},
    el("thead", {}, el("tr", {}, el("th", {}), el("th", {}), marcas ? el("th", { class: "small", style: "vertical-align:bottom" }, "Voto favorable") : null,
      columnas.map((s) => el("th", { class: "rot" }, el("div", {}, s))))),
    el("tbody", {}, d.votaciones.map((v) => {
      const titulo = v.titulo && !v.sintetica ? v.titulo : (v.texto_expediente || "").split("\n")[0];
      const sub = [v.titulo_subgrupo, v.texto_subgrupo].filter(Boolean).join(" — ");
      return el("tr", { class: "clic", onclick: () => abrir(`v:${v.id}`) },
        el("td", { class: "small", style: "white-space:nowrap;color:var(--ink-2)" }, fecha(v.fecha)),
        el("td", { class: "tit" },
          el("div", { title: titulo }, tituloCorto(titulo, 150)),
          el("div", { class: "small muted" }, [META.tipos_votacion[v.tipo_votacion] + (v.tipo_votacion === "totalidad" ? " (voto invertido)" : ""),
            v.grupo_autor ? "propone " + grupo(v.legislatura, v.grupo_autor).siglas : null, sub ? sub.slice(0, 80) : null].filter(Boolean).join(" · ")),
          el("div", { class: "small" }, badgeResultado(v.resultado), ` ${v.a_favor}–${v.en_contra}–${v.abstenciones}`)),
        marcas ? selectorMarca(v) : null,
        columnas.map((s) => {
          const c = (d.celdas[v.id] || {})[s];
          if (!c || !CELDA[c.apoyo]) return el("td", {});
          const [cls, glifo, txt] = CELDA[c.apoyo];
          return conTip(el("td", { class: `vc ${cls}`, tabindex: 0 }, glifo), `${s}: ${txt}`,
            `Sí ${c.si} · Abst. ${c.abstencion} · No ${c.no}`, c.tipo_votacion === "totalidad" ? "Enmienda a la totalidad: votar sí es votar contra el proyecto" : null);
        }));
    }))));
}

// ------------------------------------------------------------------ perfil de grupo

VISTAS.grupo = async (q) => {
  // Varios grupos se analizan juntos, como un bloque: se suman sus votos, iniciativas y afinidades.
  const gs = lista(q.g).length ? lista(q.g) : [todasSiglas()[0]];
  const d = await api("grupoPerfil", { g: gs.join(","), leg: q.leg, familia: q.familia });
  const nombres = [...new Set(META.legislaturas.flatMap((l) => (META.grupos[l.id] || []).filter((g) => gs.includes(g.siglas)).map((g) => g.nombre)))];
  const cont = el("div", {},
    el("p", { class: "small", style: "margin:0" }, el("a", { href: `#/grupos${q.leg ? "?leg=" + q.leg : ""}` }, "← Grupos")),
    el("h2", {}, gs.map((s, i) => [i ? " + " : null, swatch(colorSiglas(s)), s])),
    el("p", { class: "sub" }, gs.length > 1
      ? `Bloque de ${gs.length} grupos (${nombres.join(" · ")}): se suman sus votos, sus iniciativas y su afinidad con el resto. Presentes en las legislaturas ${d.legislaturas.map(romano).join(", ")}.`
      : `${nombres.join(" · ")}. Presente en las legislaturas ${d.legislaturas.map(romano).join(", ")}. «${gs[0]}» agrupa los grupos parlamentarios de ese partido en distintas legislaturas.`),
    formFiltros([
      multiSelect("g", todasSiglas().map((s) => [s, s]), gs.join(","), "Grupo", "grupos"),
      multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
      multiSelect("familia", optFamiliasAnalisis(), q.familia, "Todo tipo de asunto", "categorías"),
    ], q, (f) => irA("grupo", f)));
  if (d.programas.length) {
    cont.append(el("p", { class: "small" }, el("a", { href: "#/programas?" + new URLSearchParams({ g: d.programas.join(",") }) },
      `${d.programas.length > 1 ? "Sus programas electorales" : "Su programa electoral"}: lo que prometió frente a lo que votó →`)));
  }

  const total = d.porTema.reduce((o, r) => { for (const c of ["si", "no", "abst", "div", "n", "nv"]) o[c] += r[c]; return o; }, { si: 0, no: 0, abst: 0, div: 0, n: 0, nv: 0 });
  const legsFiltro = lista(q.leg).length ? lista(q.leg).map(Number) : d.legislaturas;
  const decisivasTotales = d.totalesDecisivas.filter((r) => legsFiltro.includes(r.legislatura)).reduce((a, r) => a + r.n, 0);
  const abst = d.decisivo.filter((r) => r.modo === "absteniendose").reduce((a, r) => a + r.n, 0);
  const coh = d.cohesion.reduce((o, r) => ({ n: o.n + r.n, p: o.p + r.partidas }), { n: 0, p: 0 });
  const propias = d.propuestas.reduce((a, r) => a + r.n, 0);
  const propiasOk = d.propuestas.filter((r) => SALE_RES.has(r.resultado_final)).reduce((a, r) => a + r.n, 0);
  cont.append(el("div", { class: "grid g4" },
    stat("Vota a favor", `${pctFavor(total)}%`, `de ${fmt(Math.round(total.n))} asuntos votados (${fmt(total.nv)} votaciones decisivas de fondo)`),
    stat("Sus iniciativas", `${pct(propiasOk, propias)}% salen`, `${fmt(propiasOk)} de ${fmt(propias)} votadas`),
    stat("Decisivo absteniéndose", fmt(abst), `de ${fmt(decisivasTotales)} votaciones decisivas nominales`),
    stat("Divisiones internas", `${(coh.n ? (100 * coh.p) / coh.n : 0).toFixed(1)}%`, "votaciones de fondo con ≥10% del grupo en contra de su mayoría")));

  // Voto por tema.
  const media = pctFavor(total);
  // Sin tema: debates de política general, cuyas propuestas de resolución tratan de cualquier cosa.
  const itemsTema = d.porTema.filter((r) => r.tema && r.n >= 3).sort((a, b) => pctFavor(b) - pctFavor(a)).map((r) => ({
    label: temaNombre(r.tema), segs: segsApoyo(r), valorTexto: `${pctFavor(r)}% (${pctFavor(r) - media > 0 ? "+" : ""}${pctFavor(r) - media})`,
    tip: (s) => `${fmtAs(s.v)} de ${fmtAs(r.n)} asuntos (${fmt(r.nv)} votaciones)`, onclick: () => irA("tema", { tema: r.tema, leg: q.leg, familia: q.familia }),
  }));
  // Sus iniciativas por tema.
  const prop = new Map();
  for (const r of d.propuestas) {
    if (!r.tema) continue;
    const o = prop.get(r.tema) || { sale: 0, cae: 0, otra: 0, n: 0 };
    o[SALE_RES.has(r.resultado_final) ? "sale" : CAE_RES.has(r.resultado_final) ? "cae" : "otra"] += r.n;
    o.n += r.n;
    prop.set(r.tema, o);
  }
  const itemsProp = [...prop.entries()].sort((a, b) => b[1].n - a[1].n).map(([t, o]) => ({
    label: temaNombre(t), valorTexto: `${o.sale} de ${o.n}`,
    segs: [{ v: o.sale, color: "var(--si)", nombre: "salen adelante" }, { v: o.otra, color: "var(--abs)", nombre: "caducan o siguen" }, { v: o.cae, color: "var(--no)", nombre: "rechazadas" }],
    tip: (s) => `${fmt(s.v)} iniciativas que ${s.nombre}`,
  }));
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Cómo vota en cada tema"),
      el("p", { class: "small muted" }, `Porcentaje de asuntos en que votó a favor en la votación decisiva y, entre paréntesis, diferencia con su media (${media}%). Cada asunto cuenta una vez aunque se votara por puntos. Incluye lo que presenta el propio grupo, que casi siempre apoya. Clic en un tema para analizarlo.`),
      leyendaApoyo(), itemsTema.length ? barrasH(itemsTema, { segs: true, normalizar: true, formato: fmtAs }) : el("p", { class: "muted" }, "Sin votaciones."),
      el("p", { class: "small" }, el("a", { href: "#/comparar?" + new URLSearchParams(Object.entries({ g: gs.join(","), leg: q.leg, familia: q.familia }).filter(([, v]) => v)) }, "Compáralo con otros grupos, separando lo propio de lo ajeno →"))),
    el("div", { class: "card" }, el("h3", {}, "Sus iniciativas, por tema"),
      el("p", { class: "small muted" }, "Asuntos presentados por el grupo que llegaron a votarse y cómo acabaron."),
      el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--si)" }), "Salen"), el("span", {}, el("i", { style: "background:var(--abs)" }), "Caducan o siguen"), el("span", {}, el("i", { style: "background:var(--no)" }), "Rechazadas")),
      itemsProp.length ? barrasH(itemsProp, { segs: true }) : el("p", { class: "muted" }, "No presentó asuntos que se votaran con estos filtros."))));

  // Con quién coincide: global y dónde más y menos.
  const porOtro = new Map();
  for (const r of d.afinidad) {
    const o = porOtro.get(r.otro) || { otro: r.otro, color: r.color, global: null, temas: [] };
    if (r.tema === "*") o.global = r;
    else if (r.tema !== "?" && r.total >= 10) o.temas.push(r);
    porOtro.set(r.otro, o);
  }
  const otros = [...porOtro.values()].filter((o) => o.global && o.global.total >= 20)
    .sort((a, b) => b.global.coinciden / b.global.total - a.global.coinciden / a.global.total);
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Con quién coincide"),
    el("p", { class: "small muted" }, "Coincidencia en votaciones de fondo con cada grupo, y los temas en que más y menos coinciden (con al menos 10 votaciones)."),
    el("table", { class: "tabla" },
      el("thead", {}, el("tr", {}, el("th", {}, "Grupo"), el("th", { class: "num" }, "Coincidencia"), el("th", {}, "Donde más"), el("th", {}, "Donde menos"))),
      el("tbody", {}, otros.map((o) => {
        const ts = o.temas.sort((a, b) => b.coinciden / b.total - a.coinciden / a.total);
        const f = (r) => r ? `${temaNombre(r.tema)} ${Math.round((100 * r.coinciden) / r.total)}%` : "—";
        return el("tr", { class: "clic", onclick: () => irA("grupo", { g: o.otro, leg: q.leg }) },
          el("td", {}, swatch(o.color), o.otro),
          el("td", { class: "num" }, `${Math.round((100 * o.global.coinciden) / o.global.total)}%`),
          el("td", { class: "small" }, f(ts[0])), el("td", { class: "small" }, ts.length > 1 ? f(ts.at(-1)) : "—"));
      })))));

  // Cuándo decide.
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cuándo su voto decidió el resultado"),
    el("p", { class: "small muted" }, "Votaciones decisivas de fondo en que bastaba con que el grupo se abstuviera para que el resultado fuera el contrario."),
    d.clave.length ? el("table", { class: "tabla" }, el("tbody", {}, d.clave.map((v) => el("tr", { class: "clic", onclick: () => abrir(`v:${v.id}`) },
      el("td", { class: "small", style: "white-space:nowrap" }, fecha(v.fecha)),
      el("td", {}, textoCorto(v.titulo && !v.sintetica ? v.titulo : v.texto_expediente, 140),
        el("div", { class: "small muted" }, [META.tipos_votacion[v.tipo_votacion], v.tema_principal ? temaNombre(v.tema_principal) : null].filter(Boolean).join(" · "))),
      el("td", { class: "small", style: "white-space:nowrap" }, badgeResultado(v.resultado), ` ${v.a_favor}–${v.en_contra}`))))) :
      el("p", { class: "muted" }, "Ninguna con estos filtros.")));
  return cont;
};

// ------------------------------------------------------------------ panel de detalle

function ocultarPanel() {
  $("#panel").classList.remove("abierto");
  $("#panelFondo").classList.remove("abierto");
  $("#panel").setAttribute("aria-hidden", "true");
}
async function abrirPanel(ver) {
  const panel = $("#panel");
  panel.classList.add("abierto");
  $("#panelFondo").classList.add("abierto");
  panel.setAttribute("aria-hidden", "false");
  panel.replaceChildren(el("div", { class: "vacio" }, "Cargando…"));
  const [tipo, ...resto] = ver.split(":");
  let nodo;
  try {
    if (tipo === "v") nodo = await panelVotacion(+resto[0]);
    else if (tipo === "i") nodo = await panelIniciativa(resto[0], resto.slice(1).join(":"));
    else if (tipo === "d") nodo = await panelDiputado(+resto[0]);
    else if (tipo === "ayuda") nodo = panelAyuda(resto[0]);
  } catch (e) {
    nodo = el("div", { class: "vacio" }, "Error: " + e.message);
  }
  panel.replaceChildren(el("button", { class: "cerrar", onclick: cerrarPanel }, "Cerrar ✕"), nodo);
  envolverTablas(panel);
  panel.scrollTop = 0;
}

function bloqueFicha(f) {
  if (!f) return el("p", { class: "muted small" }, "Esta iniciativa aún no tiene ficha.");
  if ((f.modelo || "").startsWith("reglas")) {
    return el("div", { class: "ficha" },
      el("div", { class: "badges" }, el("span", { class: "badge ia" }, temaNombre(f.tema_principal)),
        (f.temas_secundarios || []).map((t) => el("span", { class: "badge ia" }, temaNombre(t)))),
      el("p", { class: "procedencia" }, `Tema provisional según la ${f.fuente_texto.replace("comisión competente: ", "")}. Coincide en torno al 90% con el tema definitivo; el resumen y las etiquetas llegarán con la ficha completa.`));
  }
  return el("div", { class: "ficha" },
    el("p", {}, f.resumen),
    (f.marcas || []).includes("debate general") ? el("p", { class: "procedencia" }, "Debate de política general: los grupos presentan propuestas de resolución sobre asuntos muy distintos, así que sus votaciones no cuentan en ningún tema. En el Congreso, cada propuesta se atribuye al grupo que la presenta.") : null,
    el("div", { class: "badges" },
      f.tema_principal ? el("span", { class: "badge ia" }, temaNombre(f.tema_principal)) : null,
      (f.temas_secundarios || []).map((t) => el("span", { class: "badge ia" }, temaNombre(t))),
      (f.marcas || []).map((m) => el("span", { class: "badge ia" }, m)),
      f.ambito && f.ambito !== "estatal" ? el("span", { class: "badge ia" }, f.ambito) : null,
      (f.etiquetas || []).map((e) => el("a", { class: "badge ia", href: `#/iniciativas?etiqueta=${encodeURIComponent(e)}` }, "#" + e))),
    f.bloques && f.bloques.length ? el("ul", { class: "small" }, f.bloques.map((b) => el("li", {}, b.descripcion, b.ley_afectada ? el("span", { class: "muted" }, ` (${b.ley_afectada})`) : null, " · ", temaNombre(b.tema)))) : null,
    f.leyes_afectadas && f.leyes_afectadas.length ? el("p", { class: "small" }, el("strong", {}, "Leyes afectadas: "), f.leyes_afectadas.join("; ")) : null);
}

// ---- enlaces a la información original ----
const enlace = (href, texto) => el("a", { href, target: "_blank", rel: "noopener" }, texto);
const FUENTES = { xml: "datos abiertos en XML", json: "datos abiertos en JSON", csv: "datos abiertos en CSV", html: "página de la fuente",
  "html-reglas": "página de la fuente", "pdf-reglas": "PDF de la fuente", "json-reglas": "texto del diario de sesiones", "pdf-llm": "leída del PDF de la fuente", "html-llm": "leída de la página de la fuente" };
const fechaDMA = (iso) => iso.split("-").reverse().join("/");

function enlacesVotacion(v) {
  const info = infoLeg(v.legislatura);
  const enlaces = [];
  if (info.cuerpo === "congreso") {
    enlaces.push(enlace(`https://www.congreso.es/es/opendata/votaciones?p_p_id=votaciones&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&targetLegislatura=${romano(v.legislatura)}&targetDate=${fechaDMA(v.fecha)}`, "Votaciones de ese día en el Congreso ↗"));
    if (v.url) enlaces.push(enlace(v.url, "datos de esta votación (JSON) ↗"));
  } else if (v.url) {
    enlaces.push(enlace(v.url, "Ver la votación en la fuente ↗"));
    if (FUENTES[v.fuente]) enlaces.push(el("span", { class: "muted" }, FUENTES[v.fuente]));
  }
  return enlaces.length ? el("p", { class: "small" }, enlaces.map((e, k) => [k ? " · " : "", e])) : null;
}

function enlaceIniciativa(i) {
  if (!i || i.sintetica) return null;
  if (i.url) return enlace(i.url, "Ficha de la iniciativa en la fuente ↗");
  if (infoLeg(i.legislatura).cuerpo === "congreso" && /^\d{3}\//.test(i.expediente)) {
    return enlace(`https://www.congreso.es/es/busqueda-de-iniciativas?p_p_id=iniciativas&p_p_lifecycle=0&p_p_state=normal&p_p_mode=view&_iniciativas_mode=mostrarDetalle&_iniciativas_legislatura=${romano(i.legislatura)}&_iniciativas_id=${encodeURIComponent(i.expediente)}`, "Ficha de la iniciativa en el Congreso ↗");
  }
  return null;
}

function bloqueIniciativa(i) {
  if (!i) return null;
  const ficha = enlaceIniciativa(i);
  return el("div", { class: "small" },
    el("div", {}, el("strong", {}, i.sintetica ? "Sin expediente identificado" : `Expediente ${i.expediente}`), i.tipo ? ` · ${i.tipo}` : ""),
    ficha ? el("div", {}, ficha) : null,
    i.autor ? el("div", {}, "Autor: ", i.autor) : null,
    i.fecha_presentacion && !i.sintetica ? el("div", {}, "Presentada: ", fecha(i.fecha_presentacion)) : null,
    i.comision ? el("div", {}, "Comisión: ", i.comision) : null,
    i.resultado_tramitacion ? el("div", {}, "Resultado oficial de tramitación: ", i.resultado_tramitacion) : null,
    i.resultado_final ? el("div", { class: "badges" }, badgeResultado(i.resultado_final)) : null,
    i.bocg.length ? el("div", {}, "BOCG: ", i.bocg.slice(0, 6).map((u, k) => [k ? ", " : "", el("a", { href: u, target: "_blank", rel: "noopener" }, u.split("/").pop().split("#")[0])])) : null,
    i.boe.length ? el("div", {}, "BOE: ", i.boe.map((u, k) => [k ? ", " : "", el("a", { href: u, target: "_blank", rel: "noopener" }, u.split("=").pop())])) : null);
}

async function panelVotacion(id) {
  const d = await api("votacion", { id });
  const v = d.votacion;
  const leg = v.legislatura;
  const decis = new Map(d.decisivos.map((x) => [x.grupo, x.modo]));
  const sub = [v.titulo_subgrupo, v.texto_subgrupo].filter(Boolean).join(" — ");
  let explica;
  const res = v.resultado === "aprobada" ? "Aprobada" : v.resultado === "rechazada" ? "Rechazada" : "Resultado no publicado";
  if (v.asentimiento) explica = "Aprobada por asentimiento o unanimidad, sin recuento.";
  else if (v.a_favor === null) explica = `${res}. La fuente no publica el recuento de votos.`;
  else if (v.mayoria === "absoluta") explica = `${res}: necesitaba mayoría absoluta (${mayoriaAbs(leg)} síes) y obtuvo ${v.a_favor}.`;
  else explica = `${res}: ${v.a_favor} a favor frente a ${v.en_contra ?? 0} en contra (mayoría simple)${v.a_favor === (v.en_contra ?? 0) ? (v.resultado === "aprobada" ? "; el empate lo deshace el voto de calidad" : "; el empate se entiende rechazado") : ""}.`;
  const info = infoLeg(leg);
  const territorial = info.cuerpo && info.cuerpo !== "congreso";
  const leidaDeActa = /llm/.test(v.fuente || "");
  const gob = gobiernoEn(info.cuerpo, v.fecha);

  const cont = el("div", {},
    el("div", { class: "muted small" }, [fecha(v.fecha), territorial ? info.cuerpo_nombre : null, `Leg. ${romano(leg)}`,
      // La numeración de sesión y votación solo es la oficial en el Congreso.
      !territorial && v.sesion ? `Sesión ${v.sesion}, votación ${v.numero}` : null, v.seccion].filter(Boolean).join(" · ")),
    el("h2", {}, d.iniciativa && !d.iniciativa.sintetica ? d.iniciativa.titulo : (v.texto_expediente || "").split("\n")[0]),
    sub ? el("p", { class: "sub" }, sub) : null,
    (v.texto_expediente || "").includes("\n") ? el("p", { class: "small muted" }, v.texto_expediente.split("\n").slice(1).join(" ").trim()) : null,
    el("div", { class: "badges" }, badgeResultado(v.resultado), el("span", { class: "badge" }, META.tipos_votacion[v.tipo_votacion]), v.decisiva ? el("span", { class: "badge" }, "votación decisiva de la iniciativa") : null,
      v.derrota ? el("span", { class: "badge" }, "derrota del Gobierno") : null),
    el("section", {}, barraVotos(v), el("p", { class: "small" }, explica, v.a_favor === null ? "" : ` Presentes: ${v.presentes ?? "—"}; no votan: ${v.no_votan ?? "—"}.`),
      gob ? el("p", { class: "small" }, `Gobierno de ${gob.presidente} (${partidosGobierno(gob)}).`,
        v.derrota ? ` Derrota del Gobierno: el ${gob.partido} votó ${v.resultado === "rechazada" ? "a favor y se rechazó" : "en contra y se aprobó"}.` : "") : null,
      v.aviso ? el("p", { class: "small", style: "color:var(--bad-text)" }, "⚠ ", v.aviso) : null,
      leidaDeActa ? el("p", { class: "procedencia" }, "Votación leída del diario de sesiones o del acta: el asunto, los totales y el voto de cada grupo salen del texto; conviene contrastarlos con el documento original.") : null,
      enlacesVotacion(v)),
    el("section", {}, el("h3", {}, "Qué es"), bloqueFicha(d.ficha), el("div", { style: "margin-top:10px" }, bloqueIniciativa(d.iniciativa)),
      d.iniciativa ? el("p", { class: "small" }, el("a", { href: "#", onclick: (e) => { e.preventDefault(); abrir(`i:${leg}:${d.iniciativa.expediente}`); } }, "Ver la iniciativa y todas sus votaciones →")) : null,
      d.iniciativa ? lineaProgramas(leg, d.iniciativa.expediente) : null));

  // Por grupos.
  const filas = d.grupos.filter((g) => g.grupo !== "?").map((g) => {
    const info = grupo(leg, g.grupo);
    const modo = decis.get(g.grupo);
    // Hay fuentes que solo dicen qué votó cada grupo, sin recuento: entonces no se ponen ceros.
    const cuenta = (n) => (g.si + g.no + g.abstencion + g.no_vota ? n : "—");
    return el("tr", {},
      el("td", {}, el("span", { style: `display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;background:${info.color}` }), el("strong", {}, info.siglas), info.nombre !== info.siglas ? el("span", { class: "muted" }, " " + info.nombre) : null),
      el("td", { class: "num" }, cuenta(g.si)), el("td", { class: "num" }, cuenta(g.abstencion)), el("td", { class: "num" }, cuenta(g.no)), el("td", { class: "num" }, cuenta(g.no_vota)),
      el("td", {}, (SENTIDO[g.sentido] || ["", "—"])[1]),
      el("td", { class: "small" }, modo ? (modo === "absteniendose" ? "Decisivo: bastaba con abstenerse" : "Decisivo: cambiando su voto") : ""));
  });
  if (filas.length) cont.append(el("section", {}, el("h3", {}, "Por grupos"),
    el("table", { class: "tabla" }, el("thead", {}, el("tr", {}, el("th", {}, "Grupo"), el("th", { class: "num" }, "Sí"), el("th", { class: "num" }, "Abst."), el("th", { class: "num" }, "No"), el("th", { class: "num" }, "No vota"), el("th", {}, "Voto del grupo"), el("th", {}, ""))), el("tbody", {}, filas))));

  // Nominal.
  if (d.votos.length) {
    const porGrupo = {};
    for (const x of d.votos) (porGrupo[x.grupo] = porGrupo[x.grupo] || []).push(x);
    const disid = d.votos.filter((x) => x.disidente);
    cont.append(el("section", {}, el("h3", {}, "Voto nominal"),
      disid.length ? el("p", { class: "small" }, el("strong", {}, disid.length > 1 ? `${disid.length} ${miembros(leg)} votaron distinto a su grupo: ` : `1 ${miembros(leg, true)} votó distinto a su grupo: `), disid.map((x) => `${x.nombre} (${grupo(leg, x.grupo).siglas})`).join("; ")) : null,
      el("div", { class: "nominal" }, Object.entries(porGrupo).map(([g, xs]) => el("div", { class: "g" },
        el("h4", {}, el("span", { style: `display:inline-block;width:10px;height:10px;border-radius:2px;background:${grupo(leg, g).color}` }), grupo(leg, g).siglas),
        xs.map((x) => el("div", { class: "d" + (x.disidente ? " dis" : "") },
          el("a", { href: "#", onclick: (e) => { e.preventDefault(); abrir(`d:${x.id}`); } }, x.nombre),
          el("span", { class: `v ${x.sentido}` }, (SENTIDO[x.sentido] || ["", x.sentido])[1]))))))));
  }

  if (d.otras.length > 1) cont.append(el("section", {}, el("h3", {}, `Todas las votaciones de este asunto (${d.otras.length})`), tablaOtras(d.otras, id)));
  return cont;
}

function tablaOtras(otras, actual) {
  return el("table", { class: "tabla" }, el("tbody", {}, otras.map((o) => el("tr", { class: "clic", style: o.id === actual ? "font-weight:600" : "", onclick: () => abrir(`v:${o.id}`) },
    el("td", { class: "small" }, fecha(o.fecha)),
    el("td", {}, META.tipos_votacion[o.tipo_votacion], o.decisiva ? " ★" : "", el("div", { class: "small muted" }, [o.titulo_subgrupo, o.texto_subgrupo].filter(Boolean).join(" — ").slice(0, 140))),
    el("td", { class: "small" }, o.asentimiento ? "asentimiento" : `${o.a_favor}–${o.en_contra}–${o.abstenciones}`),
    el("td", {}, badgeResultado(o.resultado))))));
}

async function panelIniciativa(leg, exp) {
  const d = await api("iniciativa", { leg, exp });
  const i = d.iniciativa;
  const programas = await bloqueProgramas(leg, exp);
  // Las que aún no se han votado solo están en en_tramite: se abren desde «Qué viene» si están en algún programa.
  if (!i) {
    const t = q1("SELECT * FROM en_tramite WHERE legislatura=? AND expediente=?", [+leg, exp]);
    if (!t) return el("div", { class: "vacio" }, "Esta iniciativa no está en los datos cargados.");
    const ficha = enlaceIniciativa({ legislatura: +leg, expediente: exp });
    return el("div", {},
      el("div", { class: "muted small" }, [`Leg. ${romano(leg)}`, t.tipo].filter(Boolean).join(" · ")),
      el("h2", {}, t.titulo),
      el("section", {}, bloqueFicha(d.ficha)),
      el("section", { class: "small" }, el("div", {}, el("strong", {}, `Expediente ${exp}`)), ficha ? el("div", {}, ficha) : null,
        t.autor ? el("div", {}, "Autor: ", t.autor) : null,
        t.fecha_presentacion ? el("div", {}, "Presentada: ", fecha(t.fecha_presentacion)) : null,
        t.fase ? el("div", {}, "Fase: ", t.fase, t.organo ? el("span", { class: "muted" }, ` (${t.organo})`) : null) : null,
        el("div", { class: "muted" }, "Todavía no se ha votado en el Pleno.")),
      programas);
  }
  return el("div", {},
    el("div", { class: "muted small" }, [infoLeg(leg).cuerpo !== "congreso" ? infoLeg(leg).cuerpo_nombre : null, `Leg. ${romano(leg)}`, i.tipo].filter(Boolean).join(" · ")),
    el("h2", {}, i.titulo),
    el("section", {}, bloqueFicha(d.ficha)),
    el("section", {}, bloqueIniciativa(i)),
    programas,
    el("section", {}, el("h3", {}, `Votaciones (${d.votaciones.length})`), el("p", { class: "small muted" }, "★ votación decisiva"),
      el("div", { class: "lista" }, d.votaciones.map(filaVotacion))));
}

async function panelDiputado(id) {
  const d = await api("diputado", { id });
  return el("div", {},
    el("h2", {}, d.diputado.nombre),
    el("section", {}, el("h3", {}, "Grupos en los que ha votado"),
      el("table", { class: "tabla" }, el("thead", {}, el("tr", {}, el("th", {}, "Leg."), el("th", {}, "Grupo"), el("th", {}, "Desde"), el("th", {}, "Hasta"), el("th", { class: "num" }, "Votaciones"), el("th", { class: "num" }, "No vota"))),
        el("tbody", {}, d.grupos.map((g) => el("tr", {}, el("td", {}, legTexto(g.legislatura)), el("td", {}, grupo(g.legislatura, g.grupo).siglas),
          el("td", {}, fecha(g.desde)), el("td", {}, fecha(g.hasta)), el("td", { class: "num" }, fmt(g.n)), el("td", { class: "num" }, `${pct(g.ausencias, g.n)}%`)))))),
    el("section", {}, el("h3", {}, `Votos distintos a su grupo (${d.disidencias.length}${d.disidencias.length === 100 ? "+" : ""})`),
      d.disidencias.length ? el("table", { class: "tabla" }, el("tbody", {}, d.disidencias.map((x) => el("tr", { class: "clic", onclick: () => abrir(`v:${x.id}`) },
        el("td", { class: "small" }, fecha(x.fecha)), el("td", {}, textoCorto(x.texto_expediente, 120), el("div", { class: "small muted" }, META.tipos_votacion[x.tipo_votacion])),
        el("td", { class: "small" }, `Votó ${SENTIDO[x.sentido][1]}; su grupo, ${SENTIDO[x.sentido_grupo][1]}`))))) : el("p", { class: "muted" }, "Siempre votó con su grupo.")));
}

