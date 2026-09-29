"use strict";
// Programas electorales: lo que prometió cada partido frente a lo que votó después en el Pleno.
// Los programas, sus compromisos y el estado de cada uno van en comun.js; los títulos y los votos de las
// iniciativas relacionadas, en los ficheros de su legislatura (hace falta el Congreso en el ámbito).

// Los compromisos van en su propio fichero (datos/programas.js), que se descarga la primera vez que hace falta.
// Cada cambio de ámbito rehace la base en memoria: entonces se vuelven a adjuntar sus tablas, sin descargar nada.
let PROGRAMAS_BD = null;
async function cargarProgramas() {
  const f = CATALOGO.programas;
  if (!f) return false;
  if (q1("SELECT 1 AS x FROM sqlite_master WHERE type='table' AND name='compromiso'")) return true;
  if (!PROGRAMAS_BD) {
    await cargarScript(conVersion(f));
    PROGRAMAS_BD = await descomprimir(DATOS().programas);
    delete DATOS().programas;
  }
  const trozo = new SQL.Database(PROGRAMAS_BD);
  DB.exec(`ATTACH DATABASE '/${trozo.filename}' AS p`);
  const objetos = q("SELECT type, name, sql FROM p.sqlite_master WHERE sql IS NOT NULL ORDER BY type='index'");
  for (const o of objetos) DB.exec(o.sql);
  for (const o of objetos.filter((x) => x.type === "table")) DB.exec(`INSERT INTO main."${o.name}" SELECT * FROM p."${o.name}"`);
  DB.exec("DETACH DATABASE p");
  trozo.close();
  return true;
}

// Estado de cada compromiso según lo que votó el partido: [nombre, color, explicación]. En este orden se enseñan.
const ESTADO_COMPROMISO = {
  impulsado: ["Impulsado", "var(--si)", "Presentó una iniciativa en la dirección del compromiso (o la presentó el Gobierno mientras el partido gobernaba)."],
  apoyado: ["Apoyado", "color-mix(in srgb, var(--si) 45%, var(--surface-1))", "Votó a favor de iniciativas de otros en la dirección del compromiso, o en contra de las que iban en la contraria."],
  mixto: ["Mixto", "color-mix(in srgb, var(--si) 50%, var(--no) 50%)", "Votó en los dos sentidos en distintas iniciativas relacionadas."],
  contradicho: ["Contradicho", "var(--no)", "Votó en contra de algo en la dirección del compromiso, o a favor de algo en la contraria."],
  abstencion: ["Abstención", "var(--abs)", "Se abstuvo (o se dividió) en lo relacionado que se votó."],
  sin_votacion: ["Sin votación", "var(--novota)", "No se ha votado nada relacionado en el Pleno. No quiere decir que no se haya cumplido."],
  fuera_parlamento: ["No verificable en el Parlamento", "var(--grid)", "Depende del Gobierno (real decreto, presupuestos, gestión) o de otra Administración, y no ha pasado por el Pleno como decreto-ley."],
  generico: ["Declaración general", "transparent", "Intención sin medida concreta: se muestra, pero no cuenta en las cifras."],
};
const ESTADOS_VERIFICABLES = Object.keys(ESTADO_COMPROMISO).filter((e) => e !== "generico");
const SENTIDO_COMPROMISO = { misma: "En la dirección del compromiso", contraria: "En la dirección contraria", relacionada: "Trata lo mismo, sin dirección clara" };
const ACCION_COMPROMISO = { legislar: "Legislar", derogar: "Derogar", financiar: "Financiar", crear_organismo: "Crear un organismo",
  bajar_impuesto: "Bajar un impuesto", subir_impuesto: "Subir un impuesto", declaracion: "Declaración", otra: "Otra medida" };
const RESPONSABLE_COMPROMISO = { parlamento: "Depende de las Cortes", gobierno: "Depende del Gobierno", otra_administracion: "Depende de otra Administración" };
const VOTO_PROGRAMA = { si: "votó a favor", no: "votó en contra", abstencion: "se abstuvo", dividido: "se dividió" };
const eleccionTexto = (e) => String(e || "").replace(/^generales-(\d{4})$/, "Generales de $1");
const puntoEstado = (e) => el("i", { class: "punto-estado", style: `background:${ESTADO_COMPROMISO[e][1]}` });
// Parte de los compromisos con votación en un sentido claro que coincide con el programa.
const coinciden = (o) => { const n = (o.impulsado || 0) + (o.apoyado || 0) + (o.contradicho || 0); return { p: n ? ((o.impulsado || 0) + (o.apoyado || 0)) / n : 0, n }; };

API.programas = (p) => {
  const [wg, ag] = enSQL("p.partido", p.g);
  const [wl, al] = enSQL("p.legislatura", p.leg, { conv: Number });
  const [wt, at] = enSQL("c.tema", p.tema);
  const [wa, aa] = enSQL("c.tipo_accion", p.accion);
  const [we, ae] = enSQL("COALESCE(ce.estado, 'generico')", p.estado);
  const programas = q(`SELECT p.* FROM programa p WHERE 1=1 ${wg} ${wl} ORDER BY p.fecha_eleccion DESC, p.estado<>'leido', p.compromisos DESC, p.partido`, [...ag, ...al]);
  // Recuentos por programa, tema y estado con los filtros de partido, legislatura, tema y acción (el de estado solo filtra la lista).
  const base = `FROM compromiso c JOIN programa p ON p.id=c.programa LEFT JOIN compromiso_estado ce ON ce.compromiso=c.id
    WHERE 1=1 ${wg} ${wl} ${wt} ${wa}`;
  const args = [...ag, ...al, ...at, ...aa];
  const resumen = q(`SELECT p.id AS programa, p.partido, c.tema, COALESCE(ce.estado, 'generico') AS estado, COUNT(*) AS n
    ${base} GROUP BY 1, 2, 3, 4`, args);
  // Lo que presentó cada partido en la legislatura que cubre su programa, por tema (para comparar el peso de cada tema).
  const propuestas = q(`SELECT gr.siglas AS partido, f.tema_principal AS tema, COUNT(*) AS n ${FROM_ASUNTO}
    JOIN grupo gr ON gr.legislatura=i.legislatura AND gr.codigo=i.grupo_autor
    JOIN programa p ON p.partido=gr.siglas AND p.legislatura=i.legislatura
    WHERE 1=1 ${wg} ${wl} GROUP BY 1, 2`, [...ag, ...al]);
  const total = q1(`SELECT COUNT(*) AS n ${base} ${we}`, [...args, ...ae]).n;
  const pagina = Math.max(1, +(p.pagina || 1));
  const tam = 25;
  const compromisos = q(`SELECT c.*, p.partido, p.url, p.titulo AS programa_titulo, p.eleccion, ce.estado, ce.aprobada
    ${base} ${we} ORDER BY p.fecha_eleccion DESC, p.partido, c.orden LIMIT ? OFFSET ?`, [...args, ...ae, tam, (pagina - 1) * tam]);
  const ids = compromisos.map((c) => c.id);
  const marcas = ids.map(() => "?").join(",");
  // Las que aún no se han votado solo están en en_tramite (si siguen abiertas).
  const relacionadas = ids.length ? q(`SELECT ci.*, COALESCE(i.titulo, t.titulo) AS titulo, i.titulo IS NOT NULL AS votada,
      COALESCE(i.resultado_final, CASE WHEN t.expediente IS NOT NULL THEN 'en_tramite' END) AS resultado_final,
      COALESCE(i.grupo_autor, t.grupo_autor) AS grupo_autor
    FROM compromiso_iniciativa ci
    LEFT JOIN iniciativa i ON i.legislatura=ci.legislatura AND i.expediente=ci.expediente
    LEFT JOIN en_tramite t ON t.legislatura=ci.legislatura AND t.expediente=ci.expediente
    WHERE ci.compromiso IN (${marcas}) ORDER BY ci.sentido='relacionada', ci.legislatura, ci.expediente`, ids) : [];
  // Lo que votó el partido del programa en cada votación decisiva de fondo de cada iniciativa relacionada.
  const votos = ids.length ? q(`SELECT ci.compromiso, v.legislatura, v.expediente, v.id, v.fecha, v.tipo_votacion, v.resultado,
      CASE WHEN v.asentimiento=1 THEN 'si' ELSE ${SQL_APOYO} END AS apoyo
    FROM compromiso_iniciativa ci
    JOIN compromiso c ON c.id=ci.compromiso JOIN programa p ON p.id=c.programa
    JOIN votacion v ON v.legislatura=ci.legislatura AND v.expediente=ci.expediente AND v.decisiva=1 AND v.tipo_votacion IN (${FONDO_SQL})
    LEFT JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.siglas=p.partido
    LEFT JOIN voto_grupo g ON g.votacion_id=v.id AND g.grupo=gr.codigo
    WHERE ci.compromiso IN (${marcas}) ORDER BY v.fecha`, ids) : [];
  const opciones = {
    partidos: q("SELECT DISTINCT partido FROM programa ORDER BY 1").map((r) => r.partido),
    legislaturas: q("SELECT legislatura, MIN(eleccion) AS eleccion FROM programa WHERE legislatura IS NOT NULL GROUP BY 1 ORDER BY 1 DESC"),
  };
  return { programas, resumen, propuestas, compromisos, relacionadas, votos, total, pagina, tam, opciones };
};

// Compromisos relacionados con una iniciativa (para su ficha en el panel de detalle).
API.programasIniciativa = (p) => q(`SELECT c.id, c.texto, c.pagina, ci.sentido, p.partido, p.eleccion, p.url
  FROM compromiso_iniciativa ci JOIN compromiso c ON c.id=ci.compromiso JOIN programa p ON p.id=c.programa
  WHERE ci.legislatura=? AND ci.expediente=? ORDER BY ci.sentido='relacionada', p.partido, c.orden`, [+p.leg, p.exp]);

VISTAS.programas = async (ruta) => {
  if (!(await cargarProgramas())) return el("div", { class: "vacio" }, "Todavía no hay programas electorales.");
  const d = await api("programas", { g: ruta.g, leg: ruta.leg, tema: ruta.tema, accion: ruta.accion, estado: ruta.estado, pagina: ruta.pagina });
  const ir = (cambios) => irA("programas", { ...ruta, pagina: "", ...cambios });
  const cont = el("div", {},
    el("h2", {}, "Programas electorales"),
    el("p", { class: "sub" }, "Lo que prometió cada partido en su programa y lo que votó después en el Pleno: cada compromiso con su cita y su página, las iniciativas que tratan lo mismo y el voto del partido en ellas. Los temas son los mismos que los de las votaciones."),
    formFiltros([
      multiSelect("g", d.opciones.partidos.map((s) => [s, s]), ruta.g, "Todos los partidos", "partidos"),
      multiSelect("leg", d.opciones.legislaturas.map((l) => [l.legislatura, `${eleccionTexto(l.eleccion)} · ${legTexto(l.legislatura)}`]), ruta.leg, "Todas las elecciones", "elecciones"),
      multiSelect("tema", optTemas(), ruta.tema, "Todos los temas", "temas"),
      multiSelect("accion", Object.entries(ACCION_COMPROMISO), ruta.accion, "Cualquier acción", "acciones"),
      multiSelect("estado", Object.entries(ESTADO_COMPROMISO).map(([k, v]) => [k, v[0]]), ruta.estado, "Cualquier estado", "estados"),
    ], ruta, (f) => irA("programas", f)));
  if (!d.programas.length) {
    cont.append(el("div", { class: "vacio" }, d.opciones.partidos.length ? "Ningún programa con estos filtros." : "Todavía no hay programas electorales."));
    return cont;
  }
  if (!META.cuerpos.includes("congreso")) {
    cont.append(el("div", { class: "aviso-fuentes" }, "Los programas se comparan con las votaciones del Congreso: elige «Nacional» en el ámbito para ver las iniciativas relacionadas y lo que votó cada partido."));
  }

  // Recuentos por programa y por partido.
  const porPrograma = new Map(), porPartido = new Map();
  for (const r of d.resumen) {
    for (const [mapa, clave] of [[porPrograma, r.programa], [porPartido, r.partido]]) {
      const o = mapa.get(clave) || { todos: 0, verificables: 0 };
      o[r.estado] = (o[r.estado] || 0) + r.n;
      o.todos += r.n;
      if (r.estado !== "generico") o.verificables += r.n;
      mapa.set(clave, o);
    }
  }

  // 0. La cifra rápida: qué parte de lo que prometió cada partido coincide con lo que votó.
  const conCifra = [...porPartido.entries()].map(([s, o]) => ({ s, ...coinciden(o), a: (o.impulsado || 0) + (o.apoyado || 0) }))
    .filter((x) => x.n).sort((a, b) => b.p - a.p);
  if (conCifra.length) {
    cont.append(el("div", { class: "card", style: "margin-bottom:16px" }, el("h3", {}, "¿Votan lo que prometieron?"),
      el("p", { class: "small muted" }, "De los compromisos de cada programa que tuvieron una votación en un sentido claro, qué parte coincide con lo que votó el partido (impulsados o apoyados, frente a contradichos). Entre paréntesis, cuántos compromisos cuentan: con pocos, la cifra dice poco. Clic en un partido para ver sus compromisos; filtra por el estado «Contradicho» para ver dónde no coincide."),
      barrasH(conCifra.map((x) => ({ label: x.s, color: colorSiglas(x.s), barColor: colorSiglas(x.s), v: Math.round(100 * x.p),
        valorTexto: `${Math.round(100 * x.p)}% (de ${fmt(x.n)})`, tip: () => `${fmt(x.a)} de ${fmt(x.n)} compromisos coinciden con su voto`,
        onclick: () => ir({ g: x.s }) })), { max: 100 })));
  }

  // 1. Los programas, frente a frente.
  cont.append(el("div", { class: "card" }, el("h3", {}, "Los programas"),
    el("p", { class: "small muted" }, "Cuántos compromisos tiene cada programa y cuántos son verificables (un programa más concreto tiene más). «Coinciden» es la parte de los compromisos con votación en un sentido claro que quedaron impulsados o apoyados, frente a contradichos. Con los filtros de tema y acción, solo esos compromisos."),
    el("table", { class: "tabla" },
      el("thead", {}, el("tr", {}, el("th", {}, "Partido"), el("th", {}, "Programa"), el("th", { class: "num" }, "Compromisos"),
        el("th", { class: "num" }, "Verificables"), el("th", { class: "num" }, "Coinciden"), el("th", { class: "num" }, "Contradichos"), el("th", { class: "num" }, "Sin votación"))),
      el("tbody", {}, d.programas.map((p) => {
        const o = porPrograma.get(p.id) || { todos: 0, verificables: 0 };
        const co = coinciden(o);
        return el("tr", { class: "clic", onclick: () => ir({ g: p.partido }) },
          el("td", { style: "white-space:nowrap" }, swatch(colorSiglas(p.partido)), p.partido),
          el("td", {}, el("a", { href: p.url, target: "_blank", rel: "noopener", onclick: (e) => e.stopPropagation() }, p.titulo),
            el("div", { class: "small muted" }, [eleccionTexto(p.eleccion), `${fmt(p.paginas)} páginas`, p.legislatura ? `cubre la ${legTexto(p.legislatura)}` : null,
              p.origen === "copia-prensa" ? "copia publicada por un medio" : null, p.estado === "pendiente" ? "pendiente de leer" : p.estado === "error" ? "no se ha podido leer" : null].filter(Boolean).join(" · "))),
          el("td", { class: "num" }, p.estado === "leido" ? fmt(o.todos) : "—"),
          el("td", { class: "num" }, p.estado === "leido" ? `${fmt(o.verificables)} (${pct(o.verificables, o.todos)}%)` : "—"),
          el("td", { class: "num" }, co.n ? `${Math.round(100 * co.p)}%` : "—"),
          el("td", { class: "num" }, p.estado === "leido" ? fmt(o.contradicho || 0) : "—"),
          el("td", { class: "num" }, p.estado === "leido" ? fmt((o.sin_votacion || 0) + (o.fuera_parlamento || 0)) : "—"));
      })))));
  if (!d.resumen.length) return cont;

  // 2. Estado de los compromisos verificables de cada partido.
  const partidos = [...porPartido.keys()].sort((a, b) => porPartido.get(b).verificables - porPartido.get(a).verificables);
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Qué pasó con lo que prometieron"),
    el("p", { class: "small muted" }, "Compromisos verificables de cada partido según lo que votó en el Pleno. «Sin votación» no es incumplimiento: muchas promesas se cumplen o no por real decreto, por presupuestos o por gestión. Clic en un partido para ver solo los suyos."),
    el("div", { class: "legend" }, ESTADOS_VERIFICABLES.map((e) => el("span", { title: ESTADO_COMPROMISO[e][2] }, el("i", { style: `background:${ESTADO_COMPROMISO[e][1]}` }), ESTADO_COMPROMISO[e][0]))),
    barrasH(partidos.map((s) => {
      const o = porPartido.get(s);
      return { label: s, color: colorSiglas(s), valorTexto: `${fmt(o.verificables)} verificables`,
        segs: ESTADOS_VERIFICABLES.map((e) => ({ v: o[e] || 0, color: ESTADO_COMPROMISO[e][1], nombre: ESTADO_COMPROMISO[e][0] })),
        tip: (sg) => `${fmt(sg.v)} de ${fmt(o.verificables)} compromisos (${pct(sg.v, o.verificables)}%)`, onclick: () => ir({ g: s }) };
    }), { segs: true, normalizar: true })));

  // 3. Tema a tema: dónde coincide cada partido con su voto y cuánto pesa cada tema en su programa y en lo que presenta.
  const celdas = new Map();
  for (const r of d.resumen) {
    if (r.estado === "generico" || !r.tema) continue;
    const k = r.partido + "|" + r.tema;
    const o = celdas.get(k) || { verificables: 0 };
    o[r.estado] = (o[r.estado] || 0) + r.n;
    o.verificables += r.n;
    celdas.set(k, o);
  }
  const temas = META.temas.map((t) => t.codigo).filter((t) => partidos.some((s) => celdas.has(s + "|" + t)));
  const prop = new Map(d.propuestas.map((r) => [r.partido + "|" + r.tema, r.n]));
  const totalProp = (s) => d.propuestas.filter((r) => r.partido === s).reduce((a, r) => a + r.n, 0);
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Tema a tema"),
    el("p", { class: "small muted" }, "Porcentaje de compromisos del tema, con votación en un sentido claro, que coinciden con lo que votó el partido. «·» si hay menos de 3. Clic en un partido para ver solo los suyos."),
    mapaCalor(partidos, temas, (s, t) => { const o = celdas.get(s + "|" + t); return o ? coinciden(o) : null; }, {
      etiquetaCol: temaNombre, minimo: 3, alClicarFila: (s) => ir({ g: s }),
      tip: (s, t, x) => [`${Math.round(100 * x.p)}% coinciden`, `${s} · ${temaNombre(t)}`, `${fmt(x.n)} compromisos con votación en un sentido claro`],
    }),
    el("h3", { style: "margin-top:16px" }, "Cuánto pesa cada tema"),
    el("p", { class: "small muted" }, "Parte de los compromisos verificables del programa que son de cada tema / parte de las iniciativas que presentó el grupo en la legislatura que cubre el programa. Si un tema pesa mucho más en el programa que en lo que presenta, se ve aquí."),
    el("table", { class: "tabla" },
      el("thead", {}, el("tr", {}, el("th", {}, "Tema"), partidos.map((s) => el("th", { class: "num" }, swatch(colorSiglas(s)), s)))),
      el("tbody", {}, temas.map((t) => el("tr", { class: "clic", onclick: () => ir({ tema: t }) }, el("td", {}, temaNombre(t)),
        partidos.map((s) => {
          const o = celdas.get(s + "|" + t);
          const enProg = pct(o ? o.verificables : 0, porPartido.get(s).verificables);
          const enInic = pct(prop.get(s + "|" + t) || 0, totalProp(s));
          return el("td", { class: "num", style: "white-space:nowrap" }, `${enProg}% / ${enInic}%`);
        })))))));

  // 4. Los compromisos, uno a uno, con sus iniciativas y votos.
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, `Compromisos (${fmt(d.total)})`),
    el("p", { class: "small muted" }, "Cada compromiso con la cita del programa y su página, las iniciativas del Pleno que tratan lo mismo y lo que votó el partido en su votación decisiva. Clic en una iniciativa para ver su ficha y sus votaciones."),
    d.compromisos.length ? el("div", {}, d.compromisos.map((c) => filaCompromiso(c, d))) : el("div", { class: "vacio" }, "Ninguno con estos filtros."),
    d.total > d.tam ? paginacion(d.total, d.pagina, d.tam, (pagina) => irA("programas", { ...ruta, pagina })) : null));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cómo se calcula"), markdown(`
- De cada programa se toman los **compromisos** con su cita literal y su página. Los que solo expresan una intención («impulsaremos», «apostaremos por») son **declaraciones generales**: se muestran, pero no cuentan en las cifras.
- Cada compromiso se relaciona con las iniciativas del Pleno de la legislatura siguiente a las elecciones que tratan la misma medida, y se indica si van **en su dirección**, **en la contraria** o solo tratan lo mismo. Al decidirlo no se tiene en cuenta qué partido hizo la promesa ni quién presentó la iniciativa, y lo que va en una dirección se comprueba en una segunda revisión más estricta: no basta con que se llamen parecido.
- Se usa lo que votó el partido en la **votación decisiva** de cada iniciativa (en las enmiendas a la totalidad, votar sí es votar contra el proyecto). Apoyar algo en la dirección del compromiso o rechazar algo en la contraria **coincide con el programa**; lo inverso, no.
- **Sin votación no es incumplimiento**: muchas promesas se cumplen o no por real decreto, por presupuestos o por gestión. De lo que depende del Gobierno solo se tienen en cuenta los decretos-leyes, que se convalidan en el Pleno.
- Se indica si el partido estaba en el Gobierno o en la oposición en cada votación: votar contra una promesa propia por un acuerdo de coalición es un dato, no una anomalía.`)));
  return cont;
};

function filaCompromiso(c, d) {
  const [nombre, , explicacion] = ESTADO_COMPROMISO[c.estado || "generico"];
  const rels = d.relacionadas.filter((r) => r.compromiso === c.id);
  const anio = (String(c.eleccion).match(/\d{4}/) || [""])[0];
  return el("article", { class: "compromiso" },
    el("div", { class: "small muted cabecera" },
      el("span", { class: "badge", title: explicacion }, puntoEstado(c.estado || "generico"), nombre),
      el("span", {}, [temaNombre(c.tema), ACCION_COMPROMISO[c.tipo_accion], c.verificable ? RESPONSABLE_COMPROMISO[c.responsable] : null].filter(Boolean).join(" · ")),
      el("a", { href: `${c.url}#page=${c.pagina}`, target: "_blank", rel: "noopener", title: c.programa_titulo }, `Programa ${c.partido} ${anio}, p. ${c.pagina}`),
      c.aprobada ? el("span", { class: "badge ok" }, "Salió adelante algo en su dirección") : null),
    el("div", { class: "texto" }, c.texto),
    el("blockquote", {}, `«${c.cita}»`),
    rels.length ? el("ul", { class: "relacionadas" }, rels.map((r) => filaRelacionada(r, c, d)))
      : c.verificable ? el("p", { class: "small muted", style: "margin:0" }, "Ninguna iniciativa del Pleno relacionada.") : null);
}

function filaRelacionada(r, c, d) {
  const votos = d.votos.filter((v) => v.compromiso === c.id && v.legislatura === r.legislatura && v.expediente === r.expediente);
  const autor = r.grupo_autor ? grupo(r.legislatura, r.grupo_autor) : null;
  return el("li", {},
    el("div", {}, el("span", { class: "sentido-rel" }, SENTIDO_COMPROMISO[r.sentido] || r.sentido), " · ",
      r.votada ? el("a", { href: "#", onclick: (e) => { e.preventDefault(); abrir(`i:${r.legislatura}:${r.expediente}`); } }, textoCorto(r.titulo, 120))
        : r.titulo ? textoCorto(r.titulo, 120) : el("span", { class: "muted" }, r.expediente),
      autor ? el("span", { class: "muted" }, ` · presentada por ${autor.siglas}`) : null, " ", badgeResultado(r.resultado_final)),
    votos.map((v) => lineaVoto(v, r.sentido, c.partido)),
    r.justificacion ? el("div", { class: "small muted" }, r.justificacion) : null);
}

// Lo que votó el partido en una votación decisiva y si coincide con su programa (según el sentido de la iniciativa
// respecto al compromiso), con si estaba en el Gobierno o en la oposición.
function lineaVoto(v, sentido, partido) {
  const g = gobiernoEn(infoLeg(v.legislatura).cuerpo || "congreso", v.fecha);
  const enGobierno = g && (g.partido === partido || lista(g.socios).includes(partido));
  const coincide = sentido !== "relacionada" && (v.apoyo === "si" || v.apoyo === "no") ? (v.apoyo === "si") === (sentido === "misma") : null;
  return el("div", { class: "small" }, `${partido} ${VOTO_PROGRAMA[v.apoyo] || "no consta"}`,
    el("span", { class: "muted" }, ` · ${META.tipos_votacion[v.tipo_votacion] || v.tipo_votacion}, ${fecha(v.fecha)} · ${enGobierno ? "en el Gobierno" : "en la oposición"}`), " ",
    coincide === null ? null : el("span", { class: `badge ${coincide ? "ok" : "ko"}` }, coincide ? "coincide con el programa" : "no coincide con el programa"));
}

// Votaciones decisivas de fondo de una iniciativa con lo que votó un partido (apoyo a la iniciativa).
const votosPartido = (leg, exp, partido) => q(`SELECT v.legislatura, v.id, v.fecha, v.tipo_votacion,
    CASE WHEN v.asentimiento=1 THEN 'si' ELSE ${SQL_APOYO} END AS apoyo
  FROM votacion v
  LEFT JOIN grupo gr ON gr.legislatura=v.legislatura AND gr.siglas=?
  LEFT JOIN voto_grupo g ON g.votacion_id=v.id AND g.grupo=gr.codigo
  WHERE v.legislatura=? AND v.expediente=? AND v.decisiva=1 AND v.tipo_votacion IN (${FONDO_SQL}) ORDER BY v.fecha`, [partido, +leg, exp]);

// Bloque del detalle de una iniciativa: qué partidos llevaban en su programa algo relacionado. Solo descarga los
// programas si la iniciativa aparece en alguno (programa_iniciativa, en comun.js).
async function bloqueProgramas(leg, exp) {
  if (!q1("SELECT 1 AS x FROM programa_iniciativa WHERE legislatura=? AND expediente=?", [+leg, exp])) return null;
  await cargarProgramas();
  const cs = API.programasIniciativa({ leg, exp });
  if (!cs.length) return null;
  return el("section", {}, el("h3", {}, "En los programas electorales"),
    el("p", { class: "small muted" }, "Partidos que llevaban en su programa algo relacionado, si esta iniciativa iba en la dirección de su compromiso y si lo que votaron coincide con él."),
    el("ul", { class: "relacionadas" }, cs.map((c) => {
      const votos = votosPartido(leg, exp, c.partido);
      return el("li", {},
        el("div", {}, swatch(colorSiglas(c.partido)), el("b", {}, c.partido), " · ", SENTIDO_COMPROMISO[c.sentido] || c.sentido, " · ",
          el("a", { href: `${c.url}#page=${c.pagina}`, target: "_blank", rel: "noopener" }, `${eleccionTexto(c.eleccion)}, p. ${c.pagina}`)),
        el("div", {}, c.texto),
        votos.length ? votos.map((v) => lineaVoto(v, c.sentido, c.partido)) : el("div", { class: "small muted" }, "Todavía no se ha votado."));
    })),
    el("p", { class: "small" }, el("a", { href: "#/programas" }, "Programas electorales: lo que prometió cada partido frente a lo que votó →")));
}
