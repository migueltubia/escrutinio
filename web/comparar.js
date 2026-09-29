"use strict";
// Comparar grupos: cómo votan dos o más grupos los mismos asuntos, tema a tema y legislatura a
// legislatura, separando lo que presenta cada uno (que casi siempre apoya) de lo que presentan los
// demás. Cuenta asuntos, no votaciones (tabla peso de app.js). Usa las utilidades de app.js.

const APOYO_TEXTO = { si: ["✓", "a favor"], no: ["✗", "en contra"], abstencion: ["~", "abstención"], dividido: ["±", "dividido"] };
const CAMPOS_APOYO = { si: "si", no: "no", abstencion: "abst", dividido: "div" };
const FAMILIA_UNA = { ley: "Ley", decreto_ley: "Decreto-ley", pnl: "PNL", mocion: "Moción", internacional: "Convenio internacional",
  organizacion: "Organización", control: "Control", otro: null };

API.comparar = (p) => {
  const gs = lista(p.g);
  if (gs.length < 2) return { unidades: [] };
  const [w, a] = filtrosAsunto(p);
  const desde = `FROM votacion v
    JOIN peso pe ON pe.votacion_id=v.id
    JOIN iniciativa i ON i.legislatura=v.legislatura AND i.expediente=v.expediente
    JOIN ficha_llm f ON f.legislatura=i.legislatura AND f.expediente=i.expediente
    LEFT JOIN tipo_expediente te ON te.prefijo=i.prefijo`;
  // En los debates con propuestas de resolución, lo votado es de un grupo, no del autor del asunto.
  const votaciones = q(`SELECT v.id, v.legislatura, v.expediente, ${SQL_PROPONE} AS propone, pe.peso, v.fecha,
      v.tipo_votacion, v.texto_expediente, i.titulo, i.sintetica, i.resultado_final, te.familia, f.tema_principal AS tema,
      f.etiquetas, i.grupo_autor AS autor
    ${desde} WHERE ${w}`, a);
  const posiciones = q(`SELECT v.id, gr.siglas, ${SQL_APOYO} AS apoyo ${desde}
    JOIN voto_grupo g ON g.votacion_id=v.id
    JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.codigo=g.grupo
    WHERE g.grupo<>'?' AND g.sentido IS NOT NULL AND gr.siglas IN (${gs.map(() => "?").join(",")}) AND ${w}`, [...gs, ...a]);

  // Unidad: el asunto (o, en los debates, las propuestas de un grupo), con sus votaciones decisivas.
  const unidades = new Map(), porId = new Map();
  for (const v of votaciones) {
    const clave = `${v.legislatura}|${v.expediente}|${v.propone}`;
    let u = unidades.get(clave);
    if (!u) {
      u = { clave, leg: v.legislatura, exp: v.expediente, propone: v.propone, tema: v.tema, familia: v.familia,
        autor: v.autor, resultado: v.resultado_final, etiquetas: jsonDe(v.etiquetas, []), fecha: v.fecha, votaciones: [],
        titulo: v.titulo && !v.sintetica ? v.titulo : (v.texto_expediente || "").split("\n")[0], tipos: new Set(), pos: {} };
      unidades.set(clave, u);
    }
    u.votaciones.push({ id: v.id, peso: v.peso });
    u.tipos.add(v.tipo_votacion);
    if (v.fecha > u.fecha) u.fecha = v.fecha;
    porId.set(v.id, u);
  }
  for (const r of posiciones) {
    const u = porId.get(r.id);
    if (!u || !CAMPOS_APOYO[r.apoyo]) continue;
    (u.pos[r.siglas] = u.pos[r.siglas] || {})[r.id] = r.apoyo;
  }
  return { unidades: [...unidades.values()].filter((u) => Object.keys(u.pos).length) };
};

// ---- cálculos sobre las unidades ----

// Voto de un grupo en una unidad: fracciones del asunto (suman lo que votó, 1 si votó en todo).
function apoyoEn(u, g) {
  const o = { si: 0, no: 0, abst: 0, div: 0, n: 0 };
  for (const { id, peso } of u.votaciones) {
    const a = (u.pos[g] || {})[id];
    if (!a) continue;
    o[CAMPOS_APOYO[a]] += peso;
    o.n += peso;
  }
  return o;
}
function sumar(unidades, g) {
  const t = { si: 0, no: 0, abst: 0, div: 0, n: 0, asuntos: 0 };
  for (const u of unidades) {
    const o = apoyoEn(u, g);
    if (!o.n) continue;
    for (const c of ["si", "no", "abst", "div", "n"]) t[c] += o[c];
    t.asuntos++;
  }
  return t;
}
const autorSiglas = (u) => (u.propone ? grupo(u.leg, u.propone).siglas : u.autor ? grupo(u.leg, u.autor).siglas : "Sin autor");
const esDeGrupo = (u) => {
  const codigo = u.propone || u.autor;
  return !!codigo && (META.grupos[u.leg] || []).some((x) => x.codigo === codigo && x.codigo !== "?");
};
// Qué es la unidad para el grupo g: lo presenta él, el Gobierno, otro grupo u otro autor.
function relacion(u, g) {
  const s = autorSiglas(u);
  if (s === g) return "propio";
  if (s === "Gobierno") return "gobierno";
  return esDeGrupo(u) ? "otro_grupo" : "otro";
}
// Coincidencia entre dos grupos en una unidad: parte del asunto en que votaron lo mismo, de lo que votaron ambos.
function coincidencia(u, a, b) {
  let igual = 0, ambos = 0;
  for (const { id, peso } of u.votaciones) {
    const x = (u.pos[a] || {})[id], y = (u.pos[b] || {})[id];
    if (!x || !y) continue;
    ambos += peso;
    if (x === y) igual += peso;
  }
  return ambos ? igual / ambos : null;
}
// ¿Votaron todos lo mismo? true / false / «parte», o null si no hay al menos dos grupos con voto.
function acuerdo(u, gs) {
  const fr = [];
  for (let i = 0; i < gs.length; i++) for (let j = i + 1; j < gs.length; j++) {
    const c = coincidencia(u, gs[i], gs[j]);
    if (c !== null) fr.push(c);
  }
  if (!fr.length) return null;
  if (fr.every((c) => c > 0.999)) return true;
  if (fr.every((c) => c < 0.001)) return false;
  return "parte";
}
const pctDe = (o) => (o && o.n ? Math.round((100 * o.si) / o.n) : null);

// ---- piezas ----

// Dos o más valores por fila sobre una escala de 0 a 100 (un punto por grupo, unidos por una línea).
function pesas(filas, gs, valor, { extra = null, cabeceraExtra = "", alClicar = null, minimo = 3 } = {}) {
  const cont = el("div", { class: "pesas" },
    el("div", { class: "pesas-fila pesas-eje" }, el("span"),
      el("div", { class: "pesas-escala" }, el("span", {}, "0%"), el("span", {}, "50%"), el("span", {}, "100%")),
      el("span", { class: "small muted" }, cabeceraExtra)));
  for (const f of filas) {
    const puntos = gs.map((g) => ({ g, x: valor(f, g) })).filter((d) => d.x && d.x.n);
    const validos = puntos.filter((d) => d.x.n >= minimo).map((d) => (100 * d.x.si) / d.x.n);
    const pista = el("div", { class: "pesas-pista" });
    if (validos.length > 1) {
      const lo = Math.min(...validos), hi = Math.max(...validos);
      pista.append(el("span", { class: "pesas-linea", style: `left:${lo}%;width:${hi - lo}%` }));
    }
    for (const { g, x } of puntos) {
      const p = (100 * x.si) / x.n;
      const pocos = x.n < minimo;
      pista.append(conTip(el("span", { class: "pesas-punto" + (pocos ? " pocos" : ""), tabindex: 0,
        style: `left:${p}%;${pocos ? `border-color:${colorSiglas(g)}` : `background:${colorSiglas(g)}`}` }),
        `${Math.round(p)}% a favor`, `${g} · ${f.label}`,
        `${fmtAs(x.si)} de ${fmtAs(x.n)} asuntos${pocos ? " · pocos casos: tómalo con cautela" : ""}`));
    }
    cont.append(el("div", { class: "pesas-fila" + (alClicar ? " clic" : ""), onclick: alClicar ? () => alClicar(f) : null },
      el("div", { class: "small pesas-label", title: [f.label, f.sub].filter(Boolean).join(" · ") }, f.label,
        f.sub ? el("div", { class: "pesas-sub" }, f.sub) : null), pista,
      el("div", { class: "small" }, extra ? extra(f) : "")));
  }
  return cont;
}
const leyendaGrupos = (gs) => el("div", { class: "legend" }, gs.map((g) => el("span", {}, el("i", { style: `background:${colorSiglas(g)}` }), g)),
  el("span", {}, el("i", { class: "hueco" }), "menos de 3 asuntos"));

// Barra de un porcentaje con su texto.
const barraPct = (p, color) => el("div", { class: "cmp-barra" },
  el("div", { class: "cmp-pista" }, el("div", { style: `width:${p ?? 0}%;background:${color}` })),
  el("b", {}, p === null ? "—" : `${p}%`));

// Posición de un grupo en una unidad: el signo si fue una votación; si fueron varias, cuántas de cada.
function chipPosicion(u, g) {
  const votos = u.votaciones.map((v) => (u.pos[g] || {})[v.id]).filter(Boolean);
  const info = el("span", { class: "sw", style: `background:${colorSiglas(g)}` });
  if (!votos.length) return conTip(el("span", { class: "chip", tabindex: 0 }, info, g, el("span", { class: "s muted" }, "—")), `${g}: no consta su voto`, null);
  const cuenta = {};
  for (const a of votos) cuenta[a] = (cuenta[a] || 0) + 1;
  const orden = ["si", "abstencion", "dividido", "no"].filter((a) => cuenta[a]);
  const texto = votos.length === 1 ? [el("span", { class: `s ${votos[0]}` }, APOYO_TEXTO[votos[0]][0])]
    : orden.map((a) => el("span", { class: `s ${a}` }, `${APOYO_TEXTO[a][0]}${cuenta[a]}`));
  const detalle = votos.length === 1 ? APOYO_TEXTO[votos[0]][1]
    : orden.map((a) => `${APOYO_TEXTO[a][1]} en ${cuenta[a]}`).join(", ") + ` (de ${u.votaciones.length} votaciones)`;
  return conTip(el("span", { class: "chip", tabindex: 0 }, info, g, ...texto), `${g}: ${detalle}`,
    [...u.tipos].includes("totalidad") ? "Enmienda a la totalidad: votar sí a la devolución es votar contra el proyecto" : null);
}

function filaUnidad(u, gs) {
  const titulo = u.titulo + (u.propone ? ` · propuestas de ${autorSiglas(u)}` : "");
  const abrirla = () => abrir(u.votaciones.length === 1 ? `v:${u.votaciones[0].id}` : `i:${u.leg}:${u.exp}`);
  return el("article", { class: "fila cmp-fila", tabindex: 0, onclick: abrirla, onkeydown: (e) => e.key === "Enter" && abrirla() },
    el("div", {}, el("div", { class: "fecha" }, fecha(u.fecha)), el("div", { class: "muted small" }, legTexto(u.leg))),
    el("div", {},
      el("div", { class: "titulo", title: titulo }, tituloCorto(titulo, esMovil() ? 110 : 160)),
      el("div", { class: "detalle" }, [FAMILIA_UNA[u.familia],
        `presenta ${autorSiglas(u) === "Sin autor" ? "—" : grupo(u.leg, u.propone || u.autor).nombre}`,
        u.votaciones.length > 1 ? `${u.votaciones.length} votaciones` : null, u.tema ? temaNombre(u.tema) : null].filter(Boolean).join(" · ")),
      el("div", { class: "badges" }, badgeResultado(u.resultado))),
    el("div", { class: "chips" }, gs.map((g) => chipPosicion(u, g))));
}

// ---- vista ----

VISTAS.comparar = async (q) => {
  const legsElegidas = lista(q.leg).map(Number);
  const disponibles = gruposDeLegs(legsElegidas.length ? legsElegidas : META.legislaturas.map((l) => l.id)).map((g) => g.siglas);
  const gs = lista(q.g).length ? lista(q.g) : disponibles.slice(0, 2);
  const temas = lista(q.tema);
  const d = await api("comparar", { ...q, g: gs.join(",") });
  const base = Object.fromEntries(Object.entries({ g: gs.join(","), tema: q.tema, leg: q.leg, familia: q.familia, sec: q.sec }).filter(([, v]) => v));
  const cont = el("div", {}, subnav(NAV_COMPARAR, "comparar", q),
    el("h2", {}, "Comparar grupos"),
    el("p", { class: "sub" }, "Cómo votan dos o más grupos los mismos asuntos, tema a tema, separando lo que presenta cada uno (que casi siempre apoya) de lo que presentan los demás. Elige los grupos, los temas y las legislaturas."),
    formFiltros([
      multiSelect("g", todasSiglas().map((s) => [s, s]), gs.join(","), "Grupos", "grupos"),
      multiSelect("tema", optTemas(), q.tema, "Todos los temas", "temas"),
      multiSelect("leg", optLegs(), q.leg, "Todas las legislaturas", "legislaturas"),
      multiSelect("familia", optFamiliasAnalisis(), q.familia, "Todo tipo de asunto", "categorías"),
      temas.length ? el("label", { class: "check" }, el("input", { type: "checkbox", name: "sec", checked: q.sec === "1" }), "Contar también si es tema secundario") : null,
      q.etiqueta ? el("input", { type: "hidden", name: "etiqueta", value: q.etiqueta }) : null,
      q.etiqueta ? el("a", { class: "chip", href: "#/comparar?" + new URLSearchParams(base) }, `#${q.etiqueta} ✕`) : null,
    ], q, (f) => irA("comparar", f)));

  if (gs.length < 2) {
    cont.append(el("div", { class: "vacio" }, "Elige al menos dos grupos."));
    return cont;
  }
  const us = d.unidades;
  if (!us.length) {
    cont.append(el("div", { class: "vacio" }, "Estos grupos no tienen votaciones decisivas en común con estos filtros."));
    return cont;
  }
  const contexto = [temas.length ? textoTemas(temas) : "todos los temas", lista(q.leg).length ? textoLegs(lista(q.leg).map(Number)) : "todas las legislaturas"].join(" · ");
  const [A, B] = gs;

  // 1. La respuesta corta: en cuántos asuntos votaron lo mismo.
  const estados = us.map((u) => acuerdo(u, gs)).filter((x) => x !== null);
  const igual = estados.filter((x) => x === true).length, distinto = estados.filter((x) => x === false).length, parte = estados.length - igual - distinto;
  const frase = gs.length === 2 ? `${A} y ${B} votaron lo mismo en ${fmt(igual)} de ${fmt(estados.length)} asuntos (${pct(igual, estados.length)}%)`
    : `Los ${gs.length} grupos votaron lo mismo en ${fmt(igual)} de ${fmt(estados.length)} asuntos (${pct(igual, estados.length)}%)`;
  const segsAcuerdo = [
    { v: igual, color: "var(--seq-600)", nombre: "votaron lo mismo" },
    { v: parte, color: "var(--seq-200)", nombre: "coincidieron en unos puntos y en otros no" },
    { v: distinto, color: "var(--abs)", nombre: gs.length === 2 ? "votaron distinto" : "no votaron todos lo mismo" },
  ];
  const tarjeta = el("div", { class: "card cmp-respuesta" },
    el("p", { class: "cmp-frase" }, frase),
    el("p", { class: "small muted", style: "margin:4px 0 10px" }, `${gs.length === 2 ? `Distinto en ${fmt(distinto)}` : `No todos igual en ${fmt(distinto)}`}${parte ? ` y en parte en ${fmt(parte)} (asuntos votados por puntos)` : ""}. ${contexto[0].toUpperCase() + contexto.slice(1)}.`),
    el("div", { class: "legend" }, segsAcuerdo.map((s) => el("span", {}, el("i", { style: `background:${s.color}` }), s.nombre[0].toUpperCase() + s.nombre.slice(1)))),
    barrasH([{ label: "Asuntos", segs: segsAcuerdo, valorTexto: fmt(estados.length), tip: (s) => `${fmt(s.v)} asuntos en que ${s.nombre}` }], { segs: true, normalizar: true }));
  if (gs.length > 2) {
    tarjeta.append(el("h3", { style: "margin-top:12px" }, "Por parejas"),
      el("p", { class: "small muted" }, "Porcentaje de lo votado en común en que cada pareja votó lo mismo (cada asunto cuenta una vez)."),
      mapaCalor(gs, gs, (a, b) => {
        if (a === b) return null;
        let s = 0, n = 0;
        for (const u of us) { const c = coincidencia(u, a, b); if (c !== null) { s += c; n++; } }
        return n ? { p: s / n, n, s } : null;
      }, { minimo: 3, etiquetaFila: (s) => [swatch(colorSiglas(s)), s], tip: (a, b, x) => [`${Math.round(100 * x.p)}% igual`, `${a} y ${b}`, `${fmtAs(x.s)} de ${fmt(x.n)} asuntos`] }));
  }
  cont.append(tarjeta);

  // 2. El porcentaje que engaña: todo lo votado frente a lo que presentan otros grupos.
  const tot = Object.fromEntries(gs.map((g) => [g, sumar(us, g)]));
  const ajeno = Object.fromEntries(gs.map((g) => [g, sumar(us.filter((u) => relacion(u, g) === "otro_grupo"), g)]));
  const propios = Object.fromEntries(gs.map((g) => [g, us.filter((u) => relacion(u, g) === "propio").length]));
  const filasPct = gs.map((g) => el("div", { class: "cmp-grupo" },
    el("div", { class: "cmp-nombre" }, swatch(colorSiglas(g)), el("b", {}, g),
      el("span", { class: "small muted" }, ` presentó ${fmt(propios[g])} de los ${fmt(us.length)} asuntos (${pct(propios[g], us.length)}%)`)),
    el("div", { class: "cmp-dos" },
      el("span", { class: "small" }, "Todo lo votado"), barraPct(pctDe(tot[g]), colorSiglas(g)),
      el("span", { class: "small" }, "Lo que presentan otros grupos"), barraPct(pctDe(ajeno[g]), colorSiglas(g)))));
  let lectura = null;
  if (gs.length === 2 && tot[A].n && tot[B].n && ajeno[A].n >= 3 && ajeno[B].n >= 3) {
    const dTodo = pctDe(tot[A]) - pctDe(tot[B]), dAjeno = pctDe(ajeno[A]) - pctDe(ajeno[B]);
    const [mas, menos] = dTodo >= 0 ? [A, B] : [B, A];
    if (Math.abs(dTodo) >= 10 && Math.abs(dAjeno) <= Math.abs(dTodo) / 2) {
      lectura = `${mas} vota a favor ${Math.abs(dTodo)} puntos más que ${menos} en todo lo votado, pero ante lo que presentan otros grupos la diferencia se queda en ${Math.abs(dAjeno)}: sale sobre todo de quién presenta los asuntos (${A} presentó ${fmt(propios[A])} y ${B}, ${fmt(propios[B])}).`;
    } else {
      lectura = `Ante lo que presentan otros grupos, ${A} vota a favor en el ${pctDe(ajeno[A])}% de los asuntos y ${B}, en el ${pctDe(ajeno[B])}%`
        + (Math.abs(dAjeno) <= 3 ? ": prácticamente lo mismo." : `: ${Math.abs(dAjeno)} puntos de diferencia.`);
    }
  }
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cuánto apoya cada uno: todo o solo lo de otros"),
    el("p", { class: "small muted" }, "Porcentaje de asuntos en que el grupo votó a favor. Cada grupo apoya casi siempre lo que presenta él mismo, y el partido del Gobierno, lo que presenta el Gobierno: por eso el porcentaje de todo lo votado depende mucho de cuántos asuntos presentó cada uno. «Lo que presentan otros grupos» deja fuera lo propio y lo del Gobierno."),
    el("div", { class: "cmp-grupos" }, filasPct),
    lectura ? el("p", { class: "aviso-lectura small" }, lectura) : null));

  // 3. A quién apoya cada uno, según quién presenta el asunto.
  const porAutor = new Map();
  for (const u of us) {
    const s = autorSiglas(u);
    const k = s === "Gobierno" || esDeGrupo(u) ? s : "Otros";
    (porAutor.get(k) || porAutor.set(k, []).get(k)).push(u);
  }
  const columnasAutor = [...porAutor.entries()].filter(([k]) => k !== "Otros").sort((a, b) => b[1].length - a[1].length).slice(0, 12).map(([k]) => k);
  if (porAutor.has("Otros")) columnasAutor.push("Otros");
  const tablaAutor = mapaCalor(gs, columnasAutor, (g, s) => {
    const x = sumar(porAutor.get(s) || [], g);
    return x.n ? { p: x.si / x.n, n: x.n, x } : null;
  }, {
    minimo: 3, etiquetaFila: (s) => [swatch(colorSiglas(s)), s],
    etiquetaCol: (s) => `${s} (${porAutor.get(s).length})`,
    tip: (g, s, r) => [`${Math.round(100 * r.p)}% a favor`, `${g} ante lo que presenta ${s === "Otros" ? "otro autor (Senado, comunidades, iniciativa popular…)" : s}`, `${fmtAs(r.x.si)} de ${fmtAs(r.x.n)} asuntos`],
  });
  for (const tr of tablaAutor.querySelectorAll("tbody tr")) {
    const g = gs[[...tr.parentNode.children].indexOf(tr)];
    const i = columnasAutor.indexOf(g);
    if (i >= 0) tr.children[i + 1].classList.add("propio");
  }
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "A quién apoya cada uno"),
    el("p", { class: "small muted" }, "Filas: el grupo que vota. Columnas: quién presenta el asunto (entre paréntesis, cuántos). Porcentaje de asuntos en que votó a favor. Recuadrado, lo que presenta el propio grupo; «·», menos de 3 asuntos."),
    tablaAutor));

  // 4. Tema a tema y legislatura a legislatura, con la medida elegida.
  let medida = q.medida === "todo" ? "todo" : "ajeno";
  const cajaEvol = el("div", {});
  const pintarEvol = () => {
    const filtro = (u, g) => medida === "todo" || relacion(u, g) === "otro_grupo";
    const valorDe = (grupoUs) => (f, g) => sumar(grupoUs(f).filter((u) => filtro(u, g)), g);
    const igualEn = (xs) => {
      if (gs.length !== 2) return "";
      let s = 0, n = 0;
      for (const u of xs) { const c = coincidencia(u, A, B); if (c !== null) { s += c; n++; } }
      return n ? `${Math.round((100 * s) / n)}%` : "—";
    };
    const botones = el("div", { class: "segmentos", role: "group", "aria-label": "Qué se cuenta" },
      [["ajeno", "Lo que presentan otros grupos"], ["todo", "Todo lo votado"]].map(([k, t]) => el("button", {
        type: "button", class: "boton" + (medida === k ? " activo" : ""), "aria-pressed": String(medida === k),
        onclick: () => { medida = k; pintarEvol(); },
      }, t)));
    const nodos = [botones, leyendaGrupos(gs)];
    const porTema = new Map();
    for (const u of us) if (u.tema) (porTema.get(u.tema) || porTema.set(u.tema, []).get(u.tema)).push(u);
    if (porTema.size > 1) {
      const filas = [...porTema.entries()].filter(([, xs]) => xs.length >= 3).sort((a, b) => b[1].length - a[1].length)
        .map(([t, xs]) => ({ clave: t, label: temaNombre(t), xs }));
      nodos.push(el("h3", { style: "margin-top:12px" }, "Tema a tema"),
        el("p", { class: "small muted" }, `Un punto por grupo: porcentaje de asuntos del tema en que votó a favor (${medida === "todo" ? "todo lo votado" : "solo lo que presentan otros grupos"}). Cuanto más separados, más distinto votan.${gs.length === 2 ? " A la derecha, en qué parte de lo votado coincidieron." : ""} Clic en un tema para compararlo a fondo.`),
        pesas(filas, gs, valorDe((f) => f.xs), { extra: gs.length === 2 ? (f) => igualEn(f.xs) : null, cabeceraExtra: gs.length === 2 ? "igual" : "",
          alClicar: (f) => irA("comparar", { ...base, tema: f.clave, sec: "", medida: medida === "todo" ? "todo" : "" }) }));
    }
    const porLeg = new Map();
    for (const u of us) (porLeg.get(u.leg) || porLeg.set(u.leg, []).get(u.leg)).push(u);
    if (porLeg.size > 1) {
      const filas = [...porLeg.entries()].sort((a, b) => a[0] - b[0])
        .map(([l, xs]) => ({ clave: l, label: legTexto(l), sub: gobiernosLeg(l) && `Gob. ${gobiernosLeg(l)}`, xs }));
      nodos.push(el("h3", { style: "margin-top:16px" }, "Legislatura a legislatura"),
        el("p", { class: "small muted" }, "Lo mismo por legislatura, con quién gobernaba: sirve para ver cómo cambia un partido entre el Gobierno y la oposición (el que gobierna apoya lo que presenta el Gobierno, que aquí no cuenta como de otro grupo)."),
        pesas(filas, gs, valorDe((f) => f.xs), { extra: gs.length === 2 ? (f) => igualEn(f.xs) : null, cabeceraExtra: gs.length === 2 ? "igual" : "" }));
    }
    if (nodos.length === 2) nodos.push(el("p", { class: "small muted" }, "Elige más de un tema o de una legislatura (o ninguno) para ver la comparación tema a tema o legislatura a legislatura."));
    cajaEvol.replaceChildren(...nodos);
  };
  pintarEvol();
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, cajaEvol));

  // 5. Los asuntos, uno a uno: dónde difieren y dónde coinciden.
  const modos = gs.length === 2
    ? [["difieren", "Votaron distinto", (x) => x === false], ["parte", "En parte", (x) => x === "parte"], ["coinciden", "Votaron lo mismo", (x) => x === true], ["todos", "Todos", () => true]]
    : [["difieren", "No todos igual", (x) => x !== true], ["coinciden", "Todos igual", (x) => x === true], ["todos", "Todos", () => true]];
  let modo = modos.find(([k]) => k === q.modo) ? q.modo : "difieren";
  let mostrar = 25;
  const ordenadas = us.map((u) => ({ u, a: acuerdo(u, gs) })).filter((x) => x.a !== null).sort((x, y) => (y.u.fecha > x.u.fecha ? 1 : y.u.fecha < x.u.fecha ? -1 : 0));
  const etq = new Map();
  for (const u of us) for (const e of u.etiquetas) etq.set(e, (etq.get(e) || 0) + 1);
  const topEt = [...etq.entries()].sort((a, b) => b[1] - a[1]).slice(0, 24);
  const cajaLista = el("div", {});
  const pintarLista = () => {
    const [, , filtro] = modos.find(([k]) => k === modo);
    const xs = ordenadas.filter((x) => filtro(x.a));
    cajaLista.replaceChildren(
      el("div", { class: "segmentos", role: "group", "aria-label": "Qué asuntos mostrar" }, modos.map(([k, t, f]) => el("button", {
        type: "button", class: "boton" + (modo === k ? " activo" : ""), "aria-pressed": String(modo === k),
        onclick: () => { modo = k; mostrar = 25; pintarLista(); },
      }, `${t} (${fmt(ordenadas.filter((x) => f(x.a)).length)})`))),
      xs.length ? el("div", { class: "lista" }, xs.slice(0, mostrar).map((x) => filaUnidad(x.u, gs))) : el("div", { class: "vacio" }, "Ninguno."),
      xs.length > mostrar ? el("p", {}, el("button", { type: "button", class: "boton", onclick: () => { mostrar += 25; pintarLista(); } },
        xs.length - mostrar > 25 ? `Ver 25 más (quedan ${fmt(xs.length - mostrar)})` : `Ver los ${fmt(xs.length - mostrar)} que quedan`)) : null);
  };
  pintarLista();
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Asunto a asunto"),
    el("p", { class: "small muted" }, "Lo votado, del más reciente al más antiguo, con la posición de cada grupo respecto al asunto (✓ a favor, ✗ en contra, ~ abstención, ± grupo dividido). Si se votó por puntos, cuántas votaciones de cada. Clic en un asunto para ver el resumen, el voto nominal y la fuente oficial."),
    topEt.length ? el("div", { class: "chips", style: "margin-bottom:10px" }, el("span", { class: "small muted" }, "Subtemas:"),
      topEt.map(([e, n]) => el("a", { class: "chip" + (e === q.etiqueta ? " decisivo" : ""), href: "#/comparar?" + new URLSearchParams({ ...base, etiqueta: e }) }, `#${e}`, el("span", { class: "muted" }, ` ${n}`)))) : null,
    cajaLista));

  // 6. Cómo se calcula.
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cómo se calcula"),
    markdown(`
- Se usa la **votación decisiva** de cada asunto (la de conjunto de una ley, la convalidación de un decreto-ley, la de una PNL o una moción…), solo si es nominal y de fondo.
- **Cada asunto cuenta una vez**: si se votó por puntos, los puntos se reparten su peso. En los debates con propuestas de resolución, las de cada grupo cuentan como un asunto.
- **A favor** es apoyar el asunto: en las enmiendas a la totalidad, votar sí a la devolución es votar en contra del proyecto.
- El voto de un grupo es el de la mayoría de sus miembros. Con varias legislaturas o instituciones, los grupos se suman por siglas.
- Los **debates de política general** (estado de la nación, de la comunidad…) no tienen tema: sus propuestas tratan de cualquier asunto. Solo cuentan con «Todos los temas».
- Votar a favor de asuntos de un tema no es apoyar «el tema»: un mismo tema reúne propuestas en direcciones opuestas. Para puntuar a los grupos con tu criterio, marca en [Mis causas](#/causa?${new URLSearchParams(Object.fromEntries(Object.entries({ tema: q.tema, leg: q.leg, etiqueta: q.etiqueta }).filter(([, v]) => v)))}) qué voto era el favorable.`)));
  return cont;
};
