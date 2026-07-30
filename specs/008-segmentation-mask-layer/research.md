# Research — `008-segmentation-mask-layer`

Continúa la numeración de decisiones de `007-road-edge-segmentation` (que terminó en D33).

Todas las cifras de este documento se midieron sobre la instancia real antes de decidir, no se
estimaron. Los dos corredores de referencia son:

| Corredor | Tarea | Longitud | Semiancho | Ortofoto | Máscara |
|---|---|---|---|---|---|
| Corto | `Polideportivo María Puebla Vásquez` | 66 m | 20 m | 1688×1919 @ 5 cm/px | 422×479 @ 20 cm/px |
| Largo | `Noria - 3/17/2026` | 293 m | 25 m | 14145×29380 @ 2,2 cm/px | 1020×1123 @ 20 cm/px |

---

## D34 — Vectorizar la máscara ráster ya guardada, no pedirle el GeoJSON al modelo

**Decisión**: obtener los polígonos con `rasterio.features.shapes()` sobre el `mask.tif` que
`segmentation.run_segmentation` ya produce, y no llamando a `geodeep.segment(output_type='geojson')`.

**Por qué importa**: la spec asumía que se usaría la salida GeoJSON de la librería. Al leer el
código de `007` esa suposición resultó **inviable sin pagar el modelo dos veces**:
`compute._read_block` necesita la máscara **ráster** para muestrear los perfiles transversales
(abre el `mask.tif` con rasterio y lo muestrea en las mismas coordenadas que el DEM). Y
`geodeep.segment()` devuelve *o* la matriz *o* el GeoJSON, nunca ambos —
`geodeep/segmentation.py`: `if output_type in ('raw','default'): return mask; elif output_type ==
'geojson': return mask_to_geojson(...)`. Pedir el GeoJSON obligaría a una segunda inferencia
completa.

**Medido — las dos vías dan el mismo resultado**:

| Vía | Crudo | Simplificado 0,20 m | Vértices | Coste |
|---|---|---|---|---|
| `geodeep.segment(output_type='geojson')` | 115,0 KB | 19,5 KB | 464 | ~0,66 s (2.ª inferencia) |
| `rasterio.features.shapes()` sobre el ráster | 115,0 KB | 19,5 KB | 464 | **0,048 s** |

Idénticos byte a byte, y la vectorización es **catorce veces más barata** que volver a correr el
modelo. En el corredor largo la diferencia sería aún mayor: 0,036 s frente a 13,49 s.

**Alternativas descartadas**:
- *Segunda llamada a `geodeep.segment`*: duplica la inferencia (13,49 s extra en el corredor largo)
  para un resultado idéntico.
- *Usar `geodeep.segmentation.mask_to_geojson()` directamente sobre la matriz*: necesita `config` y
  `scale_factor`, que son internos de `segment()` y no se devuelven. Ataría el plugin a detalles
  privados de la librería.

`rasterio` ya es dependencia del plugin desde `005`. No hay dependencia nueva (Principio IV: no
aplica la escalera, no se toca `requirements.txt` ni el `Dockerfile`).

---

## D35 — Persistir junto a los tramos, con el mismo mecanismo del framework

**Decisión**: guardar la máscara en
`get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.mask.json`, al lado del
`<analysis_id>.json` de tramos que el plugin ya escribe.

**Rationale**: la constitución («Restricciones de infraestructura») exige que los datos persistentes
de plugins vayan por `get_persistent_path()` / `plugin_data_store` y **nunca** en rutas ad-hoc del
contenedor. `store.py` ya usa exactamente ese mecanismo (`segments_dir`), así que la máscara hereda
sin esfuerzo: misma ruta, mismo ciclo de vida, misma escritura atómica
(`tmp` + `os.replace`, ya justificada en `006` para que un worker cancelado no deje un JSON
truncado).

Hoy la máscara se escribe en un temporal de `MEDIA_TMP` que **nadie limpia y nadie sirve** — el
punto de partida de esta feature fue precisamente tener que rescatar uno a mano. Ese temporal sigue
siendo necesario durante el cálculo (el ráster que se muestrea), pero deja de ser el único sitio
donde vive el resultado.

**Alternativa descartada**: meter la máscara dentro del propio documento de tramos. Lo lee
`AnalysisDetail.get` y también `AnalysisExport`, así que cada exportación CSV cargaría en memoria
decenas de KB de polígonos que no usa. Separarlos mantiene barato lo que ya existe.

---

## D36 — Endpoint propio, cargado de forma perezosa

**Decisión**: `GET task/<pk>/analyses/<analysis_id>/mask`, que el frontend pide **solo cuando el
usuario enciende la capa**. La máscara no viaja en la respuesta de `AnalysisDetail`.

**Rationale**: FR-014 exige que la capa esté apagada por defecto. Si la máscara viajara embebida en
el detalle del análisis, cada apertura del panel arrastraría 19,5–76,9 KB que la mayoría de las
veces no se van a dibujar. Con un endpoint aparte, quien no enciende la capa no paga nada.

Encaja además con el patrón de rutas de `007`: literales específicas antes del patrón genérico de
`<analysis_id>`, y todas ancladas con `$` (el comentario de `plugin.py` advierte que un
`MountPoint` sin `$` resuelve por prefijo y se tragaría rutas hermanas).

---

## D37 — Un indicador en el índice para saber si hay máscara sin leerla

**Decisión**: el registro del análisis en el índice gana un campo booleano que dice si tiene máscara
guardada. Lo escribe el worker al terminar, junto al resto del resumen.

**Rationale**: FR-015 dice que el control solo se ofrece cuando hay máscara, y FR-017 exige
distinguir tres estados. El panel necesita saberlo **antes** de decidir si pinta el control, y sin
pagar la lectura del fichero de máscara. Un booleano en el índice —que ya se envía en
`AnalysisList.get` y `AnalysisDetail.get`— resuelve las dos cosas.

Los tres estados de FR-017 quedan así:

| Estado | Indicador en el índice | Respuesta del endpoint | Qué ve el usuario |
|---|---|---|---|
| Máscara con calzada | verdadero | `200` + polígonos | Control disponible; capa dibuja |
| Máscara vacía (el modelo no vio calzada) | verdadero | `200` + colección vacía | Control disponible; aviso de que no se detectó calzada |
| Sin máscara (análisis anterior a `008`) | ausente/falso | `404` con código propio | Sin control; explicación y sugerencia de recalcular |

El tercer caso **no puede confundirse con el segundo**: «el modelo no encontró calzada» es un
resultado con valor informativo (explica por qué los tramos salieron sin borde), mientras que «no se
guardó máscara» no es un resultado en absoluto. Confundirlos sería mentirle al usuario.

Los análisis viejos no necesitan migración: la ausencia del campo se interpreta como «no hay
máscara», igual que `_upgrade_segments` interpreta en memoria los documentos de `005` sin tocar el
disco (`006`/FR-024).

---

## D38 — Simplificación: tolerancia atada a la resolución de la propia máscara

**Decisión**: simplificar con `GEOSGeometry.simplify(tolerance, preserve_topology=True)` a **0,20 m**
y descartar los polígonos por debajo de un área mínima.

**Rationale**: 0,20 m no es un número de compromiso — es exactamente la resolución a la que el
modelo devuelve la máscara. Por debajo de ella no hay información que perder: los vértices más finos
son artefactos del contorno de píxeles, no forma medida. Simplificar hasta ahí es gratis en
información y muy caro de evitar en bytes.

**Medido**:

| Corredor | Crudo | 0,20 m | 0,40 m | 0,60 m |
|---|---|---|---|---|
| 66 m | 115,0 KB (2790 v.) | **19,5 KB** (464 v.) | 7,0 KB (158 v.) | 4,0 KB (85 v.) |
| 293 m | 309,5 KB | **76,9 KB** (1836 v.) | 34,2 KB (797 v.) | 26,2 KB (601 v.) |

`preserve_topology=True` para no generar autointersecciones, que Leaflet dibuja mal.

**Hallazgo honesto sobre el filtro de área**: la spec (FR-008) lo planteaba en parte como palanca de
tamaño. **No lo es** en estos corredores: con umbrales de 1 m² y 4 m² no se descarta ni un polígono,
porque `geodeep.segment()` ya aplica internamente su propio `filter_small_segments` antes de
devolver la matriz. El filtro se mantiene como red de seguridad para escenas más ruidosas, pero no
debe venderse como lo que controla el tamaño — lo que lo controla es la simplificación.

**Limitación conocida (anisotropía)**: la tolerancia se aplica en grados sobre geometría EPSG:4326,
con el factor de la latitud (1 grado ≈ 111 320 m). Un grado de longitud es más corto que uno de
latitud fuera del ecuador, así que a la latitud de las pruebas (−33,4°) la tolerancia efectiva en
longitud es ~0,167 m en vez de 0,20 m. El sesgo va hacia **conservar más detalle**, nunca menos, y
las cifras medidas arriba ya lo incluyen. Simplificar en el CRS proyectado de la ortofoto sería más
exacto, pero añade dos reproyecciones por una diferencia que no cambia ninguna decisión.

---

## D39 — Dibujo: capa propia, no interactiva, fuera de la paleta del semáforo

**Decisión**: una capa Leaflet independiente del `L.FeatureGroup` del análisis, con
`interactive: false`, relleno translúcido en un tono **azul**, dibujada por debajo del eje y de las
reglas.

**Rationale**, punto por punto:

- *Capa aparte, no dentro del grupo del análisis*: `roadBridge.publishAnalysis` registra el grupo en
  `PluginsAPI.Map.addAnnotation`, de modo que el análisis aparece como una anotación del core.
  Meter la máscara ahí la haría aparecer y desaparecer con el análisis entero, y encender/apagar la
  capa tocaría una estructura que el core también gestiona. Separarlas mantiene ortogonales las dos
  cosas.
- *`interactive: false`* (**no negociable**): `roadBridge` tiene un manejo cuidadoso de clic y hover
  —una polilínea `hit` invisible de `weight: 20` por tramo, halos, `pinnedLayer`— y un polígono
  encima capturando eventos lo rompería. La máscara es para mirarla, no para pincharla.
- *Fuera de la paleta*: `segmentStyle.colors()` usa `#2e9e4f` verde, `#e8b900` amarillo, `#d9422b`
  rojo y `#8a8a8a` gris, y esa escala significa pendiente (y, en las reglas, ancho). Un relleno en
  cualquiera de esos tonos se leería como una tercera métrica que no existe. El azul está libre
  (FR-012).
- *Por debajo*: las reglas de ancho ya se dibujan deliberadamente bajo el eje
  (`segmentStyle.js`: «Se dibuja por DEBAJO del tramo, así el eje coloreado la cruza por encima»).
  La máscara, siendo un relleno de superficie, va todavía más abajo (FR-013).

---

## D40 — Corredores largos: medido, y con consecuencia sobre la spec

**Decisión**: aceptar que la máscara crece con la longitud del corredor, con la tolerancia fija de
D38, sin mecanismo adaptativo.

Este era el riesgo que la checklist de la spec dejó explícitamente abierto («solo se ha medido un
corredor de 66 m»). **Medido sobre el corredor de 293 m**: 76,9 KB, casi el doble del techo de
8,7–42 KB que FR-009 fijaba antes de tener datos. **La spec se corrigió** (FR-009 y SC-003) en vez
de ajustar la tolerancia para hacer cuadrar un número inventado.

Dos invariantes útiles quedan comprobados:

- **El tamaño escala con la longitud del corredor, no con el GSD de la ortofoto.** La ortofoto larga
  es de 2,2 cm/px y la corta de 5 cm/px, y ambas producen máscara a 20 cm/px. Los vértices van de
  464 a 1836 (×3,96) para una longitud de 66 a 293 m (×4,44): crecimiento aproximadamente lineal.
- **El tamaño no se dispara de orden.** 76,9 KB frente a los 42 KB del documento de tramos del mismo
  análisis: 1,8×, no 10×.

**Alternativa descartada**: tolerancia adaptativa (subirla hasta encajar en un presupuesto). Añade
una rama de comportamiento y hace que dos análisis del mismo modo tengan precisiones distintas sin
que el usuario lo sepa, para resolver un problema que la medición dice que no existe. Complejidad
especulativa.

**Hallazgo colateral relevante para el progreso**: la segmentación del corredor largo tardó
**13,49 s** frente a 0,66 s en el corto — veinte veces más. Refuerza el reparto de progreso que
`007`/D27 ya introdujo, y da por fin un caso donde la fase de segmentación es observable (el
Escenario 4 que quedó pendiente en la validación de `007` por ser todo demasiado rápido).

---

## D41 — Disciplina de imports para el worker

**Decisión**: la vectorización y la simplificación viven en `segmentation.py`, al que `compute.py`
ya importa a nivel de módulo. `run_analysis` no gana ningún import nuevo.

**Rationale**: `run_analysis` es **self-contained** — `run_function_async` la recompila desde su
código fuente en un espacio de nombres vacío, así que solo existe lo que ella importa dentro de su
cuerpo. Alcanza `segmentation` a través de `compute`, exactamente el mismo patrón ya establecido
para `coherence` en `006`/D23 y para `segmentation` en `007`/D31. Repetirlo aquí es lo que evita
el `NameError` en el worker que ese patrón existe para prevenir.

`django.contrib.gis.geos` (para `simplify`) y `rasterio.features` se importan en `segmentation.py`,
no en `run_analysis`.
