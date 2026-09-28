# Análisis de votaciones parlamentarias con IA

Sep 26, 2026 · @Miguel

## Objetivo y enfoque

La idea es tener, para cada cosa que se vota en el Congreso y el Senado, una ficha con qué es, quién la propone, qué dice en dos frases, de qué temas trata, si salió adelante y cómo votó cada grupo. Con esas fichas se pueden responder preguntas como «qué se ha votado sobre vivienda esta legislatura y quién lo ha tumbado» o «qué leyes ha modificado de rebote una ley ómnibus».

El trabajo se reparte en dos mitades muy distintas. La primera es determinista: descargar los datos abiertos, normalizarlos y cruzarlos por número de expediente. Aquí no interviene la IA, porque los votos, los resultados y las relaciones entre normas ya vienen estructurados y un LLM solo añadiría errores. La segunda mitad es donde el LLM aporta: leer el texto de cada iniciativa, resumirlo, extraer qué leyes toca y clasificarlo por temas.

La regla que guía todo el diseño es que el LLM nunca calcula ni decide nada que ya esté en los datos. No se le pregunta «¿se aprobó?», se le da el resultado. Sus salidas se guardan como campos nuevos junto a los datos oficiales, con el modelo y la versión del prompt, para poder regenerarlas cuando cambie la taxonomía.

## Fuentes de datos

Son cinco fuentes y cada una cubre un hueco distinto. Ninguna basta por sí sola.

**1. Votaciones del Congreso.** Es la fuente central. El portal de [datos abiertos de votaciones](https://www.congreso.es/es/opendata/votaciones) publica un fichero por votación, agrupado por legislatura y sesión plenaria, en JSON, XML y PDF. La ruta tiene la forma `/webpublica/opendata/votaciones/Leg15/SesionNNN/AAAAMMDD/`. Cada fichero trae el número de expediente, el título, el texto del asunto votado (por ejemplo «Enmiendas del Grupo X» o «Votación de conjunto»), los totales y el voto nominal de cada diputado con su grupo. Tiene buena calidad desde la X legislatura (2011).

**2. Iniciativas del Congreso.** Están en [datos abiertos de iniciativas](https://www.congreso.es/es/opendata/iniciativas) en CSV, JSON y XML. Solo cubren las legislativas: proyectos de ley, proposiciones de ley, reformas de estatutos e iniciativas aprobadas. Sirven para saber el tipo, el autor, la situación y el resultado final de la tramitación de una ley. Las proposiciones no de ley y las mociones no están en este conjunto. Para ellas hay que tomar el título y el resultado de la propia votación y, si se quiere el texto, ir a la ficha web de la iniciativa.

**3. Votaciones del Senado.** El [catálogo del Senado](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/index.html) tiene [votaciones por iniciativa](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/votaciones/index.html) y [votaciones de mociones](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/votacionesmociones/index.html), sobre todo en XML. El Senado tiene su propia numeración de expedientes, así que para enlazar un proyecto de ley con su paso por el Congreso hay que emparejarlos (ver el apartado de cruces).

**4. Boletín Oficial de las Cortes Generales (BOCG).** Aquí está el texto de cada iniciativa: el texto presentado, las enmiendas, el informe de la ponencia, el dictamen de comisión y el texto aprobado. Es la única fuente de contenido para lo que no llega al BOE (todo lo rechazado y lo que sigue en trámite). Se publica en PDF, y la ficha de cada iniciativa enlaza sus publicaciones. Es lo que se le pasa al LLM.

**5. BOE, legislación consolidada.** Solo para lo que se aprueba y se publica. La [API de legislación consolidada](https://www.boe.es/datosabiertos/api/api.php) da, para cada norma, el texto por bloques (`/id/{id}/texto`) y un análisis (`/id/{id}/analisis`) en XML o JSON. El análisis trae las materias asignadas por el propio BOE y las referencias anteriores: la lista de normas que esta modifica, deroga, añade o cita, con el artículo afectado. Para una ley ómnibus, esta lista es la respuesta exacta a «qué leyes toca», sin necesidad de IA ([documentación](https://www.boe.es/datosabiertos/documentos/APIconsolidada.pdf)).

Hay algunas limitaciones que conviene asumir desde el principio. Las votaciones en comisión no tienen voto nominal. Los reales decretos-leyes no se votan como una ley: se vota su convalidación (y a veces su tramitación como proyecto de ley), y el texto ya está en el BOE antes de votarse. Y en las leyes con votación de conjunto por mayoría absoluta (orgánicas), el éxito depende del umbral, no de ganar a los noes.

## Modelo de datos y cruces

El eje de todo es la **iniciativa**, identificada por legislatura y número de expediente. Todo lo demás cuelga de ella: sus votaciones, sus textos, la norma del BOE en la que acaba y la clasificación que haga el LLM. Con una base de datos sencilla (SQLite o Postgres) bastan estas tablas:

- `iniciativa`: expediente, legislatura, tipo, título, autor o grupo proponente, fechas, situación, resultado final.
- `votacion`: cámara, sesión, fecha, expediente, texto del asunto, tipo de votación, totales, mayoría requerida, resultado.
- `voto`: votación, parlamentario, grupo en esa fecha, sentido del voto.
- `texto`: iniciativa, fase (presentado, enmiendas, dictamen, aprobado), URL del BOCG, texto extraído.
- `norma_boe`: id BOE-A, rango, número, fecha, materias del BOE.
- `relacion_normativa`: norma que actúa, norma afectada, tipo de relación (modifica, deroga, añade…), artículo.
- `ficha_llm`: iniciativa, resumen, temas, etiquetas, leyes afectadas extraídas, modelo y versión del prompt.

Los cruces, en el orden en que conviene hacerlos:

**Votación con iniciativa.** Se unen por expediente. El prefijo del expediente ya dice el tipo, lo que evita depender del título: por ejemplo, 121 son proyectos de ley, 122 proposiciones de ley de grupos, 130 reales decretos-leyes, 162 proposiciones no de ley en pleno y 173 mociones consecuencia de interpelación. Conviene sacar la tabla completa de prefijos de la propia web del Congreso y guardarla como catálogo.

**Tipo de cada votación dentro de una iniciativa.** Una ley genera muchas votaciones: toma en consideración, enmiendas a la totalidad, enmiendas parciales, votaciones separadas por artículos, votación de conjunto, veto o enmiendas del Senado y, en los decretos-leyes, convalidación y tramitación como proyecto de ley. Casi siempre el texto del asunto permite clasificarlas con reglas («conjunto», «totalidad», «convalidación», «enmienda»). Lo que no encaje con reglas se le pasa a un LLM pequeño con una lista cerrada de tipos. Este paso es imprescindible, porque de él depende qué votación decide si la iniciativa «sale».

**Resultado.** Para PNL y mociones, el resultado es el de su única votación. Para leyes se usa el estado final de la tramitación que da el conjunto de iniciativas, y se contrasta con la votación decisiva. Hay que calcular también el resultado a partir de los totales y la mayoría requerida (simple o absoluta, 176 en el Congreso). Si no coincide con el oficial, es un error de datos que conviene revisar a mano.

**Congreso con Senado.** Un proyecto de ley tiene un expediente en cada cámara. Si la ficha del Senado no indica la procedencia, se emparejan por título normalizado (sin tildes, mayúsculas ni artículos) y por fechas: la entrada en el Senado es posterior a la aprobación en el Congreso. Los casos dudosos se revisan a mano, porque son pocos.

**Iniciativa con BOE.** Las iniciativas aprobadas dan el número de ley resultante («Ley 12/2023»). Con eso se busca en la API del BOE y se obtiene el identificador BOE-A. Desde ahí se descargan las materias y las referencias anteriores, que llenan `relacion_normativa` con las leyes que modifica. Es el cruce que resuelve las leyes ómnibus.

**Parlamentario con grupo.** El grupo se guarda en cada voto con la fecha, no en el diputado, porque hay cambios de grupo, pases al Mixto y sustituciones. Todo el análisis por grupos se hace sobre el grupo que tenía en esa votación.

## Uso del LLM

El LLM trabaja sobre una iniciativa cada vez y devuelve siempre el mismo JSON. No se le pasan votos ni resultados para que resuma, solo el texto y los metadatos que necesita para situarse (tipo, proponente, fecha).

**Qué texto se le pasa.** Si la iniciativa se aprobó y está en el BOE, el texto consolidado de la norma. Si no, el texto del BOCG de la fase más avanzada a la que llegó: el presentado si no pasó la toma en consideración, el dictamen si murió después. Una PNL o una moción son una o dos páginas y caben enteras. Una ley larga no. Para esas se trocea por títulos y disposiciones: primero se resume cada bloque por separado y después se hace una segunda llamada que une los resúmenes. En las leyes ómnibus esto sale casi solo, porque cada disposición final suele modificar una ley distinta.

**Qué se le pide.** Cuatro cosas en una sola llamada:

1. Un resumen neutro de dos o tres frases que diga qué cambia y para quién, sin adjetivos valorativos ni el lenguaje del preámbulo.
2. Un desglose por bloques cuando el texto trate varios asuntos, con una línea por bloque y la ley afectada si la hay.
3. Los temas, sacados de la lista cerrada del apartado siguiente: uno principal y como máximo dos secundarios.
4. Etiquetas libres para lo que la lista no recoge («alquiler de temporada», «DANA Valencia», «permisos de nacimiento»).

Para las leyes aprobadas, las leyes afectadas no se piden al LLM, se toman de las referencias del BOE. Para las que no llegaron al BOE sí se le piden, y conviene pasarle una lista de las normas más citadas para que devuelva nombres normalizados y no «la ley de arrendamientos» un día y «LAU» otro.

Un esquema de salida razonable:

```json
{
  "resumen": "string, 2-3 frases",
  "bloques": [
    {"descripcion": "string", "ley_afectada": "Ley 29/1994 | null", "tema": "VIV"}
  ],
  "tema_principal": "VIV",
  "temas_secundarios": ["FIS"],
  "etiquetas": ["alquiler de temporada", "zonas tensionadas"],
  "ambito": "estatal | autonomico | internacional",
  "confianza": 0.0
}
```

Conviene forzar este esquema con la salida estructurada del modelo (JSON schema o tool use), con los códigos de tema como un `enum`. Así el modelo no puede inventar un tema nuevo aunque quiera.

**El problema de las categorías infinitas.** Si se deja al modelo elegir temas libremente, en un mes tienes «vivienda», «política de vivienda», «acceso a la vivienda» y «housing». La solución es separar dos niveles. El primero es la lista cerrada de temas, fija, pensada para agregar y comparar a lo largo de los años. El segundo son las etiquetas libres, que captan la actualidad. Las etiquetas se normalizan después: se calculan sus embeddings, se agrupan las muy parecidas y se elige un nombre canónico por grupo. Cada cierto tiempo (por ejemplo cada trimestre) se revisan las etiquetas más frecuentes. Si una se repite mucho y no encaja bien en ningún tema, se promociona a subtema, pero la lista de temas principales se toca lo mínimo.

Las materias que asigna el BOE sirven de control. No se usan como categorías porque son muy técnicas y numerosas, pero si el BOE dice «arrendamientos urbanos» y el LLM dice «Empleo», hay algo que revisar.

**Control de calidad.** Antes de procesarlo todo, conviene clasificar a mano unas 50 o 100 iniciativas variadas y medir cuánto coincide el modelo. Después se revisan a mano las de baja confianza y una muestra aleatoria de cada lote. Cada ficha guarda el modelo, la versión del prompt y la de la taxonomía, para poder reprocesar solo lo afectado cuando cambie algo. Y como el resultado se va a usar para comparar partidos, el prompt debe prohibir expresamente valorar la iniciativa o reproducir la exposición de motivos, que siempre es la versión del proponente.

## Categorías

Propongo 23 temas principales cerrados, pensados con dos criterios: que se correspondan con los debates que sigue la gente (vivienda, pensiones, inmigración) y que sean estables, para que una PNL de 2012 y una ley de 2026 caigan en el mismo cubo. Los subtemas son ejemplos de por dónde empezar. Salen de la revisión de etiquetas y se pueden añadir sin romper nada.

| Código | Tema | Subtemas de ejemplo |
| --- | --- | --- |
| VIV | Vivienda y urbanismo | alquiler, vivienda pública, desahucios, okupación, pisos turísticos, suelo |
| EMP | Empleo y relaciones laborales | salario mínimo, jornada, reforma laboral, desempleo, autónomos, conciliación |
| PEN | Pensiones y Seguridad Social | revalorización, sostenibilidad, cotizaciones, ingreso mínimo vital |
| FIS | Fiscalidad | IRPF, IVA, sociedades, impuestos a banca y energéticas, fraude fiscal |
| PRE | Presupuestos y finanzas públicas | Presupuestos Generales, deuda, techo de gasto, fondos europeos |
| ECO | Economía, empresa y consumo | banca, competencia, consumidores, industria, pymes, turismo |
| SAN | Sanidad | sanidad pública, listas de espera, medicamentos, salud mental, tabaco |
| EDU | Educación y universidades | leyes educativas, becas, FP, universidades, ciencia |
| SOC | Políticas sociales y familia | dependencia, discapacidad, infancia, pobreza, mayores |
| IGU | Igualdad y derechos civiles | violencia de género, LGTBI, paridad, memoria democrática, libertades |
| MIG | Inmigración y asilo | regularización, fronteras, menores no acompañados, asilo |
| JUS | Justicia | Código Penal, CGPJ, amnistía, organización judicial, indultos |
| SEG | Seguridad e interior | policía, terrorismo, tráfico, prisiones, crimen organizado |
| DEF | Defensa | gasto militar, misiones, Fuerzas Armadas, industria de defensa |
| EXT | Política exterior y UE | tratados, Unión Europea, cooperación, conflictos internacionales |
| TER | Organización territorial | estatutos, financiación autonómica, Cataluña, País Vasco, entes locales |
| INS | Instituciones y calidad democrática | régimen electoral, transparencia, corrupción, Corona, reglamentos de las Cámaras |
| ENE | Energía | precio de la luz, renovables, nuclear, gas |
| MED | Medio ambiente y clima | cambio climático, agua, residuos, biodiversidad, bienestar animal |
| AGR | Agricultura, pesca y mundo rural | PAC, sequía, despoblación, cadena alimentaria |
| TRA | Transporte e infraestructuras | ferrocarril, abonos de transporte, carreteras, aeropuertos, puertos |
| DIG | Digital y tecnología | inteligencia artificial, ciberseguridad, protección de datos, telecomunicaciones |
| CUL | Cultura, deporte y lenguas | cultura, deporte, medios de comunicación, lenguas cooficiales |

Hay dos categorías que no son temas, sino marcas que se añaden a la ficha. Una es `emergencia` para lo que responde a una catástrofe o crisis concreta (COVID, DANA, volcán de La Palma, apagón). La otra es `omnibus` para las normas que tocan tres o más temas sin relación entre sí. Una DANA mete medidas de vivienda, empleo y fiscales a la vez. Con la marca se puede filtrar «todo lo aprobado por emergencias» sin inventar un tema que no dice de qué trata la norma.

Las reglas que se le dan al LLM para clasificar son pocas:

- El tema principal es el del contenido que más cambia, no el del título. En una ómnibus, el del bloque de más peso. Los demás bloques se clasifican cada uno con su tema.
- Como máximo dos temas secundarios, y solo si hay articulado concreto sobre ellos, no una mención de paso.
- Si nada encaja, se usa el tema más cercano con confianza baja y una etiqueta libre que lo explique. Así aparece en la revisión trimestral.

Si en algún momento se quiere comparar con estudios académicos, existe el [Comparative Agendas Project](https://www.comparativeagendas.net/), que clasifica la actividad parlamentaria de muchos países (España incluida) en unos 20 temas mayores. La lista de arriba se parece bastante y se puede mapear a ella con una tabla de equivalencias. La he adaptado para que pesen más los temas de actualidad española, como vivienda, pensiones o territorial, que allí quedan diluidos.

## Análisis y plan por fases

Con las fichas montadas, los análisis que más dan de sí son estos:

- **Tasa de éxito por tema y por proponente.** Por ejemplo, cuántas iniciativas de vivienda se han presentado, cuántas salen y de quién son las que salen.
- **Grupo decisivo.** En votaciones ajustadas, qué grupo habría cambiado el resultado votando distinto. En una legislatura sin mayorías claras, esto dice más que el voto de los grandes.
- **Afinidad entre grupos por tema.** Porcentaje de votaciones en que dos grupos votan igual, desglosado por tema. Es habitual que dos grupos coincidan en economía y choquen en territorial.
- **Qué leyes se tocan más y por qué vía.** Con `relacion_normativa`: cuántas veces se ha modificado la Ley de Arrendamientos Urbanos o el Estatuto de los Trabajadores, y cuántas de esas veces fue dentro de una ómnibus o de un decreto-ley.
- **Diferencia entre lo que se vota y lo que se aprueba.** Las PNL y mociones son declaraciones sin fuerza de ley. Separarlas de las leyes evita conclusiones del tipo «el Congreso aprobó bajar el IVA» cuando fue una PNL.

Para llegar ahí propongo cuatro fases, cada una útil por sí misma:

1. **Congreso, legislatura actual, sin IA.** Descarga de votaciones e iniciativas, cruce por expediente, tipo de votación y resultados. Ya permite la tasa de éxito por proponente, el grupo decisivo y la afinidad global. Es la base de todo y conviene dejarla sólida antes de seguir.
2. **PNL y mociones con LLM.** Son textos cortos y muy numerosos, ideales para ajustar el prompt y la taxonomía con poco coste. Incluye la muestra etiquetada a mano y la primera revisión de etiquetas libres.
3. **Leyes y decretos-leyes.** Cruce con el BOE para sacar las leyes afectadas y las materias, y resúmenes por bloques para las ómnibus. Es la fase más laboriosa por la extracción de texto de los PDF del BOCG.
4. **Senado y legislaturas anteriores.** Emparejamiento de expedientes entre cámaras y reprocesado hacia atrás hasta la X legislatura, donde los datos siguen teniendo buena calidad.

Todo el flujo se puede automatizar después con una ejecución semanal que descargue las sesiones nuevas, procese solo las iniciativas nuevas o modificadas y actualice las fichas.

## Fuentes

- [Congreso: datos abiertos](https://www.congreso.es/es/datos-abiertos), [votaciones](https://www.congreso.es/es/opendata/votaciones) e [iniciativas](https://www.congreso.es/es/opendata/iniciativas)
- [Senado: catálogo de datos abiertos](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/index.html), [votaciones por iniciativa](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/votaciones/index.html) y [votaciones de mociones](https://www.senado.es/web/relacionesciudadanos/datosabiertos/catalogodatos/votacionesmociones/index.html)
- [BOE: API de datos abiertos](https://www.boe.es/datosabiertos/api/api.php) y [documentación de legislación consolidada](https://www.boe.es/datosabiertos/documentos/APIconsolidada.pdf)
- [Comparative Agendas Project](https://www.comparativeagendas.net/)
