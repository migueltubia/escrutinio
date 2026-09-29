"use strict";
// Vistas de análisis (coaliciones, mapa ideológico, disciplina, enmiendas) y de activismo
// (mis causas con scorecard y CSV, qué viene). Usa las utilidades y la base de datos de app.js.

// ------------------------------------------------------------------ utilidades comunes

function subnav(items, actual, q = {}) {
  return el("nav", { class: "subnav" }, items.map(([ruta, texto]) => el("a", {
    class: ruta === actual ? "activo" : "", href: `#/${ruta}${q.leg ? "?leg=" + q.leg : ""}`,
  }, texto)));
}
const NAV_ANALISIS = [["coaliciones", "Coaliciones ganadoras"], ["mapa", "Mapa ideológico y polarización"], ["disciplina", "Disciplina y ausencias"], ["enmiendas", "Enmiendas"]];
const NAV_ACTIVISMO = [["causas", "Mis causas"], ["viene", "Qué viene"]];

const siglas = (leg, codigo) => grupo(leg, codigo).siglas;
const hoyISO = () => new Date().toISOString().slice(0, 10);
const legPorDefecto = () => String(legsActuales()[0]);

function descargarCSV(nombre, cabecera, filas) {
  const celda = (v) => {
    const t = v === null || v === undefined ? "" : String(v);
    return /[";\n\r]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const texto = "﻿" + [cabecera, ...filas].map((f) => f.map(celda).join(";")).join("\r\n");
  const url = URL.createObjectURL(new Blob([texto], { type: "text/csv;charset=utf-8" }));
  const a = el("a", { href: url, download: nombre });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

// Posición de cada grupo (siglas) en una lista de votaciones, con el apoyo ya invertido en totalidades.
function celdasDe(ids) {
  const celdas = {};
  for (let i = 0; i < ids.length; i += 500) {
    const trozo = ids.slice(i, i + 500);
    for (const c of q(`SELECT g.votacion_id, gr.siglas, g.sentido, g.si, g.no, g.abstencion, g.no_vota, v.tipo_votacion,
          ${SQL_APOYO} AS apoyo
        FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id
        JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
        WHERE g.votacion_id IN (${trozo.map(() => "?").join(",")}) AND g.grupo<>'?'`, trozo)) {
      (celdas[c.votacion_id] = celdas[c.votacion_id] || {})[c.siglas] = c;
    }
  }
  return celdas;
}

// Tope de filas del CSV de votaciones (las más recientes): más haría esperar demasiado al navegador.
const MAX_FILAS_CSV = 30000;

function exportarVotacionesCSV(filtros) {
  const d = API.votaciones({ ...filtros, pagina: "1", tam: "200" });
  const todas = [];
  for (let p = 1; p <= Math.ceil(Math.min(d.total, MAX_FILAS_CSV) / 200); p++) todas.push(...API.votaciones({ ...filtros, pagina: String(p), tam: "200" }).votaciones);
  const celdas = celdasDe(todas.map((v) => v.id));
  const cols = todasSiglas().filter((s) => todas.some((v) => (celdas[v.id] || {})[s]));
  const texto = { si: "sí", no: "no", abstencion: "abstención", dividido: "dividido" };
  descargarCSV(`votaciones-${hoyISO()}.csv`,
    ["id", "fecha", "institucion", "legislatura", "expediente", "titulo", "detalle", "tipo_votacion", "resultado", "a_favor", "en_contra", "abstenciones",
      "derrota_gobierno", "tema", ...cols.map((s) => `voto_${s}`)],
    todas.map((v) => [v.id, v.fecha, infoLeg(v.legislatura).cuerpo_nombre, romano(v.legislatura), v.sintetica ? "" : v.expediente, tituloVotacion(v),
      [v.titulo_subgrupo, v.texto_subgrupo].filter(Boolean).join(" — "), META.tipos_votacion[v.tipo_votacion], v.resultado,
      v.a_favor, v.en_contra, v.abstenciones, v.derrota ? "sí" : "", v.tema_principal ? temaNombre(v.tema_principal) : "",
      ...cols.map((s) => { const c = (celdas[v.id] || {})[s]; return c ? texto[c.sentido] || "" : ""; })]));
}

// Gráfico de línea de una serie con cruz y tooltip (sin segundo eje).
function lineaTiempo(datos, { alto = 160, ancho = 1000, etiqueta = "", formato = (v) => `${Math.round(v)}%`, max = 100 } = {}) {
  const W = anchoGrafico(ancho), H = alto, ml = 40, mb = 22, mt = 10, mr = 10;
  const ns = "http://www.w3.org/2000/svg";
  const mk = (t, a) => { const n = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) n.setAttribute(k, v); return n; };
  const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": etiqueta });
  const x = (i) => ml + ((W - ml - mr) * i) / Math.max(1, datos.length - 1);
  const y = (v) => mt + (H - mt - mb) * (1 - v / max);
  for (const v of [0, max / 2, max]) {
    svg.appendChild(mk("line", { x1: ml, x2: W - mr, y1: y(v), y2: y(v), class: v === 0 ? "baseline" : "gridline" }));
    const t = mk("text", { x: ml - 6, y: y(v) + 4, "text-anchor": "end" }); t.textContent = formato(v); svg.appendChild(t);
  }
  let ultimaEtiqueta = -Infinity;
  datos.forEach((d, i) => {
    if (d.tick && x(i) - ultimaEtiqueta >= 34) {
      ultimaEtiqueta = x(i);
      const t = mk("text", { x: x(i), y: H - 6, "text-anchor": "middle" }); t.textContent = d.tick; svg.appendChild(t);
    }
    if (d.corte) svg.appendChild(mk("line", { x1: x(i), x2: x(i), y1: mt, y2: H - mb, class: "gridline" }));
  });
  let tramo = "";
  datos.forEach((d, i) => { if (d.y === null) { tramo += " "; return; } tramo += `${tramo.trim() === "" || datos[i - 1]?.y === null ? "M" : "L"}${x(i)},${y(d.y)} `; });
  svg.appendChild(mk("path", { d: tramo, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  const cruz = mk("line", { y1: mt, y2: H - mb, stroke: "var(--axis)", "stroke-width": 1, visibility: "hidden" });
  const punto = mk("circle", { r: 4, fill: "var(--accent)", stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" });
  svg.append(cruz, punto);
  const hit = mk("rect", { x: ml, y: mt, width: W - ml - mr, height: H - mt - mb, class: "hit" });
  const ocultar = () => { cruz.setAttribute("visibility", "hidden"); punto.setAttribute("visibility", "hidden"); tipOff(); };
  alPasar(hit, (e) => {
    const r = svg.getBoundingClientRect();
    const px = ((e.clientX - r.left) / r.width) * W;
    const i = Math.max(0, Math.min(datos.length - 1, Math.round(((px - ml) / (W - ml - mr)) * (datos.length - 1))));
    const d = datos[i];
    if (d.y === null) { tipOff(); return; }
    cruz.setAttribute("x1", x(i)); cruz.setAttribute("x2", x(i)); cruz.setAttribute("visibility", "visible");
    punto.setAttribute("cx", x(i)); punto.setAttribute("cy", y(d.y)); punto.setAttribute("visibility", "visible");
    tip(e, formato(d.y), d.label, d.extra);
  }, ocultar);
  svg.appendChild(hit);
  return el("div", { class: "chart" }, svg);
}

// ------------------------------------------------------------------ coaliciones ganadoras

API.coaliciones = (p) => {
  const [w, a] = filtrosAsunto(p);
  const votaciones = q(`SELECT v.id, v.fecha, v.legislatura, v.resultado, v.tipo_votacion, v.a_favor, v.en_contra, v.abstenciones,
      v.margen, v.texto_expediente, i.titulo, i.sintetica, i.grupo_autor, te.familia, f.tema_principal
    FROM votacion v
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) AND ${w}
    ORDER BY v.fecha DESC`, a);
  return { votaciones, celdas: celdasDe(votaciones.map((v) => v.id)) };
};

function tamanoSiglas() {
  const t = new Map();
  for (const l of META.legislaturas) for (const g of META.grupos[l.id] || []) t.set(g.siglas, Math.max(t.get(g.siglas) || 0, g.diputados));
  return t;
}

VISTAS.coaliciones = async (q) => {
  const d = await api("coaliciones", q);
  const tam = tamanoSiglas();
  const ordenar = (xs) => xs.sort((a, b) => (tam.get(b) || 0) - (tam.get(a) || 0));
  const coal = new Map();
  const presencia = new Map();
  let nSale = 0, nCae = 0;
  for (const v of d.votaciones) {
    const sale = v.tipo_votacion === "totalidad" ? v.resultado === "rechazada" : v.resultado === "aprobada";
    sale ? nSale++ : nCae++;
    const cs = d.celdas[v.id] || {};
    const ganadores = ordenar(Object.keys(cs).filter((s) => cs[s].apoyo === (sale ? "si" : "no")));
    for (const s of Object.keys(cs)) {
      const o = presencia.get(s) || { siglas: s, sale: 0, cae: 0, enSale: 0, enCae: 0 };
      if (sale) { o.sale++; if (ganadores.includes(s)) o.enSale++; } else { o.cae++; if (ganadores.includes(s)) o.enCae++; }
      presencia.set(s, o);
    }
    const clave = (sale ? "S|" : "C|") + ganadores.join(" + ");
    const c = coal.get(clave) || { clave, sale, grupos: ganadores, n: 0, votaciones: [] };
    c.n++;
    c.votaciones.push(v);
    coal.set(clave, c);
  }
  const cont = el("div", {}, subnav(NAV_ANALISIS, "coaliciones", q),
    el("h2", {}, "Coaliciones ganadoras"),
    el("p", { class: "sub" }, "Qué grupos formaron la mayoría en la votación decisiva de cada asunto: los que votaron a favor cuando salió adelante y los que votaron en contra cuando se tumbó. En las enmiendas a la totalidad el voto se invierte (votar sí a la devolución es votar contra el proyecto)."),
    formFiltros([
      multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
      multiSelect("familia", optFamiliasAnalisis(), q.familia, "Todo tipo de asunto", "categorías"),
      multiSelect("tema", optTemas(), q.tema, "Cualquier tema", "temas"),
      el("input", { type: "search", name: "q", value: q.q || "", placeholder: "Texto (vivienda, amnistía…)" }),
    ], q, (f) => irA("coaliciones", f)));
  if (!d.votaciones.length) { cont.append(el("div", { class: "vacio" }, "Sin votaciones con estos filtros.")); return cont; }

  cont.append(el("div", { class: "grid g4" },
    stat("Votaciones decisivas", fmt(d.votaciones.length), "nominales, de fondo"),
    stat("Salen adelante", fmt(nSale), `${pct(nSale, d.votaciones.length)}%`),
    stat("Se tumban", fmt(nCae), `${pct(nCae, d.votaciones.length)}%`),
    stat("Combinaciones distintas", fmt(coal.size), "de grupos ganadores")));

  const pres = [...presencia.values()].filter((o) => o.sale + o.cae >= 5).sort((a, b) => b.enSale / Math.max(1, b.sale) - a.enSale / Math.max(1, a.sale));
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "En cuántas mayorías que aprueban está cada grupo"),
      el("p", { class: "small muted" }, "Porcentaje de lo que salió adelante que contó con el voto a favor del grupo."),
      barrasH(pres.map((o) => ({ label: o.siglas, color: colorSiglas(o.siglas), v: o.enSale, valorTexto: `${pct(o.enSale, o.sale)}%`, tip: () => `${o.enSale} de ${o.sale} votaciones decisivas aprobadas` })), { max: Math.max(...pres.map((o) => o.sale)) })),
    el("div", { class: "card" }, el("h3", {}, "En cuántas mayorías que tumban está cada grupo"),
      el("p", { class: "small muted" }, "Porcentaje de lo que se rechazó que contó con el voto en contra del grupo."),
      barrasH(pres.slice().sort((a, b) => b.enCae / Math.max(1, b.cae) - a.enCae / Math.max(1, a.cae)).map((o) => ({ label: o.siglas, color: colorSiglas(o.siglas), v: o.enCae, barColor: "var(--no)", valorTexto: `${pct(o.enCae, o.cae)}%`, tip: () => `${o.enCae} de ${o.cae} votaciones decisivas rechazadas` })), { max: Math.max(1, ...pres.map((o) => o.cae)) }))));

  const listaCoal = (sale) => [...coal.values()].filter((c) => c.sale === sale).sort((a, b) => b.n - a.n).slice(0, 15);
  const total = { true: nSale, false: nCae };
  const tablaCoal = (sale) => el("table", { class: "tabla" }, el("tbody", {}, listaCoal(sale).map((c) => el("tr", { class: "clic", onclick: () => irA("coaliciones", { ...q, ver: "", coal: c.clave }) },
    el("td", {}, el("div", { class: "chips", style: "margin:0" }, c.grupos.length ? c.grupos.map((s) => el("span", { class: "chip" }, el("span", { class: "sw", style: `background:${colorSiglas(s)}` }), s)) : el("span", { class: "muted small" }, "ningún grupo entero"))),
    el("td", { class: "num" }, fmt(c.n)), el("td", { class: "num muted" }, `${pct(c.n, total[sale])}%`)))));
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Combinaciones que aprueban"), el("p", { class: "small muted" }, "Clic en una fila para ver qué se aprobó con esa mayoría."), tablaCoal(true)),
    el("div", { class: "card" }, el("h3", {}, "Combinaciones que tumban"), el("p", { class: "small muted" }, "Grupos que votaron en contra de lo que se rechazó."), tablaCoal(false))));

  if (q.coal && coal.get(q.coal)) {
    const c = coal.get(q.coal);
    cont.append(el("div", { class: "card", style: "margin-top:16px" },
      el("h3", {}, `${c.sale ? "Aprobado" : "Tumbado"} con ${c.grupos.join(" + ") || "ningún grupo entero"} (${c.n})`),
      el("table", { class: "tabla" }, el("tbody", {}, c.votaciones.slice(0, 100).map((v) => el("tr", { class: "clic", onclick: () => abrir(`v:${v.id}`) },
        el("td", { class: "small", style: "white-space:nowrap" }, fecha(v.fecha)),
        el("td", {}, textoCorto(v.titulo && !v.sintetica ? v.titulo : v.texto_expediente, 160),
          el("div", { class: "small muted" }, [META.tipos_votacion[v.tipo_votacion], v.tema_principal ? temaNombre(v.tema_principal) : null].filter(Boolean).join(" · "))),
        el("td", { class: "small", style: "white-space:nowrap" }, `${v.a_favor}–${v.en_contra}–${v.abstenciones}`)))))));
  }
  return cont;
};

// ------------------------------------------------------------------ mapa ideológico y polarización

// MDS clásico sobre la distancia 1 - afinidad: devuelve las dos primeras coordenadas.
function mds(nombres, dist) {
  const n = nombres.length;
  const d2 = dist.map((f) => f.map((x) => x * x));
  const media = d2.map((f) => f.reduce((a, b) => a + b, 0) / n);
  const total = media.reduce((a, b) => a + b, 0) / n;
  const B = d2.map((f, i) => f.map((x, j) => -0.5 * (x - media[i] - media[j] + total)));
  const vectores = [], valores = [];
  let M = B.map((f) => f.slice());
  for (let k = 0; k < 2; k++) {
    let v = Array.from({ length: n }, (_, i) => 1 + i / n);
    let lambda = 0;
    for (let it = 0; it < 500; it++) {
      const w = M.map((f) => f.reduce((a, x, j) => a + x * v[j], 0));
      const norma = Math.hypot(...w) || 1;
      lambda = w.reduce((a, x, i) => a + x * v[i], 0) / (Math.hypot(...v) ** 2 || 1);
      v = w.map((x) => x / norma);
    }
    vectores.push(v);
    valores.push(Math.max(0, lambda));
    M = M.map((f, i) => f.map((x, j) => x - lambda * v[i] * v[j]));
  }
  const traza = B.reduce((a, f, i) => a + Math.max(0, f[i]), 0);
  return {
    puntos: nombres.map((s, i) => ({ s, x: vectores[0][i] * Math.sqrt(valores[0]), y: vectores[1][i] * Math.sqrt(valores[1]) })),
    varianza: valores.map((l) => (traza ? l / traza : 0)),
  };
}

API.mapa = (p) => {
  const legs = legsOActual(p.leg), temas = lista(p.tema).filter((t) => t !== "*");
  const pares = afinidadSiglas(legs, temas);
  // Por grupo, con los mismos filtros: cuántas veces vota lo que acaba saliendo y cuántas vota lo
  // mismo cuando PSOE y PP coinciden. Sirven para decir qué es cada eje del mapa.
  const w = ["v.decisiva=1", "v.asentimiento=0", `v.tipo_votacion IN (${FONDO_SQL})`, "g.grupo<>'?'",
    "g.sentido IN ('si','no','abstencion')"], a = [];
  condIn(w, a, "v.legislatura", legs.join(","), Number);
  let conFicha = "";
  if (temas.length) {
    conFicha = "JOIN ficha_llm f ON f.legislatura=v.legislatura AND f.expediente=v.expediente";
    condIn(w, a, "f.tema_principal", temas.join(","));
  }
  const votos = q(`SELECT v.id, v.resultado, gr.siglas, g.sentido FROM votacion v
    JOIN voto_grupo g ON g.votacion_id=v.id JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
    ${conFicha} WHERE ${w.join(" AND ")}`, a);
  const acuerdo = new Map(); // votación -> sentido común de PSOE y PP (si coinciden)
  const porVot = new Map();
  for (const r of votos) (porVot.get(r.id) || porVot.set(r.id, {}).get(r.id))[r.siglas] = r.sentido;
  for (const [id, s] of porVot) if (s.PSOE && s.PSOE === s.PP) acuerdo.set(id, s.PSOE);
  const perfil = new Map();
  for (const r of votos) {
    const o = perfil.get(r.siglas) || { siglas: r.siglas, n: 0, gana: 0, abst: 0, nAcuerdo: 0, conAcuerdo: 0 };
    o.n++;
    if (r.sentido === "abstencion") o.abst++;
    if ((r.resultado === "aprobada" && r.sentido === "si") || (r.resultado === "rechazada" && r.sentido === "no")) o.gana++;
    if (acuerdo.has(r.id)) { o.nAcuerdo++; if (acuerdo.get(r.id) === r.sentido) o.conAcuerdo++; }
    perfil.set(r.siglas, o);
  }
  const serie = q(`SELECT v.id, v.fecha, v.a_favor, v.en_contra, v.abstenciones, v.margen, v.mayoria, g.grupo, g.sentido,
      g.si + g.no + g.abstencion AS peso
    FROM votacion v JOIN voto_grupo g ON g.votacion_id=v.id
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) AND g.grupo<>'?'
    ORDER BY v.fecha`);
  return { pares, serie, perfil: [...perfil.values()] };
};

// Qué es cada eje del mapa. Los ejes del escalado no traen significado: se prueba qué indicador
// medible explica mejor la posición de los grupos en cada uno (correlación) y se rotula con él.
// Si ninguno encaja (|r| < 0,7), se rotulan con los grupos de los extremos.
function interpretarEjes(puntos, par, perfil) {
  const af = (a, b) => (a === b ? 1 : par[a + "|" + b]);
  const perf = new Map(perfil.map((r) => [r.siglas, r]));
  const hay = (s) => puntos.some((p) => p.s === s);
  const candidatos = [];
  if (hay("PSOE") && hay("PP")) {
    candidatos.push({
      valor: (s) => (af(s, "PP") ?? NaN) - (af(s, "PSOE") ?? NaN),
      alto: "Vota como el PP", bajo: "Vota como el PSOE",
      texto: "cuánto se parece el voto de cada grupo al del PP frente al del PSOE",
    });
    candidatos.push({
      valor: (s) => { const r = perf.get(s); return r && r.nAcuerdo >= 10 ? r.conAcuerdo / r.nAcuerdo : NaN; },
      alto: "Se suma al acuerdo PSOE-PP", bajo: "Se aparta del acuerdo PSOE-PP",
      texto: "cuántas veces vota lo mismo cuando PSOE y PP coinciden",
    });
  }
  candidatos.push({
    valor: (s) => { const r = perf.get(s); return r && r.n >= 10 ? r.gana / r.n : NaN; },
    alto: "Vota con el lado ganador", bajo: "Vota con el lado perdedor",
    texto: "cuántas veces vota lo que acaba saliendo adelante o tumbándose",
  });
  candidatos.push({
    valor: (s) => { const r = perf.get(s); return r && r.n >= 10 ? r.abst / r.n : NaN; },
    alto: "Se abstiene más", bajo: "Se abstiene menos",
    texto: "cuántas veces se abstiene",
  });
  const pearson = (xs, ys) => {
    const n = xs.length, mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
    let sxy = 0, sxx = 0, syy = 0;
    for (let i = 0; i < n; i++) { sxy += (xs[i] - mx) * (ys[i] - my); sxx += (xs[i] - mx) ** 2; syy += (ys[i] - my) ** 2; }
    return sxx && syy ? sxy / Math.sqrt(sxx * syy) : 0;
  };
  const usados = new Set();
  return ["x", "y"].map((eje) => {
    let mejor = null;
    for (const c of candidatos) {
      if (usados.has(c)) continue;
      const pts = puntos.filter((p) => Number.isFinite(c.valor(p.s)));
      if (pts.length < 4) continue;
      const r = pearson(pts.map((p) => p[eje]), pts.map((p) => c.valor(p.s)));
      if (!mejor || Math.abs(r) > Math.abs(mejor.r)) mejor = { c, r };
    }
    if (mejor && Math.abs(mejor.r) >= 0.7) {
      usados.add(mejor.c);
      return { mas: mejor.r > 0 ? mejor.c.alto : mejor.c.bajo, menos: mejor.r > 0 ? mejor.c.bajo : mejor.c.alto, texto: mejor.c.texto, r: Math.abs(mejor.r) };
    }
    const orden = puntos.slice().sort((a, b) => a[eje] - b[eje]);
    return { mas: orden.at(-1).s, menos: orden[0].s, texto: null, r: null };
  });
}

// infoDe(siglas) -> { siglas, nombre, color, diputados }
// ejes: [horizontal, vertical], cada uno { mas, menos } (rótulo del extremo positivo y del negativo).
function graficoMapa(puntos, infoDe, ejes = null) {
  // En móvil, lienzo al ancho de la pantalla y casi cuadrado.
  const W = anchoGrafico(760), H = esMovil() ? Math.round(W * 0.9) : 460, m = esMovil() ? 36 : 50;
  const xs = puntos.map((p) => p.x), ys = puntos.map((p) => p.y);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)], [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const esc = Math.min((W - 2 * m) / Math.max(1e-6, x1 - x0), (H - 2 * m) / Math.max(1e-6, y1 - y0));
  const cx = (W - esc * (x1 - x0)) / 2, cy = (H - esc * (y1 - y0)) / 2;
  const X = (x) => cx + (x - x0) * esc, Y = (y) => H - (cy + (y - y0) * esc);
  const ns = "http://www.w3.org/2000/svg";
  const mk = (t, a) => { const n = document.createElementNS(ns, t); for (const [k, v] of Object.entries(a)) n.setAttribute(k, v); return n; };
  const svg = mk("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Mapa de grupos según sus votos" });
  svg.appendChild(mk("line", { x1: m / 2, x2: W - m / 2, y1: H / 2, y2: H / 2, class: "gridline" }));
  svg.appendChild(mk("line", { x1: W / 2, x2: W / 2, y1: m / 2, y2: H - m / 2, class: "gridline" }));
  // Etiquetas a la derecha del punto; si chocan con otra ya colocada, se desplazan en vertical.
  const radio = (p) => Math.max(5, Math.sqrt((infoDe(p.s) || {}).diputados || 4) * 1.6);
  // Los puntos también son obstáculos para las etiquetas.
  const colocadas = puntos.map((p) => ({ x: X(p.x) - radio(p), y: Y(p.y) + 4, w: 2 * radio(p) }));
  if (ejes) {
    const [h, v] = ejes;
    const rotulo = (x, y, texto, ancla) => {
      const t = mk("text", { x, y, "text-anchor": ancla, class: "eje" });
      t.textContent = texto;
      svg.appendChild(t);
      const w = texto.length * 6.2;
      colocadas.push({ x: ancla === "end" ? x - w : ancla === "middle" ? x - w / 2 : x, y, w });
    };
    rotulo(m / 2, H / 2 - 6, `← ${h.menos}`, "start");
    rotulo(W - m / 2, H / 2 - 6, `${h.mas} →`, "end");
    rotulo(W / 2, m / 2 - 6, `↑ ${v.mas}`, "middle");
    rotulo(W / 2, H - m / 2 + 16, `↓ ${v.menos}`, "middle");
  }
  // Busca sitio a la derecha o a la izquierda del punto, desplazándose en vertical si hace falta.
  const sitio = (cxp, cyp, r, ancho) => {
    const libre = (x, y) => !colocadas.some((c) => Math.abs(c.y - y) < 15 && x < c.x + c.w && c.x < x + ancho);
    for (const dy of [0, 16, -16, 32, -32, 48, -48, 64, -64, 80, -80]) {
      for (const lado of [1, -1]) {
        const x = lado > 0 ? cxp + r + 5 : cxp - r - 5 - ancho;
        if (libre(x, cyp + 4 + dy)) { colocadas.push({ x, y: cyp + 4 + dy, w: ancho }); return { x, y: cyp + 4 + dy, lado }; }
      }
    }
    colocadas.push({ x: cxp + r + 5, y: cyp + 4, w: ancho });
    return { x: cxp + r + 5, y: cyp + 4, lado: 1 };
  };
  for (const p of puntos.slice().sort((a, b) => b.y - a.y)) {
    const info = infoDe(p.s) || { siglas: p.s, nombre: p.s, color: "#9aa0a6", diputados: 4 };
    const r = Math.max(5, Math.sqrt(info.diputados || 4) * 1.6);
    const g = mk("g", { tabindex: 0 });
    g.appendChild(mk("circle", { cx: X(p.x), cy: Y(p.y), r, fill: info.color, stroke: "var(--surface-1)", "stroke-width": 2, class: "mark" }));
    const ancho = info.siglas.length * 8 + 4;
    const lugar = sitio(X(p.x), Y(p.y), r, ancho);
    if (lugar.y !== Y(p.y) + 4) {
      const xl = lugar.lado > 0 ? lugar.x - 1 : lugar.x + ancho + 1;
      g.appendChild(mk("line", { x1: X(p.x) + lugar.lado * r, y1: Y(p.y), x2: xl, y2: lugar.y - 4, stroke: "var(--axis)", "stroke-width": 1 }));
    }
    const t = mk("text", { x: lugar.x, y: lugar.y, class: "lbl" }); t.textContent = info.siglas; g.appendChild(t);
    g.appendChild(mk("circle", { cx: X(p.x), cy: Y(p.y), r: Math.max(r, 14), class: "hit" }));
    alPasar(g, (e) => tip(e, info.siglas, info.nombre, `${info.diputados} diputados`));
    svg.appendChild(g);
  }
  return el("div", { class: "chart", style: "max-width:820px" }, svg);
}

VISTAS.mapa = async (q) => {
  const legs = legsOActual(q.leg);
  const temas = lista(q.tema).filter((t) => t !== "*");
  const d = await api("mapa", { leg: legs.join(","), tema: temas.join(",") });
  const cont = el("div", {}, subnav(NAV_ANALISIS, "mapa", q),
    el("h2", {}, "Mapa ideológico y polarización"),
    el("p", { class: "sub" }, "Cada grupo se sitúa según con quién vota: cuanto más cerca están dos puntos, más a menudo votan igual. Se calcula con escalado multidimensional sobre la afinidad en votaciones de fondo. Cada eje lleva en sus extremos el indicador de voto que mejor explica la posición de los grupos en él. El mapa se orienta con el PP a la derecha del PSOE y el PNV arriba para poder comparar legislaturas. Con varias legislaturas o temas, cada partido suma todas sus votaciones."),
    formFiltros([
      multiSelect("leg", optLegs(), legs.join(","), "Legislatura", "legislaturas"),
      multiSelect("tema", optTemas(), temas.join(","), "Todos los temas", "temas"),
    ], q, (f) => irA("mapa", f)));

  // Grupos (por siglas) con afinidad calculada con todos los demás (mínimo 5 votaciones por par).
  const info = new Map(gruposDeLegs(legs).map((g) => [g.siglas, g]));
  const gs = [...info.keys()];
  const par = {};
  for (const r of d.pares) if (r.total >= 5) par[r.a + "|" + r.b] = r.coinciden / r.total;
  let incluidos = gs.slice();
  while (incluidos.length > 2) {
    const faltan = incluidos.map((a) => incluidos.filter((b) => b !== a && par[a + "|" + b] === undefined).length);
    const peor = Math.max(...faltan);
    if (peor === 0) break;
    incluidos.splice(faltan.indexOf(peor), 1);
  }
  const fuera = gs.filter((g) => !incluidos.includes(g));
  let mapa = null;
  if (incluidos.length >= 3) {
    const dist = incluidos.map((a) => incluidos.map((b) => (a === b ? 0 : 1 - par[a + "|" + b])));
    mapa = mds(incluidos, dist);
    const pos = Object.fromEntries(mapa.puntos.map((p) => [p.s, p]));
    if (pos.PP && pos.PSOE && pos.PP.x < pos.PSOE.x) mapa.puntos.forEach((p) => (p.x = -p.x));
    const pnv = pos.PNV;
    if (pnv && pnv.y < 0) mapa.puntos.forEach((p) => (p.y = -p.y));
  }
  const ejes = mapa ? interpretarEjes(mapa.puntos, par, d.perfil) : null;
  cont.append(el("div", { class: "card" },
    el("h3", {}, `Posición de los grupos · ${textoLegs(legs)}${temas.length ? " · " + textoTemas(temas) : ""}`),
    mapa ? [graficoMapa(mapa.puntos, (s) => info.get(s), ejes),
      el("p", { class: "small muted" }, ejes.map((e, i) => {
        const cual = i ? "Eje vertical" : "Eje horizontal";
        const pct = `${Math.round(100 * mapa.varianza[i])}% de las diferencias de voto`;
        return e.texto
          ? `${cual} (${pct}): ${e.texto} (correlación ${e.r.toLocaleString("es-ES", { maximumFractionDigits: 2 })}). `
          : `${cual} (${pct}): ningún indicador lo explica bien con estos filtros; se rotula con los grupos de los extremos. `;
      }).join(""), "El tamaño del punto es el número de diputados.",
        fuera.length ? ` Sin datos suficientes para situar: ${fuera.join(", ")}.` : "")] :
      el("div", { class: "vacio" }, "No hay votaciones suficientes para dibujar el mapa con estos filtros.")));

  // Polarización trimestral en todo el periodo.
  const porVot = new Map();
  for (const r of d.serie) {
    const o = porVot.get(r.id) || { fecha: r.fecha, a_favor: r.a_favor, en_contra: r.en_contra, abst: r.abstenciones, margen: r.margen, mayoria: r.mayoria, grupos: [] };
    if (["si", "no", "abstencion"].includes(r.sentido)) o.grupos.push([r.sentido, r.peso]);
    porVot.set(r.id, o);
  }
  const tri = new Map();
  for (const v of porVot.values()) {
    const k = `${v.fecha.slice(0, 4)}-T${Math.floor((+v.fecha.slice(5, 7) - 1) / 3) + 1}`;
    const o = tri.get(k) || { n: 0, consenso: 0, ajustadas: 0, polar: 0 };
    const emitidos = v.a_favor + v.en_contra + v.abst;
    o.n++;
    if (emitidos && Math.max(v.a_favor, v.en_contra) >= 0.8 * emitidos) o.consenso++;
    if (v.mayoria === "simple" && Math.abs(v.margen) <= 10) o.ajustadas++;
    let dis = 0, tot = 0;
    for (let i = 0; i < v.grupos.length; i++) for (let j = i + 1; j < v.grupos.length; j++) {
      const w = v.grupos[i][1] * v.grupos[j][1];
      tot += w;
      if (v.grupos[i][0] !== v.grupos[j][0]) dis += w;
    }
    o.polar += tot ? dis / tot : 0;
    tri.set(k, o);
  }
  const claves = [];
  const [y0, y1] = [2012, +hoyISO().slice(0, 4)];
  for (let y = y0; y <= y1; y++) for (let t = 1; t <= 4; t++) claves.push(`${y}-T${t}`);
  const inicios = new Set(META.legislaturas.map((l) => `${l.desde.slice(0, 4)}-T${Math.floor((+l.desde.slice(5, 7) - 1) / 3) + 1}`));
  const serie = (f) => claves.map((k) => {
    const o = tri.get(k);
    return { label: k.replace("-", " "), y: o && o.n >= 5 ? f(o) : null, extra: o ? `${o.n} votaciones decisivas` : "sin votaciones", tick: k.endsWith("T1") && +k.slice(0, 4) % 2 === 0 ? k.slice(0, 4) : null, corte: inicios.has(k) };
  }).filter((d, i, xs) => i < xs.length - 1 || d.y !== null);
  cont.append(el("div", { class: "card", style: "margin-top:16px" },
    el("h3", {}, "Polarización por trimestre"),
    el("p", { class: "small muted" }, "Desacuerdo medio entre grupos en las votaciones decisivas de fondo, ponderado por el número de diputados de cada par: 0% si todos votan igual, 100% si cada par vota distinto. Las líneas verticales marcan el inicio de cada legislatura."),
    lineaTiempo(serie((o) => (100 * o.polar) / o.n), { etiqueta: "Índice de polarización por trimestre" })));
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Votaciones con amplio acuerdo"),
      el("p", { class: "small muted" }, "Porcentaje de votaciones decisivas en que el 80% o más de los votos emitidos fue en el mismo sentido."),
      lineaTiempo(serie((o) => (100 * o.consenso) / o.n), { alto: 170, ancho: 560, etiqueta: "Votaciones con amplio acuerdo" })),
    el("div", { class: "card" }, el("h3", {}, "Votaciones ajustadas"),
      el("p", { class: "small muted" }, "Porcentaje de votaciones decisivas resueltas por 10 votos o menos."),
      lineaTiempo(serie((o) => (100 * o.ajustadas) / o.n), { alto: 170, ancho: 560, etiqueta: "Votaciones ajustadas" }))));
  return cont;
};

// ------------------------------------------------------------------ disciplina y ausencias

API.disciplina = (p) => {
  const leg = +(lista(p.leg).at(-1) || legPorDefecto());
  const votos = q(`SELECT v.id, v.fecha, v.tipo_votacion, v.decisiva, v.resultado, v.a_favor, v.en_contra, v.abstenciones,
      v.margen, v.mayoria, n.sentidos
    FROM votacion v JOIN voto_nominal n ON n.votacion_id=v.id WHERE v.legislatura=? AND v.asentimiento=0 ORDER BY v.fecha`, [leg]);
  const grupos = q(`SELECT g.votacion_id, g.grupo, g.sentido, g.si, g.no, g.abstencion, g.no_vota
    FROM voto_grupo g JOIN votacion v ON v.id=g.votacion_id WHERE v.legislatura=? AND v.asentimiento=0`, [leg]);
  const tramos = q("SELECT diputado_id, grupo, desde, hasta FROM diputado_grupo WHERE legislatura=? ORDER BY desde", [leg]);
  const titulos = q(`SELECT v.id, i.titulo, i.sintetica, v.texto_expediente FROM votacion v
    LEFT JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    WHERE v.legislatura=? AND v.decisiva=1 AND v.asentimiento=0`, [leg]);
  return { leg, votos, grupos, tramos, titulos, plantilla: plantilla(leg) };
};

VISTAS.disciplina = async (q) => {
  const legs = legsOActual(q.leg);
  const leg = legs.join(",");
  const filtroGrupos = new Set(lista(q.grupo));
  const fondo = new Set(TIPOS_FONDO);
  // Se calcula legislatura a legislatura (cada una tiene su plantilla) y se suma por diputado y por grupo.
  const dips = new Map(), coh = new Map(), tit = {}, perdidas = [];
  for (const l of legs) {
    const d = await api("disciplina", { leg: l });
    const porVot = new Map();
    for (const g of d.grupos) (porVot.get(g.votacion_id) || porVot.set(g.votacion_id, {}).get(g.votacion_id))[g.grupo] = g;
    const tramosDe = new Map();
    for (const t of d.tramos) (tramosDe.get(t.diputado_id) || tramosDe.set(t.diputado_id, []).get(t.diputado_id)).push(t);
    const grupoEn = (did, f) => {
      const ts = tramosDe.get(did) || [];
      if (ts.length === 1) return ts[0].grupo;
      for (const t of ts) if (t.desde <= f && f <= t.hasta) return t.grupo;
      return ts.length ? ts.at(-1).grupo : "?";
    };
    // Posición en la plantilla de la legislatura -> diputado (acumulado entre legislaturas).
    const dip = d.plantilla.map((p) => {
      const o = dips.get(p.id) || { id: p.id, nombre: p.nombre, presente: 0, novota: 0, fondo: 0, disc: 0, discDec: 0 };
      const g = grupo(l, (tramosDe.get(p.id) || []).at(-1)?.grupo || "?");
      o.siglas = g.siglas; o.color = g.color;
      dips.set(p.id, o);
      return o;
    });
    for (const v of d.votos) {
      const gs = porVot.get(v.id) || {};
      const esFondo = fondo.has(v.tipo_votacion);
      for (let i = 0; i < v.sentidos.length; i++) {
        const c = v.sentidos[i];
        if (c === ".") continue;
        const o = dip[i];
        o.presente++;
        if (c === "-") { o.novota++; continue; }
        if (!esFondo) continue;
        const g = grupoEn(o.id, v.fecha);
        if (GRUPOS_HETEROGENEOS.has(g)) continue;
        const sg = gs[g] && gs[g].sentido;
        if (!["si", "no", "abstencion"].includes(sg)) continue;
        o.fondo++;
        if (LETRA_SENTIDO[c] !== sg) { o.disc++; if (v.decisiva) o.discDec++; }
      }
    }

    // Votaciones que se perdieron (o se salvaron) por ausencias.
    for (const t of d.titulos) tit[t.id] = (t.titulo && !t.sintetica ? t.titulo : t.texto_expediente || "").split("\n")[0];
    for (const v of d.votos) {
      if (!v.decisiva || !fondo.has(v.tipo_votacion)) continue;
      const gs = Object.values(porVot.get(v.id) || {}).filter((g) => g.grupo !== "?");
      const aprobada = v.resultado === "aprobada";
      const lado = aprobada ? "no" : "si";
      const ausentes = gs.filter((g) => g.sentido === lado && g.no_vota > 0);
      const extra = ausentes.reduce((a, g) => a + g.no_vota, 0);
      let cambia;
      if (v.mayoria === "absoluta") cambia = !aprobada && v.a_favor + extra >= mayoriaAbs(l);
      else cambia = aprobada ? v.en_contra + extra >= v.a_favor : v.a_favor + extra > v.en_contra;
      if (cambia) perdidas.push({ v, ausentes, extra, aprobada, leg: l });
    }

    // Cohesión por grupo (por siglas).
    for (const v of d.votos) {
      if (!fondo.has(v.tipo_votacion)) continue;
      for (const g of Object.values(porVot.get(v.id) || {})) {
        if (g.grupo === "?") continue;
        const s = siglas(l, g.grupo);
        const emit = g.si + g.no + g.abstencion;
        const o = coh.get(s) || { n: 0, partidas: 0, novota: 0, total: 0, heterogeneo: false };
        o.n++;
        if (emit - Math.max(g.si, g.no, g.abstencion) >= Math.max(2, 0.1 * emit)) o.partidas++;
        o.novota += g.no_vota; o.total += emit + g.no_vota;
        o.heterogeneo ||= GRUPOS_HETEROGENEOS.has(g.grupo);
        coh.set(s, o);
      }
    }
  }
  perdidas.sort((a, b) => b.v.fecha.localeCompare(a.v.fecha));
  const porGrupoAus = new Map();
  for (const p of perdidas) for (const g of p.ausentes) porGrupoAus.set(siglas(p.leg, g.grupo), (porGrupoAus.get(siglas(p.leg, g.grupo)) || 0) + 1);
  const visibles = [...dips.values()].filter((o) => !filtroGrupos.size || filtroGrupos.has(o.siglas));
  const optsGrupo = gruposDeLegs(legs, 0).map((g) => [g.siglas, g.siglas]);

  const cont = el("div", {}, subnav(NAV_ANALISIS, "disciplina", q),
    el("h2", {}, "Disciplina y ausencias"),
    el("p", { class: "sub" }, "Quién vota distinto a su grupo, quién falta y qué votaciones habrían cambiado si hubieran votado los ausentes. «No vota» incluye bajas, permisos y otras causas que los datos no distinguen, y desde 2020 el voto telemático reduce mucho las ausencias. En el Mixto y el Plural no se cuentan discrepancias porque reúnen partidos distintos."),
    formFiltros([
      multiSelect("leg", optLegs(), leg, "Legislatura", "legislaturas"),
      multiSelect("grupo", optsGrupo, [...filtroGrupos].join(","), "Todos los grupos", "grupos"),
    ], q, (f) => irA("disciplina", f)));

  const gruposOrden = gruposDeLegs(legs, 0).filter((g) => coh.get(g.siglas));
  cont.append(el("div", { class: "card" }, el("h3", {}, `Cohesión y asistencia por grupo · ${textoLegs(legs)}`),
    el("table", { class: "tabla" },
      el("thead", {}, el("tr", {}, el("th", {}, "Grupo"), el("th", { class: "num" }, legs.length > 1 ? "Diputados (última)" : "Diputados"), el("th", { class: "num" }, "Votaciones de fondo con el grupo partido"), el("th", { class: "num" }, "Votos no emitidos"), el("th", { class: "num" }, "Votaciones perdidas por ausencias propias"))),
      el("tbody", {}, gruposOrden.map((g) => {
        const o = coh.get(g.siglas);
        return el("tr", { class: "clic" + (filtroGrupos.has(g.siglas) ? " activo" : ""), onclick: () => irA("disciplina", { leg, grupo: g.siglas }) },
          el("td", {}, swatch(g.color), g.siglas), el("td", { class: "num" }, g.diputados),
          el("td", { class: "num" }, `${((100 * o.partidas) / o.n).toFixed(1)}%${o.heterogeneo ? " (grupo heterogéneo)" : ""}`),
          el("td", { class: "num" }, `${((100 * o.novota) / o.total).toFixed(1)}%`),
          el("td", { class: "num" }, fmt(porGrupoAus.get(g.siglas) || 0)));
      })))));

  const tablaDip = (filas, fmtCol) => el("table", { class: "tabla" }, el("tbody", {}, filas.map((o) => el("tr", { class: "clic", onclick: () => abrir(`d:${o.id}`) },
    el("td", {}, o.nombre), el("td", { class: "small" }, swatch(o.color), o.siglas), el("td", { class: "num" }, fmtCol(o))))));
  const rebeldes = visibles.filter((o) => o.disc > 0).sort((a, b) => b.disc - a.disc).slice(0, 25);
  const ausentes = visibles.filter((o) => o.presente >= 100).sort((a, b) => b.novota / b.presente - a.novota / a.presente).slice(0, 25);
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Votan distinto a su grupo"),
      el("p", { class: "small muted" }, "Votaciones de fondo en que el diputado votó distinto a la mayoría de su grupo (entre paréntesis, cuántas eran decisivas). Un voto aislado puede ser un error al pulsar."),
      rebeldes.length ? tablaDip(rebeldes, (o) => `${o.disc} (${o.discDec})`) : el("p", { class: "muted" }, "Nadie en esta selección.")),
    el("div", { class: "card" }, el("h3", {}, "Más votos no emitidos"),
      el("p", { class: "small muted" }, "Porcentaje de votaciones en que el diputado, siendo miembro de la Cámara, no votó. Mínimo 100 votaciones. Los datos no dicen por qué: bajas, permisos, suspensiones o la agenda de quien preside el Gobierno, es ministro o dirige su partido cuentan igual, así que no todas las ausencias son comparables."),
      tablaDip(ausentes, (o) => `${((100 * o.novota) / o.presente).toFixed(1)}% (${o.novota})`))));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, `Votaciones que habrían cambiado con los ausentes (${perdidas.length})`),
    el("p", { class: "small muted" }, "Votaciones decisivas en que los diputados que no votaron de los grupos del lado perdedor habrían bastado para dar la vuelta al resultado, si hubieran votado lo mismo que su grupo."),
    perdidas.length ? el("table", { class: "tabla" }, el("tbody", {}, perdidas.slice(0, 60).map((p) => el("tr", { class: "clic", onclick: () => abrir(`v:${p.v.id}`) },
      el("td", { class: "small", style: "white-space:nowrap" }, fecha(p.v.fecha)),
      el("td", {}, textoCorto(tit[p.v.id], 150), el("div", { class: "small muted" }, `${META.tipos_votacion[p.v.tipo_votacion]} · ${p.aprobada ? "aprobada" : "rechazada"} ${p.v.a_favor}–${p.v.en_contra}`)),
      el("td", { class: "small" }, "No votaron: ", p.ausentes.map((g) => `${g.no_vota} de ${siglas(p.leg, g.grupo)}`).join(", ")))))) :
      el("p", { class: "muted" }, "Ninguna con estos filtros.")));
  return cont;
};

// ------------------------------------------------------------------ enmiendas

API.enmiendas = (p) => {
  const w = ["v.enmienda_grupo IS NOT NULL"], a = [];
  condIn(w, a, "v.legislatura", p.leg, Number);
  if (p.sinpge === "1") w.push("COALESCE(f.tema_principal,'') <> 'PRE'");
  condIn(w, a, "f.tema_principal", p.tema);
  const where = w.join(" AND ");
  const base = `FROM votacion v
    LEFT JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    LEFT JOIN ficha_llm f ON f.legislatura=v.legislatura AND f.expediente=v.expediente
    WHERE ${where}`;
  return {
    porGrupo: q(`SELECT v.legislatura, v.enmienda_grupo AS grupo, v.tipo_votacion AS tipo, COUNT(*) AS n,
        SUM(v.resultado='aprobada') AS ok, SUM(COALESCE(v.enmiendas_n,0)) AS enm, SUM(CASE WHEN v.resultado='aprobada' THEN COALESCE(v.enmiendas_n,0) ELSE 0 END) AS enm_ok
      ${base} GROUP BY 1, 2, 3`, a),
    leyes: q(`SELECT v.legislatura, v.expediente, i.titulo, i.resultado_final, COUNT(*) AS n, SUM(v.resultado='aprobada') AS ok,
        GROUP_CONCAT(CASE WHEN v.resultado='aprobada' THEN v.enmienda_grupo END) AS grupos_ok
      ${base} AND v.tipo_votacion='enmiendas' GROUP BY 1, 2 HAVING ok > 0 ORDER BY ok DESC, n DESC LIMIT 40`, a),
    cruce: q(`SELECT v.legislatura, v.enmienda_grupo AS autor, g.grupo AS votante, SUM(g.sentido='si') AS si, COUNT(*) AS n
      ${base.replace("WHERE", "JOIN voto_grupo g ON g.votacion_id=v.id WHERE")} AND v.tipo_votacion='enmiendas' AND g.grupo<>'?' AND g.sentido IS NOT NULL
      GROUP BY 1, 2, 3`, a),
  };
};

VISTAS.enmiendas = async (q) => {
  const d = await api("enmiendas", q);
  const nombre = (leg, g) => (g === "Senado" ? "Senado" : g === "Transaccional" ? "Transaccionales" : g === "Varios" ? "Varios grupos" : siglas(leg, g));
  const agg = new Map();
  for (const r of d.porGrupo) {
    const k = r.tipo + "|" + nombre(r.legislatura, r.grupo);
    const o = agg.get(k) || { tipo: r.tipo, s: nombre(r.legislatura, r.grupo), n: 0, ok: 0, enm: 0, enm_ok: 0 };
    o.n += r.n; o.ok += r.ok; o.enm += r.enm; o.enm_ok += r.enm_ok;
    agg.set(k, o);
  }
  const de = (tipo) => [...agg.values()].filter((o) => o.tipo === tipo).sort((a, b) => b.ok / b.n - a.ok / a.n || b.n - a.n);
  const colorDe = (s) => (["Senado", "Transaccionales", "Varios grupos"].includes(s) ? "#9aa0a6" : colorSiglas(s));
  const barras = (xs) => barrasH(xs.filter((o) => o.n >= 3).map((o) => ({
    label: o.s, color: colorDe(o.s), valorTexto: `${o.ok} de ${o.n} (${pct(o.ok, o.n)}%)`,
    segs: [{ v: o.ok, color: "var(--si)", nombre: "aprobadas" }, { v: o.n - o.ok, color: "var(--no)", nombre: "rechazadas" }],
    tip: (s) => `${fmt(s.v)} votaciones ${s.nombre}${o.enm ? ` · unas ${fmt(o.enm)} enmiendas votadas, ${fmt(o.enm_ok)} aprobadas` : ""}`,
  })), { segs: true, normalizar: true });

  const cont = el("div", {}, subnav(NAV_ANALISIS, "enmiendas", q),
    el("h2", {}, "Enmiendas"),
    el("p", { class: "sub" }, "Quién consigue cambiar las leyes. Se cuentan las enmiendas que llegan a votarse en el Pleno (las pactadas en ponencia o comisión ya están incorporadas al texto y no aparecen aquí). Una votación puede agrupar varias enmiendas."),
    formFiltros([
      multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
      multiSelect("tema", optTemas(), q.tema, "Cualquier tema", "temas"),
      el("label", { class: "check" }, el("input", { type: "checkbox", name: "sinpge", checked: q.sinpge === "1" }), "Sin Presupuestos"),
    ], q, (f) => irA("enmiendas", f)));
  const leyendaEnm = el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--si)" }), "Aprobadas"), el("span", {}, el("i", { style: "background:var(--no)" }), "Rechazadas"));
  cont.append(el("div", { class: "grid g2" },
    el("div", { class: "card" }, el("h3", {}, "Enmiendas parciales defendidas en el Pleno"),
      el("p", { class: "small muted" }, "Votaciones de enmiendas de cada grupo y cuántas se aprobaron. Las transaccionales son acuerdos entre grupos."),
      leyendaEnm, barras(de("enmiendas"))),
    el("div", { class: "card" }, el("h3", {}, "Enmiendas a la totalidad"),
      el("p", { class: "small muted" }, "Enmiendas de devolución o texto alternativo. Si prosperan, el proyecto vuelve al Gobierno o se sustituye."),
      leyendaEnm, barras(de("totalidad")),
      el("h3", { style: "margin-top:16px" }, "Enmiendas del Senado"),
      el("p", { class: "small muted" }, "Cambios introducidos por el Senado que el Congreso acepta o rechaza."),
      barras(de("enmiendas_senado")))));

  // Quién apoya las enmiendas de quién (por siglas).
  const cruce = new Map();
  for (const r of d.cruce) {
    if (["Senado", "Transaccional", "Varios", "Otros"].includes(r.autor)) continue;
    const k = siglas(r.legislatura, r.autor) + "|" + siglas(r.legislatura, r.votante);
    const o = cruce.get(k) || { si: 0, n: 0 };
    o.si += r.si; o.n += r.n;
    cruce.set(k, o);
  }
  const autores = [...new Set([...cruce.keys()].map((k) => k.split("|")[0]))];
  const orden = todasSiglas().filter((s) => autores.includes(s));
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Quién apoya las enmiendas de quién"),
    el("p", { class: "small muted" }, "Filas: grupo que presenta la enmienda. Columnas: grupo que vota. Porcentaje de votaciones en que el grupo de la columna votó a favor."),
    mapaCalor(orden, orden, (a, b) => {
      const o = cruce.get(a + "|" + b);
      return o ? { p: o.si / o.n, n: o.n, o } : null;
    }, {
      etiquetaFila: (s) => [swatch(colorSiglas(s)), s],
      tip: (a, b, x) => [`${Math.round(100 * x.p)}% a favor`, `${b} ante las enmiendas de ${a}`, `${x.o.si} de ${x.n} votaciones`],
    })));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Leyes con más enmiendas aprobadas en el Pleno"),
    el("table", { class: "tabla" }, el("tbody", {}, d.leyes.map((l) => el("tr", { class: "clic", onclick: () => abrir(`i:${l.legislatura}:${l.expediente}`) },
      el("td", {}, textoCorto(l.titulo, 150), el("div", { class: "small muted" }, `Leg. ${romano(l.legislatura)} · ${[...new Set((l.grupos_ok || "").split(",").filter(Boolean).map((g) => nombre(l.legislatura, g)))].join(", ")}`)),
      el("td", { class: "num" }, `${l.ok} de ${l.n}`), el("td", {}, badgeResultado(l.resultado_final))))))));
  return cont;
};

// ------------------------------------------------------------------ mis causas y scorecard

const CLAVE_CAUSAS = "escrutinio.causas";
function leerCausas() {
  try { return JSON.parse(localStorage.getItem(CLAVE_CAUSAS) || "[]"); } catch { return []; }
}
function guardarCausas(cs) {
  try { localStorage.setItem(CLAVE_CAUSAS, JSON.stringify(cs)); return true; } catch { return false; }
}
function criteriosTexto(c) {
  return [c.q ? `texto «${c.q}»` : null, c.tema ? `tema ${lista(c.tema).map(temaNombre).join(" o ")}` : null, c.etiqueta ? `#${c.etiqueta}` : null,
    lista(c.leg).length ? `Leg. ${lista(c.leg).map(romano).join(", ")}` : "todas las legislaturas"].filter(Boolean).join(" · ");
}

API.causa = (p) => {
  const filtro = { q: p.q, tema: p.tema, etiqueta: p.etiqueta, leg: p.leg, sec: "1" };
  const [w, a] = filtrosAsunto(filtro);
  const asuntos = q(`SELECT i.legislatura, i.expediente, i.titulo, i.grupo_autor, i.resultado_final, te.familia ${FROM_ASUNTO} WHERE ${w}`, a);
  const votaciones = q(`SELECT v.id, v.fecha, v.legislatura, v.tipo_votacion, v.resultado, v.a_favor, v.en_contra, v.abstenciones,
      v.margen, v.titulo_subgrupo, v.texto_subgrupo, v.texto_expediente, i.titulo, i.sintetica, i.grupo_autor, te.familia
    FROM votacion v
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo
    WHERE v.decisiva=1 AND v.asentimiento=0 AND v.tipo_votacion IN (${FONDO_SQL}) AND ${w}
    ORDER BY v.fecha DESC, v.numero DESC LIMIT 400`, a);
  return { asuntos, votaciones, celdas: celdasDe(votaciones.map((v) => v.id)) };
};

// Puntuación de cada diputado en las votaciones marcadas (a partir del voto nominal).
function puntuacionDiputados(marcadas) {
  const res = new Map();
  if (!marcadas.length) return res;
  const ids = marcadas.map((m) => m.id);
  const filas = q(`SELECT v.id, v.legislatura, v.fecha, v.tipo_votacion, n.sentidos FROM votacion v JOIN voto_nominal n ON n.votacion_id=v.id
    WHERE v.id IN (${ids.map(() => "?").join(",")})`, ids);
  const objetivo = Object.fromEntries(marcadas.map((m) => [m.id, m.favorable]));
  const tramos = new Map();
  for (const f of filas) {
    const plant = plantilla(f.legislatura);
    if (!tramos.has(f.legislatura)) tramos.set(f.legislatura, q("SELECT diputado_id, grupo, desde, hasta FROM diputado_grupo WHERE legislatura=?", [f.legislatura]));
    const grupoDe = {};
    for (const t of tramos.get(f.legislatura)) if (t.desde <= f.fecha && f.fecha <= t.hasta) grupoDe[t.diputado_id] = t.grupo;
    for (const d of plant) {
      const c = f.sentidos[d.pos - 1];
      if (!c || c === ".") continue;
      const o = res.get(d.id) || { id: d.id, nombre: d.nombre, grupo: null, leg: f.legislatura, bien: 0, mal: 0, abst: 0, ausente: 0 };
      o.grupo = grupoDe[d.id] || o.grupo; o.leg = f.legislatura;
      let s = LETRA_SENTIDO[c];
      if (f.tipo_votacion === "totalidad") s = s === "si" ? "no" : s === "no" ? "si" : s;
      if (s === "no_vota") o.ausente++;
      else if (s === "abstencion") o.abst++;
      else if (s === objetivo[f.id]) o.bien++;
      else o.mal++;
      res.set(d.id, o);
    }
  }
  return res;
}

VISTAS.causas = async (q) => {
  const causas = leerCausas();
  const cont = el("div", {}, subnav(NAV_ACTIVISMO, "causas", q),
    el("h2", {}, "Mis causas"),
    el("p", { class: "sub" }, "Una causa es un seguimiento guardado: un texto, un tema o una etiqueta. Para cada causa ves todo lo votado, las novedades desde tu última visita y un scorecard en el que tú decides qué voto era el favorable. Todo se guarda solo en este navegador."));
  const form = el("form", { class: "card", onsubmit: (e) => {
    e.preventDefault();
    const f = leerFormulario(form);
    if (!f.q && !f.tema && !f.etiqueta) { alert("Indica al menos un texto, un tema o una etiqueta."); return; }
    const c = { id: String(Date.now()), nombre: f.nombre || f.q || f.etiqueta || lista(f.tema).map(temaNombre).join(" + "), q: f.q, tema: f.tema, etiqueta: f.etiqueta, leg: f.leg, creada: hoyISO(), ultimaVisita: null, marcas: {} };
    causas.push(c);
    if (guardarCausas(causas)) irA("causa", { c: c.id });
    else {
      alert("Este navegador no permite guardar datos locales; la causa se abrirá pero no quedará guardada.");
      irA("causa", { q: c.q, tema: c.tema, etiqueta: c.etiqueta, leg: c.leg });
    }
  } },
    el("h3", {}, "Nueva causa"),
    el("div", { class: "filtros", style: "margin:0" },
      el("input", { type: "search", name: "nombre", placeholder: "Nombre (p. ej. Alquiler asequible)" }),
      el("input", { type: "search", name: "q", placeholder: "Texto en título, resumen o etiquetas" }),
      multiSelect("tema", optTemas(), "", "Cualquier tema", "temas"),
      el("input", { type: "search", name: "etiqueta", placeholder: "Etiqueta exacta (p. ej. alquiler)", list: "lista-etiquetas" }),
      multiSelect("leg", optLegs(), "", "Todas las legislaturas", "legislaturas"),
      el("button", { class: "boton", type: "submit" }, "Crear")),
    el("datalist", { id: "lista-etiquetas" }, API.etiquetas({}).etiquetas.map((e) => el("option", { value: e.etiqueta }))));
  cont.append(form);
  if (causas.length) {
    cont.append(el("div", { class: "lista", style: "margin-top:16px" }, causas.map((c) => {
      const d = API.causa(c);
      const nuevas = c.ultimaVisita ? d.votaciones.filter((v) => v.fecha > c.ultimaVisita).length : null;
      const marcadas = Object.keys(c.marcas || {}).length;
      return el("article", { class: "fila", style: "grid-template-columns:minmax(0,1fr) 220px", onclick: () => irA("causa", { c: c.id }) },
        el("div", {}, el("div", { class: "titulo" }, c.nombre), el("div", { class: "detalle" }, criteriosTexto(c)),
          el("div", { class: "badges" }, el("span", { class: "badge" }, `${fmt(d.asuntos.length)} asuntos`), el("span", { class: "badge" }, `${fmt(d.votaciones.length)} votaciones`),
            nuevas ? el("span", { class: "badge ok" }, `${nuevas} nuevas desde tu última visita`) : null,
            marcadas ? el("span", { class: "badge" }, `scorecard: ${marcadas} votaciones marcadas`) : null)),
        el("div", { class: "small muted" }, `Creada el ${fecha(c.creada)}`, c.ultimaVisita ? el("div", {}, `Última visita: ${fecha(c.ultimaVisita)}`) : null));
    })));
  } else {
    const sugeridas = API.etiquetas({}).etiquetas.slice(0, 16);
    cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Ideas para empezar"),
      el("p", { class: "small muted" }, "Abre una de las etiquetas más frecuentes como causa sin guardarla."),
      el("div", { class: "chips" }, sugeridas.map((e) => el("a", { class: "chip", href: "#/causa?" + new URLSearchParams({ etiqueta: e.etiqueta }) }, `#${e.etiqueta}`, el("span", { class: "muted" }, ` ${e.n}`))))));
  }
  return cont;
};

VISTAS.causa = async (q) => {
  const causas = leerCausas();
  let causa = q.c ? causas.find((c) => c.id === q.c) : null;
  const guardada = Boolean(causa);
  if (!causa) causa = { id: null, nombre: q.q || (q.etiqueta ? `#${q.etiqueta}` : lista(q.tema).map(temaNombre).join(" + ")) || "Causa", q: q.q, tema: q.tema, etiqueta: q.etiqueta, leg: q.leg, marcas: {} };
  const d = await api("causa", causa);
  const anterior = causa.ultimaVisita;
  if (guardada) { causa.ultimaVisita = hoyISO(); guardarCausas(causas); }
  const marcas = causa.marcas || (causa.marcas = {});
  const guardarMarcas = () => { if (guardada) guardarCausas(causas); };

  const cont = el("div", {}, subnav(NAV_ACTIVISMO, "causas", q),
    el("p", { class: "small", style: "margin:0" }, el("a", { href: "#/causas" }, "← Mis causas")),
    el("h2", {}, causa.nombre),
    el("p", { class: "sub" }, criteriosTexto(causa), guardada ? "" : " · sin guardar"),
    el("div", { class: "filtros" },
      guardada ? null : el("button", { class: "boton", onclick: () => {
        const c = { ...causa, id: String(Date.now()), creada: hoyISO(), ultimaVisita: hoyISO() };
        causas.push(c);
        if (guardarCausas(causas)) irA("causa", { c: c.id }); else alert("Este navegador no permite guardar datos locales.");
      } }, "Guardar causa"),
      guardada ? el("button", { class: "boton", onclick: () => {
        if (!confirm(`¿Borrar la causa «${causa.nombre}» y su scorecard?`)) return;
        guardarCausas(causas.filter((c) => c.id !== causa.id));
        irA("causas", {});
      } }, "Borrar causa") : null,
      el("button", { class: "boton", onclick: () => exportarCausaCSV(causa, d) }, "⬇ Votaciones en CSV"),
      el("button", { class: "boton", onclick: () => exportarScorecardCSV(causa, d) }, "⬇ Scorecard en CSV")));

  if (!d.asuntos.length) { cont.append(el("div", { class: "vacio" }, "Ningún asunto votado coincide con estos criterios.")); return cont; }
  const sale = d.asuntos.filter((x) => SALE_RES.has(x.resultado_final)).length;
  const nuevas = anterior ? d.votaciones.filter((v) => v.fecha > anterior) : [];
  cont.append(el("div", { class: "grid g4" },
    stat("Asuntos votados", fmt(d.asuntos.length), `${pct(sale, d.asuntos.length)}% salen adelante`),
    stat("Votaciones decisivas", fmt(d.votaciones.length), d.votaciones.length === 400 ? "se muestran las 400 más recientes" : "nominales"),
    stat("Novedades", anterior ? fmt(nuevas.length) : "—", anterior ? `desde tu última visita (${fecha(anterior)})` : "primera visita"),
    stat("Scorecard", fmt(Object.keys(marcas).length), "votaciones marcadas por ti")));

  // Scorecard por grupo.
  const marcadas = d.votaciones.filter((v) => marcas[v.id]).map((v) => ({ id: v.id, favorable: marcas[v.id] }));
  const pGrupo = new Map();
  for (const m of marcadas) for (const [s, c] of Object.entries(d.celdas[m.id] || {})) {
    const o = pGrupo.get(s) || { s, bien: 0, mal: 0, otro: 0 };
    if (c.apoyo === m.favorable) o.bien++; else if (c.apoyo === "si" || c.apoyo === "no") o.mal++; else o.otro++;
    pGrupo.set(s, o);
  }
  const score = (o) => (o.bien + o.mal + (o.otro || 0) + (o.abst || 0) ? Math.round((100 * o.bien) / (o.bien + o.mal + (o.otro || 0) + (o.abst || 0))) : 0);
  const cardScore = el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Scorecard"),
    el("p", { class: "small muted" }, "Marca en la tabla de abajo, votación a votación, cuál era el voto favorable para tu causa. La puntuación es el porcentaje de esas votaciones en que el grupo o diputado votó como tú marcaste (abstenerse o dividirse cuenta como no coincidir). Refleja tu criterio, no una valoración de esta web."),
    marcadas.length ? null : el("p", { class: "muted" }, "Todavía no has marcado ninguna votación."));
  if (marcadas.length) {
    const gruposScore = [...pGrupo.values()].sort((a, b) => score(b) - score(a));
    cardScore.append(el("div", { class: "legend" }, el("span", {}, el("i", { style: "background:var(--si)" }), "Como tu causa"), el("span", {}, el("i", { style: "background:var(--abs)" }), "Abstención o dividido"), el("span", {}, el("i", { style: "background:var(--no)" }), "En contra de tu causa")),
      barrasH(gruposScore.map((o) => ({ label: o.s, color: colorSiglas(o.s), valorTexto: `${score(o)}%`,
        segs: [{ v: o.bien, color: "var(--si)", nombre: "como tu causa" }, { v: o.otro, color: "var(--abs)", nombre: "abstención o dividido" }, { v: o.mal, color: "var(--no)", nombre: "en contra de tu causa" }],
        tip: (s) => `${s.v} de ${o.bien + o.mal + o.otro} votaciones marcadas` })), { segs: true, normalizar: true }));
    const dips = [...puntuacionDiputados(marcadas).values()].filter((o) => o.bien + o.mal + o.abst > 0);
    const orden = (xs) => xs.sort((a, b) => score(b) - score(a) || b.bien - a.bien);
    const tabla = (xs) => el("table", { class: "tabla" }, el("tbody", {}, xs.map((o) => el("tr", { class: "clic", onclick: () => abrir(`d:${o.id}`) },
      el("td", {}, o.nombre), el("td", { class: "small" }, o.grupo ? [swatch(grupo(o.leg, o.grupo).color), siglas(o.leg, o.grupo)] : ""),
      el("td", { class: "num" }, `${score(o)}%`), el("td", { class: "small muted" }, `${o.bien}/${o.bien + o.mal + o.abst}${o.ausente ? ` · ${o.ausente} sin votar` : ""}`)))));
    cardScore.append(el("div", { class: "grid g2", style: "margin-top:12px" },
      el("div", {}, el("h3", {}, "Diputados que más votaron como tu causa"), tabla(orden(dips.slice()).slice(0, 15))),
      el("div", {}, el("h3", {}, "Diputados que menos"), tabla(orden(dips.slice()).reverse().slice(0, 15)))));
  }
  cont.append(cardScore);

  // Novedades y matriz con marcas.
  const columnas = [...sumarPor(Object.values(d.celdas).flatMap((cs) => Object.values(cs).map((c) => ({ siglas: c.siglas, si: 0, no: 0, abst: 0, div: 0, n: 1 }))), (r) => r.siglas).values()]
    .sort((a, b) => b.n - a.n).map((o) => o.siglas).slice(0, 14);
  const pagina = Math.max(1, +(q.pagina || 1));
  const tamPag = 30;
  const vista = { votaciones: d.votaciones.slice((pagina - 1) * tamPag, pagina * tamPag), celdas: d.celdas };
  cont.append(el("div", { class: "card", style: "margin-top:16px" },
    el("div", { style: "display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap" },
      el("h3", {}, "Votación a votación"),
      el("div", { class: "small" },
        el("button", { class: "boton", onclick: () => { for (const v of vista.votaciones) marcas[v.id] = "si"; guardarMarcas(); estadoRuta.clave = ""; render(); } }, "Marcar las de esta página «a favor»"), " ",
        el("button", { class: "boton", onclick: () => { if (confirm("¿Quitar todas las marcas del scorecard?")) { causa.marcas = {}; guardarMarcas(); estadoRuta.clave = ""; render(); } } }, "Quitar marcas"))),
    nuevas.length ? el("p", { class: "small" }, el("span", { class: "badge ok" }, `${nuevas.length} nuevas`), " desde tu última visita: ", nuevas.slice(0, 5).map((v) => `${fecha(v.fecha)} ${tituloCorto(v.titulo || v.texto_expediente, 70)}`).join(" · ")) : null,
    el("p", { class: "small muted" }, "✓ a favor de la iniciativa, ✗ en contra, ~ abstención, ± grupo dividido. En «Voto favorable» indica qué habría querido tu causa."),
    matrizVotos(vista, columnas, { marcas, alMarcar: (id, valor) => { if (valor) marcas[id] = valor; else delete marcas[id]; guardarMarcas(); estadoRuta.clave = ""; render(); } }),
    paginacion(d.votaciones.length, pagina, tamPag, (p) => irA("causa", { ...q, pagina: p }))));
  return cont;
};

function exportarCausaCSV(causa, d) {
  const cols = todasSiglas().filter((s) => d.votaciones.some((v) => (d.celdas[v.id] || {})[s]));
  const t = { si: "a favor", no: "en contra", abstencion: "abstención", dividido: "dividido" };
  descargarCSV(`causa-${(causa.nombre || "causa").replace(/[^\p{L}\p{N}]+/gu, "-")}-${hoyISO()}.csv`,
    ["id", "fecha", "legislatura", "titulo", "tipo_votacion", "resultado", "a_favor", "en_contra", "abstenciones", "voto_favorable_marcado", ...cols.map((s) => `posicion_${s}`)],
    d.votaciones.map((v) => [v.id, v.fecha, romano(v.legislatura), (v.titulo && !v.sintetica ? v.titulo : v.texto_expediente || "").split("\n")[0],
      META.tipos_votacion[v.tipo_votacion], v.resultado, v.a_favor, v.en_contra, v.abstenciones, (causa.marcas || {})[v.id] ? t[causa.marcas[v.id]] : "",
      ...cols.map((s) => { const c = (d.celdas[v.id] || {})[s]; return c ? t[c.apoyo] || "" : ""; })]));
}

function exportarScorecardCSV(causa, d) {
  const marcadas = d.votaciones.filter((v) => (causa.marcas || {})[v.id]).map((v) => ({ id: v.id, favorable: causa.marcas[v.id] }));
  if (!marcadas.length) { alert("Marca primero alguna votación con su voto favorable."); return; }
  const dips = [...puntuacionDiputados(marcadas).values()];
  descargarCSV(`scorecard-${(causa.nombre || "causa").replace(/[^\p{L}\p{N}]+/gu, "-")}-${hoyISO()}.csv`,
    ["diputado", "grupo", "legislatura", "como_la_causa", "en_contra", "abstenciones", "sin_votar", "puntuacion"],
    dips.map((o) => [o.nombre, o.grupo ? siglas(o.leg, o.grupo) : "", romano(o.leg), o.bien, o.mal, o.abst, o.ausente,
      o.bien + o.mal + o.abst ? Math.round((100 * o.bien) / (o.bien + o.mal + o.abst)) : ""]));
}

// ------------------------------------------------------------------ qué viene

API.viene = (p) => {
  const w = ["1=1"], a = [];
  condTema(w, a, p.tema);
  const fases = lista(p.fase);
  if (fases.length) { w.push(`(${fases.map(() => "e.fase LIKE ?").join(" OR ")})`); a.push(...fases.map((f) => `%${f}%`)); }
  condIn(w, a, "e.grupo_autor", p.autor);
  for (const palabra of (p.q || "").split(/\s+/).filter(Boolean)) {
    w.push("(e.titulo LIKE ? OR f.resumen LIKE ? OR f.etiquetas LIKE ?)"); a.push(...Array(3).fill(`%${palabra}%`));
  }
  // prometen: partidos con un compromiso de su programa en la dirección de la iniciativa.
  return { filas: q(`SELECT e.*, f.resumen, f.tema_principal, f.etiquetas, pi.prometen FROM en_tramite e
    LEFT JOIN ficha_llm f ON f.legislatura=e.legislatura AND f.expediente=e.expediente
    LEFT JOIN programa_iniciativa pi ON pi.legislatura=e.legislatura AND pi.expediente=e.expediente WHERE ${w.join(" AND ")}`, a) };
};

VISTAS.viene = async (q) => {
  // Las fases y los plazos solo los publican los datos abiertos del Congreso.
  if (!META.cuerpos.includes("congreso")) {
    return el("div", {}, subnav(NAV_ACTIVISMO, "viene", q), el("h2", {}, "Qué viene"),
      el("div", { class: "vacio" }, "Esta sección usa las fases y los plazos de tramitación que publica el Congreso, y el Congreso no está en el ámbito elegido. ",
        el("button", { class: "boton", onclick: () => irAmbito(compactarAmbito(new Set([...AMBITO.cuerpos, "congreso"]))) }, "Añadir el Congreso")));
  }
  const d = await api("viene", q);
  const hoy = hoyISO();
  const dias = (f) => Math.round((new Date(f) - new Date(hoy)) / 86400000);
  const fases = [...new Set(API.viene({}).filas.flatMap((e) => (e.fase || "").split(" + ")).filter(Boolean))].sort();
  const autores = [...new Set(API.viene({}).filas.map((e) => e.grupo_autor).filter(Boolean))];
  const legActual = META.legislaturas.filter((l) => l.cuerpo === "congreso").at(-1).id;
  const cont = el("div", {}, subnav(NAV_ACTIVISMO, "viene", q),
    el("h2", {}, "Qué viene"),
    el("p", { class: "sub" }, `Proyectos y proposiciones de ley que siguen abiertos en la Leg. ${romano(legActual)}, con su fase y sus plazos según los datos abiertos del Congreso (datos del ${fecha(META.totales.generado.slice(0, 10))}; se actualizan con python -m escrutinio iniciativas y web). Los plazos de enmiendas son las ventanas para hacer llegar propuestas a los grupos.`),
    formFiltros([
      el("input", { type: "search", name: "q", value: q.q || "", placeholder: "Buscar en títulos, resúmenes y etiquetas" }),
      multiSelect("tema", optTemas(), q.tema, "Cualquier tema", "temas"),
      multiSelect("fase", fases.map((f) => [f, f]), q.fase, "Cualquier fase", "fases"),
      multiSelect("autor", autores.map((c) => [c, siglas(legActual, c)]), q.autor, "Cualquier proponente", "proponentes"),
    ], q, (f) => irA("viene", f)));

  const recientes = d.filas.filter((e) => e.plazo_hasta && e.plazo_hasta >= hoy && e.ampliaciones <= 2 && /enmiendas/i.test(e.plazo_tipo || ""));
  const enmiendas = d.filas.filter((e) => /enmiendas/i.test(e.fase || ""));
  const toma = d.filas.filter((e) => /toma en consideraci|contestaci/i.test(e.fase || ""));
  const congeladas = d.filas.filter((e) => e.ampliaciones >= 10);
  cont.append(el("div", { class: "grid g4" },
    stat("Iniciativas abiertas", fmt(d.filas.length), "con estos filtros"),
    stat("Recién abiertas a enmiendas", fmt(recientes.length), "plazo en curso, dos ampliaciones como mucho"),
    stat("Esperan el debate en el Pleno", fmt(toma.length), "toma en consideración pendiente"),
    stat("Plazo ampliado 10 veces o más", fmt(congeladas.length), `de ${fmt(enmiendas.length)} en fase de enmiendas`)));

  // Se abre la ficha si ya tuvo votaciones o si está en algún programa (para ver qué prometía cada partido).
  const fila = (e, extra) => el("tr", { class: e.votada || e.prometen ? "clic" : "", onclick: e.votada || e.prometen ? () => abrir(`i:${e.legislatura}:${e.expediente}`) : null },
    el("td", {}, el("div", { title: e.titulo }, tituloCorto(e.titulo, 150)), e.resumen ? el("div", { class: "small muted" }, e.resumen) : null,
      el("div", { class: "badges" }, e.tema_principal ? el("span", { class: "badge ia" }, temaNombre(e.tema_principal)) : null,
        el("span", { class: "badge" }, e.grupo_autor ? siglas(e.legislatura, e.grupo_autor) : e.autor || "—"),
        e.votada ? el("span", { class: "badge" }, "ya tuvo votaciones en el Pleno") : null,
        e.prometen ? el("span", { class: "badge", title: "Llevaban en su programa electoral un compromiso en la dirección de esta iniciativa. Clic para ver cuál." },
          `En la línea ${lista(e.prometen).length > 1 ? "de los programas" : "del programa"} de ${textoPartidos(e.prometen)}`) : null,
        e.bocg ? el("a", { class: "badge", href: e.bocg.split("\n")[0], target: "_blank", rel: "noopener", onclick: (ev) => ev.stopPropagation() }, "BOCG") : null)),
    el("td", { class: "small" }, e.fase || "—", el("div", { class: "muted" }, e.organo || "")),
    el("td", { class: "small", style: "white-space:nowrap" }, extra(e)));
  const plazoTxt = (e) => (e.plazo_hasta ? [fecha(e.plazo_hasta), el("div", { class: "muted" }, `${e.plazo_tipo || ""}${e.plazo_hasta >= hoy ? ` · quedan ${dias(e.plazo_hasta)} días` : ""}`)] : "—");

  cont.append(el("div", { class: "card" }, el("h3", {}, "Recién abiertas a enmiendas"),
    el("p", { class: "small muted" }, "Iniciativas cuyo plazo de enmiendas está en curso y apenas se ha ampliado: es cuando los grupos preparan sus enmiendas y cuando más sentido tiene hacerles llegar propuestas."),
    recientes.length ? el("table", { class: "tabla" }, el("tbody", {}, recientes.sort((a, b) => a.plazo_hasta.localeCompare(b.plazo_hasta)).map((e) => fila(e, plazoTxt)))) :
      el("p", { class: "muted" }, "Ninguna con estos filtros.")));
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Esperan el debate de toma en consideración"),
    el("p", { class: "small muted" }, "Proposiciones de ley presentadas que el Pleno aún no ha debatido. Cada semana la Junta de Portavoces decide cuáles entran en el orden del día; el Gobierno tiene un plazo para dar su criterio."),
    toma.length ? el("table", { class: "tabla" }, el("tbody", {}, toma.sort((a, b) => (b.fecha_presentacion || "").localeCompare(a.fecha_presentacion || "")).slice(0, 40)
      .map((e) => fila(e, (x) => [`presentada el ${fecha(x.fecha_presentacion)}`, x.plazo_hasta ? el("div", { class: "muted" }, `${x.plazo_tipo}: ${fecha(x.plazo_hasta)}`) : null])))) :
      el("p", { class: "muted" }, "Ninguna con estos filtros.")));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Paradas en comisión"),
    el("p", { class: "small muted" }, "Iniciativas cuyo plazo de enmiendas se ha ampliado más veces. La Mesa lo amplía semana a semana mientras no hay acuerdo para seguir, así que muchas ampliaciones suelen indicar que la iniciativa está parada."),
    el("table", { class: "tabla" }, el("tbody", {}, d.filas.filter((e) => e.ampliaciones > 0).sort((a, b) => b.ampliaciones - a.ampliaciones).slice(0, 25)
      .map((e) => fila(e, (x) => [`${x.ampliaciones} ampliaciones`, el("div", { class: "muted" }, `desde ${fecha(x.primer_plazo)}`)]))))));

  const porTema = new Map();
  for (const e of d.filas) porTema.set(e.tema_principal || "?", (porTema.get(e.tema_principal || "?") || 0) + 1);
  cont.append(el("div", { class: "grid g2", style: "margin-top:16px" },
    el("div", { class: "card" }, el("h3", {}, "Abiertas por tema"),
      barrasH([...porTema.entries()].sort((a, b) => b[1] - a[1]).map(([t, n]) => ({ label: t === "?" ? "Sin clasificar" : temaNombre(t), v: n, onclick: () => irA("viene", { ...q, tema: t === "?" ? "" : t }) })))),
    el("div", { class: "card" }, el("h3", {}, "Abiertas por fase"),
      barrasH(fases.map((f) => [f, d.filas.filter((e) => (e.fase || "").split(" + ").includes(f)).length]).filter(([, n]) => n).sort((a, b) => b[1] - a[1]).map(([f, n]) => ({ label: f, v: n, onclick: () => irA("viene", { ...q, fase: f }) }))))));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, `Todas (${d.filas.length})`),
    el("p", { class: "small" }, el("button", { class: "boton", onclick: () => descargarCSV(`en-tramite-${hoy}.csv`,
      ["expediente", "titulo", "autor", "tema", "fase", "organo", "plazo_hasta", "plazo_tipo", "ampliaciones", "presentada", "bocg"],
      d.filas.map((e) => [e.expediente, e.titulo, e.autor, e.tema_principal ? temaNombre(e.tema_principal) : "", e.fase, e.organo, e.plazo_hasta, e.plazo_tipo, e.ampliaciones, e.fecha_presentacion, (e.bocg || "").split("\n")[0]])) }, "⬇ Exportar a CSV")),
    el("table", { class: "tabla" }, el("tbody", {}, d.filas.sort((a, b) => (b.fecha_presentacion || "").localeCompare(a.fecha_presentacion || "")).map((e) => fila(e, (x) => [fecha(x.fecha_presentacion), el("div", { class: "muted" }, "presentada")]))))));
  return cont;
};
