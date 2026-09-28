# Programas y votos: lo que dicen frente a lo que votan

Sep 28, 2026 · @Miguel

## Qué se obtiene

Para cada partido y cada elección, la lista de compromisos concretos de su programa, cada uno enlazado con las iniciativas que tratan ese asunto y con lo que el partido votó en ellas. La pregunta que responde es sencilla: «lo que prometiste, ¿lo has votado?».

Un ejemplo de cómo quedaría una fila en la web: «Programa de 2023 del partido X, p. 47: *Derogaremos la ley Y*. Iniciativas relacionadas en la XV legislatura: proposición de ley de derogación presentada por el grupo Z (el partido X votó en contra); enmienda del propio grupo X para derogarla (rechazada)». Todo con la cita del programa y el enlace a cada votación.

Sobre esa base se construyen los indicadores: coherencia entre programa y voto por partido y tema, cambio de comportamiento entre gobierno y oposición, coherencia entre lo que el portavoz dice en tribuna y lo que su grupo vota, y peso de cada tema en el programa frente al peso en la actividad parlamentaria.

El principio es el mismo de Escrutinio. El LLM lee y propone (qué compromisos hay, qué iniciativas se relacionan y en qué sentido). Los votos, los resultados y los indicadores se calculan con reglas a partir de datos que ya tienes. Y cada documento se lee una sola vez: lo leído se guarda y se registra para que no se vuelva a pagar.

## Fuentes

**Programas electorales de las generales.** Del [Manifesto Project](https://manifesto-project.wzb.eu/information/documents/corpus) sale el texto completo de los programas desde 1977, con acceso por API ([manifestoR](https://github.com/ManifestoProject/manifestoR)). Además viene codificado frase a frase en unas 56 categorías, lo que sirve para contrastar la clasificación por temas del LLM. Si falta alguno reciente, se descarga el PDF de la web del partido y se guarda la URL y la fecha, porque los partidos retiran los programas de su web con el tiempo.

**Programas autonómicos.** El [Regional Manifestos Project](http://www.regionalmanifestosproject.com/espaol/descarga-de-datos) (Instituto Juan March) tiene los programas autonómicos codificados. Hay que revisar hasta qué año llega. Lo que falte, igual que arriba: web del partido.

**Intervenciones en el Pleno.** Los [datos abiertos de intervenciones](https://www.congreso.es/es/opendata/intervenciones) del Congreso y los diarios de sesiones que ya lee Escrutinio. Se usan solo las de fijación de posición sobre iniciativas que se votan.

**Contraste externo.** La [Chapel Hill Expert Survey](https://www.chesdata.eu/2024-chapel-hill-expert-survey-ches) sitúa a cada partido en escalas por tema según la opinión de expertos, con oleadas desde 1999. No entra en el cálculo. Sirve para comprobar que el retrato que sale de programas y votos no es disparatado.

## Leer una sola vez: el registro

Un programa electoral no cambia después de las elecciones, y un diario de sesiones tampoco. Por eso cada documento se descarga, se lee con el LLM y se guarda una sola vez. El registro es lo que garantiza que no se repita el trabajo ni el gasto, y que cualquiera que actualice (GitHub Actions o tú en local) sepa qué está hecho.

Funciona igual que las fichas y las actas: ficheros JSONL versionados en `data/llm/`, que son la fuente de verdad. La base SQLite se reconstruye a partir de ellos con `unir`.

**`data/llm/programas/registro.jsonl`**, una línea por documento:

```json
{"id": "generales-2023-psoe", "eleccion": "generales-2023", "ambito": "congreso", "partido": "PSOE",
 "origen": "manifesto-project | web-partido", "url": "...", "descargado": "2026-10-02",
 "sha256": "...", "paginas": 312, "tokens": 148000,
 "estado": "pendiente | leido | error", "leido": "2026-10-03",
 "modelo": "deepseek-v4-pro", "version_prompt": "compromisos-v1", "compromisos": 412}
```

**`data/llm/programas/<id>.jsonl`**, una línea por compromiso extraído, con la cita literal y la página. Es el resultado de la lectura y no se regenera.

**`data/raw/programas/<id>.txt`**, el texto ya extraído del PDF. Se guarda para no depender de que el partido mantenga el PDF en su web. Si hay problemas de derechos con el PDF, se versiona solo el texto.

Las reglas:

1. Antes de leer un documento se mira el registro. Si ya consta como `leido` con el mismo `sha256`, se salta. Esto es lo que hace el comando por defecto.
2. Si el fichero cambia (otro `sha256`, por ejemplo porque el partido corrigió el PDF), se registra como documento nuevo con su propia línea. La lectura anterior no se borra.
3. Un cambio de prompt no relee nada por sí solo. Releer con una versión nueva del prompt es una orden explícita (`programas-releer --version compromisos-v2 --id ...`) y queda anotado en el registro. Así nunca se relee todo por accidente.
4. Los fallos (PDF escaneado, respuesta inválida) quedan como `error` con el motivo, y se reintentan solo al pedirlo.
5. Los emparejamientos validados a mano tampoco se recalculan nunca. Se guardan aparte (ver el modelo de datos) y un nuevo cálculo automático no los pisa.

Los diarios de sesiones para la parte de discurso siguen el mismo esquema, con su propio registro: `data/llm/discursos/registro.jsonl`, una línea por sesión y grupo leídos.

El comando `python -m escrutinio programas-estado` muestra el registro: qué está leído, qué falta, qué falló y cuánto se ha gastado, calculado con los tokens anotados.

## Modelo de datos

Son cinco tablas nuevas en la base de trabajo. Todas se reconstruyen desde los JSONL de `data/llm/`, igual que `ficha_llm`.

- **`programa`**: una fila por documento del registro (partido, elección, ámbito, institución de Escrutinio a la que corresponde, fechas y estado). La legislatura que «cubre» un programa es la que empieza tras esa elección.
- **`compromiso`**: el texto normalizado, la cita literal, la página, el tema (los mismos 23 códigos de las fichas), las etiquetas y si es verificable. También el tipo de acción que promete: legislar, derogar, financiar, crear un organismo, bajar o subir un impuesto, o una declaración general. Y quién tendría que hacerlo: el Parlamento, el Gobierno por decreto o por gestión, u otro nivel de la Administración.
- **`compromiso_iniciativa`**: los emparejamientos con iniciativas de Escrutinio. Cada uno lleva el sentido de la iniciativa respecto al compromiso («misma dirección», «dirección contraria» o «relacionada sin dirección»), la justificación en una frase, el origen (LLM o manual) y el estado (propuesto, validado o rechazado).
- **`compromiso_estado`**: el resultado calculado por partido y compromiso (ver la sección de comparación). Es una tabla derivada, se recalcula siempre.
- **`posicion_discurso`**: por intervención de fijación de posición, el grupo, la iniciativa, la posición anunciada (a favor, en contra, abstención o no se deduce) y la cita.

Las validaciones manuales van en un fichero propio, `data/llm/programas/validaciones.jsonl`, con la persona, la fecha y el motivo. Al reconstruir la base se aplican por encima de lo propuesto por el LLM. Es la misma idea que las equivalencias de etiquetas: lo revisado a mano manda.

## Proceso paso a paso

**1. Descargar y registrar** (sin LLM). Se baja el programa, se extrae el texto con `pdftotext` como en las fuentes territoriales y se anota en el registro con su `sha256`. Los programas escaneados se detectan (sin capa de texto) y quedan como `error` para decidir aparte si merece la pena hacerles OCR.

**2. Extraer compromisos** (LLM, una vez por programa, modelo Pro). El programa se trocea por capítulos, que casi siempre coinciden con temas, y se procesa cada trozo por separado. De cada trozo el LLM devuelve los compromisos concretos con la cita literal y la página, el tema, el tipo de acción y si es verificable. Las mismas reglas que en las actas:

- La cita debe aparecer tal cual en el texto. Si no, se descarta.
- Nada que no esté escrito.
- Las frases vagas («impulsaremos», «apostaremos por») se marcan como no verificables en vez de convertirlas en compromisos inventados.

Se escribe el resultado en `data/llm/programas/<id>.jsonl` y se marca `leido` en el registro.

**3. Buscar candidatas** (sin LLM, en local). Para cada compromiso verificable se buscan las 10 iniciativas más parecidas de la legislatura siguiente a la elección, entre las fichas que ya existen (resumen, tema y etiquetas). Se usa búsqueda por texto (BM25) o embeddings con un modelo multilingüe pequeño que corre en el equipo. Filtrar por tema reduce mucho el ruido. Esto no cuesta nada y es lo que evita mandar miles de fichas al LLM.

**4. Decidir el emparejamiento** (LLM, Flash). El LLM recibe el compromiso y sus 10 candidatas, sin votos ni resultados, y dice cuáles tratan de verdad lo mismo y en qué sentido. Por ejemplo, ante «derogar la ley Y», una proposición de derogación va en la misma dirección y una que amplía la ley Y, en la contraria. El resultado se guarda y también se lee una sola vez: solo se vuelve a decidir si aparecen iniciativas nuevas del mismo tema.

**5. Validar a mano** (persona). En el piloto se revisan todos los emparejamientos de una muestra. Después, los de baja confianza y un 5 % aleatorio. La web puede tener una vista de revisión para hacerlo rápido: compromiso a la izquierda, iniciativa a la derecha y tres botones.

**6. Calcular** (sin LLM). Con los emparejamientos y los votos que ya están en Escrutinio se calcula el estado de cada compromiso y los indicadores. Es determinista y se recalcula en cada actualización. Así, cuando se vota algo nuevo relacionado con un compromiso, su estado cambia solo, sin volver a leer nada.

**Parte de discursos** (LLM Flash, una vez por sesión). De cada fijación de posición ligada a una iniciativa votada se extrae la posición anunciada con su cita. La comparación con el voto real es un cruce directo.

## Comparar con lo que votan

Esta es la parte que da sentido a todo. La clave está en combinar dos datos: el **sentido** de la iniciativa respecto al compromiso, que decide el LLM y valida una persona, y el **apoyo** del partido a esa iniciativa, que ya calcula Escrutinio (con las enmiendas a la totalidad invertidas). Si la iniciativa va en la misma dirección que el compromiso y el partido la apoya, es coherente. Si va en la contraria y la apoya, es incoherente. Así se evita el error de contar como «incumplido» votar en contra de algo que en realidad iba contra la promesa.

Con eso, cada compromiso queda en uno de estos estados, en este orden de prioridad:

| Estado | Cuándo |
| --- | --- |
| Impulsado | El partido presentó una iniciativa en la dirección del compromiso |
| Apoyado | Votó a favor de iniciativas en la dirección del compromiso presentadas por otros |
| Contradicho | Votó a favor de algo en dirección contraria, o en contra de algo en la misma dirección |
| Mixto | Hay votos coherentes e incoherentes en distintas iniciativas relacionadas |
| Sin votación | No se ha votado nada relacionado en el Pleno |
| No verificable en el Parlamento | Depende del Gobierno (decreto, presupuestos, gestión) u otra Administración. Solo cuentan los decretos-leyes, porque se convalidan |

Además se marca si la norma salió adelante, para distinguir «el partido lo votó pero no prosperó» de «se aprobó». Y se guarda en cada caso si el partido estaba en el Gobierno o en la oposición en esa fecha, con `gobiernos.py`.

Los indicadores que salen de ahí:

- **Coherencia programa-voto** por partido, tema y legislatura: proporción de compromisos con votación que quedan en impulsado o apoyado frente a contradicho. Los «sin votación» se muestran aparte y no cuentan ni a favor ni en contra.
- **Efecto gobierno.** La coherencia de un mismo partido cuando gobierna y cuando está en la oposición. Es lo más revelador: suele bajar al gobernar porque entran los socios y la realidad presupuestaria.
- **Discurso frente a voto:** en cuántas fijaciones de posición el grupo votó lo que anunció en tribuna. Debería rondar el 100 %; las excepciones son las interesantes.
- **Énfasis:** peso de cada tema en el programa frente a su peso en las iniciativas presentadas por el grupo. Si vivienda es el 15 % del programa y el 3 % de lo que presenta, se ve.
- **Coherencia entre niveles:** el mismo compromiso del programa nacional frente a cómo vota ese partido el mismo tema en los parlamentos autonómicos y ayuntamientos que ya tienes.

En la web encajaría como una pestaña nueva en el perfil de grupo, «Programa», con la lista de compromisos filtrable por tema y estado. Cada compromiso llevaría su cita y página y, debajo, las votaciones relacionadas con el enlace a cada una. En Comparar se añadiría la coherencia de varios partidos frente a frente.

## Fases

Cada fase deja algo útil y no se pasa a la siguiente sin cumplir su criterio. Los costes son órdenes de magnitud con los precios de DeepSeek publicados por terceros ([CostGoat](https://costgoat.com/pricing/deepseek-api)), en horario valle, que es cuando ya corre Actions.

| Fase | Qué incluye | Criterio para pasar | Coste LLM |
| --- | --- | --- | --- |
| 0. Registro | Comandos `programas-descargar`, `programas-estado` y `programas-releer`, registro JSONL, extracción de texto y tablas vacías | El registro impide releer un documento ya leído (probarlo lanzando dos veces) | 0 |
| 1. Piloto | Generales 2023: los programas de PSOE, PP, Vox y Sumar, emparejados con la XV legislatura. Todo validado a mano | Muestra de 100 compromisos: al menos el 90 % bien extraídos (cita, tema, verificable). Al menos el 85 % de emparejamientos propuestos correctos, con el sentido bien puesto | < 10 $ |
| 2. Congreso completo | Resto de partidos con grupo propio en 2023 y generales de 2011 a 2019 frente a las legislaturas X a XIV. Validación por muestreo | La precisión del piloto se mantiene en una muestra de cada elección | 15-50 $ |
| 3. Discursos | Fijaciones de posición del Congreso, primero la XV y después hacia atrás. Indicador discurso-voto | Muestra de 100 posiciones anunciadas bien leídas en al menos el 95 % | \~10-15 $ por legislatura |
| 4. Autonómicos | Programas autonómicos de los parlamentos con voto por grupo (Andalucía, Asturias, País Vasco, Extremadura, Cantabria…) | Mismos criterios que la fase 2 | 15-100 $, según modelo |
| 5. Web y contraste | Pestaña «Programa» en el perfil de grupo, vista de revisión y comparación con la CHES | Los partidos no salen en posiciones absurdas frente a la CHES | 0 |

El coste de verdad está en la validación manual del piloto. Con cuatro partidos saldrán del orden de 1.000 a 1.500 compromisos, pero solo hace falta revisar a fondo los emparejamientos de una muestra, no todos. Merece la pena hacerlo bien porque fija la calidad de todo lo que viene después.

Una vez terminado, el coste recurrente es casi nulo. Programas y diarios pasados no se vuelven a leer. Cada día solo se deciden emparejamientos para las iniciativas nuevas y se recalcula el estado de los compromisos con los votos nuevos. Hay un pico de lectura cada vez que hay elecciones.

## Riesgos y neutralidad

Esta es la parte más delicada de Escrutinio, porque sus resultados se pueden usar como argumento de un partido contra otro. Las reglas son las mismas para todos:

- **Solo compromisos verificables.** Las frases vagas se muestran como tales y nunca cuentan en los indicadores. Si un partido tiene programas más concretos, tendrá más compromisos evaluables, y eso debe verse: la web muestra cuántos compromisos verificables tiene cada programa.
- **«Sin votación» no es «incumplido».** Muchas promesas se cumplen o no por decreto, por presupuestos o por gestión. La web nunca debe sumarlas como incumplimiento.
- **Lenguaje descriptivo.** «El programa de 2023 decía X (p. 47); el grupo votó en contra de la iniciativa Y». Nunca «miente», «traiciona» ni juicios parecidos.
- **Contexto de coalición.** Cuando el partido gobierna en coalición o con apoyos externos, se indica. Votar contra una promesa propia por un acuerdo de gobierno es un dato, no una anomalía oculta.
- **Trazabilidad total.** Cada estado se puede seguir hasta la cita del programa, la ficha de la iniciativa, el emparejamiento (con quién lo validó) y la votación oficial.
- **Sesgo del LLM.** El LLM nunca ve el partido cuando decide el sentido de un emparejamiento: recibe el compromiso y las iniciativas sin autor. Así no puede «ayudar» a nadie.
- **Programas que desaparecen.** Se guarda el texto extraído y la URL original con fecha, para que la cita siga siendo comprobable aunque el partido retire el PDF.

## Fuentes

- [Manifesto Project, corpus](https://manifesto-project.wzb.eu/information/documents/corpus) y [manifestoR](https://github.com/ManifestoProject/manifestoR)
- [Regional Manifestos Project, descarga de datos](http://www.regionalmanifestosproject.com/espaol/descarga-de-datos)
- [Congreso, datos abiertos de intervenciones](https://www.congreso.es/es/opendata/intervenciones)
- [Chapel Hill Expert Survey 2024](https://www.chesdata.eu/2024-chapel-hill-expert-survey-ches)
- [Precios de la API de DeepSeek (CostGoat)](https://costgoat.com/pricing/deepseek-api)
