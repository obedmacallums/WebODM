# Research: características geométricas de caminos (`road`)

**Feature**: 005-road-metrics | **Fecha**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

Todas las incógnitas del Technical Context quedan resueltas aquí. Cada decisión indica qué se
eligió, por qué, y qué alternativas se descartaron.

---

## D1 — Cómo obtiene `road` el DEM, original o realineado

**Decisión**: los originales se resuelven como ya hace `annotations`
(`task.get_asset_download_path('dsm.tif' | 'dtm.tif')`, disponibilidad por `task.dsm_extent` /
`task.dtm_extent`, sin tocar disco). Para los realineados se **añade a `realign` un contrato Python
mínimo**, análogo al que ya expone `annotations`:

```python
class Plugin(PluginBase):
    def contract_version(self): ...          # 1
    def corrected_rasters(self, task_id): ...  # {'dsm': '/ruta/dsm.tif', ...} solo los existentes
```

`road` lo consume con `get_plugin_by_name('realign')` y degrada a los originales si devuelve `None`
o si el contrato es de una versión mayor que la que sabe interpretar.

**Justificación**: la constitución exige que los plugins se integren por los puntos de extensión del
framework, y el precedente de `annotations` (v2, `contracts/plugin-contract.md`) ya fijó la forma de
hacerlo dentro de este fork. `realign` es código propio del fork, no del core upstream, así que
ampliarlo no toca el Principio I.

**Alternativas descartadas**:

- *Reconstruir la ruta con `get_plugins_persistent_path('realign', 'task_<pk>')/<tipo>.tif`*:
  acopla `road` al layout interno de otro plugin; cualquier cambio allí lo rompe en silencio.
- *Llamar al REST de `realign` desde el worker*: petición HTTP a sí mismo, con autenticación y
  latencia, para leer una ruta de disco.

---

## D2 — Muestreo del DEM: por bloques y vectorizado

**Decisión**: el eje se procesa en **bloques de tramos consecutivos**. Para cada bloque se calcula
la ventana de ráster que cubre sus transversales (bbox del bloque expandido por el semiancho de
búsqueda más un margen de un píxel), se lee esa ventana completa a un array `numpy` con
`rasterio.windowed_read` (`ds.read(1, window=...)`), y todas las muestras del bloque se resuelven
por indexación vectorizada sobre ese array (vecino más próximo, coherente con el remuestreo `near`
que `realign` aplica a los DEM). El tamaño de bloque se elige para que la ventana no supere un techo
de memoria configurable interno.

**Justificación**: `ds.sample()` —lo que usa `annotations`— hace una lectura por punto. Con un
camino de 1 km y los parámetros por defecto se pasa de ~2.000 muestras (`annotations`, eje solo) a
~40.000 (200 transversales × 200 muestras), y de ahí escala con la longitud. Leer por ventanas y
resolver con numpy convierte cientos de miles de lecturas en unas pocas decenas, y da el punto
natural de reporte de progreso y de comprobación de cancelación (una vez por bloque).

**Alternativas descartadas**:

- *`ds.sample()` punto a punto*: simple y ya probado en el fork, pero es el cuello de botella
  directo de SC-002 (1 km en menos de 2 minutos).
- *Leer el DEM entero de una vez*: un DEM de un vuelo grande no cabe cómodamente en memoria del
  worker, y el eje solo cubre una franja estrecha de él.

---

## D3 — Detección del borde por quiebre de pendiente

**Decisión**: sobre el perfil transversal `z(d)`, con `d` la distancia con signo al eje muestreada
cada `paso` hasta `±semiancho`, se recorre cada lado **desde el eje hacia afuera** calculando la
pendiente local por diferencias entre muestras vecinas. El borde es la posición de la **primera
muestra de la primera racha** de al menos `min_muestras` posiciones consecutivas cuya pendiente
local supera, en valor absoluto, el `umbral_quiebre`. Si el lado se queda sin muestras válidas antes
de encontrar la racha, ese lado se reporta sin borde con el motivo correspondiente (D3b).

**Justificación**: es la formulación más directa de "el camino termina donde el terreno se rompe"
(talud, berma, cuneta), no necesita más que el DEM, y el requisito de racha mínima es lo que separa
un quiebre real del ruido de un DEM fotogramétrico. Tomar la primera muestra de la racha —y no la
del máximo de pendiente— sitúa el borde en el arranque del quiebre, que es el borde de calzada.

**D3b — Motivos de "sin borde"**: cada lado registra `no_break` (se recorrió todo el semiancho sin
racha), `no_data` (el DEM dejó de tener dato antes de completar el recorrido: `nodata`, `NaN`, o
fuera del ráster) o `break_at_axis` (la racha arranca sobre el propio eje, así que no hay calzada
que medir: el trazado no pasa por el camino en ese tramo). La distinción es requisito (FR-021) y
sale casi gratis del propio recorrido.

`break_at_axis` se añadió durante la implementación, tras verlo en la verificación en worker sobre
un DSM real: sin él ese caso producía `width: 0.0` marcado como `measured` con la pendiente
transversal vacía, rompiendo el primer invariante de `data-model.md` §6.

**D3c — No se rellenan huecos del DEM, y no hace falta.** El recorrido transversal se detiene en la
primera muestra sin dato, sin tolerancia ni interpolación. Se consideró añadir un `max_gap_samples`
que saltara huecos cortos, pensando en los vacíos típicos de un DEM fotogramétrico. **Medición
sobre los seis DEM de la instancia de desarrollo (3 tareas × DSM/DTM, hasta 14145×29379 px): cero
huecos interiores en todos ellos.** El 17–37 % de `nodata` que tienen es íntegramente perímetro
exterior, fuera de la huella del vuelo. La causa es que ODM ejecuta relleno de huecos al generar el
DEM (`--dem-gapfill-steps`, 3 por defecto), así que lo que llega a WebODM ya viene cerrado por
dentro.

Consecuencia: un `no_data` en una transversal no significa "se topó con un píxel malo" sino "el
recorrido llegó al borde del vuelo", que es justo lo que el motivo comunica. Un parámetro de
tolerancia sería un mando que nunca se dispara sobre datos reales. Descartado también
`rasterio.fill.fillnodata` sobre el ráster de entrada: inventaría cotas que entrarían en el ancho y
en las pendientes sin nada que las distinga de las medidas, en contra de FR-022.

**Alternativas descartadas**:

- *Máximo de la derivada segunda (curvatura)*: más sensible al ruido y con peor comportamiento en
  taludes suaves de caminos de tierra.
- *Umbral sobre la diferencia de cota respecto del eje*: falla en caminos con peralte marcado, donde
  la calzada ya acumula desnivel antes del borde.

---

## D4 — Pendiente longitudinal por mínimos cuadrados

**Decisión**: por tramo se ajusta una recta `z = a·s + b` (mínimos cuadrados, `numpy.polyfit` de
grado 1) sobre **todas** las muestras del eje contenidas en el tramo, con `s` la progresiva en
planta. La pendiente reportada es `a` (en % y en grados, `atan`), y la cota del tramo es el valor
del ajuste en el punto medio. Con menos de tres muestras el ajuste degenera de forma natural a la
recta que une los extremos.

**Justificación**: decisión tomada en la clarificación del 2026-07-27. Con tramos de 5 m sobre un
DEM de 5 cm hay ~100 muestras por tramo; usar solo los extremos entrega la pendiente al ruido de dos
píxeles, y el semáforo pasaría de verde a rojo entre tramos vecinos sin que el terreno cambie.

**Alternativas descartadas**: diferencia de extremos (ruidosa), mediana de pendientes consecutivas
(subestima los quiebres reales de rasante), suavizado previo del perfil (parámetro extra y desplaza
los quiebres).

---

## D5 — Pendiente transversal (bombeo/peralte)

**Decisión**: mismo método que D4 aplicado al perfil transversal, restringido a las muestras
**entre el borde izquierdo y el derecho**: ajuste lineal de `z` contra `d`, pendiente en %. Sin
ambos bordes no hay calzada delimitada y la pendiente transversal se reporta vacía.

**Justificación**: coherencia con D4 —la misma clase de estimador para la misma clase de magnitud— y
robustez frente al ruido. Restringirla a la calzada es lo que la hace significar bombeo o peralte y
no "la inclinación del terreno alrededor".

**Alternativa descartada**: `(z_derecho − z_izquierdo) / ancho`, que depende de dos muestras
concretas —justo las que caen en el arranque del quiebre, las más ruidosas del perfil.

---

## D6 — Geometría de la transversal

**Decisión**: una transversal por tramo, en su **punto medio por progresiva**, perpendicular a la
**cuerda del tramo** (vector entre sus extremos), calculada en el CRS proyectado del DEM. El lado
izquierdo es el que queda a la izquierda del sentido de avance del eje.

**Justificación**: es la interpretación más simple y predecible de "perpendicular al eje", y con
tramos cortos la cuerda y la tangente son indistinguibles a efectos de medición. Fijar izquierda y
derecha respecto del sentido de trazado hace que la asimetría del eje sea interpretable.

**Alternativa descartada**: perpendicular a la tangente suavizada del eje (media de las direcciones
de los tramos vecinos), que en curvas cerradas se comporta mejor pero introduce dependencia entre
tramos contiguos y complica explicar qué se midió.

---

## D7 — CRS, unidades y proyección

**Decisión**: el eje llega en EPSG:4326 y se proyecta al **CRS del propio DEM** con
`rasterio.warp.transform`, exactamente como hace `annotations.geometry.project_vertices`. Todos los
cálculos (progresivas, pasos, semiancho, anchos) ocurren en unidades nativas del ráster y se
convierten a metros con `app.geoutils.get_rasterio_to_meters_factor`. Las cotas se reportan tal como
las entrega el ráster, sin conversión de datum vertical.

**Justificación**: reutiliza una decisión ya tomada y probada en el fork (`annotations`, D11), evita
un reproyectado intermedio y garantiza que la geometría medida y el ráster muestreado vivan en el
mismo sistema. No requiere `pyproj`, que está en la imagen pero no declarado en `requirements.txt`.

---

## D8 — Persistencia: índice en el DataStore, tramos en archivo

**Decisión**: dos niveles.

- **Índice y metadatos** en `GlobalDataStore('road')`, clave `task_<pk>`: un documento JSON con la
  lista de análisis (identidad, origen del eje, geometría del eje, modelo, variante, parámetros,
  umbrales del semáforo, estado, progreso, `celery_task_id`, `source_mtime`, contadores) y el
  candado de ejecución (D10). Se escribe bajo el mismo `document_lock` con advisory lock de
  PostgreSQL que ya usa `annotations.store`.
- **Tramos** en un archivo JSON por análisis, en
  `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json`, escrito por el worker al
  terminar (escritura atómica: archivo temporal + `os.replace`).

**Justificación**: `PluginDatum` guarda el documento entero en una fila y `annotations` ya sufrió las
carreras de lectura-modificación-escritura sobre él. Un análisis de 5 km con tramos de 5 m son 1.000
tramos con una docena de campos cada uno: del orden de megabytes en una sola fila de texto, releída
y reescrita en cada actualización de estado. Separar el volumen del índice mantiene el documento
pequeño y hace que el progreso se pueda actualizar sin arrastrar los datos.

**Alternativas descartadas**:

- *Todo en el DataStore*: simple, pero convierte cada `PATCH` de progreso en una reescritura de
  megabytes y hace que el `GET` del estado cargue todos los tramos.
- *Tabla propia en la base de datos*: exigiría migraciones dentro del plugin, algo que ningún plugin
  del fork hace hoy y que complica habilitar y deshabilitar.

---

## D9 — Ejecución asíncrona: función self-contained, progreso y cancelación

**Decisión**: `run_function_async(compute.run_analysis, ..., with_progress=True, with_cancel=True)`,
con la función escrita **self-contained** según el patrón ya establecido en `realign.corrections` y
`realign.pointcloud`: todos los `import` dentro del cuerpo y **absolutos**
(`from coreplugins.road import compute, store`), sin imports relativos ni referencias a los globals
del módulo, porque `app/plugins/worker.py: eval_async` reejecuta el código fuente en un namespace
vacío. El progreso se emite una vez por bloque (D2) con `progress_callback(status, perc)`, y
`should_cancel()` se consulta en el mismo punto, envuelto en `try/except` porque bajo
`CELERY_TASK_ALWAYS_EAGER` (tests) no hay backend de resultados. La cancelación desde el backend usa
el mismo `TestSafeAsyncResult(...).backend.store_result(..., state="ABORTED")` que `realign`.

**Justificación**: es el patrón vigente del fork, ya validado contra workers reales, y el único que
funciona con el mecanismo de ejecución por código fuente del framework.

---

## D10 — Un análisis en curso por tarea

**Decisión**: el documento del DataStore lleva un bloque `running` con `{analysis_id,
celery_task_id, started_at}`. `POST .../analyses` comprueba y escribe ese bloque **dentro del
`document_lock`**, de modo que dos peticiones simultáneas no puedan pasar ambas. Con `running`
presente y la tarea de Celery aún viva, la segunda petición responde `409 Conflict` con el
`analysis_id` en curso. El bloque se limpia al terminar, al fallar y al cancelar; además se
considera obsoleto —y se ignora— si el `AsyncResult` correspondiente ya está `ready()`, para que un
worker muerto no deje la tarea bloqueada para siempre.

**Justificación**: decisión de la clarificación del 2026-07-27 (uno a la vez por tarea). El candado
con salida por resultado terminado evita el fallo clásico de este patrón: un proceso que muere sin
liberar y deja la funcionalidad inutilizable hasta que alguien borre el estado a mano.

---

## D11 — Estimación previa de coste

**Decisión**: endpoint `POST .../analyses/estimate` que, sin lanzar nada, devuelve
`{segments, cross_sections, samples, estimated_seconds, warn}`. El conteo es aritmético:
`n_tramos = ceil(longitud / paso_tramo)`, `muestras_transversal = floor(2·semiancho / paso) + 1`,
`muestras_eje = ceil(longitud / paso)`, y el total es su combinación. La duración sale de una tasa
de muestras por segundo calibrada durante la implementación y guardada como constante del módulo.
`warn` se activa por encima de un umbral de muestras, y en ese caso el `POST` de creación exige
`confirm: true`; sin él responde `409` con la estimación. **No existe tope que impida lanzar.**

**Justificación**: decisión de la clarificación (sin tope fijo: estimar y avisar). Calcular el coste
es aritmética pura sobre la longitud del eje, así que la estimación es inmediata y no requiere tocar
el ráster.

---

## D12 — Obsolescencia del análisis

**Decisión**: se guarda el `st_mtime` del archivo DEM usado (`source_mtime`), y el estado derivado
`stale` se calcula al leer comparándolo con el `mtime` actual, igual que
`annotations.elevation.is_stale`. Un DEM ausente o ilegible cuenta como `stale`.

**Justificación**: un reproceso de la tarea reescribe el archivo, así que la marca cambia siempre
que cambia el dato. Es la misma señal que ya usa el fork, sin coste de cómputo.

---

## D13 — Ingesta y validación del GeoJSON subido

**Decisión**: `multipart/form-data` con un único archivo, tope de tamaño de subida, y validación en
cascada con un error por causa: JSON parseable → `Feature`, `FeatureCollection` de un solo elemento
o geometría suelta → geometría de tipo `LineString` → coordenadas 2D numéricas (una tercera se
ignora silenciosamente sólo si el usuario sube una línea con Z, avisando en la respuesta) → al menos
dos vértices distintos y no más que el tope → miembro `crs` ausente o EPSG:4326 (RFC 7946 fija
CRS84) → la línea intersecta la extensión del modelo de elevación elegido
(`task.dsm_extent` / `task.dtm_extent`, que son geometrías GEOS ya en la base de datos). La
validación de vértices reutiliza la lógica de `annotations.geometry.validate_vertices`, replicada en
`road` para no depender de un módulo interno de otro plugin.

**Justificación**: FR-003 exige identificar la causa concreta, lo que obliga a validar en pasos
nombrados en vez de un "archivo inválido" genérico. Comprobar la extensión contra la columna de la
base de datos evita abrir el ráster para rechazar un archivo.

---

## D14 — La capa en el mapa y el panel de capas del core

**Decisión**: los tramos se publican como **una anotación del core por análisis** —un
`L.FeatureGroup` con una polilínea por tramo— a través del bus `PluginsAPI.Map`
(`addAnnotation` / `onToggleAnnotation` / `onDeleteAnnotation`), con un bridge propio calcado del de
`annotations`. Regla crítica heredada: **todo manejador devuelve `false` sobre layers ajenos**, o
rompe al otro productor; el bus se detiene en el primer valor truthy.

**Justificación**: el usuario obtiene mostrar/ocultar y borrar nativos, y el análisis aparece junto
al resto de capas de la tarea en vez de vivir escondido en el panel del plugin. `annotations` ya
demostró que el bus funciona y dejó documentada la regla de convivencia.

**Alternativa descartada**: capa gestionada sólo por el panel del plugin. Menos código, pero la capa
desaparece del panel de capas y el usuario pierde el control que espera de cualquier otra capa.

---

## D15 — Semáforo en el cliente, umbrales persistidos

**Decisión**: el backend entrega la pendiente por tramo; el color lo decide el frontend aplicando
los dos umbrales, y cambiarlos sólo dispara un `setStyle` sobre las polilíneas ya dibujadas. Los
umbrales viajan al backend con un `PATCH` al análisis (campo `color_thresholds`), que los guarda en
el índice del DataStore sin tocar ni invalidar el resultado.

**Justificación**: decisión del usuario en la clarificación. Recolorear es una operación de
presentación sobre datos que ya están en el navegador: hacerla en el cliente la vuelve instantánea
(SC-005) y persistirla en el servidor evita que un refresco devuelva el camino a los colores por
defecto. Para caminos con muchos tramos el `setStyle` masivo es el punto a vigilar en rendimiento.

---

## D16 — Estrategia de tests

**Decisión**: tres niveles, todos ejecutables desde la suite de Django dentro de Docker.

1. **Unitarios de geometría y detección** (`coreplugins/road/tests.py`): perfiles sintéticos
   construidos en memoria —calzada plana con taludes a distancia conocida, rampa de pendiente
   conocida, perfil con ruido, perfil sin quiebre, perfil truncado por `nodata`— verificando ancho,
   pendientes y motivos de "sin borde" contra el valor exacto esperado.
2. **Integración con DEM sintético**: un GeoTIFF pequeño generado con `rasterio` en un directorio
   temporal, con un camino de geometría conocida, para ejercitar el pipeline completo, la
   exportación CSV/GeoJSON y los estados de cobertura parcial.
3. **API y estado**: las vistas REST con `CELERY_TASK_ALWAYS_EAGER`, incluidos el `409` de análisis
   concurrente, el `409` de confirmación requerida, la sustitución al recalcular y el borrado.
4. **Frontend** (`coreplugins/road/public/tests/`): el harness jsdom + Leaflet que `annotations`
   ya usa, ejecutado desde la suite de Django, para el bridge del bus y el recoloreado por umbrales.

**Justificación**: la parte que más puede equivocarse en silencio es la detección de bordes, y es
justamente la que se puede probar de forma exacta con perfiles sintéticos, sin depender de un vuelo
real. El resto sigue el patrón ya establecido por `annotations` y `realign`.
