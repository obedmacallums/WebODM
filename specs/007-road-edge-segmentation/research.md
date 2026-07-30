# Research — borde por segmentación semántica de la ortofoto (`007-road-edge-segmentation`)

Decisiones numeradas **D25 en adelante**, continuando la serie de `006-street-width` (D17–D24), que
a su vez continuó la de `005-road-metrics` (D1–D16): las tres features describen el mismo plugin y
el código cita las decisiones por número.

A diferencia de `006`, aquí **no hay mediciones reales** del modelo `roads` de `geodeep` sobre datos
del proyecto: el modelo no se ha corrido todavía sobre ninguna ortofoto de la instancia. Lo que
sigue combina hechos verificados leyendo el código actual de `coreplugins/road/` y
`coreplugins/objdetect/`, y la documentación pública de GeoDeep (README de
`https://github.com/uav4geo/GeoDeep`, confirmado el 2026-07-29). Donde una decisión depende de un
comportamiento del modelo que no se ha observado, se dice explícitamente.

---

## D25 — Dónde entra la segmentación en el pipeline: un módulo nuevo, análogo a `coherence.py`

**Decisión**: nuevo módulo `coreplugins/road/segmentation.py`. Antes del bucle de bloques de
`compute.analyze`, cuando `params['edge_mode'] == 'segmentation'`, se genera el corredor del eje
(D26), se recorta la ortofoto y se ejecuta `geodeep.segment` para producir una máscara ráster
`road` / `not_road` georreferenciada. El `dataset` de esa máscara se abre igual que hoy se abre el
DEM (`with rasterio.open(...)`) y se muestrea en los mismos puntos del perfil transversal que ya
calcula `geometry.cross_section_points`, con la misma función de muestreo por vecino más próximo que
ya usa `_sample` para el DEM.

**Justificación**: reutilizar el muestreo existente es lo que evita construir un pipeline paralelo.
El perfil transversal —offsets con signo desde el eje, muestreado por vecino más próximo, con `NaN`
donde no hay dato— es una idea agnóstica de qué ráster se está leyendo; hoy solo se usa sobre el DEM
porque hasta esta feature no había otro ráster que muestrear. Duplicar esa lógica para la máscara
sería divergencia esperando a pasar.

Que sea un módulo nuevo y no una rama de `compute.py` sigue el mismo criterio de `006/D23`
(`coherence.py` separado de `profile.py`): la generación del corredor y la llamada a `geodeep` son
E/S y dependen de una librería externa opcional, mientras que el resto de `compute.py` para los
otros dos modos es memoria y matemática. Mezclarlo obligaría a que todo `compute.py` maneje
`ImportError` de una dependencia que dos de sus tres modos no usan nunca.

**Alternativas descartadas**:

- *Segmentar dentro de `profile.py`*: `profile.py` declara explícitamente que no hace E/S
  (`profile.py:1-6`); abrir un ráster o invocar `subprocess` ahí rompería esa garantía, que es lo
  que permite probarlo con perfiles sintéticos sin montar Django ni rásteres.
- *Recortar y segmentar dentro de `_read_block`, por bloque de tramos*: repetiría la inferencia del
  modelo tantas veces como bloques tenga el análisis (D9 de `005`: hasta unas pocas decenas para un
  eje largo). La inferencia de un modelo ONNX es cara comparada con indexar un array ya en memoria;
  hacerlo una vez por análisis, no por bloque, es obligatorio para que el coste no escale con la
  longitud del eje más de lo necesario.

---

## D26 — El corredor del eje, no la ortofoto completa (resuelve Q2 de la clarificación)

**Decisión**: antes de invocar `geodeep.segment`, se recorta la ortofoto a un corredor: el buffer
del eje completo (todos los vértices, no por tramo) por `search_half_width` más un margen fijo, con
`gdalwarp -cutline` sobre un `VRT`, exactamente el mismo patrón que ya usa
`coreplugins/objdetect/api.py:detect()` cuando `crop` no es `None`.

**Justificación**: el usuario ya eligió esta opción en la clarificación (2b) frente a segmentar la
ortofoto completa de la tarea o segmentar por tramo individual. Verificado en el código, la razón
que la hace preferible es la misma que ya documentó `objdetect`: recortar con `gdalwarp` antes de
correr el modelo evita cargar en memoria un ráster cuyo tamaño no depende de la longitud del eje
sino del vuelo completo, y evita repetir la inferencia una vez por tramo (que sería el coste de
segmentar por tramo, la opción C descartada por el usuario).

El margen sobre `search_half_width` existe porque el buffer se calcula sobre el eje **antes** de
conocer los bordes; sin margen, un borde real que cae justo en el límite del semiancho de búsqueda
podría quedar fuera del recorte por el redondeo del buffer o por el remuestreo del propio modelo
(resolución nativa 21 cm/px, D28). El valor concreto del margen es un detalle de implementación, no
de esta spec; una fracción de la resolución nativa del modelo basta y se fija en `tasks.md`.

**Alternativas descartadas** (documentadas ya en la clarificación con el usuario, D26 solo añade la
justificación técnica encontrada en el código):

- *Ortofoto completa de la tarea*: coste de memoria y tiempo de inferencia que no depende de la
  longitud del eje trazado, sino del vuelo entero — desproporcionado para un eje corto sobre un
  vuelo grande.
- *Por tramo individual*: repite la inferencia del modelo en los bordes compartidos entre tramos
  contiguos, y multiplica por el número de tramos (cientos, según D9 de `005`) el coste fijo de
  invocar el modelo, que domina sobre el coste de segmentar más o menos superficie.

---

## D27 — El progreso de la segmentación viaja por el canal que ya existe, no por uno nuevo

**Decisión**: `compute.run_analysis` **ya** ejecuta como tarea asíncrona con progreso y cancelación
(`api.py:328-333`: `run_function_async(compute.run_analysis, ..., with_progress=True,
with_cancel=True)`), con un candado de ejecución por tarea en `store.py` y una `progress_callback`
que ya informa el avance del bucle de bloques (`compute.py:415-416`). La etapa de segmentación se
inserta como una fase adicional que reporta sobre el mismo `progress_callback`, antes del bucle
principal — por ejemplo, un tramo de progreso reservado para "Segmentando la ortofoto" antes del
tramo ya existente "Analizando el camino".

**Justificación**: esta decisión corrige una premisa incorrecta de la primera versión de `spec.md`
(FR-009), que describía el modo segmentación como necesitado de "un mecanismo asíncrono con
progreso, como ya hace `objdetect`", dando a entender que los modos `break` y `surface` corren hoy
de forma síncrona. Leyendo `api.py`, `compute.py` y `store.py` se confirmó que **no** es así: todo
análisis del plugin `road`, en cualquier modo, ya corre en segundo plano con progreso, candado de
ejecución y cancelación, desde antes de `005-road-metrics`. El objetivo que perseguía la
clarificación con el usuario (3b: que el usuario vea progreso mientras el modelo de IA corre, y
pueda cerrar el panel sin cancelar el cálculo) se cumple sin construir nada nuevo: basta con que la
etapa de segmentación, que puede tardar bastante por ser inferencia de un modelo, reporte a través
del canal que ya existe en vez de dejar al usuario sin señal alguna durante esa fase. `spec.md`
FR-009 y FR-016a se corrigieron para reflejar esto (`checklists/requirements.md`, nota del
2026-07-29).

**Alternativas descartadas**:

- *Construir un mecanismo de segundo plano nuevo, calcado del `Workers.waitForCompletion` de
  `objdetect`*: sería la alternativa correcta si `road` no tuviera ya su propio mecanismo, pero
  tenerlo y no reutilizarlo sería una duplicación deliberada sin ninguna ventaja — dos formas de
  hacer lo mismo en el mismo plugin, con el doble de superficie de test.

---

## D28 — Fallo global de la fuente de segmentación, frente a falta de cobertura de un tramo

**Decisión**: se distinguen dos situaciones que la spec agrupó bajo el mismo requisito (FR-007) pero
que se resuelven en dos sitios distintos del pipeline:

1. **Fallo global de la etapa de segmentación** — la tarea no tiene ortofoto en absoluto, la
   librería `geodeep` no está instalada, o el modelo `roads` no se puede descargar (sin red desde el
   worker, o el repositorio de modelos no responde): el análisis **completo** falla, con el mismo
   mecanismo de excepción que `run_analysis` ya usa hoy para cualquier fallo (`compute.py:709-716`:
   `except Exception as e: ... _finish({'status': 'failed', 'error': str(e), ...})`). No se llega a
   producir ni un solo tramo.
2. **Falta de cobertura de un tramo concreto** — la etapa de segmentación se completó (hay máscara),
   pero la ortofoto no cubre la zona de ese tramo en particular (vuelo con un hueco, o el eje se
   sale del área volada en un punto intermedio): **ese** tramo, y solo ese, se reporta sin borde con
   el motivo nuevo de D29.

**Justificación**: es el mismo patrón que ya separa, en los otros dos modos, un DEM que falta por
completo (la tarea no tiene DTM/DSM: la petición se rechaza antes de lanzar el análisis,
`api.py:no_elevation_model()`) de una muestra concreta sin dato dentro de un DEM que sí existe (el
motivo `no_data` de `profile.py`, por tramo). No es una distinción nueva que esta feature inventa;
es aplicar la que ya existe a la fuente de datos nueva.

Cumple igualmente FR-007 tal como quedó redactado tras la clarificación (1b): el usuario recibe
"un motivo identificable" en los dos casos. En el caso 1 el motivo es el mensaje de error del
análisis completo (`analysis.error`, ya expuesto por el contrato existente); en el caso 2 es el
motivo nuevo por tramo. No hace falta reabrir la clarificación porque ninguna de las tres opciones
que se le presentaron al usuario (A/B/C) distinguía entre "global" y "por tramo" — todas hablaban
del motivo en sí, no de dónde vive la comprobación.

**Alternativas descartadas**:

- *Tratar la falta total de ortofoto o de modelo como un motivo más por tramo*, repitiéndolo en los
  cientos de tramos del análisis: técnicamente posible, pero peor experiencia (un CSV de 200 filas
  todas con el mismo motivo, cuando el problema es uno solo y es del análisis, no del tramo) y
  contrario al patrón ya establecido para el DEM ausente.

---

## D29 — El motivo nuevo: `no_orthophoto`, y por qué aquí sí se amplía el contrato

**Decisión**: se añade una cuarta constante de motivo en `profile.py`, `NO_ORTHOPHOTO =
'no_orthophoto'`, junto a las tres ya existentes (`NO_BREAK`, `NO_DATA`, `BREAK_AT_AXIS`). Se usa
exclusivamente para el caso 2 de D28: cobertura de ortofoto ausente sobre un tramo concreto, en modo
segmentación.

**Justificación**: `006/FR-010` estableció que el modo `surface` **reutiliza** los tres motivos
existentes sin añadir ninguno, y `006/D21` explica por qué (no romper el contrato que ya consume el
frontend con tres etiquetas). Esa restricción sigue vigente para `break` y `surface`, que comparten
la misma fuente de datos —el DEM— y por tanto los mismos tres modos de fallo. El modo segmentación
tiene una fuente de datos estructuralmente distinta —la ortofoto y un modelo externo—, con un modo
de fallo que ninguno de los tres motivos existentes describe con precisión: `no_data` en `profile.py`
significa hoy "el DEM se quedó sin dato" (`profile.py:26`), y reutilizarlo para "no hay ortofoto"
mentiría sobre cuál de las dos fuentes falló, justo cuando el usuario tiene dos fuentes distintas que
diagnosticar por primera vez.

Es la misma decisión que ya tomó `006/D21` para el origen del borde (`medido`/`inferido`): cuando
una distinción nueva no cabe en el contrato existente sin perder información, se amplía el contrato
en vez de forzarla dentro de una categoría que ya significa otra cosa.

**Alternativas descartadas**:

- *Reutilizar `no_data`*: es la opción A que se le ofreció al usuario en la clarificación y que no
  eligió (1b, no 1a). Sería menos invasiva en el contrato pero mentiría sobre la causa.
- *Dos motivos separados, uno para "sin ortofoto" y otro para "modelo no disponible"* (opción C
  ofrecida y no elegida): innecesaria a la luz de D28 — el caso "modelo no disponible" ya no es
  un motivo por tramo, es un fallo global del análisis, así que la distinción que la opción C quería
  capturar por tramo no llega a plantearse ahí.

---

## D30 — Detección de borde sobre la máscara: mismo patrón de recorrido, distinto criterio de parada

**Decisión**: nueva función `profile.detect_edges_segmentation(distances, mask_values,
min_consecutive)`, con el mismo contrato de entrada/salida que `detect_edges_surface` (mismo
`distances` con signo, mismo `center`, mismos tres motivos existentes reinterpretados más
`NO_ORTHOPHOTO`). `mask_values` es la clasificación binaria (`1.0` = calzada, `0.0` = no calzada,
`None` sin cobertura) muestreada en los mismos offsets que la elevación. El borde de cada lado es la
**última muestra conforme** —la última clasificada como calzada, no la primera ya fuera— antes de
que la clasificación deje de ser calzada y se mantenga así durante `min_consecutive_samples`
muestras.

**Justificación, y una corrección sobre el diseño inicial**: la primera implementación (durante
`/speckit-implement`) reportaba la *primera* muestra no-calzada, calcada de `_scan_side` (el
arranque del quiebre en modo `break`). Los tests sintéticos con un semiancho de calzada exacto en el
grid de muestreo (p. ej. 4,00 m con paso 0,25 m) esperaban ese valor exacto y obtuvieron 4,25 m: un
paso de muestreo de más, porque "la primera muestra no-calzada" cae necesariamente un paso más allá
del límite real. A diferencia del quiebre de pendiente, donde el "arranque de la racha" tiene sentido
porque el propio quiebre es una zona de transición que se está describiendo, aquí la clasificación es
binaria y nítida: no hay transición que describir, solo un límite. El punto que de verdad dice "hasta
aquí es calzada" es la última muestra conforme, exactamente el mismo criterio que `_scan_side_surface`
ya usa para el pie del quiebre en modo `surface` — que es, además, el modo con el que el criterio de
segmentación comparte más naturaleza (los dos buscan dónde *termina* la calzada, no dónde *empieza*
una transición afilada). Se corrigió el código y los tests en el mismo commit, sin que esto afecte a
ningún requisito de `spec.md`: `007/FR-006` habla de "el punto donde la clasificación deja de ser
calzada", que es compatible con las dos lecturas, y esta es la que da un resultado exacto y más útil.

Reutiliza `_center_index` y la misma forma de recorrido que `_scan_side_surface`, en vez de
introducir una tercera manera de recorrer un perfil. `min_consecutive_samples` sigue siendo el único
parámetro antirruido que necesita este modo (`007/FR-015b`): una máscara de segmentación puede tener
píxeles aislados mal clasificados —ruido de inferencia, no ruido de sensor, pero con el mismo efecto
sobre un recorrido muestra a muestra— y exigir una racha sostenida los filtra igual que ya filtra el
ruido de un DEM fotogramétrico en `break`.

Los tres motivos existentes se reinterpretan sobre la máscara sin cambiar de nombre: `NO_BREAK` ("se
recorrió todo el semiancho sin encontrar quiebre") pasa a significar "toda la franja hasta el
semiancho se clasificó como calzada", y `BREAK_AT_AXIS` ("el terreno se rompe sobre el propio eje")
pasa a "la primera muestra vecina al eje ya se clasifica como no-calzada, sin ninguna muestra
conforme que reportar". `NO_DATA` no se usa en este modo: **cualquier** hueco de cobertura dentro de
la máscara —esté donde esté dentro del corredor ya recortado— se reporta como `NO_ORTHOPHOTO` de
manera uniforme (D29), sin distinguir si el hueco viene de fuera de la ortofoto original o de un
`nodata` interno de la propia imagen; esa distinción no aporta nada que el usuario pueda accionar de
forma distinta.

**Alternativas descartadas**:

- *Vectorizar la máscara a polígonos y calcular la intersección geométrica del rayo transversal con
  el polígono de calzada*: es la operación que `geodeep segment` hace por defecto en modo CLI (salida
  GeoJSON de polígonos). Se descarta para la detección de borde porque obligaría a mantener dos rutas
  de lectura de un ráster —muestreo puntual para el DEM, poligonización y operaciones vectoriales
  para la máscara— cuando el muestreo puntual ya resuelve el problema con el mismo código que los
  otros dos modos. La salida vectorial de `geodeep` puede seguir siendo útil para depuración manual,
  pero no es lo que alimenta la detección.
- *Reportar la primera muestra no-calzada* (diseño inicial): descartada tras medir contra los tests
  sintéticos, según el párrafo de justificación de arriba.

---

## D31 — Import de `geodeep` y de `segmentation.py`: mismas reglas que D23 de `006`

**Decisión**: `segmentation.py` importa `geodeep` con el mismo patrón defensivo que
`coreplugins/objdetect/api.py:detect()` — import **dentro** de la función que lo usa, con
`try/except ImportError` que traduce la ausencia de la librería en el fallo global de D28, nunca en
una excepción sin manejar. Y `compute.run_analysis`, que ya importa sus colaboradores de forma
absoluta y dentro del cuerpo por ser self-contained (`006/D23`), importa también
`coreplugins.road.segmentation` con la misma regla.

**Justificación**: `run_function_async` reejecuta `run_analysis` **por su código fuente** en un
namespace vacío (`006/D23`, verificado entonces sobre `coherence.py` y válido sin cambios aquí);
cualquier import a nivel de módulo o relativo pasa todos los tests locales y solo falla dentro del
worker. Es exactamente el riesgo que ya obligó a la verificación de worker no negociable del
Principio IV en `005` y `006`, y aquí se suma un riesgo nuevo del mismo origen que no existía antes:
la primera vez que el worker ejecuta el modo segmentación, `geodeep` necesita **descargar** el
modelo `roads` (README de GeoDeep: los modelos se cachean en `~/.cache/geodeep` por defecto, y
`objdetect.api.detect()` ya lo redirige a `MEDIA_CACHE/detection_models`). Eso exige que el
contenedor worker tenga salida de red hacia donde GeoDeep resuelve sus modelos
(`https://huggingface.co/datasets/UAV4GEO/GeoDeep-Models`, según el README). Si el entorno no tiene
esa salida, el primer intento de usar el modo segmentación falla — y cae, correctamente, en el
fallo global de D28, no en un error opaco.

**Alternativas descartadas**: ninguna nueva; D23 ya descartó meter la lógica en `compute.py` para no
crear un módulo aparte, con la misma razón que aquí (mezclar E/S con la parte pura del pipeline).

---

## D32 — `geodeep` no es una dependencia nueva de la imagen, aunque sí lo sea del plugin

**Decisión**: no hace falta tocar `requirements.txt` del plugin ni el `Dockerfile` del fork
(Principio IV, pasos 1 y 2). Verificado: `geodeep==0.9.12` **ya** está en el `requirements.txt` del
core (`requirements.txt:25`), porque lo necesita `coreplugins/objdetect`, que es upstream. La imagen
ya lo instala hoy, con independencia de esta feature.

**Justificación**: es un hallazgo, no una decisión de diseño — se deja registrado porque cambia la
lectura del Constitution Check (Principio IV) frente a lo que `spec.md` daba por supuesto
("introduce una dependencia de terceros nueva para el plugin `road`", en la sección Dependencies).
Sigue siendo cierto que es nueva **para el código del plugin `road`**, que hasta ahora no la
importaba; no lo es para la imagen ni para el entorno del worker. El paso 3 del Principio IV
(verificación de workers) sigue aplicando igual —y es, de hecho, el único paso de la escalera que
esta feature necesita recorrer—, porque lo que hay que demostrar no es que la librería se instale,
sino que el módulo nuevo del plugin la importa correctamente dentro del namespace vacío del worker
(D31).

**Alternativas descartadas**: n/a — es la constatación de un hecho verificado en el repositorio, no
una elección entre alternativas.

---

## D33 — Lo que sigue sin medirse: si el modelo `roads` sirve sobre ortofotos de dron reales

**Decisión**: se implementa el modo segmentación **sin haber corrido** el modelo `roads` sobre
ninguna ortofoto real del proyecto. Queda como riesgo documentado, no como hecho medido — igual
tratamiento que `006/D24` dio a la pregunta de si hacían falta dos modos de detección, antes de
medirlo.

**Justificación**: `spec.md` ya lo recoge en Assumptions ("el modo segmentación puede rendir peor
que quiebre o superficie fuera del dominio de entrenamiento del modelo") y en Fuera de alcance
("mejorar el desempeño del modelo... se documenta como límite conocido"). Se repite aquí porque es
la incertidumbre que más puede invalidar el diseño entero: si el modelo, entrenado sobre imágenes de
Google Earth a 21 cm/px, no reconoce calzada de forma útil sobre ortofotos de dron a 2-5 cm/px, el
modo segmentación quedaría implementado y disponible pero inútil en la práctica. Nada en este plan
lo puede resolver por adelantado porque depende del propio modelo, no del código que lo envuelve.

**Cómo se resuelve, si se quiere resolver**: correr el modo segmentación sobre una tarea real con
ortofoto y comparar, tramo a tramo, contra el modo superficie donde ambos midan sobre el mismo
bordillo, y contra ningún modo donde el borde sea solo cambio de textura (el caso que motiva la
feature). Es el mismo tipo de comparación que resolvió `006/D24`, y queda como escenario de
validación manual en [quickstart.md](./quickstart.md), no como criterio de aceptación automatizado.

**Resolución (2026-07-29, tras implementar)**: se corrió sobre `Polideportivo María Puebla Vásquez`
(proyecto `marcoleta`), el mismo eje ya trazado (66 m, 14 tramos) que tiene un análisis `surface`
completado. Resultado, comparando ambos modos tramo a tramo:

| | `surface` | `segmentation` |
|---|---|---|
| Tramos medidos | 14 / 14 | 13 / 14 |
| Ancho medio | 7,90 m | 9,35 m |
| Ancho mín. – máx. | 6,79 – 10,39 m | 7,10 – 12,80 m |

El modo `segmentation` **no falla** —mide en 13 de 14 tramos, sin errores— pero mide
sistemáticamente **más ancho** que `surface`: +1,80 m de media sobre los 13 tramos que ambos
midieron, con un máximo de +4,36 m en un solo tramo (progresiva 50–55 m: 8,44 m en `surface` frente
a 12,80 m en `segmentation`). La diferencia no es ruido aleatorio —es sistemáticamente positiva en
12 de los 13 tramos comparables— sino un sesgo. Es exactamente el límite que ya anticipaba
`spec.md` en "Edge Cases" ("Manchas de calzada desconectadas de la calle real") y en Assumptions,
ahora medido en vez de solo hipotetizado.

**Corrección del 2026-07-29 (tarde), tras inspeccionar la máscara.** La primera redacción de este
apartado atribuía el sesgo a que el modelo "probablemente" incluía la acera adyacente. Al renderizar
la máscara devuelta por el modelo superpuesta al recorte del corredor, la causa real resultó ser
bastante más gruesa: el modelo marca como calzada **el descampado de tierra compactada contiguo a
la vía** —una franja de varios metros que no es vía en absoluto— y zonas de tierra de un parque
vecino. En esa escena clasificó como `road` el **25,3 %** de los píxeles del corredor. No es una
imprecisión de pocos centímetros en el bordillo: es confusión entre calzada y superficie de tierra
clara, consistente con lo que la documentación de GeoDeep advierte ("works best on wide car roads")
y con haberse entrenado sobre Google Earth.

**Resolución de la máscara — decisión que el spec dejaba abierta, ahora medida.** El spec planteaba
decidir "si se corre a resolución nativa (más rápido, menos preciso en el borde) o se fuerza a la
resolución de la ortofoto". Medido: el recorte que se le entrega es de 1688×1919 px a **5 cm/px** y
la máscara que devuelve es de 422×479 px a **20 cm/px** — exactamente 1/4, la resolución nativa de
entrenamiento del modelo.

La implementación actual toma ese comportamiento por defecto, y eso **es la decisión de facto**: en
`geodeep/segmentation.py`, `scale_factor = int(model_res // input_res)` y la máscara se reserva como
`np.zeros((height // scale_factor, width // scale_factor))`. Con 5 cm de entrada y 20 cm de modelo,
`scale_factor = 4`.

Precisión terminológica: GeoDeep **no lo impone**. `segment()` acepta `resolution=` y sobrescribe
`config['resolution']`, así que forzar la resolución de la ortofoto es posible con un solo
parámetro. No se hace, y la razón es que el modelo se entrenó a 21 cm/px: alimentarlo a 5 cm/px le
presenta las formas a una escala cuatro veces mayor de la que aprendió, con degradación esperable de
la clasificación. Queda como una palanca disponible y sin medir, no como una limitación cerrada.

Consecuencia práctica mientras siga el valor por defecto: la precisión del borde en este modo está
acotada a ~20 cm, cuatro veces peor que el `sample_step` de 0,1 m que el panel permite configurar.
Bajar `sample_step` en modo `segmentation` no mejora el resultado; el panel no lo impide y esto
queda como límite documentado, no como validación.

La hipótesis concreta de D33 —"el modelo no reconoce calzada de forma útil"— resulta **parcialmente
equivocada**: sí reconoce calzada de forma consistente y sin fallar, pero mide algo más ancho que
"solo el asfalto delimitado por bordillo", que es lo que `surface` mide. El modo queda tan útil como
se diseñó para el caso que lo motiva —bordes sin relieve, donde `surface` no mide nada en
absoluto— pero su cifra de ancho, cuando ambos modos sí miden, no debe tomarse como intercambiable
con la de `surface`: son criterios que responden preguntas relacionadas pero no idénticas, igual
que ya ocurre entre `break` y `surface` en terreno rural (`006/D24`, resolución).

No se llegó a comparar contra el caso puro que motiva la feature —un tramo sin bordillo real donde
`surface` da `no_break`— porque en esta tarea concreta no hay, hoy, un tramo así con un eje ya
trazado; queda para cuando exista una tarea de referencia con ese caso.
