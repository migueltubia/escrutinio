# Escrutinio

Votaciones del Pleno del Congreso de los Diputados y de parlamentos autonómicos, juntas generales y
ayuntamientos en SQLite, con una ficha por iniciativa (resumen neutro, tema, etiquetas, leyes
afectadas) y una web que se abre sin servidor. Implementa las fases 1 y 2 de `Análisis de votaciones
parlamentarias con IA.md` para el Congreso, de la X a la XV legislatura, y las amplía al nivel
autonómico y local según `Votaciones autonómicas y locales fuentes por territorio.md`. Se actualiza
cada día con GitHub Actions y DeepSeek, o desde cualquier equipo con el repositorio clonado.

Web publicada: <https://migueltubia.github.io/escrutinio/>

Solo usa la biblioteca estándar de Python (3.10 o superior): ni dependencias ni servidor. Para leer
los PDF de algunas fuentes territoriales usa `pdftotext` (poppler-utils) o, si no está, `pypdf`. Si
hay varios `pdftotext` en el PATH se usa el de poppler, el mismo que en GitHub Actions: el de xpdf
que trae Git para Windows ordena distinto algunos PDF.

## La web: sin servidor

Abre `web/index.html` con doble clic. El navegador carga SQLite compilado a WebAssembly
([sql.js](https://github.com/sql-js/sql.js), MIT, incluido en `web/vendor/`) y la página hace sus
consultas SQL directamente sobre la base de datos, en memoria.

Los navegadores no permiten a una página `file://` leer ficheros con `fetch`, así que
`python -m escrutinio web` genera una SQLite compacta y la guarda comprimida y en base64 dentro de
ficheros `.js`, que la página carga con etiquetas `<script>`. Van troceados igual que la base:

| Fichero | Contenido |
| --- | --- |
| `web/datos/indice.js` | Lista de ficheros de datos con su institución, su huella y la fecha de generación |
| `web/datos/comun.js` | Catálogos, instituciones y árbol de ámbitos, gobiernos, diputados, informe y los índices de la base |
| `web/datos/programas.js` | Compromisos de los programas electorales, sus iniciativas relacionadas y su estado. Solo se descarga al entrar en Activismo · Programas electorales, al abrir una iniciativa que aparece en algún programa o al pulsar «¿Qué prometieron sobre esto?» en una causa |
| `web/datos/<institución>/legNN.js` | Votaciones, voto nominal, iniciativas, fichas y afinidades de la legislatura NN de esa institución (`congreso/leg15.js`, `parl-AS/leg12.js`…) |

En el navegador se juntan en una sola SQLite en memoria, pero **solo los de las instituciones del
ámbito elegido** (ver «Ámbito territorial»): con el Congreso son unos 4,5 MB (el mayor, 1,6 MB);
con todas las instituciones (28), unos 27 MB.
Solo se reescriben los ficheros cuyo contenido cambia, así que cada semana solo cambian las
legislaturas en curso, `comun.js` y el índice. La misma carpeta `web/` es la que se publica en
GitHub Pages.

## Vistas

| Sección | Qué responde |
| --- | --- |
| Resumen | Cifras generales, lo que se vota frente a lo que se aprueba, actividad mensual y análisis de las cifras |
| Votaciones / Iniciativas | Buscador con filtros (también derrotas del Gobierno), detalle con voto nominal, grupo decisivo, quién gobernaba y exportación a CSV |
| Temas → ficha de tema | Cómo vota cada grupo en el tema, quién propone y quién lo consigue, afinidad, evolución por legislatura y matriz votación a votación |
| Grupos → perfil de grupo | Su voto por tema, sus iniciativas, con quién coincide y en qué, y cuándo su voto decidió el resultado |
| Comparar | Dos o más grupos frente a frente en los mismos asuntos: en cuántos votan igual, cuánto apoya cada uno lo que presentan los demás, a quién apoya cada uno, tema a tema y legislatura a legislatura, y asunto a asunto |
| Análisis · Coaliciones ganadoras | Qué combinaciones de grupos aprueban y tumban cada cosa |
| Análisis · Mapa ideológico y polarización | Posición de los grupos según sus votos (MDS sobre la afinidad) y polarización por trimestre |
| Análisis · Disciplina y ausencias | Diputados que votan distinto a su grupo, votos no emitidos y votaciones que habrían cambiado con los ausentes |
| Análisis · Enmiendas | Qué grupo consigue cambiar las leyes, quién apoya las enmiendas de quién y leyes con más enmiendas aprobadas |
| Activismo · Mis causas | Seguimiento guardado en el navegador (texto, tema o etiqueta), novedades desde la última visita, scorecard con tu criterio, qué prometían los partidos sobre lo mismo en sus programas y CSV |
| Activismo · Qué viene | Iniciativas abiertas de la legislatura actual: recién abiertas a enmiendas, pendientes de debate y paradas en comisión, con los partidos que llevaban en su programa algo en su dirección |
| Activismo · Programas electorales | Lo que prometió cada partido en su programa frente a lo que votó: primero, dónde votó en contra de lo que prometía; después, los programas frente a frente, cuánto pesa cada tema y compromiso a compromiso con su cita y las iniciativas relacionadas (ver «Programas electorales»). El detalle de cada iniciativa dice qué partidos llevaban algo relacionado en su programa, y el de cada votación enlaza con él |
| Ayuda | Qué es, qué hace, de dónde salen los datos, qué se actualiza y cada cuánto, conceptos y limitaciones. Cada pestaña tiene además su «Cómo se lee» |

En listas y tablas los títulos oficiales se acortan (abreviatura del tipo, número y asunto: «RDL
23/2026 · Medidas fiscales…», «PNL · Digitalización de…»); el título completo sale al pasar el ratón,
en el detalle y en los CSV.

Todos los filtros admiten varias opciones a la vez (legislaturas, temas, tipos, grupos…). En Grupos
y en el Mapa, con varias legislaturas o temas se suman las votaciones de cada partido; en el perfil
de grupo, varios grupos se analizan juntos como un bloque.

En el móvil (pantalla estrecha, o un teléfono girado) la web cambia de interfaz: secciones en una
barra inferior (con «Más» para Análisis y Activismo), filtros plegados tras un botón, selectores
como hojas inferiores, gráficos al ancho de la pantalla, tablas con desplazamiento horizontal y
tooltips que se abren al tocar.

En todas las vistas de análisis se usa el «apoyo» a la iniciativa: en las enmiendas a la totalidad
votar sí es votar contra el proyecto, así que ese voto se invierte. Los porcentajes de apoyo por grupo cuentan
asuntos, no votaciones: si un asunto se votó por puntos (PNL, mociones), los puntos se reparten su peso, y
en los debates con propuestas de resolución las de cada grupo cuentan como un asunto. Cada grupo apoya
casi siempre lo que presenta él mismo, así que Comparar separa lo propio (y lo del Gobierno) de lo que
presentan los demás.

Los debates de política general (estado de la nación, de la comunidad o de la región, orientación
política del Gobierno) no tienen tema: cada grupo presenta propuestas de resolución sobre cualquier
asunto. Se reconocen por el título (`texto.es_debate_general`); sus votaciones cuentan en los totales,
pero en ningún tema. En el Congreso, cada propuesta se atribuye al grupo que la presenta.

## Almacenamiento: una SQLite por institución y legislatura

GitHub rechaza ficheros de más de 100 MB y la base completa ocupa casi 400 MB, sobre todo por los
casi 7 millones de filas de voto nominal. Por eso lo que se versiona es `data/bd/`, troceado por
institución y legislatura, que es la unidad natural de los datos y además estable (una legislatura
cerrada no cambia):

| Fichero | Contenido |
| --- | --- |
| `data/bd/comun.sqlite` | Legislaturas de todas las instituciones, catálogos, diputados e informe |
| `data/bd/<institución>/legNN.sqlite` | Todo lo de la legislatura NN de una institución (`congreso/leg15.sqlite`, `parl-AN/leg12.sqlite`, `ayto-gijon/leg12.sqlite`…): días de pleno, votaciones, agregados por grupo, iniciativas, fichas, afinidades… |
| `data/bd/manifiesto.json` | Huella del contenido de cada fichero y recuentos |

Cada institución tiene un número fijo (`escrutinio/territorio.py`) y su legislatura N se guarda con
el id `número * 100 + N`. El Congreso es el 0, así que sus ids son los de siempre (10 a 15) y todo lo
que filtra por legislatura vale para cualquier institución.

El voto nominal va compacto en `voto_compacto`: por cada votación, una cadena con el sentido de cada
diputado de la plantilla (`S` sí, `N` no, `A` abstención, `-` no vota, `.` no era diputado) y otra con
su grupo (índice en `grupo_idx`). Los ficheros no llevan índices de SQLite: solo guardan los datos, y
`unir` crea los índices al reconstruir la base de trabajo. El mayor fichero ronda los 14 MB (Congreso,
XIV legislatura) y el total, unos 160 MB: 40 del Congreso y el resto de las demás instituciones.

`data/escrutinio.sqlite` es la base de trabajo (todo junto, con `voto` en filas): no se versiona y
se reconstruye con `unir`. `partir` vuelve a generar los troceados y solo reescribe los que han
cambiado, así que cada semana en git solo cambia la legislatura en curso.

## Uso

```bash
python -m escrutinio unir          # base de trabajo desde data/bd/ (menos de un minuto)
python -m escrutinio actualizar    # todo el ciclo: datos nuevos, reglas, fichas si hay clave, web y partir
python -m escrutinio estado        # resumen de la base de trabajo
```

Pasos sueltos, por si hacen falta:

```bash
python -m escrutinio votaciones / iniciativas / procesar / analizar / web / partir
python -m escrutinio fichas-deepseek --limite 100     # fichas nuevas con DeepSeek (DEEPSEEK_API_KEY)
python -m escrutinio informe-deepseek                 # informe de análisis con DeepSeek
python -m escrutinio fichas-exportar                  # lotes JSONL para generarlas por otra vía
python -m escrutinio fichas-validar 1
python -m escrutinio fichas-importar "data/llm/resultados/x/*.jsonl" --modelo <modelo>
python -m escrutinio estadisticas
python -m escrutinio territorial [--fuente asturias,andalucia] [--completo]   # votaciones autonómicas y locales
python -m escrutinio territorial-estado                                       # cobertura de cada conector
python -m escrutinio territorial-probar <conector> --limite 30                # probar un conector sin tocar la base
python -m escrutinio actas-deepseek --limite 40      # votaciones de diarios de sesiones y actas (DEEPSEEK_API_KEY)
python -m escrutinio actas-exportar --limite 20      # textos pendientes para procesarlos por otra vía
python -m escrutinio actas-importar "data/llm/actas/respuestas/*.json" --modelo <modelo>
python -m escrutinio programas-descargar / programas-estado    # programas electorales (ver «Programas electorales»)
python -m escrutinio programas-leer / programas-emparejar / programas-calcular
```

## Actualizar los datos: en la nube o en local

La actualización es un solo programa, `python -m escrutinio actualizar`, y da igual quién lo lance:
GitHub Actions cada día, o cualquier persona desde su equipo con el repositorio clonado. Los dos
caminos parten de la misma base troceada (`data/bd/`) y de las mismas fichas y actas guardadas
(`data/llm/`), y dejan el resultado en el repositorio, así que quien actualiza después, sea el runner
o una persona, sigue donde lo dejó el anterior.

### En la nube: GitHub Actions y GitHub Pages

Dos workflows:

| Workflow | Cuándo | Qué hace |
| --- | --- | --- |
| `actualizar.yml` («Actualizar datos») | **Diaria**, de lunes a sábado a las 04:20 UTC y a las 22:40 UTC: la de la noche recoge las votaciones del mismo día y cubre a la de la mañana si GitHub la descarta | `python -m escrutinio actualizar`, commit de `data/llm` (las fichas generadas) y publicación de la web con los datos del día |
| | **Semanal**, el domingo a las 04:20 UTC, y a mano | Lo mismo, más el informe de análisis de la portada (`--informe`) y commit también de `data/bd` y `web/datos` |
| `pages.yml` («Publicar web») | Al subir cambios de `web/` a `main` y a mano | Publica `web/` en GitHub Pages, tal cual |

La base y los datos de la web se guardan en git solo una vez por semana para que el historial no
sume cada día una copia binaria de varios MB; la web publicada sí se actualiza a diario, porque la
publica el propio workflow con lo que acaba de calcular. Las fichas (`data/llm`) se guardan
cada día porque no se pueden volver a descargar. Al subir un cambio de código, «Publicar web» publica
los datos de la última copia semanal hasta la siguiente actualización diaria.

Configuración, una sola vez, en el repositorio de GitHub:

1. *Settings > Pages > Build and deployment > Source*: **GitHub Actions**.
2. *Settings > Secrets and variables > Actions*:

   | Tipo | Nombre | Valor |
   | --- | --- | --- |
   | Secret | `DEEPSEEK_API_KEY` | Clave de la API de DeepSeek. Sin ella se actualiza todo menos las fichas nuevas |
   | Variable | `DEEPSEEK_MODEL` | Opcional; por defecto `deepseek-flash` (también `deepseek-v4-pro`) |

3. Pestaña *Actions*: ejecutar «Publicar web» para la primera publicación (luego va sola) y, si se
   quiere probar ya, «Actualizar datos».

Los workflows declaran los permisos que necesitan (`contents: write` para el commit, `pages: write`
para publicar). Si el commit falla con un 403, en *Settings > Actions > General > Workflow
permissions* hay que elegir «Read and write permissions».

Qué hace cada día:

1. Reconstruye la base de trabajo desde `data/bd/` (el runner empieza de cero).
2. Descarga las votaciones nuevas (y revisa las de los últimos 14 días, por si se publicaron
   incompletas) y el catálogo, plazos y fases de las iniciativas de la legislatura actual.
3. Carga las fichas versionadas y procesa todo con reglas fijas.
4. Con DeepSeek: decide el tipo de las votaciones que las reglas no reconocen y genera las fichas de
   las iniciativas nuevas (hasta 400 por ejecución). Sin clave, las leyes nuevas quedan con el tema
   provisional por comisión.
5. Votaciones autonómicas y locales: cada conector trae lo publicado desde su última votación
   guardada (con unos días de margen) y, con DeepSeek, se leen hasta 40 diarios de sesiones o actas
   pendientes, repartidos entre instituciones. Un conector que falla (web caída, cambio de formato)
   se anota, no para a los demás ni al Congreso y la web lo avisa (ver el apartado siguiente).
6. Recalcula agregados, regenera la web y vuelve a trocear la base.
7. Hace commit de lo que toque (ver la tabla) y publica la web.

Qué se actualiza y cada cuánto, contado para quien usa la web, está también en la página de ayuda
(`#/ayuda`), que además explica cada pestaña con el botón «Cómo se lee».

### En local: desde cualquier equipo

Hace falta Python 3.10 o superior y git, nada más (para los PDF de algunas fuentes, `pdftotext` o
`pypdf`, ver arriba). La clave de DeepSeek es opcional: sin ella se actualiza todo menos las fichas
nuevas, la lectura de diarios y actas y el informe (ver el apartado siguiente). Los pasos, siempre en
este orden y de una vez:

```bash
git pull                              # 1. la última base y las últimas fichas
python -m escrutinio unir            # 2. base de trabajo desde data/bd/ (sustituye la que hubiera)
python -m escrutinio actualizar      # 3. lo mismo que hace Actions: de unos minutos a más de una hora
git add data/bd web/datos data/llm    # 4. base troceada, datos de la web, fichas y actas
git commit -m "Actualización de datos"
git push                              # 5. enseguida, antes de que actualice otro
```

Los mismos comandos valen en PowerShell. Opciones de `actualizar`: `--limite-fichas N` (400 por
defecto), `--limite-actas N` (40), `--informe` (redacta el informe de la portada), `--sin-ia` (no
llamar a DeepSeek aunque haya clave) y `--sin-territorial` (solo el Congreso). Antes de subir se puede
ver el resultado abriendo `web/index.html`. La web publicada se actualiza con el siguiente «Actualizar
datos» o lanzando «Publicar web» a mano en la pestaña *Actions*.

Dos reglas para no chocar con Actions ni con otra persona:

- **Pull justo antes y push justo después.** `data/bd` son SQLite y `web/datos` va en base64: git no
  puede fusionarlos, solo elegir una versión. Dos actualizaciones seguidas, cada una a partir de la
  anterior, no dan problema; dos cruzadas, sí: la segunda no puede subir.
- **Evitar las franjas de Actions y no dejar datos sin subir.** El runner corre a las 04:20 UTC (06:20
  en verano y 05:20 en invierno, hora peninsular) y a las 22:40 UTC, y cada pasada suele durar menos
  de dos horas, más si hay cola. Los domingos sube su copia de la base, así que unos datos locales de
  varios días chocan seguro.

Si el push falla porque `main` ha avanzado mientras tanto, no hay que fusionar los binarios sino
regenerarlos: `git pull --no-rebase`; en los conflictos de `data/bd` y `web/datos`, quedarse con los
propios (`git checkout --ours -- data/bd web/datos`); en los de `data/llm`, conservar las líneas de
las dos versiones (cada línea de los `.jsonl` es independiente; si choca el informe, elegir uno);
volver a ejecutar `python -m escrutinio actualizar`, que importa las fichas y actas recién traídas y
regenera la base y la web; y hacer commit y push.

### La clave de DeepSeek

DeepSeek hace tres cosas en la actualización: las fichas de las iniciativas nuevas, la lectura de los
diarios de sesiones y actas que solo se publican en texto libre, y el informe de la portada. Todo lo
que devuelve se guarda en `data/llm/` y se versiona, así que la clave la necesita solo quien
actualiza; ni la web ni `unir` la usan. Dónde va, según quién actualiza:

| Quién | Dónde |
| --- | --- |
| GitHub Actions | *Settings > Secrets and variables > Actions*: secret `DEEPSEEK_API_KEY` y, opcional, la variable `DEEPSEEK_MODEL` |
| Una persona, en su equipo | Fichero `.env` en la raíz del repositorio, copiado de `.env.ejemplo`. Está en `.gitignore` y no se sube. También vale como variable de entorno del sistema, que tiene prioridad |

| Variable | Para qué |
| --- | --- |
| `DEEPSEEK_API_KEY` | La clave. Sin ella, `actualizar` lo avisa en el registro y hace todo lo demás |
| `DEEPSEEK_MODEL` | Modelo; por defecto `deepseek-flash` (también `deepseek-v4-pro`) |
| `DEEPSEEK_BASE_URL` | Dirección de la API; por defecto `https://api.deepseek.com` |

Sin clave, o con otro sistema: `fichas-exportar` y `actas-exportar` dejan en `data/llm/pendientes/`
y `data/llm/actas/pendientes/` los lotes pendientes con sus instrucciones (`data/llm/INSTRUCCIONES.md`),
para que los procese otro modelo, otro servicio u otra persona; `fichas-validar` y `actas-validar`
comprueban las respuestas y `fichas-importar` y `actas-importar` las cargan. El cliente
(`escrutinio/llm/deepseek.py`) habla con una API compatible con la de OpenAI usando solo la
biblioteca estándar, así que `DEEPSEEK_BASE_URL` y `DEEPSEEK_MODEL` son el punto de partida para otro
servicio compatible, aunque no está probado con ninguno.

### Aviso: webs que no responden desde fuera de España

Los servidores de GitHub Actions están fuera de España y varias webs de instituciones no aceptan
esas conexiones. En la primera ejecución no respondieron el Parlamento Vasco, el Ayuntamiento de
Zaragoza y las Cortes de Aragón (se agota el tiempo o cortan la conexión), y el Parlamento de
Navarra contestó con un 403: su web está detrás de una protección contra robots, que no se intenta
saltar. Una web que no deja ni conectar dos veces seguidas se da por caída hasta el final de la
ejecución, para no esperar minutos en cada petición. Esas instituciones se quedan como estaban, y se
avisa en tres sitios:

- **En la web**: la portada lista las instituciones del ámbito elegido que no se han podido
  actualizar, con el motivo y la fecha de sus últimos datos; el selector de ámbito y la tabla de
  cobertura las marcan con ⚠, y la ayuda lo explica.
- **En GitHub**: salen como avisos en el resumen de la ejecución de «Actualizar datos».
- **En el registro**: «Fuentes sin actualizar en esta ejecución», al final.

Cada recogida anota por institución si respondió y, si no, por qué (`escrutinio/territorial/estado.py`);
los avisos viajan a la web en `web/datos/indice.js`. Para poner al día esas instituciones basta hacer
la actualización en local desde España, con los pasos de «En local: desde cualquier equipo»: cada
conector trae lo que falte desde la última votación guardada de su institución.

Otras tres webs, las de las Cortes de Castilla y León, las Juntas Generales de Bizkaia y el Parlament
de les Illes Balears, fallaban en Actions por otro motivo: envían su certificado sin el intermedio,
que Windows completa por su cuenta y Linux no. Esos intermedios van en
`escrutinio/territorial/certificados.pem` y ya no fallan. En el mismo fichero va la raíz nueva de la
FNMT-RCM (G2R, de diciembre de 2025) con la que la Asamblea de Extremadura firma su certificado desde
septiembre de 2026: ni el paquete de certificados de Linux ni el almacén de Windows la traen todavía y
sin ella fallaba en los dos.

## Fichas y reglas

Casi todo es determinista: descarga, cruces, tipo de votación, resultados, grupo decisivo,
afinidades, coaliciones, enmiendas… DeepSeek describe y clasifica cada iniciativa sin recibir votos ni
resultados; en lo autonómico y local, además, lee los días de diario o acta que las reglas no saben
leer (ver «Ámbito territorial»).

| Qué | Cómo | Dónde queda |
| --- | --- | --- |
| Ficha de cada iniciativa (resumen, tema de una lista cerrada de 23, etiquetas, leyes afectadas, marcas) | Generada con DeepSeek; todo se valida contra los catálogos antes de guardarse | `data/llm/resultados/**.jsonl` (fuente de verdad) y `ficha_llm` |
| Tipo de las votaciones que las reglas no reconocen | DeepSeek, con lista cerrada | `data/llm/tipos_votacion.jsonl` |
| Tema provisional de las leyes sin ficha | Reglas sobre la comisión competente: coincide con la ficha definitiva en el 90% de los casos | `tema_provisional` |
| Equivalencias de etiquetas y nombres de leyes | Tabla revisada una vez; ahora es código | `escrutinio/llm/etiquetas.py` |
| Quién gobernaba en cada fecha (presidente, partido y socios) | Tabla a mano: Gobierno de España, comunidades autónomas, diputaciones forales y ayuntamientos | `escrutinio/gobiernos.py` |
| Informe de la portada | DeepSeek a partir de `estadisticas` | `data/llm/informe.md` |
| Votaciones de los diarios y actas que las reglas no leen | DeepSeek, solo con lo que está escrito | `data/llm/actas/<institución>.jsonl` |

Las fichas del lote inicial se generaron antes de montar la actualización automática
(`data/llm/resultados/modelos.json` las marca como «lote inicial»); las nuevas de DeepSeek llevan su
origen en cada línea. Quedan unas 11.900 iniciativas sin ficha, casi todas de las instituciones
autonómicas incorporadas al final: el workflow diario hace hasta 400 por ejecución, así que se
completan en alrededor de un mes. Todas las peticiones a DeepSeek piden responder en español de
España. Control de calidad: reclasificadas a ciegas 60 fichas al azar, el tema principal coincide
en el 93% (98% contando secundarios). El resultado calculado con los totales se contrasta con el
oficial: en convalidaciones y votaciones de conjunto solo discrepa una votación, marcada con aviso.

## Programas electorales: lo que prometen frente a lo que votan

Implementa las fases 0 y 1 de `Programas y votos lo que dicen frente a lo que votan.md` y la sección
«Programas electorales» de Activismo en la web: los compromisos del programa de cada partido, cada uno con su
cita literal y su página, enlazados con las iniciativas del Pleno que tratan lo mismo y con lo que votó
el partido en ellas. Están los programas de las generales de 2023 de los partidos con grupo propio en la XV
legislatura: PSOE, PP, VOX, Sumar, ERC, Junts, EH Bildu y PNV (los de ERC y Junts, en catalán: la cita se
guarda en la lengua del programa y el compromiso, en castellano). Los programas
se añaden en `escrutinio/programas/registro.py` (`PROGRAMAS`). Los partidos que votan dentro del Grupo
Mixto (BNG, CC, UPN, y Podemos desde diciembre de 2023) no tienen voto propio de grupo con el que
comparar: harían falta sus diputados uno a uno.

Cada programa se descarga, se lee y se guarda **una sola vez**. Lo que manda son los ficheros de
`data/llm/programas/`, versionados como las fichas, y la base se reconstruye desde ellos (`unir`,
`web` y `actualizar` los cargan):

| Fichero | Contenido |
| --- | --- |
| `data/llm/programas/registro.jsonl` | Una línea por documento: partido, elección, URL, `sha256`, páginas, estado (`pendiente`, `leido`, `error`), modelo, versión del prompt, compromisos y tokens gastados |
| `data/raw/programas/<id>.txt` | Texto extraído del PDF, con un salto de página entre páginas. Se versiona (el PDF no) para que las citas sigan siendo comprobables aunque el partido retire el programa |
| `data/llm/programas/<id>.jsonl` | Una línea por compromiso: texto, cita literal, página, tema, tipo de acción, de quién depende y si es verificable |
| `data/llm/programas/emparejamientos/<id>.jsonl` | Una línea por par compromiso–iniciativa decidido, también los que no tienen que ver, para no volver a preguntarlos |
| `data/llm/programas/verificaciones/<id>.jsonl` | Segunda revisión de cada relación con dirección (misma o contraria): manda sobre la primera y no se repite |

```bash
python -m escrutinio programas-descargar     # descarga y registra; si el sha256 no cambia, no hace nada
python -m escrutinio programas-estado        # qué está leído, qué falta, qué falló y el gasto estimado
python -m escrutinio programas-leer          # compromisos de los pendientes, con DeepSeek (modelo Pro)
python -m escrutinio programas-emparejar     # candidatas nuevas de cada compromiso, con DeepSeek
python -m escrutinio programas-verificar     # segunda revisión de las relaciones con dirección (modelo Pro)
python -m escrutinio programas-verificar --rehacer --solo contraria   # tras cambiar el prompt, solo esas
python -m escrutinio programas-calcular      # recarga todo y recalcula el estado, sin DeepSeek
python -m escrutinio programas-releer --id generales-2023-pp --version compromisos-v2   # solo a propósito
```

Cómo se hace, paso a paso:

1. **Descarga y registro** (sin DeepSeek). Si un partido corrige el PDF, entra como documento nuevo
   con su propia línea y la lectura anterior se conserva. Un PDF escaneado queda como `error`.
2. **Compromisos** (DeepSeek, una vez por programa). El texto va por trozos de unas 40 páginas. La
   cita tiene que aparecer tal cual en el programa, o el compromiso se descarta; la página sale de
   dónde está la cita, no de lo que responda el modelo. Las frases vagas quedan como no verificables.
   Si la lectura se corta, los trozos ya respondidos están en la caché local y no se vuelven a pagar.
3. **Candidatas** (sin DeepSeek). Las 10 iniciativas con ficha más parecidas de la legislatura
   siguiente, del mismo tema, con BM25 sobre título, resumen y etiquetas.
4. **Relación** (DeepSeek, modelo rápido). Recibe el compromiso y las candidatas sin partido, sin
   autor y sin votos, y dice si cada una va en su dirección, en la contraria, trata lo mismo sin
   dirección o no tiene que ver. Solo se preguntan las candidatas nuevas.
5. **Segunda revisión** (DeepSeek, modelo Pro). Las relaciones con dirección, que son las que cuentan
   en las cifras, se revisan con un criterio más estricto y más contexto: la cita literal del programa
   (sin nombres de partido) y el título, el resumen y las etiquetas de la iniciativa. No basta con que
   se llamen parecido: dos «leyes de familias» pueden proponer cosas opuestas. «En la contraria» exige
   ir en sentido opuesto: quedarse corto (un impuesto temporal frente a hacerlo permanente) va en su
   dirección, y pedir información, auditar, retocar un detalle o un trámite sin contenido propio solo
   tratan lo mismo. Ante la duda, queda como «trata lo mismo, sin dirección clara», que no cuenta.
6. **Estado** (reglas, en cada actualización). Con el apoyo del partido en la votación decisiva de
   cada iniciativa (enmiendas a la totalidad invertidas; lo aprobado por asentimiento cuenta como
   apoyo): *impulsado* si presentó algo en su dirección (o lo presentó el Gobierno mientras
   gobernaba), *apoyado*, *contradicho*, *mixto*, *abstención*, *sin votación* y *no verificable en el
   Parlamento* (lo que depende del Gobierno o de otra Administración solo se comprueba con los
   decretos-leyes). Sin votación no es incumplimiento, y la web lo dice. Un programa leído que aún no
   se ha comparado con ninguna iniciativa queda *pendiente de comparar*, que no cuenta en las cifras.

La actualización diaria lee los programas registrados que estén pendientes, decide las candidatas
nuevas (hasta 300 compromisos por ejecución), revisa las relaciones nuevas con dirección y recalcula el
estado. Descargar un programa nuevo es
siempre a mano. En la web, la lista de programas va en `web/datos/comun.js` y los compromisos, en `web/datos/programas.js`,
que solo se descarga cuando hace falta.

Pendiente, según el plan: las elecciones anteriores (2011–2019), las intervenciones en el Pleno, los programas autonómicos
y el contraste con la Chapel Hill Expert Survey. Los programas del PSOE, Junts y EH Bildu se descargan de
la copia que publicó un medio: psoe.es está tras una protección contra robots que no se intenta saltar,
y las webs de Junts y EH Bildu ya no enlazan el de 2023.

## Fuentes y limitaciones

| Dato | Fuente |
| --- | --- |
| Votaciones y voto nominal | Datos abiertos de votaciones del Congreso (un JSON por votación) |
| Expediente, autor y resultado de tramitación | Buscador de iniciativas del Congreso (endpoint JSON) |
| Situación, comisión, plazos y enlaces al BOCG (legislatura actual) | Datos abiertos de iniciativas |

- **No hay 20 años.** Las votaciones nominales en datos abiertos empiezan en la X legislatura
  (enero de 2012). La IX y anteriores no tienen voto nominal publicado.
- **Los ficheros de votación no traen expediente.** El cruce con la iniciativa se hace por título
  normalizado (y por número en los decretos-leyes y los Presupuestos). Lo que no se puede enlazar
  queda como iniciativa «sintética» (`SIN/...`) con el texto de la votación.
- **Las fichas se hacen a partir del título oficial**, no del texto del BOCG (fase 3 del plan).
- **La comisión competente solo está en los datos abiertos de la legislatura actual**, así que el
  tema provisional solo existe para ella.
- Solo el Pleno (las comisiones no tienen voto nominal). De las Cortes Generales, solo el Congreso (el
  Senado es la fase 4); lo autonómico y local tiene sus propias fuentes y limitaciones (ver «Ámbito territorial»).
- Al trocear no se guarda el número de asiento de cada diputado, que no se usa en ningún análisis.

## Ámbito territorial: parlamentos autonómicos, instituciones provinciales y ayuntamientos

Además del Congreso se recogen las votaciones de parlamentos autonómicos, Juntas Generales vascas y
ayuntamientos. Las fuentes, lo que publica cada una y lo difícil que es sacarlo están en
`Votaciones autonómicas y locales fuentes por territorio.md`.

### Elegir qué se analiza

La cabecera de la web tiene un selector de **ámbito** con un árbol:

- **Toda España**
  - **Nacional**: el Congreso (y, cuando se añadan, otras fuentes nacionales por separado).
  - **Comunidades autónomas** → cada comunidad → su parlamento, sus instituciones provinciales o
    insulares (Juntas Generales, cabildos, consells) y sus ayuntamientos.

Marcar un nodo marca todo lo que tiene debajo: una comunidad incluye su parlamento, lo provincial y
los ayuntamientos; se puede desmarcar lo que sobre o elegir solo un ayuntamiento. Los atajos por
nivel eligen un nivel entero sin lo de debajo: por ejemplo, **todos los parlamentos autonómicos**
sin juntas ni ayuntamientos, o todos los ayuntamientos. La elección va en la URL (`amb=congreso`,
`amb=AS`, `amb=*autonomico`, `amb=es`…), así que los enlaces compartidos la conservan. Al abrir la
web sin ámbito en la URL se carga solo lo nacional, que es lo más ligero; el selector ofrece volver a
la última elección y avisa cuando lo marcado pesa mucho (la primera carga puede tardar y el navegador
usa bastante memoria).

La web solo descarga y monta los ficheros de las instituciones elegidas, y todas las vistas
(votaciones, temas, grupos, coaliciones, mapa, disciplina…) trabajan sobre ese ámbito sin más
cambios. Con varias instituciones, las legislaturas llevan su nombre corto («Asturias XII») y los
grupos se suman por partido (el PSOE del Congreso y el de un parlamento cuentan juntos), lo que
permite ver, por ejemplo, con quién coincide cada partido en toda una comunidad. Cada votación
enlaza a su fuente original.

### Cómo se recogen

Cada institución tiene un conector en `escrutinio/territorial/fuentes/` que devuelve las
votaciones ya normalizadas (`escrutinio/territorial/modelo.py`); guardarlas, calcular resultados,
votación decisiva, grupos y grupos decisivos es común a todas (`territorial/cargar.py` y
`territorial/procesar.py`). Hay tres tipos de conector:

| Tipo | Qué hace | `fuente` |
| --- | --- | --- |
| Datos estructurados | Descarga XML, JSON, CSV o tablas HTML con el voto nominal, por grupo o los totales | `xml`, `json`, `csv`, `html` |
| PDF de formato fijo | Lee con reglas el PDF que genera el sistema de votación o un acta muy regular | `pdf-reglas`, `html-reglas` |
| Diario de sesiones o acta en texto libre | El conector lista los documentos del pleno; DeepSeek lee el texto condensado y devuelve cada votación con su asunto, expediente, totales, voto por grupo y resultado, sin añadir nada que no esté escrito | `pdf-llm`, `html-llm` |

Lo leído de diarios y actas se guarda en `data/llm/actas/<institución>.jsonl` (una línea por
documento): es la fuente de verdad de esa parte, así que reconstruir la base no repite nada y cada
ejecución sigue con el atraso donde lo dejó la anterior. Sin clave de DeepSeek, `actas-exportar` deja
los textos y unas instrucciones para procesarlos por otra vía y `actas-importar` carga el resultado.

Nada se inventa: si una fuente solo da el resultado, no hay totales; si solo da los totales, no hay
voto por grupo. El resultado es el oficial cuando la fuente lo publica; si no, se calcula con los
totales y la mayoría de esa cámara (sus escaños), y si ambos no cuadran la votación lleva un aviso.
Los grupos se reconocen por el nombre que publica cada fuente (`territorial/partidos.py`) para que
el mismo partido tenga las mismas siglas y el mismo color en todas partes.

Para añadir una institución basta un módulo nuevo en `escrutinio/territorial/fuentes/` que declare
`CUERPOS` (con su número, legislaturas y escaños) y `descargar(ctx)` o `documentos(ctx)`; se prueba
con `python -m escrutinio territorial-probar <módulo>` sin tocar la base.

### Cobertura

Situación a 27 de septiembre de 2026. Casi todos los diarios y actas se leen ya con reglas; «para
leer» son los días que las reglas no saben leer (investiduras por llamamiento, elecciones con
papeleta, escaneos ilegibles), que DeepSeek va procesando con un cupo por ejecución (40 documentos
al día, repartidos entre instituciones). La web calcula la tabla con lo que haya cargado en cada
momento.

En total, 106.277 votaciones de 27 instituciones autonómicas, provinciales y municipales, además de
las 16.928 del Congreso.

**Parlamentos autonómicos**

| Institución | Conector | Legislaturas | Votaciones | Detalle | Cómo |
| --- | --- | --- | --- | --- | --- |
| Parlamento de Andalucía | `andalucia` | IX–XIII (2012–) | 4.650 | Voto de cada diputado (98 %), por grupo y totales | PDF del sistema de votación, con reglas; fichas de iniciativa |
| Junta General del Principado de Asturias | `asturias` | X–XII (2015–) | 5.074 | Voto de cada diputado hasta 2023; después, totales y resultado | XML de eParlamento cruzado con el Diario de Sesiones |
| Parlamento de Canarias | `canarias` | IV–XI (1995–) | 9.847 | Totales y resultado | Texto del Diario (API de datos abiertos) y, antes de 2007, el PDF del Diario, con reglas; 4.609 iniciativas |
| Cortes de Castilla y León | `castilla_leon` | IX–XII (2015–) | 2.781 | Totales y resultado | Versión de texto del Diario, con reglas |
| Parlament de Catalunya | `cataluna` | XII–XV (2018–) | 11.836 | Totales y resultado | Diari de Sessions, con reglas |
| Corts Valencianes | `valencia` | V–XI (1999–) | 3.018 | Totales y resultado; voto de cada diputado en 2019–2020 | Sumario del Diari de Sessions, con reglas, y XML por sesión (2019–2020); los días de presupuestos e investiduras, para leer |
| Asamblea de Extremadura | `extremadura` | IX–XII (2015–) | 3.620 | Voto de cada diputado y por grupo | Informe de votaciones en PDF, con reglas |
| Parlamento de Galicia | `galicia` | X–XII (2016–) | 2.956 | Totales y resultado | Diario de Sesiones, con reglas |
| Parlamento de La Rioja | `la_rioja` | IX–XI (2015–) | 1.435 | Totales, resultado y voto por grupo (IX–X) | Diario de Sesiones, con reglas; 962 iniciativas |
| Cortes de Aragón | `aragon` | X–XII (2019–) | 3.125 | Totales, resultado y, a veces, voto por grupo | Diario de Sesiones leído entero en la primera carga; los nuevos, para leer |
| Parlamento de Cantabria | `cantabria` | VIII–XI (2013–) | 3.373 | Totales, resultado y voto por grupo (80 %) | Actas del Pleno en PDF, con reglas; 2.422 iniciativas |
| Cortes de Castilla-La Mancha | `castilla_la_mancha` | VIII–XI (2011–) | 2.767 | Totales y resultado | Diario de Sesiones, con reglas |
| Asamblea Regional de Murcia | `murcia` | IX–XI (2015–) | 1.365 | Totales, resultado y voto por grupo (sobre todo XI) | Actas en PDF, con reglas (las de IX y X están escaneadas y se leen peor) |
| Parlament de les Illes Balears | `baleares` | VIII–XI (2011–) | 12.374 | Totales y resultado | Diario de Sesiones en PDF, con reglas, contrastado con los «Resultats de votacions» (2014–2020) |
| Parlamento de Navarra | `navarra` | IX–XI (2015–) | 3.135 | Totales y resultado | Diario de Sesiones en PDF, con reglas |
| Parlamento Vasco | `pais_vasco` | X–XIII (2012–) | 5.396 | Totales y voto de cada grupo | PDF oficial con el resultado de cada votación (datos abiertos y buscador del Parlamento) |
| Asamblea de Madrid | — | | — | Sin conector | Su web exige ejecutar JavaScript antes de servir nada (protección contra robots). No se ha intentado saltarla: hace falta que la Asamblea lo permita o publique los datos |

**Provincial e insular**

| Institución | Conector | Votaciones | Detalle | Cómo |
| --- | --- | --- | --- | --- |
| Juntas Generales de Álava | `juntas_generales` | 4.125 (1999–) | Totales y resultado | Fichas HTML de expediente; catálogo de iniciativas |
| Juntas Generales de Bizkaia | `juntas_generales` | 286 (2013–) | Totales, resultado y voto por grupo | Actas en PDF, con reglas |
| Juntas Generales de Gipuzkoa | `juntas_generales` | 708 (2005–) | Totales | Listado de sesiones; el resto, actas para leer |
| Cabildo de Lanzarote, Consell de Mallorca | `cabildos_consells` | — | Actas para leer (61 y 79) | |

**Ayuntamientos**

| Ayuntamiento | Conector | Periodo | Votaciones | Detalle | Cómo |
| --- | --- | --- | --- | --- | --- |
| Zaragoza | `zaragoza` | 2015– | 7.206 | Totales, resultado y voto por grupo | Extracto de acuerdos en HTML, con reglas |
| Alicante | `alicante` | 1999– | 5.056 | Totales, resultado y voto por grupo | Actas y extractos, con reglas |
| Córdoba | `cordoba` | 2012– | 4.513 | Totales, resultado y voto por grupo | Extracto de pleno en PDF, con reglas |
| Málaga | `malaga` | 2019– | 2.959 | Totales, resultado y voto por grupo | Videoactas en PDF, con reglas |
| Valladolid | `valladolid` | 2015– (sin oct. 2023–may. 2025) | 2.103 | Totales, resultado y voto por grupo | «Acuerdos adoptados», con reglas |
| Gijón | `gijon` | 2015– | 1.580 | Voto de cada concejal (JSON municipal, hasta 2025) y por grupo | Datos abiertos y actas con reglas; actas antiguas para leer |
| Valencia | `ayto_valencia` | 2018– | 705 | Resultado y grupo proponente | CSV de mociones por sesión; actas para leer (voto por grupo) |
| Las Palmas de Gran Canaria | `las_palmas` | 2025– | 284 | Totales, resultado y voto por grupo | Actas en PDF, con reglas (las anteriores son imágenes escaneadas) |
| 69 ayuntamientos de Cataluña de más de 20.000 habitantes | `aoc_actes` | 2015– | — | Actas para leer (10.231) | Dataset «Actes de Ple» del Consorci AOC |

Descartados tras comprobarlos: Séneca (la API de votos pide identificarse), los datos abiertos del
Ayuntamiento de Madrid (no hay acuerdos ni votos), el Cabildo de Tenerife (los acuerdos piden Cl@ve) y
el de Gran Canaria (no se puede listar sus actas).

### Limitaciones

- Cada fuente cubre periodos distintos y con distinto detalle: las comparaciones entre instituciones
  deben tener en cuenta la columna «Detalle» de la tabla de la portada (que la web calcula con lo que
  hay cargado).
- Las votaciones leídas de diarios y actas dependen de cómo se redactan: si el acta dice «queda
  aprobada» sin cifras, no hay totales. Conviene contrastarlas con el documento, enlazado en cada una.
- Solo se recoge el pleno, nunca las comisiones.
- Algunas instituciones pueden ir con retraso si su web no acepta conexiones desde fuera de España
  (ver «Aviso: webs que no responden desde fuera de España»); la web lo avisa con ⚠.
- Las diputaciones provinciales de régimen común quedan fuera por lo que aportan frente al esfuerzo
  (elección indirecta, mucha unanimidad y una web distinta cada una), como explica el documento de
  fuentes.

## Licencia

Código bajo licencia MIT (`LICENSE`). sql.js, en `web/vendor/`, es MIT. Los datos proceden de los
datos abiertos del Congreso de los Diputados y de las webs de cada parlamento, juntas generales y
ayuntamiento, que se enlazan desde cada votación.
