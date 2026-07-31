# Phase 0 — Investigación

Feature: `009-training-dataset-labeling`. Fecha: 2026-07-30.

Todas las mediciones se hicieron contra la instancia real vía `docker compose exec`. Se indica en
qué contenedor, porque en `008` quedó claro que `webapp` y `worker` no son intercambiables a efectos
de dependencias.

---

## D1 — Dos superficies de interfaz, no una

**Decisión**: página global para gestionar datasets (`main_menu()` + `app_mount_points()`) más panel
sobre el mapa de la tarea para etiquetar (`include_js_files()` + `build_jsx_components()` +
`PluginsAPI`).

**Razón**: un dataset referencia varias tareas (FR-002), así que no puede colgar de ninguna. `road` y
`annotations` solo tienen panel de tarea porque sus datos sí son por tarea. El precedente para la
página global está en el propio repositorio: `coreplugins/task-manager/plugin.py` registra
`Menu(...)` en `main_menu()` y `MountPoint('$', index_view)` en `app_mount_points()`, sirviendo una
plantilla con `render(request, self.template_path("index.html"), ...)`.

**Alternativas descartadas**: colgar los datasets de una tarea «principal» —contradice FR-001 y
rompería en cuanto se borrase esa tarea—; o gestionar todo desde el panel del mapa, que dejaría la
lista de datasets inaccesible sin abrir una tarea al azar.

## D2 — Índice en el store, datos voluminosos en fichero

**Decisión**: metadatos del dataset (nombre, clases, resolución, tamaño de tesela, tareas) en
`GlobalDataStore` con namespace `training`; etiquetas de cada par (dataset, tarea) en un fichero JSON
bajo `get_persistent_path()`.

**Razón**: es exactamente el reparto que `road` ya usa —índice de análisis en el store, tramos en
fichero— y por el mismo motivo. Un trazo de pincel largo puede tener miles de vértices; el store es
una fila de base de datos y no es el sitio para eso. `annotations` sí guarda sus polilíneas en el
store, pero sus geometrías son de decenas de vértices, no de miles.

**Alternativas descartadas**: todo en el store (riesgo de filas enormes y de lecturas caras solo para
listar datasets); todo en fichero (listar datasets exigiría recorrer el disco).

## D3 — Bloqueo por documento copiado de `annotations`

**Decisión**: `pg_advisory_xact_lock` con dos claves int4 —una identifica al plugin, la otra al
documento— siguiendo `coreplugins/annotations/store.py:31-40`.

**Razón**: FR-017. El patrón ya está resuelto y probado en este repositorio, incluido el detalle de
que `crc32` es sin signo y hay que restarle 2³² para que quepa en un int4 con signo.

## D4 — El CRS métrico ya lo trae la ortofoto

**Decisión**: el buffer del pincel y el rasterizado se hacen en el CRS nativo de la ortofoto. Las
etiquetas se **guardan** en coordenadas geográficas (lo que entrega Leaflet) y se reproyectan una
sola vez, al exportar.

**Medido en `webapp`** sobre las cinco tareas reales:

```
Task of 2026-07-24            CRS=EPSG:32719  res=0.0500 m/px   6277x9567   bandas=4
Colegio Trabunco              CRS=EPSG:32719  res=0.0500 m/px   9353x9814   bandas=4
Mina La Coipa                 CRS=EPSG:32719  res=0.0635 m/px  17128x22084  bandas=4
Polideportivo María Puebla    CRS=EPSG:32719  res=0.0500 m/px   6569x4399   bandas=4
Noria                         CRS=EPSG:32719  res=0.0222 m/px  14145x29380  bandas=4
```

**Razón**: FR-012b exigía «un sistema de coordenadas métrico» y yo esperaba tener que calcular la
zona UTM a partir del centroide. No hace falta: ODM ya genera la ortofoto proyectada en UTM. El
requisito se cumple usando lo que ya está en el fichero.

Guardar en coordenadas geográficas y no en UTM es deliberado: mantiene las etiquetas válidas si la
ortofoto se regenera o cambia de zona, y evita que el frontend tenga que saber de proyecciones.

**Alternativa descartada**: guardar directamente en el CRS de la ortofoto. Ataría las etiquetas a un
fichero que puede regenerarse, que es justo el caso que la spec pide sobrevivir.

## D5 — Rasterizado tesela a tesela, nunca global

**Decisión**: para cada tesela se rasterizan solo las etiquetas que la intersecan, con el `transform`
de esa ventana. No existe en ningún momento una máscara de la ortofoto completa.

**Razón**: aritmética, no preferencia. La ortofoto de la mina a 10 cm/px son 10 876 × 14 023 px =
152 Mpx. Una máscara `uint8` global serían 152 MB y la imagen RGB 457 MB, por dataset y por
exportación. FR-030 prohíbe construir el paquete en memoria; esto lo cumple por construcción.

## D6 — El remuestreo lo hace la lectura

**Decisión**: `raster.read(indexes, window=..., out_shape=(n, 512, 512))`. Sin paso de warp
intermedio ni ficheros temporales.

**Medido en `webapp`** sobre la ortofoto de la mina (6,35 cm/px, objetivo 10 cm/px → factor 1,575):

```
ventana nativa: 806 px -> salida (3, 512, 512) | alfa validos: 100.0%
nodata: None | tiled: True | dtype: uint8
```

**Razón**: es el mismo mecanismo que `geodeep` usa internamente para adaptar la ortofoto a la
resolución del modelo, y el ráster ya viene *tiled*, así que la lectura por ventana es eficiente.

## D7 — Los píxeles válidos salen de la banda alfa

**Decisión**: el umbral de píxeles válidos de FR-027 se calcula sobre la banda 4.

**Medido**: `colorinterp: ['red', 'green', 'blue', 'alpha']` y **`nodata: None`**.

**Razón**: el segundo dato es el importante. Como no hay valor centinela declarado, cualquier
heurística sobre el valor de los píxeles (¿es negro un píxel sin datos o un píxel oscuro de sombra?)
habría sido una fuente de fallos silenciosos. El alfa lo dice sin ambigüedad.

**Consecuencia para el diseño**: las tres bandas RGB van a la tesela de imagen y el alfa se usa solo
para decidir si la tesela entra en el paquete. No se exporta el canal alfa: el modelo espera tres
canales.

## D8 — Trazo de pincel: polilínea con radio, comprobado antes de escribir código

**Decisión**: un trazo se guarda como polilínea más un radio en metros. La superficie se obtiene con
`buffer()` de GEOS en el momento de rasterizar.

**Medido en el contenedor `worker`** con el código que usaría la implementación:

```
buffer -> Polygon area m2: 118.14        (polilínea de 20 m, radio 2,5 m, EPSG:32719)
mascara: (200, 200) uint8 valores: [1, 255]
px clase 1: 11825 | px ignorar: 28175    → 11825 px × 0,01 m² = 118,25 m²
```

**Razón**: es la decisión estructural de la feature y convenía comprobarla, no suponerla. El área
rasterizada coincide con la del polígono, y el relleno 255 («ignorar») convive con los índices de
clase en el mismo `uint8` sin colisión.

**Alternativas descartadas**: guardar píxeles (ata el dataset a una resolución para siempre e impide
borrar un trazo concreto); usar `shapely`, que **no está en la imagen** y habría supuesto una
dependencia nueva prohibida por FR-037.

## D9 — Exportación asíncrona con el patrón de `road`

**Decisión**: `run_function_async` con reporte de progreso, y el paquete construido en disco bajo
`get_persistent_path()` antes de servirse.

**Razón**: FR-030. `road` ya tiene resuelto el ciclo completo —lanzar, reportar progreso, cancelar,
persistir el `celery_task_id`— y la descarga final es un `HttpResponse` con `Content-Disposition`,
como su exportación de CSV y GeoJSON (`road/api.py:598-602`).

**Riesgo asociado, y es el principal del plan**: `run_function_async` recompila la función por código
fuente en un espacio de nombres vacío. Los imports tienen que vivir en los módulos del plugin y no
dentro de la función asíncrona. En `008` esta mitigación (D41) funcionó y el log del worker salió sin
un solo `NameError`; se repite aquí y se verifica igual.

## D10 — El pincel es el riesgo de esfuerzo, no el de corrección

**Decisión**: `LabelEditor.js` extiende el enfoque de
`coreplugins/annotations/public/PolylineEditor.js` en Leaflet puro, sin librerías nuevas.

**Razón**: esas 291 líneas ya resuelven trazado, arrastre de vértices, inserción, borrado y —lo que
más caro habría salido descubrir— el silenciado del popup de la ortofoto del core durante el trazado,
vía `PluginsAPI.Map.onHandleClick`. Un polígono es una polilínea cerrada.

**Lo que no está resuelto y hay que construir**: captura de arrastre continuo, previsualización del
radio sobre el terreno, y desactivar el desplazamiento del mapa mientras se pinta. No hay precedente
en el repositorio, así que es donde la estimación es más incierta. SC-004 —que pintar sea más rápido
que dibujar polígonos— es su única justificación y debe medirse.

**Alternativa descartada**: `leaflet-draw`. No está en el proyecto (comprobado: cero coincidencias en
`app/` y `coreplugins/`), y añadirla sería una dependencia de frontend prohibida por FR-037.

## D11 — Volumen real del dataset

**Medido en `webapp`**, rejilla completa de 512 px sobre las cinco ortofotos:

```
a   2.5 cm/px -> 13486 teselas
a  10.0 cm/px ->   912 teselas
a  21.0 cm/px ->   227 teselas
```

**Consecuencia**: corrige SC-006, que llevaba una cifra derivada (~758) en lugar de medida. Y aporta
el argumento del troceo de esta entrega: Mina La Coipa aporta **616 de las 912**, así que un dataset
de una sola tarea ya es viable y US3 sale del camino crítico.

Estas son teselas de rejilla completa. Las que realmente entren en el paquete serán menos, porque
FR-027 descarta las que no tengan etiquetas ni suficientes píxeles válidos.

---

## D12 — Coste real de exportar, medido tras implementar

Cierra el riesgo abierto 3. **Medido en el contenedor `worker`** sobre la ortofoto real de Mina La
Coipa (17 128 × 22 084 px, 6,35 cm/px), con un dataset a 10 cm/px y teselas de 512 px:

```
teselas       : 169          (un área etiquetada de 600 x 600 m)
segundos      : 19,1
ms/tesela     : 113
tamaño        : 68,3 MB
RSS antes  MB : 153,5
RSS pico   MB : 177,5        -> incremento de 24,1 MB
```

**Consecuencia 1 — el tiempo no es un problema.** A 113 ms/tesela, las 616 teselas de la rejilla
completa de la mina salen en **~1,2 minutos**. La exportación asíncrona sigue estando justificada
por FR-030, pero el usuario no va a esperar horas.

**Consecuencia 2 — la aritmética de D5 se confirma en la báscula.** El enfoque tesela a tesela
consumió 24 MB para 169 teselas. Una máscara global de esa ortofoto habrían sido 152 MB y la imagen
RGB 457 MB: 609 MB frente a 24, y sin depender del tamaño de la ortofoto. La memoria queda acotada
por el tamaño de una tesela, que es lo que D5 predijo por cálculo y ahora está medido.

## D13 — `GEOSGeometry.transform` no sirve para reproyectar las etiquetas

**Encontrado al implementar**, no al planificar, y es el único supuesto del plan que hubo que
corregir.

Con PROJ moderno, GeoDjango respeta el orden de ejes que la EPSG declara para el 4326 —(lat, lon)—
así que interpreta como latitud la longitud que se le pasa. Medido sobre un punto de la ortofoto de
prueba en EPSG:32719:

```
origen                       : (400 000, 6 000 000)
ida a WGS84 (rasterio)       : (-70,111, -36,140)      correcto
vuelta con GEOSGeometry      : (1 694 024, 1 888 506)  incorrecto
```

La geometría acababa fuera de la zona UTM, ninguna etiqueta intersecaba su tesela y **la máscara
salía entera a 255** — un fallo perfectamente silencioso: el paquete se generaba, el manifiesto era
válido y las máscaras no contenían nada.

**Decisión**: la reproyección la hace `rasterio.warp.transform`, que usa el orden `(x, y)` sin
ambigüedad y ya es el camino que recorre la lectura de la ortofoto. GEOS se queda con el `buffer`
del pincel, que es lo que D8 midió y lo único que no depende del orden de ejes.

## Riesgos abiertos que el plan asume

1. **El pincel no tiene precedente** (D10). Era la estimación más incierta de la entrega. Resuelto
   en `public/LabelEditor.js` con arrastre continuo, desactivación del `dragging` del mapa y radio
   en metros de terreno; cubierto por `public/tests/labelEditor.test.js` y `brushRadius.test.js`.
   Queda por medir SC-004 (que pintar sea más rápido que dibujar polígonos), que exige cronometrar
   a una persona.
2. **La verificación del worker es obligatoria y no la cubre ningún test** (D9, Principio IV paso 3).
   Hecha: ver `quickstart.md` Escenario 4 y D12. El backend de Celery devolvió `SUCCESS` con el
   valor de retorno de `run_export_async` y el log del worker no registró ningún error.
3. ~~No se ha medido el tiempo de exportación de un dataset grande.~~ Cerrado en D12.
