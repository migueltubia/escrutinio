"use strict";
// Ayuda: página general (#/ayuda) y ayuda de cada pestaña, que se abre en el panel lateral con el
// botón «Cómo se lee» junto al título de cada vista (ver=ayuda:<vista>). El texto va en markdown
// sencillo (### títulos, listas con «- », **negrita** y [enlaces](#/ruta)).

// ------------------------------------------------------------------ ayuda de cada pestaña

const AYUDA = {
  resumen: {
    titulo: "Resumen",
    texto: `
Panorama general: cuánto se vota en el Pleno, qué sale adelante, de qué temas y cómo cambia la actividad con el tiempo.

### Cómo se lee
- **Cifras de arriba**: votaciones nominales, votos individuales de diputados, diputados distintos y fichas de asuntos.
- **Lo que se vota y lo que se aprueba**: asuntos que llegaron a votarse, por tipo, y cómo acabaron. En leyes y decretos-leyes cuenta el resultado oficial de su tramitación (una ley se vota muchas veces); en PNL y mociones, el de su votación.
- **Asuntos votados por tema**: cada asunto tiene un tema principal de una lista cerrada de 23.
- **Votaciones por mes**: pasa el ratón (o toca) una columna para ver el total y cuántas fueron ajustadas. Los picos de otoño son los Presupuestos, con cientos de votaciones de enmiendas.
- **Análisis**: comentario de las estadísticas que calcula la web.

### Filtros
- **Legislaturas**: una o varias.

### Se actualiza
- Cifras y gráficos: cada día. El análisis redactado: cada semana.
`,
  },
  votaciones: {
    titulo: "Votaciones",
    texto: `
Buscador de todas las votaciones nominales del Pleno desde 2012, con lo que votó cada grupo y cada diputado.

### Cómo se lee
- Cada tarjeta es **una votación**: fecha, asunto, qué se votaba exactamente (una enmienda, un punto…), resultado, tipo de votación, tema y quién lo propone.
- **Barra**: votos a favor (azul), abstenciones (gris) y en contra (rojo).
- **Etiquetas de grupo**: ✓ sí, ✗ no, ~ abstención, ± dividido. Con borde, los grupos **decisivos**: si hubieran votado otra cosa, el resultado habría cambiado.
- **«Votación decisiva»**: la que decide la suerte del asunto (la de conjunto de una ley orgánica, la convalidación de un decreto, la de una PNL…).
- **«Derrota del Gobierno»**: perdió lo que votó el partido del presidente del Gobierno (votó sí y se rechazó, o no y se aprobó).
- Toca una tarjeta para ver el **detalle**: voto de cada diputado, voto por grupo, quién gobernaba, ficha del asunto y las demás votaciones del mismo asunto.

### Filtros
- **Texto**: busca en títulos y expedientes (p. ej. «vivienda» o «162/000123»).
- **Legislaturas, tipo de votación, tipo de iniciativa, tema, resultado y proponente**: admiten varias opciones.
- **Fechas**, **Solo decisivas** (una por asunto), **Ajustadas** (10 votos o menos de diferencia) y **Derrotas del Gobierno** (solo donde la fuente publica el voto de cada grupo).
- **Exportar a CSV**: las votaciones filtradas, con el voto de cada grupo, para abrir en una hoja de cálculo (hasta 30.000, las más recientes).

### Ten en cuenta
- Un asunto puede tener decenas de votaciones (enmiendas, totalidad, conjunto…). Para contar asuntos usa **Solo decisivas** o la pestaña [Iniciativas](#/iniciativas).
- Lo aprobado por asentimiento no tiene voto nominal.
`,
  },
  iniciativas: {
    titulo: "Iniciativas",
    texto: `
Una ficha por asunto que llegó a votarse en el Pleno: qué es, quién lo propone, de qué trata y cómo acabó.

### Cómo se lee
- **Resumen, tema y etiquetas** describen el asunto a partir de su título oficial. Votos y resultados son los oficiales.
- **Resultado**: en leyes y decretos-leyes, el oficial de su tramitación (aprobada, convalidado, derogado, caducada, retirada, subsumida en otra…); en PNL y mociones, el de su votación.
- Toca una ficha para ver todas sus votaciones y los enlaces al Boletín de las Cortes (BOCG) y al BOE.

### Filtros
- **Texto**: busca en títulos, resúmenes y etiquetas.
- **Legislaturas, tema, tipo, proponente y resultado**: varias opciones a la vez.
- **Marca**: «emergencia» (responde a una catástrofe o crisis concreta: COVID, DANA, guerra de Ucrania…) u «ómnibus» (mezcla tres o más temas sin relación).

### Ten en cuenta
- Las iniciativas «sintéticas» (expediente SIN/…) son votaciones que no se pudieron enlazar con un expediente del Congreso; llevan el texto de la votación.
`,
  },
  temas: {
    titulo: "Temas",
    texto: `
Compara los 23 temas: cuánto se vota de cada uno y cuánto sale adelante.

### Cómo se lee
- **Éxito por tema**: asuntos votados y porcentaje aprobado, separando lo que tiene fuerza de ley (leyes y decretos) de lo declarativo (PNL y mociones). Toca un tema para analizarlo a fondo, con quién propone y quién lo consigue.
- **Etiquetas más frecuentes**: palabras clave que captan la actualidad (toca una para buscarla).
- **Leyes que más se intenta modificar**: normas citadas en los títulos de lo votado.

### Filtros
- **Legislaturas**: una o varias.
`,
  },
  tema: {
    titulo: "Análisis de un tema",
    texto: `
Todo sobre uno o varios temas: cómo vota cada grupo, quién propone y quién lo consigue, y la votación a votación.

### Cómo se lee
- **Cómo vota cada grupo**: porcentaje de asuntos en que votó a favor en la votación decisiva, sin contar lo que presenta el propio grupo ni, mientras gobierna, lo que presenta el Gobierno (casi siempre lo apoya). Al pasar el ratón, también el porcentaje contando lo propio. Cada asunto cuenta una vez: una PNL votada en 8 puntos no pesa 8 veces más que una ley. Entre paréntesis, la diferencia con su media general: «+12» quiere decir que en este tema vota a favor 12 puntos más que de costumbre.
- **Quién propone y quién lo consigue**: asuntos del tema según quién los presentó y cómo acabaron.
- **Con quién coincide cada grupo en este tema** y **cómo cambia su apoyo de una legislatura a otra**: los enlaces llevan a Grupos, con el tema elegido, y a Comparar, que separa lo que presenta cada uno de lo que presentan los demás.
- **Subtemas**: etiquetas de los asuntos; toca una para limitar todo el análisis a esos asuntos.
- **Votación a votación**: una fila por votación decisiva y una columna por grupo: azul a favor, rojo en contra, gris abstención, gris claro dividido.

### Filtros
- **Temas** (varios a la vez), **legislaturas** y **tipo de asunto**.
- **Contar también si es tema secundario**: incluye asuntos cuyo tema principal es otro.
- **Solo ajustadas**: en la votación a votación, las decididas por 10 votos o menos.

### Ten en cuenta
- En las enmiendas a la totalidad votar «sí» es votar contra el proyecto, así que ese voto se invierte y cuenta como «en contra» del asunto.
- Cada grupo vota casi siempre a favor de lo que presenta él mismo (y el partido del Gobierno, de lo que presenta el Gobierno): por eso no se cuenta. En la oposición, lo del Gobierno sí cuenta. En [Comparar](#/comparar), «lo que presentan otros grupos» deja fuera además todo lo del Gobierno, para medir a todos los grupos con la misma base.
- Votar a favor de asuntos de un tema no es apoyar «el tema»: un mismo tema reúne propuestas en direcciones opuestas.
- Los debates de política general (estado de la nación, de la comunidad…) no cuentan en ningún tema: sus propuestas de resolución tratan de cualquier asunto.
`,
  },
  grupos: {
    titulo: "Grupos",
    texto: `
Las relaciones entre grupos: con quién vota cada uno y quién tiene la llave de las votaciones.

### Cómo se lee
- **Afinidad entre grupos**: porcentaje de votaciones de fondo en que dos grupos votan lo mismo. Más oscuro, más coincidencia; «·» si tienen menos de 5 votaciones en común. Toca un grupo para ver su perfil.
- **Grupo decisivo**: en cuántas votaciones decisivas el voto del grupo determinaba el resultado. «Bastaba con abstenerse» (oscuro) es el caso más fuerte; «cambiando el voto» (claro), que tendría que haber votado lo contrario.
- **Las más ajustadas**: leyes, decretos, tomas en consideración y totalidades decididas por menos margen, con los grupos que las decidían.

### Filtros
- **Legislaturas**: por defecto, la actual. Con varias, cada partido suma todas sus votaciones.
- **Temas**: la afinidad solo en esos temas.

### Ten en cuenta
- El Grupo Mixto reúne partidos distintos; su «voto» es el de la mayoría de sus miembros.
`,
  },
  grupo: {
    titulo: "Perfil de grupo",
    texto: `
El perfil de un partido (o de un bloque de varios): cómo vota, qué propone, con quién coincide y cuándo decide.

### Cómo se lee
- **Cifras**: porcentaje de asuntos en que votó a favor (votación decisiva de fondo; cada asunto cuenta una vez), sin contar lo que presentó él ni, mientras gobernaba, el Gobierno, y al lado el porcentaje contando lo propio; porcentaje de sus iniciativas que salen adelante; veces que su abstención habría bastado para cambiar el resultado; y cuántas veces se partió el grupo (10% o más de sus diputados contra la mayoría).
- **Cómo vota en cada tema**: a favor por tema y, entre paréntesis, diferencia con su media, con la misma medida (sin lo propio).
- **Sus iniciativas, por tema**: lo que presentó y llegó a votarse, y cómo acabó.
- **Con quién coincide**: afinidad con cada grupo y los temas en que más y menos coinciden.
- **Cuándo su voto decidió el resultado**: votaciones en que bastaba con que se abstuviera para que salieran al revés.

### Filtros
- **Grupo**: con varios, se analizan juntos como un **bloque** (se suman sus votos, iniciativas y afinidades con el resto).
- **Legislaturas** y **tipo de asunto**.

### Ten en cuenta
- Las siglas agrupan los grupos de un mismo partido en distintas legislaturas.
- Lo que prometió en su programa frente a lo que votó está en [Activismo · Programas electorales](#/programas).
`,
  },
  programas: {
    titulo: "Programas electorales",
    texto: `
Lo que prometió cada partido en su programa electoral y lo que votó después en el Pleno.

### Cómo se lee
- **Dónde votaron en contra de lo que prometieron**: los compromisos en los que el partido votó al menos una vez lo contrario de lo que prometía (*contradicho*, o *mixto* si también votó a favor en otras iniciativas relacionadas), con la cita del programa y solo esas votaciones: quién presentó la iniciativa, qué votó el partido y si gobernaba.
- **Los programas**: cuántos compromisos tiene cada uno, cuántos son verificables y, de los que tuvieron votación en un sentido claro, cuántos **coinciden** con lo que votó el partido. La mayoría de lo prometido no llega a votarse en el Pleno.
- **En el Gobierno y en la oposición**: la misma cifra según el partido estuviera en el Gobierno o en la oposición cuando se votó lo relacionado con cada compromiso (sale si hay programas de un partido en los dos lados).
- **Cuánto pesa cada tema** en el programa de cada partido frente a lo que presentó después en el Congreso.
- **Qué quiere quitar y qué añadir cada partido**: sus compromisos verificables por tipo de medida, en total y por tema. Quitan: derogar una norma o bajar un impuesto; añaden: subir o crear un impuesto, dar dinero o crear un organismo o un plan; legislar no tiene signo. Quitar no es siempre el mismo lado (depende de qué se deroga): pulsa una cifra para ver esos compromisos.
- **Compromisos**: cada uno con la cita literal del programa y su página (el enlace abre el PDF en esa página), las iniciativas del Pleno que tratan lo mismo (**en su dirección**, **en la contraria** o sin dirección clara) y lo que votó el partido, en el Gobierno o en la oposición. Su estado: *impulsado* (presentó algo en su dirección, o lo presentó el Gobierno mientras gobernaba), *apoyado* (votó a favor de algo en su dirección o en contra de algo en la contraria), *contradicho* (lo inverso), *mixto* (votos en los dos sentidos), *abstención*, *sin votación* y *no verificable en el Parlamento* (depende del Gobierno o de otra Administración). Un programa leído que aún no se ha comparado con lo votado sale como *pendiente de comparar* y no cuenta en las cifras.

### Filtros
- **Partido**, **elección** (y la legislatura que cubre), **tema** (los mismos que en las votaciones), **tipo de acción** (legislar, derogar, bajar un impuesto…) y **estado** del compromiso. El estado solo filtra la lista de compromisos.

### Ten en cuenta
- **Sin votación no es incumplimiento**: muchas promesas se cumplen o no por real decreto, por presupuestos o por gestión, sin pasar por el Pleno.
- Un programa más concreto tiene más compromisos verificables; conviene mirar cuántos tiene cada partido antes de comparar porcentajes.
- Qué iniciativas tratan lo mismo que un compromiso se decide sin tener en cuenta qué partido lo prometió ni quién presentó la iniciativa. Las que van en su dirección o en la contraria se comprueban en una segunda revisión más estricta: no basta con que se llamen parecido.
- Los partidos que votan dentro del Grupo Mixto no tienen un voto de grupo propio con el que comparar.
`,
  },
  comparar: {
    titulo: "Comparar grupos",
    texto: `
Pone a dos o más grupos frente a frente en los mismos asuntos, tema a tema y legislatura a legislatura, para comprobar con los votos lo que dice cada uno.

### Cómo se lee
- **La frase de arriba**: en cuántos asuntos votaron lo mismo, distinto o «en parte» (asuntos votados por puntos en los que coincidieron en unos y no en otros). Con más de dos grupos, además, la coincidencia de cada pareja.
- **Cuánto apoya cada uno: todo o solo lo de otros**: porcentaje de asuntos en que el grupo votó a favor, primero de todo lo votado y luego solo de lo que presentan otros grupos. Cada grupo apoya casi siempre lo suyo (y el partido del Gobierno, lo del Gobierno), así que el primer número depende mucho de cuántos asuntos presentó cada uno. Si la diferencia sale de ahí, lo dice debajo.
- **A quién apoya cada uno**: filas, el grupo que vota; columnas, quién presenta el asunto. Recuadrado, lo propio.
- **Tema a tema y legislatura a legislatura**: un punto por grupo; cuanto más separados, más distinto votan. Puedes elegir si cuenta todo lo votado o solo lo que presentan otros grupos. Un punto hueco tiene menos de 3 asuntos. Toca un tema para compararlo a fondo.
- **Asunto a asunto**: lo votado, con la posición de cada grupo (✓ a favor, ✗ en contra, ~ abstención, ± dividido). Filtra por los que votaron distinto, en parte o igual, o por un subtema. Toca uno para ver el resumen, el voto nominal y la fuente oficial.

### Filtros
- **Grupos** (dos o más), **temas**, **legislaturas** y **tipo de asunto**, todos con varias opciones. Sin grupos elegidos, los dos mayores.

### Ten en cuenta
- Cuenta asuntos, no votaciones: si un asunto se votó por puntos, los puntos se reparten su peso. En los debates con propuestas de resolución, las de cada grupo cuentan como un asunto.
- Votar a favor de asuntos de un tema no es apoyar «el tema»: un mismo tema reúne propuestas en direcciones opuestas. Para puntuar con tu criterio qué voto era el bueno, usa [Mis causas](#/causas).
- Los debates de política general no tienen tema: solo cuentan con «Todos los temas».
- Lo que presenta el Gobierno va en su propia columna y no cuenta como «de otros grupos». En «Legislatura a legislatura» se indica quién gobernaba.
`,
  },
  coaliciones: {
    titulo: "Coaliciones ganadoras",
    texto: `
Qué combinaciones de grupos forman las mayorías que aprueban y las que tumban.

### Cómo se lee
- **En cuántas mayorías que aprueban está cada grupo**: de lo que salió adelante, en qué porcentaje votó a favor.
- **En cuántas mayorías que tumban**: de lo que se rechazó, en qué porcentaje votó en contra.
- **Combinaciones que aprueban / que tumban**: los grupos exactos que formaron la mayoría. Toca una fila para ver qué se aprobó o se tumbó con ella.

### Filtros
- **Legislaturas, tipo de asunto, tema** y **texto**.

### Ten en cuenta
- Se usa solo la votación decisiva de cada asunto, y en las enmiendas a la totalidad el voto se invierte.
`,
  },
  mapa: {
    titulo: "Mapa ideológico y polarización",
    texto: `
Sitúa a los grupos según cómo votan y mide si el Congreso está más o menos polarizado.

### Cómo se lee
- **Mapa**: dos grupos están cerca si votan igual a menudo. El tamaño del punto es su número de diputados. Cada eje lleva en sus extremos lo que mejor lo explica en los datos: cuánto se parece el voto de un grupo al del PP frente al del PSOE, cuántas veces se suma cuando PSOE y PP votan igual o cuántas veces vota con el lado ganador. Debajo se indica qué parte de las diferencias explica cada eje y cuánto encaja el indicador (correlación: 1 es un encaje perfecto).
- **Polarización por trimestre**: 0% si todos los grupos votan igual, 100% si cada par vota distinto (ponderado por diputados). Las líneas verticales marcan el inicio de cada legislatura.
- **Amplio acuerdo**: votaciones en que el 80% o más de los votos fue en el mismo sentido. **Ajustadas**: resueltas por 10 votos o menos.

### Filtros
- **Legislaturas** y **temas**: cambian el mapa (con varias, cada partido suma sus votaciones). Las series por trimestre cubren siempre todo el periodo.

### Ten en cuenta
- Un grupo sin suficientes votaciones en común con todos los demás no se puede situar; se indica debajo del mapa.
`,
  },
  disciplina: {
    titulo: "Disciplina y ausencias",
    texto: `
Quién vota distinto a su grupo, quién falta y qué votaciones habrían cambiado si hubieran votado los ausentes.

### Cómo se lee
- **Cohesión y asistencia por grupo**: votaciones de fondo en que el grupo se partió, votos no emitidos y votaciones perdidas por ausencias propias. Toca un grupo para filtrar por él.
- **Votan distinto a su grupo**: diputados que votaron distinto a la mayoría de su grupo (entre paréntesis, en votaciones decisivas).
- **Más votos no emitidos**: porcentaje de votaciones en que el diputado no votó (mínimo 100).
- **Votaciones que habrían cambiado con los ausentes**: si los ausentes del lado perdedor hubieran votado como su grupo, el resultado habría sido el contrario.
- Toca un diputado para ver su ficha.

### Filtros
- **Legislaturas** (varias se suman por diputado) y **grupos**.

### Ten en cuenta
- «No vota» incluye bajas, permisos y otras causas que los datos no distinguen; desde 2020 el voto telemático reduce mucho las ausencias.
- En el Mixto y el Plural no se cuentan discrepancias: reúnen partidos distintos. Un voto aislado puede ser un error al pulsar.
`,
  },
  enmiendas: {
    titulo: "Enmiendas",
    texto: `
Quién consigue cambiar las leyes en el Pleno.

### Cómo se lee
- **Enmiendas parciales**: votaciones de enmiendas de cada grupo y cuántas se aprobaron. Las transaccionales son acuerdos entre grupos.
- **Enmiendas a la totalidad**: de devolución o con texto alternativo; si prosperan, el proyecto vuelve al Gobierno.
- **Enmiendas del Senado**: cambios del Senado que el Congreso acepta o rechaza.
- **Quién apoya las enmiendas de quién**: filas, el grupo que presenta; columnas, el que vota; porcentaje de veces que votó a favor.
- **Leyes con más enmiendas aprobadas en el Pleno**.

### Filtros
- **Legislaturas**, **temas** y **Sin Presupuestos** (sus cientos de enmiendas pesan mucho).

### Ten en cuenta
- Solo cuentan las enmiendas que llegan a votarse en el Pleno; las pactadas en ponencia o comisión ya están dentro del texto. Una votación puede agrupar varias enmiendas.
`,
  },
  causas: {
    titulo: "Mis causas",
    texto: `
Sigue los asuntos que te importan y puntúa a grupos y diputados con tu propio criterio.

### Cómo se usa
- Crea una **causa** con un nombre y lo que quieres seguir: un texto (p. ej. «alquiler»), uno o varios temas o etiquetas, y las legislaturas.
- Cada causa muestra todo lo votado que encaja, las **novedades desde tu última visita** y un **scorecard**.
- **Ideas para empezar**: abre una de las etiquetas más frecuentes como causa sin guardarla.

### Ten en cuenta
- Tus causas se guardan **solo en este navegador**: no se envían a ningún sitio. Si borras los datos del navegador o cambias de dispositivo, se pierden; descarga el CSV si quieres conservarlas.
`,
  },
  causa: {
    titulo: "Una causa y su scorecard",
    texto: `
Todas las votaciones de tu causa y una puntuación de grupos y diputados según tu criterio.

### Cómo se usa
- En **Votación a votación**, marca en cada votación qué voto era el favorable para tu causa («A favor» o «En contra»). Puedes marcar toda la página de una vez.
- El **scorecard** calcula, para cada grupo y diputado, el porcentaje de las votaciones marcadas en que votó como marcaste. Abstenerse o dividirse cuenta como no coincidir.
- **¿Qué prometieron sobre esto?**: al pulsar, los compromisos concretos de los programas electorales que encajan con la causa (mismo tema, etiqueta o texto), por partido, con su estado según lo que votó después y el enlace a la página del programa.
- **Guardar causa** la conserva en este navegador; los botones de CSV descargan las votaciones y el scorecard.

### Ten en cuenta
- La puntuación refleja **tu** criterio, no una valoración de esta web.
`,
  },
  viene: {
    titulo: "Qué viene",
    texto: `
Lo que aún está por decidir: proyectos y proposiciones de ley abiertos en la legislatura actual, con su fase y sus plazos.

### Cómo se lee
- **Recién abiertas a enmiendas**: el plazo de enmiendas está en curso y apenas se ha ampliado. Es el momento de hacer llegar propuestas a los grupos.
- **Esperan el debate de toma en consideración**: proposiciones que el Pleno aún no ha debatido.
- **Paradas en comisión**: el plazo de enmiendas se ha ampliado muchas veces; suele indicar que no hay acuerdo para seguir.
- **Por tema y por fase**, y la lista completa, descargable en CSV.
- **En la línea del programa de…**: partidos que llevaban en su programa electoral un compromiso en la dirección de esa iniciativa. Toca la fila para ver qué prometía cada uno, con la cita y la página.

### Filtros
- **Texto**, **temas**, **fases** y **proponentes**.

### Se actualiza
- Cada día, con los datos abiertos del Congreso (fase, comisión y plazos).
`,
  },
};

// Botón «Cómo se lee» junto al título de cada vista.
function botonAyuda(vista, tab) {
  if (!AYUDA[tab]) return;
  const boton = el("button", { type: "button", class: "boton-ayuda", title: "Cómo se lee esta página", onclick: () => abrir(`ayuda:${tab}`) },
    el("span", { class: "ic", "aria-hidden": "true" }, "?"), el("span", {}, "Cómo se lee"));
  const h2 = vista.querySelector("h2");
  if (h2) h2.append(boton); else vista.prepend(boton);
}

function panelAyuda(clave) {
  const a = AYUDA[clave];
  if (!a) return el("div", { class: "vacio" }, "No hay ayuda para esta página.");
  return el("div", { class: "ayuda" },
    el("p", { class: "small muted", style: "margin:0" }, "Ayuda"),
    el("h2", {}, a.titulo),
    markdown(a.texto),
    el("p", { class: "small" }, el("a", { href: "#/ayuda" }, "Ayuda general: qué es, de dónde salen los datos y cuándo se actualizan →")));
}

// ------------------------------------------------------------------ página de ayuda general

const SECCIONES_WEB = [
  ["resumen", "Resumen", "Cifras generales, qué se vota y qué se aprueba, actividad por mes y un análisis de las cifras."],
  ["votaciones", "Votaciones", "Cualquier votación del Pleno, con el voto de cada grupo y de cada diputado. Exporta a CSV."],
  ["iniciativas", "Iniciativas", "Una ficha por asunto votado: qué es, quién lo propone, de qué trata y cómo acabó."],
  ["temas", "Temas", "Éxito por tema y quién consigue sacar adelante qué. Cada tema tiene su análisis a fondo."],
  ["grupos", "Grupos", "Afinidad entre grupos, quién decide las votaciones y el perfil de cada partido o bloque."],
  ["comparar", "Comparar grupos", "Dos o más partidos frente a frente, tema a tema: dónde votan igual, dónde no y cuánto apoya cada uno lo que presentan los demás."],
  ["coaliciones", "Coaliciones ganadoras", "Qué combinaciones de grupos aprueban y tumban cada cosa."],
  ["mapa", "Mapa ideológico", "Dónde se sitúa cada grupo según sus votos y cómo evoluciona la polarización."],
  ["disciplina", "Disciplina y ausencias", "Quién rompe la disciplina de voto, quién falta y qué votaciones cambiaron por las ausencias."],
  ["enmiendas", "Enmiendas", "Qué grupo consigue cambiar las leyes y quién apoya las enmiendas de quién."],
  ["causas", "Mis causas", "Sigue un asunto, recibe sus novedades y puntúa a grupos y diputados con tu criterio."],
  ["viene", "Qué viene", "Leyes abiertas: plazos de enmiendas, pendientes de debate y paradas en comisión."],
  ["programas", "Programas electorales", "Lo que prometió cada partido en su programa frente a lo que votó después: dónde votó en contra y compromiso a compromiso, con la cita."],
];

const ACTUALIZACIONES = [
  ["Votaciones del Pleno", "Cada día", "De lunes a sábado, a primera hora de la mañana. Se descargan las nuevas y se revisan las de las dos últimas semanas por si se publicaron incompletas. Los plenos suelen ser de martes a jueves."],
  ["Iniciativas en trámite: fase, comisión y plazos de enmiendas", "Cada día", "Legislatura actual, de los datos abiertos del Congreso. Alimenta «Qué viene»."],
  ["Resultado de tramitación de leyes y decretos", "Cada día", "Del buscador de iniciativas del Congreso."],
  ["Fichas de las iniciativas nuevas (resumen, tema, etiquetas)", "Cada día", "Se preparan en la actualización diaria siguiente a su aparición. Mientras no hay ficha, las leyes nuevas llevan un tema provisional según la comisión que las tramita."],
  ["Tipo de las votaciones poco habituales", "Cada día", "Las que las reglas no reconocen se clasifican con una lista cerrada."],
  ["Votaciones de parlamentos autonómicos, juntas generales y ayuntamientos", "Cada día", "Cada institución, desde su propia web. Si una web no responde, esa institución se queda sin actualizar ese día y la portada lo avisa con ⚠. Varias webs no aceptan conexiones desde fuera de España, y la actualización se hace en servidores de GitHub que están fuera."],
  ["Cálculos: resultados, grupo decisivo, afinidades, coaliciones, mapa, disciplina, enmiendas", "Cada día", "Se recalculan enteros en cada actualización, con reglas fijas."],
  ["Programas electorales: compromisos e iniciativas relacionadas", "Cada día", "Cada programa se lee una sola vez, cuando se incorpora. Cada día se buscan las iniciativas nuevas que tratan lo mismo que algún compromiso y se recalcula el estado de cada uno con los votos nuevos."],
  ["Análisis redactado de la portada", "Cada semana", "El domingo, a partir de las estadísticas calculadas."],
  ["Copia de los datos en el repositorio de GitHub", "Cada semana", "El domingo. La web publicada se actualiza cada día igualmente."],
  ["Legislaturas X a XIV", "No cambian", "Están cerradas. Solo cambiarían si el Congreso corrigiera sus datos."],
  ["Lista de temas, gobiernos, reglas de clasificación y equivalencias de etiquetas", "Con cambios en el código", "Revisadas a mano."],
  ["Tus causas y el tema claro u oscuro", "Nunca salen de tu navegador", "Se guardan en este dispositivo y en ningún otro sitio."],
];

const GLOSARIO = `
- **Votación nominal**: la que registra el voto de cada diputado (sí, no, abstención o no vota). Lo aprobado por asentimiento no tiene voto nominal.
- **Asunto o iniciativa**: lo que se vota (ley, decreto-ley, PNL, moción, convenio…). Un asunto puede tener muchas votaciones.
- **Abreviaturas**: **RDL**, real decreto-ley; **PL** y **PLO**, proyecto de ley (orgánica), que presenta el Gobierno; **PPL** y **PPLO**, proposición de ley (orgánica), que presentan los grupos, el Senado, las comunidades o la iniciativa popular; **PNL**, proposición no de ley (pide algo al Gobierno, sin fuerza de ley).
- **Votación decisiva**: la que decide la suerte de un asunto: la de conjunto de una ley orgánica, la convalidación de un decreto-ley, la de una PNL o moción, la toma en consideración o la totalidad de una ley…
- **Votación de fondo**: PNL, mociones, tomas en consideración, totalidades, votaciones de conjunto, convalidaciones… Se dejan fuera las enmiendas parciales y los trámites.
- **Apoyo**: si el grupo apoyó el asunto. En las enmiendas a la totalidad votar «sí» es votar contra el proyecto, así que ese voto se invierte.
- **Voto de un grupo**: el sentido que más votaron sus diputados; **dividido** si dos sentidos empatan.
- **Grupo decisivo**: el que habría cambiado el resultado votando de otra forma: **absteniéndose** (el caso más fuerte) o **cambiando el voto**.
- **Afinidad**: porcentaje de votaciones de fondo en que dos grupos votan lo mismo.
- **Cada asunto cuenta una vez**: en los porcentajes de apoyo por grupo, un asunto votado por puntos (una PNL, una moción) reparte su peso entre los puntos, para que no pese más que una ley que se vota una vez.
- **Lo propio y lo ajeno**: cada grupo vota casi siempre a favor de lo que presenta él mismo. Para comparar partidos, cuenta más cuánto apoya cada uno lo que presentan los demás.
- **Debate de política general**: el del estado de la nación, de la comunidad o de la región, o de orientación política del Gobierno. Cada grupo presenta propuestas de resolución sobre cualquier asunto, así que sus votaciones no cuentan en ningún tema. En el Congreso, cada propuesta se atribuye al grupo que la presenta.
- **Gobierno**: el presidente y los partidos que gobernaban en la fecha de cada votación; un Gobierno en funciones cuenta como el mismo. Sale en el detalle de cada votación. En un parlamento autonómico es el gobierno de la comunidad; en unas Juntas Generales, la Diputación Foral; en un ayuntamiento, el alcalde y los grupos de su equipo de gobierno.
- **Derrota del Gobierno**: votación que perdió el partido del presidente (o del alcalde): votó sí y se rechazó, o votó no y se aprobó. Solo se puede saber donde la fuente publica el voto de cada grupo, y no cuenta si el resultado publicado no cuadra con los totales.
- **Mayoría simple / absoluta**: más síes que noes, o 176 síes (leyes orgánicas y algunas votaciones).
- **Votación ajustada**: decidida por 10 votos o menos.
- **Iniciativa sintética (SIN/…)**: votación que no se pudo enlazar con un expediente del Congreso.
- **Tema provisional**: el que se deduce de la comisión que tramita una ley mientras no tiene ficha. Coincide con el definitivo en 9 de cada 10 casos.
- **Siglas y bloques**: las siglas agrupan los grupos de un mismo partido en distintas legislaturas. En el perfil de grupo, varios grupos elegidos a la vez se analizan juntos como un bloque.
`;

VISTAS.ayuda = async () => {
  const T = META.totales;
  const generado = T.generado ? new Date(T.generado) : null;
  const ultima = META.legislaturas.at(-1).hasta;
  const seccion = (id, titulo, ...hijos) => el("section", { class: "card ayuda-seccion", id }, el("h3", {}, titulo), ...hijos);
  const indice = [["que-es", "Qué es"], ["que-hace", "Qué puedes hacer"], ["actualizacion", "Qué se actualiza y cuándo"],
    ["fuentes", "De dónde salen los datos"], ["uso", "Cómo usarla"], ["glosario", "Conceptos"],
    ["limites", "Limitaciones"], ["privacidad", "Privacidad y código"]];
  return el("div", { class: "ayuda" },
    el("h2", {}, "Ayuda"),
    el("p", { class: "sub" }, "Qué es Escrutinio, qué puedes hacer con él, de dónde salen los datos y cada cuánto se actualizan. En cada pestaña, el botón «? Cómo se lee» junto al título explica esa página."),
    el("nav", { class: "subnav" }, indice.map(([id, t]) => el("a", { href: `#/ayuda`, onclick: (e) => { e.preventDefault(); document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" }); } }, t))),

    seccion("que-es", "Qué es",
      markdown(`
Escrutinio reúne **todas las votaciones nominales del Pleno del Congreso de los Diputados desde enero de 2012** (legislaturas X a XV): el voto de cada diputado y de cada grupo en ${fmt(T.votaciones)} votaciones, ${fmt(T.votos)} votos individuales y ${fmt(T.iniciativas)} asuntos votados.

Encima de esos datos oficiales calcula quién decide cada votación, con quién vota cada grupo, qué coaliciones aprueban cada cosa o quién rompe la disciplina de voto. Cada asunto tiene además una ficha con un resumen neutro y su tema, para poder buscar y agrupar por materias.

Es un proyecto independiente, no una web oficial del Congreso. Todo funciona en tu navegador: la web descarga una base de datos SQLite y hace las consultas en tu dispositivo, sin servidor.`),
      el("p", { class: "small muted" }, `Datos actualizados el ${generado ? generado.toLocaleString("es-ES", { dateStyle: "long", timeStyle: "short" }) : "—"}. Última votación: ${fecha(ultima)}.`)),

    seccion("que-hace", "Qué puedes hacer",
      el("table", { class: "tabla" }, el("tbody", {}, SECCIONES_WEB.map(([ruta, nombre, texto]) => el("tr", {},
        el("td", { style: "white-space:nowrap" }, el("a", { href: `#/${ruta}` }, nombre)),
        el("td", {}, texto),
        el("td", {}, AYUDA[ruta] ? el("button", { type: "button", class: "boton-ayuda", onclick: () => abrir(`ayuda:${ruta}`) }, el("span", { class: "ic" }, "?"), el("span", {}, "Cómo se lee")) : null)))))),

    seccion("actualizacion", "Qué se actualiza y cuándo",
      el("p", { class: "small muted" }, "La actualización es automática (GitHub Actions). Si un día el Congreso no publica nada, no cambia nada."),
      el("table", { class: "tabla" },
        el("thead", {}, el("tr", {}, el("th", {}, "Dato"), el("th", {}, "Frecuencia"), el("th", {}, "Detalle"))),
        el("tbody", {}, ACTUALIZACIONES.map(([dato, cada, detalle]) => el("tr", {},
          el("td", {}, dato), el("td", { style: "white-space:nowrap;font-weight:600" }, cada), el("td", { class: "small" }, detalle))))),
      avisoFuentes(Object.keys(CATALOGO.avisos || {}))),

    seccion("fuentes", "De dónde salen los datos",
      markdown(`
- **Votaciones y voto nominal**: datos abiertos de votaciones del Congreso, un fichero por votación.
- **Expediente, autor y resultado de tramitación**: buscador de iniciativas del Congreso.
- **Fase, comisión, plazos y enlaces al BOCG** (legislatura actual): datos abiertos de iniciativas del Congreso.
- **Resumen, tema, etiquetas y leyes afectadas**: fichas elaboradas a partir del título oficial.

Los votos, los totales y los resultados son siempre los oficiales. Lo que calcula la web (grupo decisivo, afinidad, coaliciones…) sale de ellos con reglas fijas.`)),

    seccion("uso", "Cómo usarla",
      markdown(`
- **Filtros**: todos admiten varias opciones a la vez. Los selectores se aplican al cerrarlos (tocando fuera o con «Aplicar»).
- **Enlaces para compartir**: la dirección de la página guarda los filtros; cópiala para compartir exactamente lo que ves.
- **Detalle**: toca cualquier votación, iniciativa o diputado para ver su ficha completa, con el título oficial entero.
- **Tooltips**: pasa el ratón (o toca en el móvil) por barras, celdas y etiquetas para ver las cifras.
- **CSV**: en Votaciones, Qué viene y Mis causas puedes descargar los datos para una hoja de cálculo.
- **Móvil**: las secciones están en la barra de abajo; Comparar, Análisis, Activismo y esta ayuda, en «Más».
- **Tema claro u oscuro**: botón ◐ arriba a la derecha.`)),

    seccion("glosario", "Conceptos", markdown(GLOSARIO)),

    seccion("limites", "Limitaciones",
      markdown(`
- **No hay 20 años**: el voto nominal en datos abiertos empieza en la X legislatura (enero de 2012).
- **Solo el Pleno del Congreso**: las comisiones no publican voto nominal y el Senado no está incluido.
- **Las fichas se hacen con el título oficial**, no con el texto completo de la iniciativa.
- **Los ficheros de votación no traen expediente**: se enlazan con la iniciativa por el título. Lo que no se puede enlazar queda como iniciativa sintética.
- **La comisión competente** solo está en los datos abiertos de la legislatura actual.
- **Algunas instituciones pueden ir con retraso**: si su web no responde en la actualización diaria (varias no aceptan conexiones desde fuera de España), se quedan como estaban hasta que vuelva a responder. La portada y el selector de ámbito las marcan con ⚠.`)),

    seccion("privacidad", "Privacidad y código",
      markdown(`
- La web no usa cookies ni analítica. Tus causas y el tema claro u oscuro se guardan solo en tu navegador.
- La web se sirve desde GitHub Pages, que como cualquier servidor registra las visitas.
- El código es libre (licencia MIT) y está en GitHub: [migueltubia/escrutinio](https://github.com/migueltubia/escrutinio). SQLite en el navegador con [sql.js](https://github.com/sql-js/sql.js).
- Los datos completos, con el voto de cada diputado, se pueden descargar del repositorio: una base SQLite por institución y legislatura en [data/bd](https://github.com/migueltubia/escrutinio/tree/main/data/bd).`)));
};
