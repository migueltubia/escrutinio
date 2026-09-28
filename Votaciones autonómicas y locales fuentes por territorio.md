# Votaciones autonómicas y locales: fuentes por territorio

Sep 26, 2026 · @Miguel

## Parlamentos autonómicos

La tabla va ordenada de más fácil a más difícil. «Voto» indica el nivel de detalle que se publica. La dificultad va de 1 (descargar un fichero) a 5 (PDF heterogéneo con la web bloqueada). Las leyes autonómicas aprobadas se publican en el BOE, así que su texto y las leyes que modifican se sacan de la API de legislación consolidada en todos los casos, igual que las estatales.

| Comunidad | Qué se publica y dónde | Voto | Cómo sacarlo | Dificultad |
| --- | --- | --- | --- | --- |
| Asturias | [eParlamento](https://eparlamento.jgpa.es/transparencia/votaciones/index.php): una página por votación con descarga en XML (`&xml=si`, ISO-8859-1) y PDF. Expediente tipo 11/0177/0001/01562. Faltan los votos telemáticos de mayo 2020 a abril 2021 | Nominal y por grupo, de 2015 a 2023. La legislatura actual está en jgpa.es/votaciones, sin verificar | Recorrer el índice de sesiones y bajar el XML de cada votación | 1-2 |
| Andalucía | [Sentido del voto](https://www.parlamentodeandalucia.es/webdinamica/portal-web-parlamento/composicionyfuncionamiento/resultadosvotaciones.do): un PDF por sesión generado por el sistema de voto electrónico, con expediente tipo 13-26/PNLP-000012. Textos en el BOPA desde 1982 | Nominal, por grupo y totales, en PDF | Buscar por sesión, bajar el PDF y parsearlo con reglas (el formato es tabular) | 2 |
| Canarias | [datos.parcan.es](https://datos.parcan.es) (CKAN, CSV y JSON): iniciativas por tipo y año desde 1995. Expediente tipo 11L/PNLP-0343. Diario de Sesiones en PDF y HTML | Solo totales, y a veces solo «queda aprobada» | Iniciativas en CSV. Totales del Diario con reglas o LLM, uniendo por expediente | 3 |
| La Rioja | Buscador de iniciativas sin exportación, con expediente tipo 11L/PNLP-0366. Diario de Sesiones en HTML desde la legislatura provisional | Solo totales | Scraping del HTML del Diario. El expediente aparece en el propio texto | 3 |
| Castilla y León | Sin datos abiertos. Diario de Sesiones en PDF con URL predecible (`DSPLN{leg}{núm}A.pdf`) en SIRDOC. Identificadores tipo PNL/000735 | Solo totales | PDF y LLM, uniendo por identificador | 3 |
| Navarra | Sin datos abiertos, pero con [RSS](https://www.parlamentodenavarra.es/es/rss-feeds) de expedientes, boletines y diarios. Ficha HTML por expediente (tipo 11-25/MOC-00007) | Solo totales, en el Diario en PDF | Expedientes por RSS, totales del PDF con LLM | 3-4 |
| Madrid | Tiene página de datos abiertos y una sección de votaciones por iniciativa, pero no se pudieron abrir | Sin verificar. Podría tener desglose por grupo | Revisar a mano primero. Si hay datos, descarga directa | 2-3 (sin verificar) |
| País Vasco | Tiene página de Open Data, que no se pudo abrir | Sin verificar | Revisar a mano primero | 2-4 (sin verificar) |
| Comunitat Valenciana | [Votaciones](https://www.cortsvalencianes.es/es/parlament-obert/transparencia/actividad/votaciones): XML por sesión con cada diputado y grupo, pero solo de septiembre 2019 a octubre 2020. La unión con la iniciativa se hace por el número de registro de entrada que va dentro del título | Nominal en 2019-2020. En la legislatura actual, sin verificar | XML para ese periodo. Para el resto, Diario de Sesiones con LLM | 1 (2019-20), 4 (resto) |
| Cataluña | Sin datos abiertos (las páginas daban error y la web está en migración). Diario de Sesiones en PDF en catalán, con número de tramitación tipo 250-00521/15 | Solo totales | PDF y LLM | 4 |
| Galicia | Sin datos abiertos. Diario de Sesiones en PDF en gallego, con expediente tipo 12/DEBA-000001. La web devuelve 403 salvo en los PDF | Solo totales | PDF y LLM. El bloqueo complica rastrear la web | 4 |
| Aragón | Diario de Sesiones y boletín en PDF, en una base Lotus Domino. Hay una página «Votaciones» que no se pudo abrir | Totales. El detalle de esa página, sin verificar | Scraping de las fichas del Diario y LLM | 4 |
| Cantabria | Buscador de expedientes con URL propia (tipo 11L/4300-0010). Diario en PDF por punto del orden del día | Solo totales | Scraping de expedientes y totales del PDF con LLM | 4 |
| Murcia | Web con certificado roto y 403. Diarios del pleno, probablemente en PDF | Sin verificar | PDF y LLM | 4 |
| Baleares | Web inaccesible con la herramienta. Existe una página de votaciones sin verificar. Diarios y boletín en PDF en catalán | Sin verificar | Si la página tiene detalle, scraping. Si no, PDF y LLM | 3-4 (sin verificar) |
| Castilla-La Mancha | Web inaccesible con la herramienta. Diario de Sesiones en PDF | Sin verificar | Previsiblemente PDF y LLM | 4 (sin verificar) |
| Extremadura | Web inaccesible con la herramienta. Tiene base de datos de iniciativas y transcripciones en HTML | Sin verificar | Transcripción HTML o PDF y LLM | 4 (sin verificar) |

Ceuta y Melilla son asambleas con rango de ayuntamiento y se tratan como tal. Las actas de Ceuta traen el voto nominal agrupado por partido en PDF. Las de Melilla están en su sede electrónica y el formato no se ha comprobado.

En la práctica esto da tres tipos de conector. El primero descarga datos estructurados (Asturias, Valencia 2019-2020, las iniciativas de Canarias). El segundo parsea PDF de formato fijo con reglas (Andalucía). El tercero, que cubre la mayoría, lee el Diario de Sesiones con un LLM para sacar cada votación con su expediente y sus totales. Casi todos los parlamentos imprimen el código de expediente en el Diario, y ese código es la llave para unir votación e iniciativa.

## Nivel provincial e insular

Aquí hay cuatro tipos de institución muy distintos, y conviene tratarlos por separado. No se ha encontrado ninguna que publique sus votaciones como datos abiertos. El BOP tampoco sirve, porque publica ordenanzas y anuncios pero no las votaciones.

**Juntas Generales vascas (Álava, Bizkaia, Gipuzkoa): incluir.** Son parlamentos de elección directa. Aprueban normas forales, entre ellas los impuestos concertados (IRPF, Sociedades), y los presupuestos forales. Para un análisis político pesan como un parlamento autonómico. Las tres tienen buscador de iniciativas con expediente: [Gipuzkoa](https://www.bngipuzkoa.eus/WAS/CORP/DJGPortalWEB/iniciativas.jsp?idioma=es), [Álava](https://www.jjggalava.eus/ultimas-iniciativas) (con una sección de estadísticas) y [Bizkaia](https://jjggbizkaia.eus/en/initiatives). No se ha podido comprobar si las fichas muestran el voto: Álava y Bizkaia cargan con JavaScript y Gipuzkoa bloquea su visor. Se trabajarían como un parlamento pequeño: scraping de iniciativas y votos del diario de sesiones con LLM. Dificultad 3.

**Cabildos canarios (7) y Consells Insulars de Baleares (4): segunda fase.** También son de elección directa y tienen competencias reales: carreteras, servicios sociales, territorio, turismo. Publican actas en PDF donde el voto por grupo va en texto libre. Por ejemplo, un acta del [Consell de Mallorca](https://seu.conselldemallorca.net/documents/785222/788352/20161212_sessio_ordinaria_ple.pdf/4a4576bd-3a2b-de15-6f21-1f6a20c105f0?t=1539174980272&download=true) dice: «s'aprova per vint-i-vuit vots a favor (PP, PSOE, MÉS per Mallorca…), cap vot en contra i una abstenció». Son solo 11 y el mismo extractor de actas municipales les sirve. Dificultad 4, sobre todo por las webs: la de transparencia de Tenerife solo carga con JavaScript y la de Gran Canaria devuelve 403.

**Diputaciones provinciales de régimen común (38): excluir.** Son de elección indirecta y sus competencias son de apoyo a los municipios: planes de obras, carreteras provinciales, recaudación. Sus plenos tienen mucha unanimidad y bastantes mociones copiadas de la agenda nacional. Publican actas en PDF o en vídeo, con una web distinta cada una ([León](https://transparencia.dipuleon.es/indicadores/Actas-y-acuerdos/11.01.-Actas-de-pleno), [Cádiz](https://www.dipucadiz.es/secretaria_general/pleno/), [Barcelona](https://seuelectronica.diba.cat/ca/sessions-del-ple-i-de-la-junta-de-govern)), y muchas bloquean los bots. El esfuerzo de cubrir 38 no compensa lo que aportan.

Hay una vía que podría cambiar esto y conviene probarla antes de descartar del todo. Varias diputaciones usan la mediateca [Séneca](https://www.depo.gal/es/w/noticia-inversion-na-mediateca-seneca-para-seguir-os-plenos) para sus plenos (Cádiz y Pontevedra confirmadas). Séneca dice indexar los plenos por punto del orden del día con sus votaciones, y la usan más de 200 instituciones con el patrón `<cliente>.seneca.tv`. Si expone los votos de forma estructurada, un solo conector cubriría muchas diputaciones y ayuntamientos a la vez. No se ha podido verificar.

## Nivel municipal

Las ciudades sí son viables, pero solo una selección. Ninguna de las 16 más grandes publica un dataset con el voto por grupo. Casi todas lo escriben en el acta o en un extracto de acuerdos, con frases bastante regulares como «25 votos a favor (GP, GS y GV), 1 en contra (GEUP) y 2 abstenciones (GC)». Un LLM las convierte en datos con fiabilidad alta. Lo que diferencia a unas ciudades de otras es encontrar los PDF, no leerlos.

| Ciudad | Fuente | Cómo aparece el voto | Dificultad | Fase |
| --- | --- | --- | --- | --- |
| Las Palmas de Gran Canaria | Actas PDF con URL predecible (`PL-A-AAAAMMDD-nn-O.pdf`) desde 2019 | Muy estructurado: número por grupo en cada sentido | 2 | 1 |
| Valladolid | PDF corto de «Acuerdos adoptados por el Pleno» por sesión | Por grupo, en una frase | 2 | 1 |
| Alicante | [Herramienta de plenos](https://w3.alicante.es/ayuntamiento/plenos/) desde 1999, con parámetros por fecha | Por grupo en el acta. El extracto HTML solo dice aprobado o rechazado | 2 | 1 |
| Gijón | [Listado de proposiciones](https://proposiciones.gijon.es) con proponente y resultado, más actas en PDF | Resultado en el listado y voto por grupo en el acta | 2 | 1 |
| Valencia | CSV de seguimiento de mociones por sesión (tipo, asunto, grupo proponente, resultado) más actas bilingües | Por grupo en el acta, no en el CSV | 2-3 | 1 |
| Córdoba | Extracto de pleno en PDF en su oficina virtual (misma plataforma que Málaga) | Por grupo en el extracto | 2-3 | 1 |
| Málaga | [Videoactas](https://videoactas.malaga.eu) desde 2019 con PDF por sesión | Por grupo | 3 | 1 |
| Madrid | Diario de Sesiones y PDF de acuerdos en transparencia.madrid.es, con ruta por fecha | Por grupo con número de concejales | 3 | 2 |
| Sevilla | Actas PDF por año con URL predecible, muy largas | Nominal por concejal y grupo | 3 | 2 |
| Vitoria-Gasteiz | Actas PDF con URL numerada | Por grupo (formato actual sin verificar) | 2-3 | 2 |
| Zaragoza | Fichas de moción en la sede y API REST municipal. La web no se pudo abrir | Sin verificar. Podría ser la mejor fuente estructurada si la ficha sale en JSON | 2-3 (sin verificar) | Comprobar primero |
| Barcelona | Gaseta Municipal y acuerdos por sesión. El resto de la web bloquea | Por grupo en catalán (visto en comisión) | 3 | 3 |
| Vigo | Sede con índice por año, pero las actas están dispersas | Por grupo en gallego | 3-4 | 3 |
| Palma | Extracto y acta en PDF en la sede (Sedipualba) | Sin verificar | 3-4 | 3 |
| Murcia | PDF con nombres de fichero sin patrón. Web bloqueada | Sin verificar | 3-4 | 3 |
| Bilbao | Blobs de WebCenter con URL impredecible. Web bloqueada | Sin verificar | 4 | 3 |

Para el resto de Cataluña hay una opción de cobertura amplia: el dataset multientidad [«Actes de Ple» del Consorci AOC](https://dadesobertes.seu-e.cat/dataset/agn-ag-actes-de-ple), en CSV con API y licencia CC0, que reúne los acuerdos de pleno de muchos municipios. No se han podido ver sus columnas, así que no se sabe si trae el voto. Merece la pena revisarlo antes de construir nada propio para Cataluña.

Los proveedores de videoacta (Gestiona, VideoActa, IActa, Séneca) no ofrecen una API pública de votos, salvo quizá Séneca. De momento no sirven como atajo.

La propuesta es empezar con las siete de la fase 1, que tienen URL predecible y el voto bien redactado, y probar con ellas el extractor de actas. Si funciona, ampliar a las de fase 2. Las de fase 3 solo cuando haya tiempo para pelearse con cada web.

## Fuentes

Solo se incluyen las páginas que se pudieron abrir. Las demás figuran en las tablas como sin verificar.

- Parlamentos: [Asturias, eParlamento votaciones](https://eparlamento.jgpa.es/transparencia/votaciones/index.php) · [Andalucía, sentido del voto](https://www.parlamentodeandalucia.es/webdinamica/portal-web-parlamento/composicionyfuncionamiento/resultadosvotaciones.do) · [Canarias, datos abiertos](https://datos.parcan.es) · [Corts Valencianes, votaciones](https://www.cortsvalencianes.es/es/parlament-obert/transparencia/actividad/votaciones) · [Navarra, RSS](https://www.parlamentodenavarra.es/es/rss-feeds) · [La Rioja, diarios de sesiones](https://www.parlamento-larioja.org/recursos-de-informacion/publicaciones-oficiales/diarios-de-sesiones) · [Castilla y León, Diario de Sesiones n.º 60](https://sirdoc.ccyl.es/SIRDOC/PDF/PUBLOFI/DS/PLN/11L/DSPLN1100060A.pdf) · [Galicia, Diario de Sesiones](https://www.parlamentodegalicia.es/sitios/web/BibliotecaDiarioSesions/D120049.pdf)
- Juntas Generales: [Gipuzkoa](https://www.bngipuzkoa.eus/WAS/CORP/DJGPortalWEB/iniciativas.jsp?idioma=es) · [Álava](https://www.jjggalava.eus/ultimas-iniciativas)
- Provincial e insular: [Diputación de León](https://transparencia.dipuleon.es/indicadores/Actas-y-acuerdos/11.01.-Actas-de-pleno) · [Diputación de Cádiz](https://www.dipucadiz.es/secretaria_general/pleno/) · [Diputació de Barcelona](https://seuelectronica.diba.cat/ca/sessions-del-ple-i-de-la-junta-de-govern) · [Consell de Mallorca](https://seu.conselldemallorca.net/acords-del-consell-executiu) · [Diputación de Pontevedra, Séneca](https://www.depo.gal/es/w/noticia-inversion-na-mediateca-seneca-para-seguir-os-plenos)
- Municipal: [Consorci AOC, Actes de Ple](https://dadesobertes.seu-e.cat/dataset/agn-ag-actes-de-ple) · [Alicante, plenos](https://w3.alicante.es/ayuntamiento/plenos/) · [Gijón, proposiciones](https://proposiciones.gijon.es) · [Málaga, videoactas](https://videoactas.malaga.eu) · [Madrid, datos abiertos](https://datos.madrid.es) · [Barcelona, acuerdos del plenario](https://ajuntament.barcelona.cat/es/accion-de-gobierno/el-consejo-municipal/acuerdos-de-plenario) · [Córdoba, acuerdos 2023](https://datosabiertos.cordoba.es/ckan/dataset/pleno-municipal-del-ayuntamiento-de-cordoba-acuerdos-2023/resource/9e664779-6a1f-411f-9515-3d64f7d2a9f4)
