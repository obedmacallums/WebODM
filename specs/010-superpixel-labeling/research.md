# Fase 0 — Investigación

Todas las cifras de este documento se midieron el 2026-07-31 dentro del contenedor `webapp`
(aarch64, Python 3.9, numpy 1.26.2, scipy 1.11.3, rasterio 1.3.10) sobre la ortofoto y el DTM reales
de la tarea `6e965174-0bf8-43e0-87e7-c1c88306ac76` (14145×29380 px a 2,22 cm/px). Los scripts están
transcritos aquí lo bastante como para poder rehacerlos.

---

## D1 — La partición se hace con `scikit-image`, con numpy y scipy pineados

**Decisión**: añadir `coreplugins/training/requirements.txt` con

```
scikit-image==0.24.0
numpy==1.26.2
scipy==1.11.3
```

**Razón**. `scikit-image` es Python puro instalable con pip, así que le toca el paso 1 de la escalera
del Principio IV. Pero el instalador del framework tiene un fallo que había que caracterizar antes de
adoptarlo. `PluginBase.check_requirements()` (`app/plugins/plugin_base.py:44`) corre

```
pip install -U -r requirements.txt --target <site-packages>
```

**sin `--no-deps`**, y `python_imports()` hace `sys.path.insert(0, ...)`: el directorio del plugin
queda **delante** del entorno de la imagen. Instalando `scikit-image` a secas:

```
$ pip install --target /tmp/skresearch scikit-image==0.24.0
$ PYTHONPATH=/tmp/skresearch python -c "import numpy, rasterio"
numpy visto por el plugin: 2.0.2 /tmp/skresearch/numpy/__init__.py
rasterio ROTO: ValueError numpy.dtype size changed, may indicate binary incompatibility.
               Expected 96 from C header, got 88 from PyObject
```

Rotura dura de `rasterio`, que es la mitad del plugin. Se probaron las dos salidas:

| Vía | Resultado | Alcanzable desde `requirements.txt` |
|---|---|---|
| `pip install --no-deps skimage lazy_loader imageio tifffile networkx` | numpy 1.26.2, scipy 1.11.3, rasterio OK, `slic` OK | ❌ el instalador no pasa `--no-deps` |
| Pinear `numpy==1.26.2` y `scipy==1.11.3` junto a `scikit-image` | numpy 1.26.2, scipy 1.11.3, rasterio OK, `slic` OK | ✅ |

El pineo es la única de las dos que cabe en el mecanismo sin tocar el core. Cuesta **246 MB** en
`MEDIA_ROOT/plugins/training/site-packages`, que es el precio de no modificar
`app/plugins/plugin_base.py` (Principio I).

**Riesgo que queda vivo y cómo se cubre**: los pines acoplan el plugin a las versiones de la imagen.
Si un merge de upstream sube numpy, el plugin seguirá instalando 1.26.2 y volverá la incompatibilidad
de ABI, esta vez al revés. Por eso el plan exige un test de regresión que compare la versión de numpy
y scipy del directorio del plugin con la del sistema y afirme que `rasterio` importa bajo
`python_imports()`. Convierte una rotura silenciosa en un fallo ruidoso.

**Alternativa considerada y descartada: implementar SLIC en numpy dentro del plugin.** Es atractiva
—cero dependencias, control total de las semillas— y la spec la dejaba abierta para evaluarla tras el
prototipo. Se prototipó (~90 líneas, k-means en 5D con radio de búsqueda `2S`) y se descartó por
coste: la versión en numpy puro tarda **decenas de segundos por celda** frente a los **0,36 s** de la
implementación en Cython de `scikit-image` sobre la misma ventana, y el motivo original para
escribirla —poder anclar las semillas a una rejilla global— resultó **innecesario** una vez medido
D2. Se deja registrada porque sigue siendo la salida si el pineo de numpy se vuelve insostenible.

---

## D2 — Las ventanas se alinean a la rejilla de semillas y se calculan con halo `8S`

**Decisión**: la partición se calcula por celdas cuadradas de `CELL` px ancladas al origen de la
ortofoto, con `CELL` múltiplo de `S`, sobre una ventana de `CELL + 2·8S` px, y se conserva solo el
núcleo. `n_segments` se fija a `(W/S)·(H/S)` para que el paso efectivo sea exactamente `S`.

**Razón**. Es la resolución del conflicto entre FR-009 (sin bordes rectos artificiales) y FR-015 (por
porciones acotadas). La primera hipótesis —«SLIC es local, un halo basta»— se midió y **es falsa**:

```
halo    halo/S   desacuerdo global   desacuerdo en la junta   t/celda
   0     0.0              9.760 %               10.970 %     0.16 s
  20     1.0             10.303 %               12.089 %     0.18 s
  40     2.0             10.247 %               11.457 %     0.19 s
  60     3.0             10.265 %               11.603 %     0.21 s
```

El halo no mejora nada y el desacuerdo no está concentrado en la junta: es global, ~10 % en toda la
celda. La causa no es el alcance espacial del operador sino que `slic` deriva el paso de la rejilla
de semillas de `sqrt(N_px / n_segments)` y siembra desde `paso/2` **relativo a la ventana**. Ventanas
de distinto tamaño u origen siembran en posiciones globales distintas y producen particiones
distintas pero igualmente válidas.

Eso convierte el problema en uno de **anclaje de semillas**, y da la solución: si la ventana empieza
en un múltiplo global de `S` y mide un múltiplo de `S`, las semillas caen en las mismas posiciones
globales se calcule desde donde se calcule. Medido:

```
desplazamiento de ventana alineado a S:
  desacuerdo en el solape (512x1024 px): 1.512 %

control, origen en 505 px (no múltiplo de S=16):
  desacuerdo en el solape: 12.506 %
```

Ocho veces mejor solo por alinear. El 1,5 % restante lo aporta la propagación de los centros entre
iteraciones, y ese sí lo cierra el halo:

```
celda central [512,1024) calculada con distintos halos, comparada con el halo mayor:
  halo 256 px (16.0 S): referencia
  halo 192 px (12.0 S): 0.000 %
  halo 128 px ( 8.0 S): 0.000 %
  halo  64 px ( 4.0 S): 0.176 %
  halo  32 px ( 2.0 S): 1.017 %
  halo  16 px ( 1.0 S): 2.218 %
  halo   0 px ( 0.0 S): 3.221 %
```

**`8S` es el primer halo que da coincidencia exacta**, y se adopta ese. Con `S = 16` px son 128 px de
margen.

Consecuencia para FR-009: un superpíxel que cruza el borde de una celda sale **igual** desde las dos
celdas, así que no hay junta que ver. Y consecuencia para FR-007/FR-008: como la rejilla se ancla al
origen de la ortofoto —el mismo criterio con el que `tiling.py` ancla las teselas de exportación—, la
celda que le toca a un punto del terreno no depende del encuadre ni del zoom.

### Corrección durante la implementación (2026-08-02)

**La coincidencia exacta de la tabla de arriba era un artefacto de la `compactness` por defecto de
skimage (10)**, que es la que se usó al medir. A estas escalas, con las bandas en `[0, 1]`, una
`compactness` de 10 hace que la distancia de color no pese nada y SLIC degenera en una rejilla de
cuadrados perfectos: convergen exactamente **porque no siguen ningún borde**. Medido sobre la
ortofoto real, la región mayor del núcleo con `compactness=10` mide 256 px, exactamente el tamaño
nominal — ninguna se ha deformado para seguir nada. Eso vacía la feature de contenido.

Calibrando `compactness` por adherencia a bordes —desviación típica **dentro** de cada región, que
es lo que mide si las regiones respetan los bordes o los atraviesan— el mínimo está en 0,5:

```
compactness   regiones   mediana   mayor región   desv. típica intra-región
   0,1           733       298 px     3524 px            0,0790
   0,3          1035       261 px     1097 px            0,0641
   0,5          1095       256 px      488 px            0,0620   <- mínimo
   0,8          1098       256 px      339 px            0,0652
  10,0          1089       256 px      256 px            0,0776   <- rejilla perfecta
```

Con `compactness = 0,5` el desacuerdo baja monótonamente con el halo pero **no llega a cero**:
2,344 % con halo 0, 0,960 % con `8S`, 0,678 % con `16S`. El anclaje sigue siendo lo que más pesa
(11,343 % con la ventana desalineada 7 px frente a 0,960 % alineada), así que las invariantes de
`WorkGrid` se mantienen.

**FR-009 se cumple, pero por costura y no por coincidencia exacta.** Cuando una región toca el borde
del núcleo y su vecino de fuera pertenece a la misma región de la ventana, se le añade entera la
región de la celda contigua que ocupa el píxel de enfrente. Medido sobre las 33 regiones que cruzan
una junta real, contra la partición de referencia de una ventana que abarca las dos celdas:

```
halo:                        0S     1S     2S     4S     8S    16S
IoU de la unión cosida     0,735  0,811  0,858  0,953  0,981  0,976
IoU sin coser (solo A)     0,735  0,777  0,785  0,786  0,795  0,801
```

Sin coser, la región se queda en 0,79 haga lo que haga el halo: le falta el trozo del otro lado, que
es el corte recto que FR-009 prohíbe. Cosiendo sube a 0,981 y se estanca — `16S` no mejora a `8S`.
**Ese estancamiento es lo que sigue fijando el halo en `8S`**, ahora por una razón medida distinta
de la original: por debajo la partición del borde está deformada por no ver el terreno de fuera.

Lo verifica `tests/test_superpixels.py::SeamTest`, que afirma la propiedad que el usuario percibe
—la región cruza la junta y no termina en línea recta— en vez de la igualdad exacta, que era falsa.

**Alternativa descartada**: reutilizar la rejilla de teselas de exportación de `009`. Se solapan por
diseño (D20 de `009`), así que un píxel cae en varias teselas y no habría una respuesta única para un
clic. La rejilla de esta feature es propia y sin solape.

**Métrica usada**: fracción de pares de píxeles vecinos en los que las dos particiones discrepan
sobre si pertenecen o no al mismo segmento. Compara particiones sin depender de los IDs, que son
arbitrarios.

---

## D3 — Celda de 512 px, paso `S` de 16 px, granularidad en tres pasos

**Decisión**: `CELL = 512` px a la resolución de trabajo del dataset. `S` por defecto 16 px, ajustable
por el usuario a 8 / 16 / 32 px. Invariantes que la implementación debe imponer: `S` divide a `CELL`,
y el halo es siempre `8·S`.

**Razón**. A los 10 cm/px por defecto, una celda cubre **51×51 m** de terreno y un superpíxel medio
mide **1,6 m** — la escala correcta para una pista minera de 4–8 m de ancho, que queda descrita por
unas pocas regiones a lo ancho. Medido: 1089 regiones en el núcleo de una celda.

El coste crece con `S` porque el halo es proporcional: con `S = 32` la ventana pasa de 768 a 1024 px,
2,25× más área. Es el techo aceptable y por eso la granularidad se ofrece en tres pasos y no como un
número libre.

---

## D4 — Coste y memoria: síncrono, sin Celery

**Decisión**: la preparación de una celda ocurre **dentro de la petición HTTP**, no en el worker.

**Razón**. Medido en la configuración de producción exacta (celda 512, halo 128, 5 bandas, ortofoto y
DTM reales):

```
ventana 768x768 px  (núcleo 512, halo 128 = 8S)
  lectura ortofoto : 0.023 s
  canales de DEM   : 0.568 s
  SLIC (5 bandas)  : 0.360 s
  TOTAL por celda  : 0.951 s
  superpíxeles en el núcleo: 1089
  mapa del núcleo int32    : 1.05 MB
  pico de memoria (numpy)  : 71.0 MB

celda = 51 x 51 m de terreno; superpíxel medio = 1.6 m
```

0,951 s es **cinco veces menos** que el techo de SC-004 y no justifica la maquinaria asíncrona:
Celery en este plugin existe para las exportaciones, que duran minutos. El pico de 71 MB deja SC-007
holgado frente al ~1 GB disponible.

Dato secundario que orienta la caché: **los canales de DEM cuestan más que la partición** (0,568 s
contra 0,360 s). Si hiciera falta afinar, el primer sitio donde mirar es cachearlos aparte de la
partición, porque sobreviven a un cambio de granularidad.

**Alternativa descartada**: precalcular la ortofoto entera al abrir el dataset. Sobre la ortofoto
medida (14145×29380 px a 2,22 cm/px ≈ 3132×6507 celdas de trabajo) serían horas y gigabytes, para un
usuario que rara vez etiqueta más que unos corredores.

---

## D5 — Caché de mapas de regiones en disco, con clave por ajustes

**Decisión**: cada núcleo de celda se guarda comprimido bajo `get_persistent_path()`, con la clave
`(task_id, resolución, S, pesos de canal, versión del algoritmo)`. Presupuesto acotado por dataset y
expulsión por antigüedad de acceso.

**Razón**. El mapa del núcleo son 1,05 MB en `int32`; comprimido baja mucho porque son ~1089 valores
distintos en 262144 píxeles. Recalcular en cada clic (0,951 s) haría inviable el arrastre de US2, así
que hay caché; y meter los ajustes en la clave hace que cambiar la granularidad **invalide sola** la
caché sin código de invalidación explícito, que es donde suelen vivir los fallos.

Incluir la versión del algoritmo en la clave evita el peor fallo posible de esta feature: que un
cambio futuro en la partición conviva con mapas viejos y rompa el determinismo de FR-007 sin que
nadie se entere.

`get_persistent_path()` es además lo que exige la constitución para datos persistentes de plugin.

---

## D6 — De región a etiqueta: polígono en 4326, `source` nuevo, `kind` existente

**Decisión**: la unión de regiones seleccionadas se vectoriza con `rasterio.features.shapes` sobre la
máscara booleana, se reproyecta a EPSG:4326 y se guarda como una etiqueta `KIND_POLYGON` con
`source = SOURCE_ASSISTED` (constante nueva en `models.py`).

**Razón**. `models.py:348` ya acepta un `source` (`manual`, `import`, `model`), así que la
procedencia cabe sin tocar el modelo. Y usar el `kind` que ya existe es lo que hace que **FR-020 se
cumpla solo**: `rasterize.py` y `export.py` no se enteran de esta feature, y el contrato del paquete
exportado no cambia ni una línea.

`SOURCE_MODEL` queda libre, como estaba reservado para la fase 3 de `009`. Que una etiqueta asistida
sea distinguible de una manual importa para el futuro: permitirá medir la calidad de la asistencia
sin volver a etiquetar.

**Nota de reutilización**: `coreplugins/road/segmentation.py:176` (`vectorize_mask`) hace exactamente
esta conversión y está medido en 0,036 s. **No se importa**: los plugins son independientes por el
Principio III y un import cruzado ataría `training` al ciclo de vida de `road`. Se replica el patrón,
no el código.

**Reproyección**: con `rasterio.warp.transform`, nunca con `GEOSGeometry.transform`, que invierte el
orden de ejes al reproyectar a 4326 y produce geometrías silenciosamente corruptas.

---

## D7 — Crecimiento por tolerancia sobre el grafo de adyacencia

**Decisión**: el grafo se deriva del mapa de etiquetas comparando cada píxel con su vecino a derecha
y abajo. Cada región lleva su vector medio de las bandas normalizadas. Desde la región pinchada se
hace un recorrido en anchura que admite una vecina si la distancia entre sus vectores medios está por
debajo de la tolerancia.

**Razón**. Construir el grafo así es un par de operaciones vectorizadas sobre el mapa que ya está en
caché, sin librería de grafos. La monotonía que pide FR-017 sale del propio recorrido: subir la
tolerancia solo puede admitir más vecinas, nunca menos, así que la selección con tolerancia menor
está contenida en la mayor.

FR-018 (tope conocido) se implementa como un límite en número de regiones, evaluado **antes** de
expandir. El aviso al usuario es parte de la respuesta, no un efecto colateral silencioso.

El crecimiento puede salirse de la celda del clic. Cuando lo hace se prepara la celda vecina y se
sigue; como D2 garantiza que las particiones coinciden en el solape, la región resultante no tiene
junta.

---

## D8 — Sin modelo de terreno, tres bandas

**Decisión**: `elevation.resolve_source()` ya distingue DTM, DSM y ninguno, y lanza
`ElevationUnavailable` cuando no hay ráster. Se captura, se cae a las tres bandas de color y la
respuesta lo declara para que la interfaz pueda decirlo (FR-011, SC-006).

**Razón**. Es la garantía de que la feature no depende de que el terreno coopere. El peso de los
canales de elevación es además ajustable hasta cero (FR-012), lo que hace que el caso «hay DTM pero
no aporta» y el caso «no hay DTM» recorran el mismo camino de código.

Medido: con 3 bandas la partición tarda 0,411 s y con 5 bandas 0,360 s sobre la misma ventana. La
diferencia está en el ruido de medición; **las bandas extra no cuestan tiempo de partición**. Lo que
cuesta es producirlas (0,568 s), y ese coste solo se paga si el peso no es cero.

---

## D9 — Modo propio en la barra, sin `Shift`

**Decisión**: `MODE_ASSIST` nuevo en `LabelEditor.js`, junto a `MODE_POLYGON`, `MODE_BRUSH`,
`MODE_ERASER`, `MODE_REVIEW` y `MODE_SELECT`, con su botón en la barra de herramientas.

**Razón**. `Shift` ya está tomado en el plugin para la selección múltiple de etiquetas y el marcado de
vértices; reutilizarlo como modificador crearía una colisión de significado en el mismo lienzo
(FR-002). El editor ya está construido alrededor de un `setMode()` con seis modos, así que añadir el
séptimo es la vía barata y la que no sorprende a quien ya conoce la interfaz.

Los ajustes (granularidad, tolerancia, peso de elevación) viven en el documento del dataset vía
`store.update_dataset`, que es lo que da FR-022 sin código de persistencia nuevo.

---

## Mediciones de la implementación (2026-08-02)

Sobre el stack en Docker y la ortofoto real del usuario (14145×29380 px, 2,22 cm/px nativos), a
través de la ruta HTTP completa y con un dataset de prueba propio que se borra al terminar.

### Coste por petición

| Caso | Medido | Criterio |
|---|---|---|
| Preparar una celda nueva (5 medidas con caché vaciada entre ellas) | mediana **0,682 s**, máximo 0,730 s | SC-004: < 5 s ✅ |
| Clic sobre celda ya preparada (5 medidas) | mediana **0,012 s** | SC-003: sin espera perceptible ✅ |
| RSS pico del proceso durante la sesión | **274 MB** (154 MB antes de la primera partición) | SC-007 ✅ |
| Partición de una celda en el **worker**, 5 bandas | **1,028 s**, 1089 regiones | — |

La cifra de 1089 regiones por celda coincide exactamente con la de D4, medida antes de escribir
nada: la implementación reproduce la partición sobre la que se planificó.

**Aviso sobre la primera petición tras un arranque limpio**: la primera midió 8,856 s porque incluía
la instalación de `requirements.txt` por parte del framework (246 MB). Solo ocurre una vez —después
existe el `install_md5`— pero conviene no confundirla con el coste de la partición.

### Coste del crecimiento por tolerancia

| Tolerancia | Regiones | `truncated` | Tiempo |
|---|---|---|---|
| 0,00 | 1 | no | 0,022 s |
| 0,05 | 9 | no | 0,754 s |
| 0,10 | 92 | no | 0,115 s |
| 0,30 | 2000 | **sí** | 6,055 s |

El tope de `MAX_GROWTH_REGIONS = 2000` funciona y se declara. **Los 6 s del último caso son reales
y no son coste de cálculo de regiones sino de preparar las celdas que el crecimiento alcanza**: unas
2000 regiones son del orden de dos celdas nuevas por cada una ya preparada. Es un gesto deliberado
—subir el deslizador al 30 % sobre terreno uniforme— y la interfaz lo anuncia mientras ocurre
(FR-024), pero es el peor caso conocido de la feature y conviene tenerlo escrito antes de que
alguien lo descubra por sorpresa.

### El aviso que faltaba: `requirements.txt` no admite comentarios

`app/plugins/pyutils.py:parse_requirements` no filtra las líneas que empiezan por `#`: toma toda
línea no vacía como nombre de paquete. Con la cabecera explicativa que llevaba el fichero,
`requirements_installed()` devolvía `False` siempre, y eso producía dos efectos que no se parecen a
un error:

1. `WARNING Failed to install requirements.txt` **con pip terminando en verde**, con lo que el aviso
   dejaba de significar nada.
2. Nunca se escribía el `install_md5`, así que el plugin reinstalaba 246 MB en **cada arranque**
   (~8 s medidos).

La explicación vive ahora en el README del plugin y hay un test que impide que vuelvan los
comentarios (`tests/test_requirements.py::test_the_file_has_no_comments`).
