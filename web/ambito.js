"use strict";

// ------------------------------------------------------------------ ámbito territorial
// Qué instituciones se analizan: el Congreso, parlamentos autonómicos, instituciones provinciales o
// insulares y ayuntamientos. Se eligen en un árbol (España > Nacional y Comunidades autónomas >
// cada comunidad > su parlamento, lo provincial o insular y los ayuntamientos): marcar un nodo
// marca todo lo que tiene debajo, así que una comunidad incluye todas sus instituciones. Los atajos
// de nivel eligen, por ejemplo, todos los parlamentos autonómicos sin nada de lo que hay debajo.
//
// La elección va en la URL (amb=congreso,AS…) con los nodos completos compactados (es = todo,
// *autonomico = todos los parlamentos autonómicos…) y se recuerda en el navegador. Solo se cargan
// los datos de las instituciones elegidas (montarBD en app.js). Este fichero solo define funciones:
// usa las utilidades de app.js cuando se llama, no al cargarse.

const AMBITO_DEFECTO = "nacional";
const CLAVE_AMBITO = "escrutinio.ambito";
// A partir de este tamaño de datos (comprimidos) el selector avisa de que la carga puede ir lenta.
const AMBITO_PESADO_BYTES = 8e6;
const NIVELES_AMBITO = { nacional: "Nacional", autonomico: "Parlamentos autonómicos", provincial: "Provincial e insular", municipal: "Ayuntamientos" };
// Filtros de la URL que dependen de las instituciones cargadas: al cambiar de ámbito se quitan.
const FILTROS_DE_AMBITO = ["leg", "autor", "g", "grupo", "pagina", "ver"];
let AMBITO = { clave: "", cuerpos: new Set() };

const hijosAmbito = (codigo) => CATALOGO.ambitos.filter((a) => a.padre === codigo);
const nodoAmbito = (codigo) => CATALOGO.ambitos.find((a) => a.codigo === codigo);

// Instituciones (códigos de cuerpo) que hay debajo de un nodo, o de un nivel («*autonomico»).
function hojasAmbito(codigo) {
  if (codigo.startsWith("*")) return Object.values(CATALOGO.cuerpos).filter((c) => c.nivel === codigo.slice(1)).map((c) => c.codigo);
  const n = nodoAmbito(codigo);
  if (!n) return [];
  if (n.cuerpo) return [n.cuerpo];
  return hijosAmbito(codigo).flatMap((h) => hojasAmbito(h.codigo));
}

const resolverAmbito = (clave) => new Set(lista(clave).flatMap(hojasAmbito).filter((c) => CATALOGO.cuerpos[c]));

// La forma más corta de escribir una selección: nodos completos del árbol o niveles completos.
function compactarAmbito(cuerpos) {
  const arbol = [];
  const visitar = (codigo) => {
    const hs = hojasAmbito(codigo);
    if (!hs.some((c) => cuerpos.has(c))) return;
    if (hs.every((c) => cuerpos.has(c))) { arbol.push(codigo); return; }
    for (const h of hijosAmbito(codigo)) visitar(h.codigo);
  };
  visitar("es");
  const niveles = Object.keys(NIVELES_AMBITO).filter((n) => {
    const hs = hojasAmbito("*" + n);
    return hs.length && hs.every((c) => cuerpos.has(c));
  });
  const deNiveles = new Set(niveles.flatMap((n) => hojasAmbito("*" + n)));
  if (niveles.length && deNiveles.size === cuerpos.size && niveles.length < arbol.length) return niveles.map((n) => "*" + n).join(",");
  return arbol.join(",");
}

function nombreNodo(codigo) {
  if (codigo.startsWith("*")) return NIVELES_AMBITO[codigo.slice(1)] || codigo;
  const n = nodoAmbito(codigo);
  if (!n) return codigo;
  if (n.cuerpo) return (CATALOGO.cuerpos[n.cuerpo] || {}).corto || n.nombre;
  // «Ayuntamientos» a secas no dice de dónde: se añade la comunidad.
  const padre = nodoAmbito(n.padre);
  return n.nivel && padre && padre.codigo !== "es" && padre.codigo !== "ccaa" ? `${n.nombre} (${padre.nombre})` : n.nombre;
}

function nombreAmbito(clave = AMBITO.clave) {
  const partes = lista(clave);
  if (partes.length <= 2) return partes.map(nombreNodo).join(" + ");
  return `${resolverAmbito(clave).size} instituciones`;
}

// ------------------------------------------------------------------ cambiar de ámbito

// El de la URL (un enlace compartido); si no, lo nacional, que es lo más ligero. El último ámbito que
// eligió esta persona no se carga solo al abrir: se ofrece en el selector, porque puede pesar mucho.
function ambitoInicial() {
  const { amb } = leerRuta();
  for (const [clave, elegido] of [[amb, true], [AMBITO_DEFECTO, false], ["congreso", false], ["es", false]]) {
    if (clave && resolverAmbito(clave).size) return { clave, elegido };
  }
  return { clave: "es", elegido: false };
}

function ambitoGuardado() {
  try {
    const clave = localStorage.getItem(CLAVE_AMBITO);
    return clave && resolverAmbito(clave).size ? clave : null;
  } catch { return null; } // sin almacenamiento
}

// Rehace la base en memoria con las instituciones de `clave` y recalcula META. Solo se recuerda en el
// navegador lo que se elige (selector o enlace), no el valor por defecto.
async function cambiarAmbito(clave, avisar = () => {}, recordar = true) {
  const cuerpos = resolverAmbito(clave);
  if (!cuerpos.size) return false;
  AMBITO = { clave: compactarAmbito(cuerpos), cuerpos };
  if (recordar) try { localStorage.setItem(CLAVE_AMBITO, AMBITO.clave); } catch { /* sin almacenamiento */ }
  await montarBD(cuerpos, avisar);
  META = await api("meta");
  pintarBotonAmbito();
  return true;
}

// Si la URL pide otro ámbito (enlace compartido, atrás/adelante del navegador), se carga.
async function aplicarAmbitoDeRuta() {
  const { amb } = leerRuta();
  if (!amb || amb === AMBITO.clave || !resolverAmbito(amb).size) return;
  const vista = $("#vista");
  await cambiarAmbito(amb, (texto) => vista.replaceChildren(el("div", { class: "vacio" }, texto)));
}

function irAmbito(clave) {
  const { tab, q } = leerRuta();
  for (const k of FILTROS_DE_AMBITO) delete q[k];
  const qs = new URLSearchParams(Object.entries({ ...q, amb: clave }).filter(([, v]) => v !== "" && v != null)).toString().replace(/%2C/g, ",");
  location.hash = `#/${tab}?${qs}`;
}

function pintarBotonAmbito() {
  const b = $("#botonAmbito");
  if (!b) return;
  const nombre = nombreAmbito();
  b.replaceChildren(
    el("span", { class: "amb-ic", "aria-hidden": "true", html: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/></svg>' }),
    el("span", { class: "amb-texto" }, nombre), el("span", { class: "amb-flecha", "aria-hidden": "true" }, "▾"));
  b.title = `Ámbito: ${nombre}. Cambiar las instituciones que se analizan`;
  const sub = $("header.top h1 span");
  if (sub) sub.textContent = ` · ${META && META.soloCongreso ? "votaciones del Congreso" : "votaciones parlamentarias"}`;
  document.title = `Escrutinio · ${nombre}`;
}

// ------------------------------------------------------------------ selector

// Lo que hay de una o varias instituciones (del catálogo: no hace falta tenerlas cargadas).
function resumenCuerpos(cuerpos) {
  const set = new Set(cuerpos);
  const legs = CATALOGO.legs.filter((l) => set.has(l.cuerpo));
  const bytes = CATALOGO.ficheros.filter((f) => set.has(f.cuerpo)).reduce((a, f) => a + f.bytes, 0);
  const suma = (k) => legs.reduce((a, l) => a + (l[k] || 0), 0);
  const desde = legs.map((l) => l.desde).filter(Boolean).sort()[0];
  const hasta = legs.map((l) => l.hasta).filter(Boolean).sort().at(-1);
  return { votaciones: suma("votaciones"), nominal: suma("nominal"), grupo: suma("por_grupo"), totales: suma("totales"), bytes, desde, hasta, legs: legs.length };
}

function detalleCuerpo(r) {
  const detalle = r.nominal ? "voto nominal" : r.grupo ? "voto por grupo" : r.totales ? "solo totales" : "solo resultado";
  const años = r.desde ? `${r.desde.slice(0, 4)}–${r.hasta.slice(0, 4)}` : "";
  return [`${fmt(r.votaciones)} votaciones`, años, detalle].filter(Boolean).join(" · ");
}

const mb = (bytes) => `${(bytes / 1e6).toLocaleString("es-ES", { maximumFractionDigits: bytes < 1e6 ? 2 : 1 })} MB`;

// ------------------------------------------------------------------ fuentes sin actualizar
// Instituciones cuya web no respondió en la última actualización (CATALOGO.avisos, de indice.js).
// Los textos son los de escrutinio/territorial/estado.py.
const MOTIVOS_AVISO = {
  sin_respuesta: "su web no ha respondido",
  rechaza: "su web ha rechazado la conexión",
  certificado: "su web tiene un certificado de seguridad incompleto",
  copia: "su web no ha respondido y se ha usado la copia del Internet Archive, que puede ir con retraso",
  error: "ha fallado la descarga (puede ser pasajero o un cambio en su web)",
};
const AVISO_EXTRANJERO = "Varias webs de instituciones no aceptan conexiones desde fuera de España, y la actualización diaria se hace en servidores de GitHub que están fuera.";

function avisosFuentes(cuerpos) {
  const avisos = CATALOGO.avisos || {};
  return [...cuerpos].filter((c) => avisos[c]).sort((a, b) => ordenCuerpo(a) - ordenCuerpo(b)).map((c) => [c, avisos[c]]);
}

function textoAviso(a) {
  return `${MOTIVOS_AVISO[a.motivo] || MOTIVOS_AVISO.error}${a.hasta ? `; tiene datos hasta el ${fecha(a.hasta)}` : ""}`;
}

// Marca ⚠ junto al nombre de una institución sin actualizar (con la explicación al pasar el ratón).
function marcaAviso(codigo) {
  const a = (CATALOGO.avisos || {})[codigo];
  return a ? el("span", { class: "aviso-marca", title: `Sin actualizar: ${textoAviso(a)}`, "aria-label": "Sin actualizar" }, "⚠") : null;
}

// Recuadro con las instituciones de `cuerpos` que se han quedado sin actualizar (null si ninguna).
function avisoFuentes(cuerpos) {
  const lista = avisosFuentes(cuerpos);
  if (!lista.length) return null;
  const extranjero = lista.some(([, a]) => ["sin_respuesta", "rechaza", "copia"].includes(a.motivo));
  return el("div", { class: "aviso-fuentes", role: "note" },
    el("p", {},
      el("strong", {}, lista.length === 1 ? "⚠ Una institución no se ha podido actualizar" : `⚠ ${lista.length} instituciones no se han podido actualizar`),
      ` en la última actualización (${fecha(lista[0][1].fecha)}), así que sus datos pueden ir con retraso. `,
      extranjero ? `${AVISO_EXTRANJERO} Se pondrán al día cuando su web vuelva a responder.` : ""),
    el("ul", {}, lista.map(([c, a]) => el("li", {}, el("strong", {}, (CATALOGO.cuerpos[c] || { nombre: c }).nombre), `: ${textoAviso(a)}.`))));
}

function abrirSelectorAmbito() {
  const panel = $("#panelAmbito"), fondo = $("#ambitoFondo");
  const sel = new Set(AMBITO.cuerpos);
  const abiertos = new Set(["es", "ccaa", "nacional"]);
  for (const a of CATALOGO.ambitos) if (!a.cuerpo && hojasAmbito(a.codigo).some((c) => sel.has(c))) abiertos.add(a.codigo);
  const cerrar = () => {
    panel.classList.remove("abierto");
    fondo.classList.remove("abierto");
    panel.setAttribute("aria-hidden", "true");
    document.removeEventListener("keydown", teclas);
    $("#botonAmbito").focus();
  };
  const teclas = (e) => { if (e.key === "Escape") cerrar(); };

  function fila(a, nivel) {
    const hojas = hojasAmbito(a.codigo);
    const n = hojas.filter((c) => sel.has(c)).length;
    const cb = el("input", { type: "checkbox", onchange: () => { for (const c of hojas) cb.checked ? sel.add(c) : sel.delete(c); pintar(); } });
    cb.checked = n > 0 && n === hojas.length;
    cb.indeterminate = n > 0 && n < hojas.length;
    const hijos = hijosAmbito(a.codigo);
    const r = resumenCuerpos(hojas);
    const info = a.cuerpo ? detalleCuerpo(r) : `${hojas.length} ${hojas.length === 1 ? "institución" : "instituciones"} · ${fmt(r.votaciones)} votaciones`;
    const abierto = abiertos.has(a.codigo);
    const cabeza = el("div", { class: "amb-fila" + (a.cuerpo ? " hoja" : ""), style: `--nivel:${nivel}` },
      hijos.length ? el("button", { type: "button", class: "amb-abrir", "aria-expanded": String(abierto), "aria-label": `${abierto ? "Plegar" : "Desplegar"} ${a.nombre}`,
        onclick: () => { abierto ? abiertos.delete(a.codigo) : abiertos.add(a.codigo); pintar(); } }, abierto ? "▾" : "▸") : el("span", { class: "amb-abrir" }),
      el("label", {}, cb, el("span", { class: "amb-nombre" }, a.nombre, a.cuerpo ? marcaAviso(a.cuerpo) : null), el("span", { class: "amb-info" }, info)));
    if (!hijos.length || !abierto) return cabeza;
    return el("div", { role: "group" }, cabeza, hijos.map((h) => fila(h, nivel + 1)));
  }

  function pintar() {
    const r = resumenCuerpos([...sel]);
    const todas = hojasAmbito("es");
    const atajos = [["Todo", todas], ...Object.entries(NIVELES_AMBITO).map(([k, t]) => [t, hojasAmbito("*" + k)]).filter(([, hs]) => hs.length)];
    const guardado = ambitoGuardado();
    if (guardado && guardado !== AMBITO.clave) atajos.push([`Tu última elección: ${nombreAmbito(guardado)}`, [...resolverAmbito(guardado)]]);
    const igual = (hs) => hs.length === sel.size && hs.every((c) => sel.has(c));
    const raiz = nodoAmbito("es");
    // Lo que falta por descargar pesa en la primera carga; montar la base depende de todo lo elegido.
    const pesado = sel.size && r.bytes > AMBITO_PESADO_BYTES;
    const sinActualizar = avisosFuentes(sel).length;
    panel.replaceChildren(
      el("div", { class: "amb-cabeza" },
        el("h2", {}, "Qué instituciones analizar"),
        el("button", { type: "button", class: "boton", onclick: cerrar, "aria-label": "Cerrar" }, "✕")),
      el("p", { class: "small muted" }, "Marca una comunidad para incluir su parlamento y todo lo que hay por debajo (instituciones provinciales o insulares y ayuntamientos), o solo las instituciones que quieras. Con los atajos eliges un nivel entero, por ejemplo todos los parlamentos autonómicos sin los ayuntamientos."),
      el("div", { class: "amb-atajos", role: "group", "aria-label": "Atajos por nivel" }, atajos.map(([t, hs]) =>
        el("button", { type: "button", class: "chip" + (igual(hs) ? " activo" : ""), "aria-pressed": String(igual(hs)),
          onclick: () => { sel.clear(); for (const c of hs) sel.add(c); pintar(); } }, t))),
      el("div", { class: "amb-arbol" }, raiz ? hijosAmbito("es").map((h) => fila(h, 0)) : null),
      el("div", { class: "amb-pie" },
        el("div", { class: "small" },
          sel.size ? `${sel.size} ${sel.size === 1 ? "institución" : "instituciones"} · ${fmt(r.votaciones)} votaciones · ${mb(r.bytes)} de datos` : "Elige al menos una institución",
          pesado ? el("div", { class: "amb-aviso", role: "status" }, "Es mucha información: la carga puede tardar un rato (sobre todo la primera vez, mientras se descarga) y el navegador usará bastante memoria. En el móvil puede ir lenta.") : null,
          sinActualizar ? el("div", { class: "amb-aviso" }, `⚠ ${sinActualizar === 1 ? "Una de las elegidas no se ha podido actualizar" : `${sinActualizar} de las elegidas no se han podido actualizar`} en la última actualización: van marcadas con ⚠ y la portada explica por qué.`) : null),
        el("div", { class: "amb-botones" },
          el("button", { type: "button", class: "boton", onclick: cerrar }, "Cancelar"),
          el("button", { type: "button", class: "boton primario", disabled: !sel.size, onclick: () => {
            const clave = compactarAmbito(sel);
            cerrar();
            if (clave !== AMBITO.clave) irAmbito(clave);
          } }, "Aplicar"))));
  }

  pintar();
  panel.classList.add("abierto");
  fondo.classList.add("abierto");
  panel.setAttribute("aria-hidden", "false");
  fondo.onclick = cerrar;
  document.addEventListener("keydown", teclas);
  const primero = panel.querySelector("input[type=checkbox]");
  if (primero) primero.focus();
}
