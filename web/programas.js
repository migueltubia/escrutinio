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
// Lo que no pasa por el Congreso va rayado: en liso se confunde con «no se ha votado».
const RAYADO = "repeating-linear-gradient(135deg, var(--novota) 0 3px, var(--surface-1) 3px 6px)";
const ESTADO_COMPROMISO = {
  impulsado: ["Lo propuso", "var(--si)", "El partido presentó una iniciativa para hacerlo (o la presentó el Gobierno mientras el partido gobernaba)."],
  apoyado: ["Lo apoyó", "color-mix(in srgb, var(--si) 45%, var(--surface-1))", "Votó a favor de iniciativas de otros que iban en esa línea, o en contra de las que iban en contra."],
  mixto: ["Unas veces sí y otras no", "color-mix(in srgb, var(--si) 50%, var(--no) 50%)", "En unas iniciativas sobre el asunto votó como prometía y en otras al revés."],
  contradicho: ["Votó en contra", "var(--no)", "Votó en contra de algo que iba en la línea de la promesa, o a favor de algo que iba en contra."],
  abstencion: ["Se abstuvo", "var(--abs)", "Se abstuvo (o su grupo se dividió) en lo que se votó sobre el asunto."],
  sin_votacion: ["No se ha votado", "var(--novota)", "En el Pleno no se ha votado nada sobre esto. No quiere decir que no se haya cumplido."],
  fuera_parlamento: ["No pasa por el Congreso", RAYADO, "Depende del Gobierno (un real decreto, los presupuestos, la gestión) o de otra administración, y no ha llegado al Pleno como decreto-ley."],
  por_comparar: ["Aún sin revisar", "transparent", "Todavía no se ha mirado qué se votó sobre esto. No cuenta en las cifras."],
  generico: ["Promesa genérica", "transparent", "Una intención sin medida concreta («impulsaremos», «apostaremos por»). Se enseña, pero no cuenta en las cifras."],
};
// Para la barra de cada programa: qué pasó con sus promesas concretas, agrupado en lo que importa al leerla.
const PASO_PROMESAS = [
  ["Votó lo prometido", "var(--si)", ["impulsado", "apoyado"]],
  ["Votó en contra alguna vez", "var(--no)", ["contradicho", "mixto"]],
  ["Se abstuvo", "var(--abs)", ["abstencion"]],
  ["No se ha votado", "var(--novota)", ["sin_votacion"]],
  ["No pasa por el Congreso", RAYADO, ["fuera_parlamento"]],
];
const SENTIDO_COMPROMISO = { misma: "Va en la línea de la promesa", contraria: "Va en contra de la promesa", relacionada: "Trata el mismo asunto" };
const ACCION_COMPROMISO = { legislar: "Legislar", derogar: "Derogar", financiar: "Financiar", crear_organismo: "Crear un organismo",
  bajar_impuesto: "Bajar un impuesto", subir_impuesto: "Subir un impuesto", declaracion: "Declaración", otra: "Otra medida" };
// Qué quita y qué añade cada tipo de medida, en el orden de las columnas. Legislar y el resto no tienen signo: una ley
// puede ampliar o recortar.
const LADOS_ACCION = [
  ["Quitan", ["bajar_impuesto", "derogar"]],
  ["Añaden", ["subir_impuesto", "financiar", "crear_organismo"]],
  ["Ni quitan ni añaden", ["legislar", "otra", "declaracion"]],
];
const RESPONSABLE_COMPROMISO = { parlamento: "Depende de las Cortes", gobierno: "Depende del Gobierno", otra_administracion: "Depende de otra administración" };
const VOTO_PROGRAMA = { si: "votó a favor", no: "votó en contra", abstencion: "se abstuvo", dividido: "se dividió" };
// «generales-2023» -> «Generales de 2023»; «generales-2019-04» -> «Generales de abril de 2019».
const eleccionTexto = (e) => String(e || "")
  .replace(/^generales-(\d{4})-(\d{2})$/, (_m, y, mes) => `Generales de ${["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"][+mes - 1]} de ${y}`)
  .replace(/^generales-(\d{4})$/, "Generales de $1");
const ORIGEN_PROGRAMA = { "copia-prensa": "copia publicada por un medio", "archivo-web": "copia guardada en el Internet Archive" };
// Dónde está una cita: en un PDF, la página (el enlace abre el PDF en ella); en un programa publicado como página
// web, el apartado (el enlace abre la copia guardada, sin «id_», que es la versión cruda para descargar).
const enlaceCita = (url, formato, pagina) => formato === "html"
  ? { href: url.replace(/(web\.archive\.org\/web\/\d+)id_\//, "$1/"), texto: `apartado ${pagina}` }
  : { href: `${url}#page=${pagina}`, texto: `p. ${pagina}` };
const puntoEstado = (e) => el("i", { class: "punto-estado", style: `background:${ESTADO_COMPROMISO[e][1]}` });
// Parte de los compromisos con votación en un sentido claro que coincide con el programa. Los de «unas veces sí y
// otras no» (mixto) cuentan como no coincidentes: así cuadra con «votó en contra alguna vez».
const coinciden = (o) => {
  const si = (o.impulsado || 0) + (o.apoyado || 0), n = si + (o.contradicho || 0) + (o.mixto || 0);
  return { p: n ? si / n : 0, si, n };
};
// Barra de un programa (o partido): sus promesas concretas según lo que pasó con ellas.
function barraPromesas(o) {
  const partes = PASO_PROMESAS.map(([nombre, color, estados]) => ({ nombre, color, v: estados.reduce((a, e) => a + (o[e] || 0), 0) })).filter((x) => x.v);
  const total = partes.reduce((a, x) => a + x.v, 0);
  const barra = el("div", { class: "barra-promesas" });
  for (const x of partes) {
    barra.append(conTip(el("div", { class: "mark", tabindex: 0, style: `flex:${x.v} 0 0;background:${x.color};min-width:3px` }),
      fmt(x.v), x.nombre, `${pct(x.v, total)}% de sus ${fmt(total)} promesas concretas`));
  }
  return barra;
}

// Filtros de la lista de compromisos: partido, legislatura, tema, acción y texto van en base (también cuentan en los
// recuentos); el de estado (we) solo filtra la lista.
function filtrosProgramas(p) {
  const [wg, ag] = enSQL("p.partido", p.g);
  const [wl, al] = enSQL("p.legislatura", p.leg, { conv: Number });
  const [wt, at] = enSQL("c.tema", p.tema);
  const [wa, aa] = enSQL("c.tipo_accion", p.accion);
  const [we, ae] = enSQL("COALESCE(ce.estado, 'generico')", p.estado);
  // Palabras sueltas: todas tienen que salir en el texto, la cita o las etiquetas.
  const palabras = (p.q || "").split(/\s+/).filter(Boolean);
  const wq = palabras.map(() => "AND (c.texto LIKE ? OR c.cita LIKE ? OR c.etiquetas LIKE ?)").join(" ");
  const aq = palabras.flatMap((x) => Array(3).fill(`%${x}%`));
  return {
    wg, ag, wl, al, we, ae,
    base: `FROM compromiso c JOIN programa p ON p.id=c.programa LEFT JOIN compromiso_estado ce ON ce.compromiso=c.id
      WHERE 1=1 ${wg} ${wl} ${wt} ${wa} ${wq}`,
    args: [...ag, ...al, ...at, ...aa, ...aq],
    // En la lista, primero lo que se votó, luego lo concreto sin votar y al final las promesas genéricas.
    orden: `CASE WHEN ce.estado IN ('contradicho','mixto','impulsado','apoyado','abstencion') THEN 0
      WHEN ce.estado IS NULL OR ce.estado='generico' THEN 2 ELSE 1 END, p.fecha_eleccion DESC, p.partido, c.orden`,
  };
}

// Todos los compromisos con los filtros, para descargarlos en CSV.
API.programasCSV = (p) => {
  const { base, args, we, ae, orden } = filtrosProgramas(p);
  return q(`SELECT c.*, p.partido, p.eleccion, p.url, p.formato, COALESCE(ce.estado, 'generico') AS estado ${base} ${we} ORDER BY ${orden}`, [...args, ...ae]);
};

API.programas = (p) => {
  const { wg, ag, wl, al, we, ae, base, args, orden } = filtrosProgramas(p);
  const programas = q(`SELECT p.* FROM programa p WHERE 1=1 ${wg} ${wl} ORDER BY p.fecha_eleccion DESC, p.estado<>'leido', p.compromisos DESC, p.partido`, [...ag, ...al]);
  const resumen = q(`SELECT p.id AS programa, p.partido, c.tema, COALESCE(ce.estado, 'generico') AS estado, COUNT(*) AS n
    ${base} GROUP BY 1, 2, 3, 4`, args);
  const total = q1(`SELECT COUNT(*) AS n ${base} ${we}`, [...args, ...ae]).n;
  const pagina = Math.max(1, +(p.pagina || 1));
  const tam = 25;
  const compromisos = q(`SELECT c.*, p.partido, p.url, p.formato, p.titulo AS programa_titulo, p.eleccion, ce.estado, ce.aprobada
    ${base} ${we} ORDER BY ${orden} LIMIT ? OFFSET ?`, [...args, ...ae, tam, (pagina - 1) * tam]);
  // Los que el partido votó alguna vez en contra (contradichos y mixtos), para ponerlos arriba. Son pocos: van todos.
  const contradichos = q(`SELECT c.*, p.partido, p.url, p.formato, p.titulo AS programa_titulo, p.eleccion, ce.estado, ce.aprobada
    ${base} AND ce.estado IN ('contradicho', 'mixto') ORDER BY ce.estado='mixto', p.fecha_eleccion DESC, p.partido, c.orden`, args);
  const ids = [...new Set([...compromisos, ...contradichos].map((c) => c.id))];
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
  const opciones = opcionesProgramas();
  // Efecto gobierno: estado de los compromisos según si el partido gobernaba en todas las votaciones relacionadas
  // (gobierno=1) o en ninguna (gobierno=0).
  const gobierno = q(`SELECT p.partido, ce.gobierno, ce.estado, COUNT(*) AS n ${base} AND ce.gobierno IS NOT NULL GROUP BY 1, 2, 3`, args);
  return { programas, resumen, compromisos, contradichos, relacionadas, votos, total, pagina, tam, opciones, gobierno };
};

const opcionesProgramas = () => ({
  partidos: q("SELECT DISTINCT partido FROM programa ORDER BY 1").map((r) => r.partido),
  legislaturas: q("SELECT legislatura, MIN(eleccion) AS eleccion FROM programa WHERE legislatura IS NOT NULL GROUP BY 1 ORDER BY 1 DESC"),
});

// Para Comparar · Programas: compromisos verificables por partido, tema y tipo de medida, y lo que presentó cada
// partido en la legislatura que cubre su programa, por tema (para comparar el peso de cada tema).
API.programasComparar = (p) => {
  const [wg, ag] = enSQL("p.partido", p.g);
  const [wl, al] = enSQL("p.legislatura", p.leg, { conv: Number });
  const [wt, at] = enSQL("c.tema", p.tema);
  const acciones = q(`SELECT p.partido, c.tema, c.tipo_accion AS accion, COUNT(*) AS n
    FROM compromiso c JOIN programa p ON p.id=c.programa LEFT JOIN compromiso_estado ce ON ce.compromiso=c.id
    WHERE COALESCE(ce.estado, 'generico')<>'generico' ${wg} ${wl} ${wt} GROUP BY 1, 2, 3`, [...ag, ...al, ...at]);
  const propuestas = q(`SELECT gr.siglas AS partido, f.tema_principal AS tema, COUNT(*) AS n ${FROM_ASUNTO}
    JOIN grupo gr ON gr.legislatura=i.legislatura AND gr.codigo=i.grupo_autor
    JOIN programa p ON p.partido=gr.siglas AND p.legislatura=i.legislatura AND p.estado='leido'
    WHERE 1=1 ${wg} ${wl} GROUP BY 1, 2`, [...ag, ...al]);
  return { acciones, propuestas, opciones: opcionesProgramas() };
};

// Compromisos relacionados con una iniciativa (para su ficha en el panel de detalle).
API.programasIniciativa = (p) => q(`SELECT c.id, c.texto, c.pagina, ci.sentido, p.partido, p.eleccion, p.url, p.formato
  FROM compromiso_iniciativa ci JOIN compromiso c ON c.id=ci.compromiso JOIN programa p ON p.id=c.programa
  WHERE ci.legislatura=? AND ci.expediente=? ORDER BY ci.sentido='relacionada', p.partido, c.orden`, [+p.leg, p.exp]);

VISTAS.programas = async (ruta) => {
  // Es una pestaña de Activismo: lo que prometieron frente a lo que votaron.
  if (!(await cargarProgramas())) return el("div", {}, subnav(NAV_ACTIVISMO, "programas"), el("div", { class: "vacio" }, "Todavía no hay programas electorales."));
  const filtros = { g: ruta.g, leg: ruta.leg, tema: ruta.tema, accion: ruta.accion, estado: ruta.estado, q: ruta.q };
  const d = await api("programas", { ...filtros, pagina: ruta.pagina });
  const ir = (cambios) => irA("programas", { ...ruta, pagina: "", ...cambios });
  const cont = el("div", {}, subnav(NAV_ACTIVISMO, "programas"),
    el("h2", {}, "Programas electorales"),
    el("p", { class: "sub" }, "Qué prometió cada partido en las elecciones generales y qué votó después en el Congreso. Cada promesa lleva la frase tal como aparece en el programa y la página donde está."),
    formFiltros([
      el("input", { type: "search", name: "q", value: ruta.q || "", placeholder: "Buscar en las promesas (alquiler, IVA, pensiones…)" }),
      multiSelect("g", d.opciones.partidos.map((s) => [s, s]), ruta.g, "Todos los partidos", "partidos"),
      multiSelect("leg", d.opciones.legislaturas.map((l) => [l.legislatura, `${eleccionTexto(l.eleccion)} · ${legTexto(l.legislatura)}`]), ruta.leg, "Todas las elecciones", "elecciones"),
      multiSelect("tema", optTemas(), ruta.tema, "Todos los temas", "temas"),
      multiSelect("accion", Object.entries(ACCION_COMPROMISO), ruta.accion, "Cualquier tipo de medida", "medidas"),
      multiSelect("estado", Object.entries(ESTADO_COMPROMISO).map(([k, v]) => [k, v[0]]), ruta.estado, "Votaran lo que votaran", "opciones"),
    ], ruta, (f) => irA("programas", f)));
  if (!d.programas.length) {
    cont.append(el("div", { class: "vacio" }, d.opciones.partidos.length ? "Ningún programa con estos filtros." : "Todavía no hay programas electorales."));
    return cont;
  }
  if (!META.cuerpos.includes("congreso")) {
    cont.append(el("div", { class: "aviso-fuentes" }, "Los programas se comparan con lo que se vota en el Congreso. Para ver las iniciativas y lo que votó cada partido, elige «Nacional» en el ámbito."));
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
  const suma = (estados) => [...porPartido.values()].reduce((a, o) => a + estados.reduce((b, e) => b + (o[e] || 0), 0), 0);
  const filtrado = ruta.tema || ruta.accion || ruta.q;

  // 1. Los programas: cuántas promesas concretas tiene cada uno y qué ha pasado con ellas. Va primero porque da la
  // medida de todo lo demás: casi nada de lo prometido llega a votarse.
  cont.append(el("div", { class: "card" }, el("h3", {}, "Los programas"),
    el("p", { class: "small muted" }, "Cuántas promesas concretas tiene cada programa y qué ha pasado con ellas. La mayoría no llega a votarse en el Congreso, porque dependen del Gobierno o porque nadie las ha llevado al Pleno. El porcentaje de la derecha cuenta solo las promesas en las que hubo una votación clara.",
      filtrado ? " Solo las promesas que encajan con la búsqueda y los filtros." : ""),
    el("div", { class: "legend" }, PASO_PROMESAS.map(([nombre, color]) => el("span", {}, el("i", { style: `background:${color}` }), nombre))),
    el("table", { class: "tabla tabla-programas" },
      el("thead", {}, el("tr", {}, el("th", {}, "Partido"), el("th", {}, "Programa y qué ha pasado con sus promesas concretas"), el("th", { class: "num" }, "Votó lo prometido"))),
      el("tbody", {}, d.programas.map((p) => {
        const o = porPrograma.get(p.id) || { todos: 0, verificables: 0 };
        const co = coinciden(o);
        // Leído pero aún sin comparar con lo votado: no hay nada que enseñar en la barra.
        const comparado = p.estado === "leido" && !o.por_comparar;
        return el("tr", { class: "clic", onclick: () => ir({ g: p.partido, leg: p.legislatura ? String(p.legislatura) : "" }) },
          el("td", { style: "white-space:nowrap" }, swatch(colorSiglas(p.partido)), p.partido),
          el("td", {}, el("a", { href: enlaceCita(p.url, p.formato, 1).href.replace(/#page=1$/, ""), target: "_blank", rel: "noopener", onclick: (e) => e.stopPropagation() }, p.titulo),
            el("div", { class: "small muted" }, [eleccionTexto(p.eleccion), p.formato === "html" ? `página web, ${fmt(p.paginas)} apartados` : `${fmt(p.paginas)} páginas`, p.legislatura ? `para la ${legTexto(p.legislatura)}` : null,
              p.legislatura && gobiernosLeg(p.legislatura) ? `gobierno: ${gobiernosLeg(p.legislatura)}` : null, ORIGEN_PROGRAMA[p.origen] || null, p.estado === "pendiente" ? "todavía sin leer" : p.estado === "error" ? "no se ha podido leer" : null].filter(Boolean).join(" · ")),
            p.estado === "leido" ? el("div", { class: "promesas-programa" },
              comparado && o.verificables ? barraPromesas(o) : null,
              el("span", { class: "small muted" }, `${fmt(o.verificables)} promesas concretas de ${fmt(o.todos)}`, comparado ? "" : " · aún sin revisar qué se votó",
                // En el móvil no cabe la última columna: el porcentaje va aquí.
                co.n ? el("span", { class: "solo-movil" }, ` · votó lo prometido en ${fmt(co.si)} de ${fmt(co.n)}`) : null)) : null),
          el("td", { class: "num", style: "white-space:nowrap" }, co.n ? [`${Math.round(100 * co.p)}%`, el("div", { class: "small muted" }, `${fmt(co.si)} de ${fmt(co.n)}`)] : "—"));
      })))));
  // Los programas entre sí (cuánto pesa cada tema, qué quiere quitar y qué añadir cada partido), en Comparar.
  const filtrosComparar = new URLSearchParams(Object.entries({ g: ruta.g, leg: ruta.leg, tema: ruta.tema }).filter(([, v]) => v));
  cont.append(el("p", { class: "small", style: "margin:12px 0 0" }, el("a", { href: `#/comparar-programas?${filtrosComparar}` },
    "Ver los programas comparados entre sí, por tema y por tipo de medida →")));
  if (!d.resumen.length) {
    cont.append(el("div", { class: "vacio" }, "Ninguna promesa con esta búsqueda y estos filtros."));
    return cont;
  }

  // 2. Dónde votaron en contra de lo que prometieron: los casos concretos, con su cita y solo las votaciones que no
  // coinciden. Se enseñan unos pocos y el resto con un botón, para que no tapen lo demás.
  const conVoto = suma(["impulsado", "apoyado", "mixto", "contradicho", "abstencion"]);
  if (conVoto) {
    const nContra = suma(["contradicho"]), nMixto = suma(["mixto"]);
    const MUESTRA = 5;
    const listaContra = el("div", {}, d.contradichos.slice(0, MUESTRA).map((c) => filaCompromiso(c, d, true)));
    const mas = d.contradichos.length > MUESTRA ? el("button", { class: "boton", style: "margin-top:8px",
      onclick: () => { listaContra.replaceChildren(...d.contradichos.map((c) => filaCompromiso(c, d, true))); mas.remove(); } }, `Ver las ${fmt(d.contradichos.length)}`) : null;
    cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cuándo votaron en contra de su programa"),
      el("p", { class: "small muted" }, `Se votó algo relacionado con ${fmt(conVoto)} promesas. En ${fmt(nContra)} el partido votó en contra de lo que prometía`,
        nMixto ? ` y en ${fmt(nMixto)} votó unas veces a favor y otras en contra.` : ".",
        " De cada una se ve la frase del programa y solo las votaciones que no encajan con ella. Conviene mirar quién presentó la iniciativa y si el partido gobernaba: a veces se vota en contra por el resto del texto o por un pacto con los socios."),
      d.contradichos.length ? [listaContra, mas] : el("p", { class: "muted" }, "Con estos filtros no hay ninguna. En lo que se votó, cada partido votó como prometía.")));
  }

  // 3. Efecto gobierno: la misma cifra cuando el partido gobernaba y cuando estaba en la oposición.
  const efecto = new Map();
  for (const r of d.gobierno) {
    const o = efecto.get(r.partido) || { g: {}, o: {} };
    const lado = r.gobierno ? o.g : o.o;
    lado[r.estado] = (lado[r.estado] || 0) + r.n;
    efecto.set(r.partido, o);
  }
  const conLosDos = [...efecto.entries()].filter(([, o]) => coinciden(o.g).n && coinciden(o.o).n);
  if (conLosDos.length) {
    const fila = (s, lado, nombre) => {
      const x = coinciden(lado);
      return { label: `${s} · ${nombre}`, color: colorSiglas(s), barColor: nombre === "en el Gobierno" ? colorSiglas(s) : `color-mix(in srgb, ${colorSiglas(s)} 45%, var(--surface-1))`,
        v: Math.round(100 * x.p), valorTexto: `${Math.round(100 * x.p)}% (de ${fmt(x.n)})`, tip: () => `${fmt(x.n)} promesas con una votación clara`, onclick: () => ir({ g: s }) };
    };
    cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "En el Gobierno y en la oposición"),
      el("p", { class: "small muted" }, "Cuántas veces votó lo prometido cada partido, según estuviera en el Gobierno o en la oposición en el momento de la votación. Cuando gobierna cuentan también las leyes y los decretos del Gobierno que van en la línea de lo prometido. Si gobierna en coalición o con apoyos, también pesan los acuerdos con los socios."),
      barrasH(conLosDos.flatMap(([s, o]) => [fila(s, o.g, "en el Gobierno"), fila(s, o.o, "en la oposición")]), { max: 100 })));
  }

  // 4. Los compromisos, uno a uno, con sus iniciativas y votos.
  const csv = async () => {
    const filas = await api("programasCSV", filtros);
    descargarCSV(`programas-${hoyISO()}.csv`,
      ["Partido", "Elección", "Promesa", "Frase del programa", "Página", "Tema", "Tipo de medida", "Depende de", "Qué pasó", "Enlace"],
      filas.map((c) => [c.partido, eleccionTexto(c.eleccion), c.texto, c.cita, c.pagina, temaNombre(c.tema), ACCION_COMPROMISO[c.tipo_accion] || "",
        c.verificable ? (RESPONSABLE_COMPROMISO[c.responsable] || "").replace(/^Depende de(l| las)? /, "") : "", ESTADO_COMPROMISO[c.estado][0], enlaceCita(c.url, c.formato, c.pagina).href]));
  };
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, `Todas las promesas (${fmt(d.total)})`),
    el("p", { class: "small muted" }, "Primero las que llegaron a votarse. Debajo de cada una están las iniciativas del Pleno sobre el mismo asunto y lo que votó el partido en la votación que decidió cada una. Pulsa una iniciativa para ver su ficha."),
    el("p", { class: "small" }, el("button", { class: "boton", onclick: csv }, "Descargar en CSV")),
    d.compromisos.length ? el("div", {}, d.compromisos.map((c) => filaCompromiso(c, d))) : el("div", { class: "vacio" }, "Ninguna con estos filtros."),
    d.total > d.tam ? paginacion(d.total, d.pagina, d.tam, (pagina) => irA("programas", { ...ruta, pagina })) : null));

  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cómo se calcula"), markdown(`
- De cada programa se sacan las promesas, con la frase tal como aparece y su página. Las que solo expresan una intención («impulsaremos», «apostaremos por») son **promesas genéricas**: se enseñan, pero no cuentan en las cifras.
- Cada promesa tiene un **tipo de medida**: legislar, derogar, dar dinero, crear un organismo, bajar o subir un impuesto u otra.
- Cada promesa se relaciona con las iniciativas del Pleno de la legislatura siguiente que tratan la misma medida, y se marca si van **en su línea**, **en contra** o solo tratan el mismo asunto. Para decidirlo no se mira qué partido hizo la promesa ni quién presentó la iniciativa. Después se repasa cada relación con un criterio más estricto, porque no basta con que dos cosas se llamen parecido. Las que todavía no se han repasado lo indican.
- Se mira lo que votó el partido en la **votación que decidió** cada iniciativa. En una enmienda a la totalidad, votar sí es votar contra el proyecto. Apoyar algo en la línea de la promesa, o rechazar algo que va en contra, cuenta como **votó lo prometido**. Lo contrario cuenta como **votó en contra**.
- **Que algo no se haya votado no quiere decir que se haya incumplido.** Muchas promesas se cumplen o no con un real decreto, con los presupuestos o con la gestión diaria. De lo que depende del Gobierno solo cuentan los decretos-leyes, porque el Pleno tiene que convalidarlos.
- En cada votación se indica si el partido estaba en el Gobierno o en la oposición. Si votó contra una promesa suya por un pacto de coalición, aquí se ve.
- Un programa que todavía no se ha revisado sale como **aún sin revisar** y no cuenta en las cifras.`)));
  return cont;
};

// Comparar · Programas: los programas de los partidos entre sí, sin votos. Clic en una cifra para ver esos compromisos
// en Activismo · Programas electorales.
VISTAS["comparar-programas"] = async (ruta) => {
  const cabecera = [subnav(NAV_COMPARAR, "comparar-programas", ruta), el("h2", {}, "Comparar programas electorales")];
  if (!(await cargarProgramas())) return el("div", {}, cabecera, el("div", { class: "vacio" }, "Todavía no hay programas electorales."));
  const opciones = opcionesProgramas();
  // Sin elección elegida, la última: sumar programas de años distintos mezcla épocas.
  const leg = ruta.leg || String((opciones.legislaturas[0] || {}).legislatura || "");
  const d = await api("programasComparar", { g: ruta.g, leg, tema: ruta.tema });
  const verCompromisos = (cambios) => irA("programas", { leg, tema: ruta.tema, ...cambios });
  const cont = el("div", {}, cabecera,
    el("p", { class: "sub" }, "Los programas de los partidos comparados entre sí, contando solo las promesas concretas. Aquí no entra lo que votaron después: eso está en Activismo · Programas electorales."),
    formFiltros([
      multiSelect("g", opciones.partidos.map((s) => [s, s]), ruta.g, "Todos los partidos", "partidos"),
      multiSelect("leg", opciones.legislaturas.map((l) => [l.legislatura, `${eleccionTexto(l.eleccion)} · ${legTexto(l.legislatura)}`]), leg, "Última elección", "elecciones"),
      multiSelect("tema", optTemas(), ruta.tema, "Todos los temas", "temas"),
    ], { ...ruta, leg }, (f) => irA("comparar-programas", f)));
  if (!d.acciones.length) {
    cont.append(el("div", { class: "vacio" }, "Ninguna promesa concreta con estos filtros."));
    return cont;
  }

  const suma = (m, k, n) => m.set(k, (m.get(k) || 0) + n);
  const ladoDe = Object.fromEntries(LADOS_ACCION.slice(0, 2).flatMap(([lado, as]) => as.map((a) => [a, lado])));
  const verificables = new Map(), nTema = new Map(), nAccion = new Map(), nLado = new Map();
  for (const r of d.acciones) {
    suma(verificables, r.partido, r.n);
    suma(nAccion, r.partido + "|" + r.accion, r.n);
    if (!r.tema) continue;
    suma(nTema, r.partido + "|" + r.tema, r.n);
    if (ladoDe[r.accion]) suma(nLado, `${r.partido}|${r.tema}|${ladoDe[r.accion]}`, r.n);
  }
  const partidos = [...verificables.keys()].sort((a, b) => verificables.get(b) - verificables.get(a));
  const temas = META.temas.map((t) => t.codigo).filter((t) => partidos.some((s) => nTema.get(s + "|" + t)));
  const cabeceraPartidos = (primera, nota) => el("thead", {}, el("tr", {}, el("th", {}, primera),
    partidos.map((s) => el("th", { class: "num" }, swatch(colorSiglas(s)), s, nota ? el("div", { class: "small muted", style: "font-weight:400" }, nota(s)) : null))));

  // 1. Qué quiere quitar y qué añadir cada partido, en total y por tema.
  const columnas = LADOS_ACCION.map(([lado, as]) => [lado, as.filter((a) => partidos.some((s) => nAccion.get(s + "|" + a)))]).filter(([, as]) => as.length);
  const cifra = (n, cambios, titulo) => n ? el("a", { href: "#", title: titulo, onclick: (e) => { e.preventDefault(); verCompromisos(cambios); } }, fmt(n)) : el("span", { class: "muted" }, "—");
  const temasLado = temas.filter((t) => partidos.some((s) => nLado.get(`${s}|${t}|Quitan`) || nLado.get(`${s}|${t}|Añaden`)));
  const accionesDe = (lado) => LADOS_ACCION.find(([l]) => l === lado)[1].join(",");
  cont.append(el("div", { class: "card" }, el("h3", {}, "Qué quiere quitar y qué añadir cada partido"),
    el("p", { class: "small muted" }, "Las promesas concretas de cada programa según el tipo de medida. Quitan las que derogan una norma o bajan un impuesto. Añaden las que suben o crean un impuesto, dan dinero (ayudas, prestaciones, inversión) o crean un organismo o un plan. Una ley nueva puede ampliar derechos o recortarlos, así que legislar no se cuenta en ningún lado. Quitar tampoco es siempre de izquierdas o de derechas: depende de qué se deroga o qué impuesto se baja."),
    el("p", { class: "small muted" }, "Debajo de cada cifra, qué parte es de todas las promesas concretas del partido: los programas tienen tamaños muy distintos. Pulsa una cifra para leer esas promesas."),
    el("table", { class: "tabla" },
      el("thead", {},
        el("tr", {}, el("th", {}), columnas.map(([lado, as]) => el("th", { colspan: as.length, style: "text-align:center" }, lado)), el("th", {})),
        el("tr", {}, el("th", {}, "Partido"), columnas.flatMap(([, as]) => as.map((a) => el("th", { class: "num" }, ACCION_COMPROMISO[a]))), el("th", { class: "num" }, "Promesas concretas"))),
      el("tbody", {}, partidos.map((s) => el("tr", {}, el("td", { style: "white-space:nowrap" }, swatch(colorSiglas(s)), s),
        columnas.flatMap(([, as]) => as.map((a) => {
          const n = nAccion.get(s + "|" + a);
          return el("td", { class: "num" }, cifra(n, { g: s, accion: a }, `${s}: ${ACCION_COMPROMISO[a].toLowerCase()}`),
            n ? el("div", { class: "small muted" }, `${pct(n, verificables.get(s))}%`) : null);
        })),
        el("td", { class: "num" }, fmt(verificables.get(s))))))),
    temasLado.length ? el("div", {}, el("h4", {}, "Por tema"),
      el("p", { class: "small muted" }, "En cada tema, cuántas promesas quitan algo (−) y cuántas añaden (+)."),
      el("table", { class: "tabla" }, cabeceraPartidos("Tema"),
        el("tbody", {}, temasLado.map((t) => el("tr", {}, el("td", {}, temaNombre(t)),
          partidos.map((s) => {
            const quitan = nLado.get(`${s}|${t}|Quitan`) || 0, anaden = nLado.get(`${s}|${t}|Añaden`) || 0;
            if (!quitan && !anaden) return el("td", { class: "num muted" }, "—");
            return el("td", { class: "num", style: "white-space:nowrap" },
              quitan ? ["−", cifra(quitan, { g: s, tema: t, accion: accionesDe("Quitan") }, `${s}, ${temaNombre(t)}: lo que quita`)] : null,
              quitan && anaden ? " " : null,
              anaden ? ["+", cifra(anaden, { g: s, tema: t, accion: accionesDe("Añaden") }, `${s}, ${temaNombre(t)}: lo que añade`)] : null);
          })))))) : null));

  // 2. Cuánto pesa cada tema en el programa de cada partido y en lo que presentó después (sin el Congreso en el
  // ámbito, solo en el programa).
  const conCongreso = META.cuerpos.includes("congreso");
  const prop = new Map(d.propuestas.map((r) => [r.partido + "|" + r.tema, r.n]));
  const totalProp = (s) => d.propuestas.filter((r) => r.partido === s).reduce((a, r) => a + r.n, 0);
  // Con menos iniciativas que esto, un porcentaje por tema dice poco (con 6, cada una es el 17 %): no se enseña.
  const MIN_PROP = 20;
  const notaPartido = (s) => conCongreso ? `${fmt(verificables.get(s))} promesas · ${fmt(totalProp(s))} iniciativas` : `${fmt(verificables.get(s))} promesas`;
  const hayPocas = conCongreso && partidos.some((s) => totalProp(s) < MIN_PROP);
  cont.append(el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "Cuánto pesa cada tema"),
    el("p", { class: "small muted" }, conCongreso
      ? "En cada casilla, dos porcentajes. El primero es la parte de las promesas concretas del programa que son de ese tema. El segundo, la parte de las iniciativas que presentó el grupo en el Congreso durante la legislatura siguiente. En negrita, los temas en los que se separan 10 puntos o más. Pulsa un tema para leer sus promesas."
      : "Parte de las promesas concretas de cada programa que son de cada tema. Pulsa un tema para leer sus promesas. Si eliges «Nacional» en el ámbito, sale también la parte de lo que presentó cada grupo en el Congreso.",
      hayPocas ? ` Si un grupo presentó menos de ${MIN_PROP} iniciativas, solo sale el primer porcentaje: con tan pocas, cada una mueve mucho la cifra.` : ""),
    el("table", { class: "tabla" }, cabeceraPartidos("Tema", notaPartido),
      el("tbody", {}, temas.map((t) => el("tr", { class: "clic", onclick: () => verCompromisos({ g: ruta.g, tema: t }) }, el("td", {}, temaNombre(t)),
        partidos.map((s) => {
          const enProg = pct(nTema.get(s + "|" + t) || 0, verificables.get(s));
          if (!conCongreso || totalProp(s) < MIN_PROP) return el("td", { class: "num", style: "white-space:nowrap" }, `${enProg}%`);
          const enProp = pct(prop.get(s + "|" + t) || 0, totalProp(s));
          return el("td", { class: "num", style: `white-space:nowrap${Math.abs(enProg - enProp) >= 10 ? ";font-weight:700" : ""}` },
            `${enProg}%`, el("span", { class: "muted" }, ` · ${enProp}%`));
        })))))));
  return cont;
};

// Con soloContra, solo las iniciativas y las votaciones en las que el voto del partido no coincide con el compromiso.
function filaCompromiso(c, d, soloContra = false) {
  const [nombre, , explicacion] = ESTADO_COMPROMISO[c.estado || "generico"];
  const votosDe = (r) => d.votos.filter((v) => v.compromiso === c.id && v.legislatura === r.legislatura && v.expediente === r.expediente
    && (!soloContra || coincideVoto(v, r.sentido) === false));
  const rels = d.relacionadas.filter((r) => r.compromiso === c.id && (!soloContra || votosDe(r).length));
  const anio = (String(c.eleccion).match(/\d{4}/) || [""])[0];
  return el("article", { class: "compromiso" },
    el("div", { class: "small muted cabecera" },
      el("span", { class: "badge", title: explicacion }, puntoEstado(c.estado || "generico"), nombre),
      el("span", {}, [temaNombre(c.tema), ACCION_COMPROMISO[c.tipo_accion], c.verificable ? RESPONSABLE_COMPROMISO[c.responsable] : null].filter(Boolean).join(" · ")),
      el("a", { href: enlaceCita(c.url, c.formato, c.pagina).href, target: "_blank", rel: "noopener", title: c.programa_titulo },
        `Programa ${c.partido} ${anio}, ${enlaceCita(c.url, c.formato, c.pagina).texto}`),
      c.aprobada ? el("span", { class: "badge ok" }, "Se aprobó algo en esa línea") : null),
    el("div", { class: "texto" }, c.texto),
    el("blockquote", {}, `«${c.cita}»`),
    rels.length ? el("ul", { class: "relacionadas" }, rels.map((r) => filaRelacionada(r, c, votosDe(r))))
      : c.verificable && c.estado !== "por_comparar" ? el("p", { class: "small muted", style: "margin:0" }, "No hay ninguna iniciativa del Pleno sobre esto.") : null);
}

function filaRelacionada(r, c, votos) {
  const autor = r.grupo_autor ? grupo(r.legislatura, r.grupo_autor) : null;
  return el("li", {},
    el("div", {}, el("span", { class: "sentido-rel" }, SENTIDO_COMPROMISO[r.sentido] || r.sentido), " · ",
      r.votada ? el("a", { href: "#", onclick: (e) => { e.preventDefault(); abrir(`i:${r.legislatura}:${r.expediente}`); } }, textoCorto(r.titulo, 120))
        : r.titulo ? textoCorto(r.titulo, 120) : el("span", { class: "muted" }, r.expediente),
      autor ? el("span", { class: "muted" }, ` · presentada por ${autor.siglas}`) : null, " ", badgeResultado(r.resultado_final),
      // Las que aún no ha visto la segunda revisión cuentan, pero se avisa.
      r.estado === "propuesto" && r.sentido !== "relacionada"
        ? el("span", { class: "small muted", title: "La relación entre la promesa y la iniciativa todavía no se ha repasado con el criterio más estricto." }, " · pendiente de repasar") : null),
    votos.map((v) => lineaVoto(v, r.sentido, c.partido)),
    r.justificacion ? el("div", { class: "small muted" }, r.justificacion) : null);
}

// Si un voto coincide con el compromiso según el sentido de la iniciativa respecto a él (null si no se puede decir).
const coincideVoto = (v, sentido) => (sentido !== "relacionada" && (v.apoyo === "si" || v.apoyo === "no") ? (v.apoyo === "si") === (sentido === "misma") : null);

// Lo que votó el partido en una votación decisiva y si coincide con su programa (según el sentido de la iniciativa
// respecto al compromiso), con si estaba en el Gobierno o en la oposición.
function lineaVoto(v, sentido, partido) {
  const g = gobiernoEn(infoLeg(v.legislatura).cuerpo || "congreso", v.fecha);
  const enGobierno = g && (g.partido === partido || lista(g.socios).includes(partido));
  const coincide = coincideVoto(v, sentido);
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

// ---- en una causa (Activismo): qué prometieron los partidos sobre lo mismo ----

// Compromisos verificables que encajan con una causa, con los mismos criterios que sus votaciones: tema (el del
// compromiso), etiqueta exacta, palabras en el texto, la cita o las etiquetas, y legislatura que cubre el programa.
API.programasCausa = (p) => {
  const w = ["c.verificable=1"], a = [];
  condIn(w, a, "c.tema", p.tema);
  condIn(w, a, "p.legislatura", p.leg, Number);
  condJson(w, a, "c.etiquetas", p.etiqueta);
  for (const palabra of (p.q || "").split(/\s+/).filter(Boolean)) {
    w.push("(c.texto LIKE ? OR c.cita LIKE ? OR c.etiquetas LIKE ?)");
    a.push(...Array(3).fill(`%${palabra}%`));
  }
  return q(`SELECT c.id, c.texto, c.cita, c.pagina, c.orden, p.partido, p.eleccion, p.fecha_eleccion, p.url, p.formato,
      COALESCE(ce.estado, 'generico') AS estado
    FROM compromiso c JOIN programa p ON p.id=c.programa LEFT JOIN compromiso_estado ce ON ce.compromiso=c.id
    WHERE ${w.join(" AND ")}`, a);
};

// Causa con el bloque abierto: marcar el scorecard vuelve a pintar la vista y así no se cierra.
let causaConProgramas = null;

// Bloque de una causa: cerrado hasta que se pulsa (entonces descarga los programas). Solo sale si hay algún programa
// leído de las legislaturas de la causa.
function bloqueCausaProgramas(causa) {
  if (!CATALOGO.programas) return null;
  const [wl, al] = enSQL("legislatura", causa.leg, { conv: Number });
  if (!q1(`SELECT 1 AS x FROM programa WHERE estado='leido' ${wl}`, al)) return null;
  const clave = JSON.stringify([causa.q, causa.tema, causa.etiqueta, causa.leg]);
  const cuerpo = el("div", {});
  const abrirBloque = async () => {
    causaConProgramas = clave;
    cuerpo.replaceChildren(el("p", { class: "muted small" }, "Cargando los programas…"));
    await cargarProgramas();
    const cs = await api("programasCausa", { q: causa.q, tema: causa.tema, etiqueta: causa.etiqueta, leg: causa.leg });
    cuerpo.replaceChildren(listaCausaProgramas(cs, causa));
  };
  cuerpo.append(el("button", { class: "boton", onclick: abrirBloque }, "Ver qué prometían los partidos"));
  if (causaConProgramas === clave) abrirBloque();
  return el("div", { class: "card", style: "margin-top:16px" }, el("h3", {}, "¿Qué prometieron sobre esto?"),
    el("p", { class: "small muted" }, "Promesas concretas de los programas electorales que tienen que ver con esta causa, y qué votó después cada partido. Primero salen las que llegaron a votarse. Las promesas genéricas no se enseñan."),
    cuerpo);
}

function listaCausaProgramas(cs, causa) {
  if (!cs.length) return el("p", { class: "muted" }, "Ninguna promesa concreta de los programas tiene que ver con esta causa.");
  const orden = Object.keys(ESTADO_COMPROMISO);
  cs.sort((a, b) => orden.indexOf(a.estado) - orden.indexOf(b.estado) || b.fecha_eleccion.localeCompare(a.fecha_eleccion) || a.orden - b.orden);
  const porPartido = new Map();
  for (const c of cs) porPartido.set(c.partido, [...(porPartido.get(c.partido) || []), c]);
  const item = (c) => {
    const [nombre, , explicacion] = ESTADO_COMPROMISO[c.estado];
    const cita = enlaceCita(c.url, c.formato, c.pagina);
    return el("li", {},
      el("div", {}, el("span", { class: "badge", title: explicacion }, puntoEstado(c.estado), nombre), " ", c.texto),
      el("div", { class: "small muted" }, el("a", { href: cita.href, target: "_blank", rel: "noopener", title: `«${c.cita}»` },
        `Programa ${c.partido}, ${eleccionTexto(c.eleccion).toLowerCase()}, ${cita.texto}`)));
  };
  const MUESTRA = 5;
  const enlace = Object.entries({ tema: causa.tema, leg: causa.leg }).filter(([, v]) => v);
  return el("div", {},
    [...porPartido.entries()].sort((a, b) => b[1].length - a[1].length).map(([s, xs]) => {
      const ul = el("ul", { class: "relacionadas" }, xs.slice(0, MUESTRA).map(item));
      const mas = xs.length > MUESTRA ? el("button", { class: "boton", style: "margin-top:6px", onclick: () => { ul.replaceChildren(...xs.map(item)); mas.remove(); } }, `Ver los ${fmt(xs.length)}`) : null;
      return el("div", { style: "margin-top:12px" },
        el("div", { style: "margin-bottom:6px" }, swatch(colorSiglas(s)), el("b", {}, s), el("span", { class: "small muted" }, ` · ${fmt(xs.length)} ${xs.length === 1 ? "promesa" : "promesas"}`)),
        ul, mas);
    }),
    el("p", { class: "small", style: "margin:12px 0 0" }, el("a", { href: "#/programas" + (enlace.length ? "?" + new URLSearchParams(enlace) : "") },
      "Ver cada promesa con sus iniciativas y lo que votó el partido →")));
}

// Partidos del índice programa_iniciativa (en comun.js, sin descargar programas.js), como texto: «PSOE y Sumar».
function textoPartidos(v) {
  const xs = lista(v).sort((a, b) => a.localeCompare(b, "es"));
  return xs.length > 1 ? `${xs.slice(0, -1).join(", ")} y ${xs.at(-1)}` : xs[0] || "";
}

// Línea de la ficha de una votación: en qué programas aparece su iniciativa, con enlace a la ficha de la iniciativa.
function lineaProgramas(leg, exp) {
  const r = q1("SELECT partidos FROM programa_iniciativa WHERE legislatura=? AND expediente=?", [+leg, exp]);
  if (!r) return null;
  return el("p", { class: "small" }, el("a", { href: "#", onclick: (e) => { e.preventDefault(); abrir(`i:${leg}:${exp}`); } },
    `Sale en ${lista(r.partidos).length > 1 ? "los programas electorales" : "el programa electoral"} de ${textoPartidos(r.partidos)}. Ver qué prometían →`));
}

// Bloque del detalle de una iniciativa: qué partidos llevaban en su programa algo relacionado. Solo descarga los
// programas si la iniciativa aparece en alguno (programa_iniciativa, en comun.js).
async function bloqueProgramas(leg, exp) {
  if (!q1("SELECT 1 AS x FROM programa_iniciativa WHERE legislatura=? AND expediente=?", [+leg, exp])) return null;
  await cargarProgramas();
  const cs = API.programasIniciativa({ leg, exp });
  if (!cs.length) return null;
  return el("section", {}, el("h3", {}, "En los programas electorales"),
    el("p", { class: "small muted" }, "Partidos que prometieron algo sobre este asunto en las elecciones. Para cada uno, si la iniciativa iba en la línea de su promesa y si lo que votó encaja con ella."),
    el("ul", { class: "relacionadas" }, cs.map((c) => {
      const votos = votosPartido(leg, exp, c.partido);
      return el("li", {},
        el("div", {}, swatch(colorSiglas(c.partido)), el("b", {}, c.partido), " · ", SENTIDO_COMPROMISO[c.sentido] || c.sentido, " · ",
          el("a", { href: enlaceCita(c.url, c.formato, c.pagina).href, target: "_blank", rel: "noopener" },
            `${eleccionTexto(c.eleccion)}, ${enlaceCita(c.url, c.formato, c.pagina).texto}`)),
        el("div", {}, c.texto),
        votos.length ? votos.map((v) => lineaVoto(v, c.sentido, c.partido)) : el("div", { class: "small muted" }, "Todavía no se ha votado."));
    })),
    el("p", { class: "small" }, el("a", { href: "#/programas" }, "Ver todos los programas y lo que votó cada partido →")));
}
