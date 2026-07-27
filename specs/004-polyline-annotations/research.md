# Phase 0 — Investigación: polilíneas anotadas sobre el mapa 2D

**Feature**: `004-polyline-annotations` | **Fecha**: 2026-07-26

Las decisiones geoespaciales de este documento se validaron ejecutando código dentro del contenedor
`webapp` en marcha, sobre el DSM y el DTM reales de una tarea procesada (proyecto 10, tarea
`6e965174-…`): **EPSG:32719, 14145 × 29379 px, resolución 0,0222 m/px, nodata −9999,0, float32**.
Las decisiones de frontend se derivan de la lectura del core de WebODM y de los plugins existentes,
citando archivo y línea.

---

## D1 — Dibujo y edición en el mapa: implementación propia sobre Leaflet

- **Decisión**: implementar el trazado y la edición de vértices directamente con la API de Leaflet
  (`L.Polyline` + marcadores arrastrables para los vértices, e inserción por click sobre la línea
  resuelta con `L.LineUtil`), sin añadir ninguna librería de dibujo.
- **Rationale**: mantiene el **nivel 0** de la escalera del Principio IV (cero dependencias nuevas).
  El repo trae Leaflet **1.3.1** (`package.json:53`) y no hay ninguna librería de edición instalada
  (`leaflet-draw`, `leaflet-geoman`, `leaflet-editable`: ninguna presente en `node_modules`). Existe
  además precedente directo en el fork: `coreplugins/realign/public/RealignPanel.jsx:249-289` ya
  implementa marcado interactivo a mano con `map.on('click')` y `L.marker(..., {draggable: true})`.
  El control propio también es necesario para requisitos que una librería genérica no cubre: mostrar
  la longitud acumulada durante el trazado (FR-006) y bloquear el trazado en vistas multi-tarea
  (FR-031).
- **Alternativas descartadas**: **leaflet-draw 1.0.4** — última versión de 2018, sin mantenimiento;
  aporta una barra de herramientas y textos propios que habría que reconciliar con el `gettext` de
  WebODM, y su edición vive en un modo aparte que encaja mal con el panel del plugin.
  **leaflet-geoman** — sus versiones actuales piden Leaflet ≥ 1.9, incompatible con el 1.3.1 del
  repo; actualizar Leaflet sería tocar el core (Principio I).

## D2 — Integración con el sistema de anotaciones del core

- **Decisión**: publicar cada polilínea guardada como anotación del core mediante
  `PluginsAPI.Map.addAnnotation(layer, name, task, stored)`, y registrar manejadores para
  `onToggleAnnotation`, `onDeleteAnnotation`, `onUpdateAnnotation` y `onDownloadAnnotations`,
  emitiendo `PluginsAPI.Map.annotationDeleted(layer)` después de borrar.
- **Rationale**: el core **ya define este contrato y no lo implementa nadie**. `PluginsAPI.Map`
  declara las funciones en `app/static/app/js/classes/plugins/Map.js:24-32`; `Map.jsx:715-717`
  registra los manejadores del core y `Map.jsx:1041-1066` inserta el layer en `state.annotations`,
  que `LayersControlAnnotations.jsx` renderiza con visibilidad, encuadre, renombrado, borrado y
  exportación. Un grep por todo el repo confirma que hoy solo hay consumidores: ningún plugin
  produce anotaciones. Esto satisface FR-028/FR-029 sin tocar el core (Principio I).
- **Consecuencias de diseño obligatorias**:
  - El core **no borra ni oculta nada por su cuenta**: al pulsar la papelera llama
    `PluginsAPI.Map.deleteAnnotation(layer)` y espera que el plugin quite el layer y responda con
    `annotationDeleted` para que el core lo saque de su estado. Sin manejador, esos botones no hacen
    nada.
  - El bus es síncrono y **el primer callback que devuelve *truthy* corta la cadena**
    (`ApiFactory.js:95-102`). Todos los manejadores del plugin deben devolver `false` cuando el layer
    no les pertenece, para no bloquear a futuros productores de anotaciones.
  - El layer necesita `getBounds()` para el encuadre (`LayersControlAnnotations.jsx:44-51`); una
    `L.Polyline` lo cumple. El core escribe `layer[Symbol.for("meta")]` con nombre, icono y
    agrupación por tarea, de donde sale FR-030 sin trabajo extra.
  - `LayersControlAnnotations.jsx:127` invoca `PluginsAPI.Map.downloadAnnotations("geojson")` y hoy
    cae en un `// TODO?` vacío: implementar ese manejador es lo que hace funcionar el botón nativo
    de exportación (FR-032).
- **Alternativas descartadas**: renderizar las polilíneas como capa propia fuera del control de
  capas — perdería FR-028/FR-029 y duplicaría una interfaz que el core ya ofrece.

## D3 — Muestreo del modelo de elevación: `rasterio`, sin dependencias nuevas

- **Decisión**: leer el DEM con `rasterio.open()` y muestrear con `dataset.sample()` (vecino más
  próximo, sin interpolación); transformar las coordenadas de EPSG:4326 al CRS del ráster con
  `rasterio.warp.transform`.
- **Rationale (medido)**: la ida y vuelta 4326 ↔ EPSG:32719 sobre el centro del DSM real dio
  `dx = dy = 0,000000 m`. `sample()` procesó **26 217 puntos en 0,97 s** en frío y **8 489 puntos en
  0,157 s** en caliente. `rasterio` 1.3.10 está en `requirements.txt:56` y los bindings `osgeo`
  también están, de modo que se mantiene el **nivel 0** del Principio IV. El vecino más próximo es
  además la lectura fiel del dato: interpolar bilinealmente inventaría cotas intermedias, justo lo
  que FR-021 prohíbe.
- **Hallazgo sobre `pyproj`**: está instalado en la imagen (**3.6.1**), pese a que
  `docs/entorno-plugins.md` lo lista como no disponible. **Aun así no se usará**: no figura en
  `requirements.txt`, por lo que es una dependencia transitiva que un merge de upstream podría
  hacer desaparecer sin aviso (Principio II). Todo lo que se necesita está en `rasterio.warp`.
  Conviene corregir esa fila del documento de entorno en una tarea aparte.
- **`shapely` confirmado ausente** — no se usa en ningún punto del diseño.
- **Detección de ausencia de dato**: `sample()` devuelve el `nodata` del ráster (−9999,0) tanto en
  huecos interiores como en puntos fuera del *bounding box*, verificado en ambos casos. Un único
  criterio (`z == nodata or isnan(z)`) cubre las dos situaciones de FR-022.

## D4 — Paso de densificación: parámetro explícito, no la resolución nativa

- **Decisión**: el paso de densificación es un **parámetro de primera clase** con valor por defecto
  `max(resolución_del_DEM, 0,25 m)`, ajustable por el usuario, y **se persiste junto a la longitud
  que produjo**. Se aplica un límite duro de **20 000 puntos densificados** por polilínea.
- **Rationale (medido)**: la longitud sobre el terreno **no es un valor único**: depende de la
  escala a la que se mida. Sobre el mismo tramo de 188,39 m en planta del DSM real, con cobertura
  completa y sin ningún nodata:

  | Paso (m) | Puntos | `sample()` | Longitud 3D | vs. planta | Desnivel acum. |
  |---|---|---|---|---|---|
  | 0,0222 (nativo) | 8 489 | 0,157 s | 311,28 m | +65,23 % | 158,74 m |
  | 0,05 | 3 769 | 0,070 s | 308,09 m | +63,54 % | 156,67 m |
  | 0,10 | 1 885 | 0,035 s | 303,39 m | +61,04 % | 153,38 m |
  | 0,25 | 755 | 0,014 s | 297,36 m | +57,85 % | 149,23 m |
  | 0,50 | 378 | 0,007 s | 280,09 m | +48,67 % | 133,91 m |
  | 1,00 | 190 | 0,004 s | 263,66 m | +39,95 % | 121,91 m |
  | 2,00 | 96 | 0,002 s | 229,71 m | +21,94 % | 86,45 m |
  | 5,00 | 39 | 0,001 s | 217,14 m | +15,26 % | 73,94 m |

  Entre el paso nativo y 5 m la longitud varía un **43 %** sobre el mismo trazado y el mismo modelo.
  A 2,2 cm el muestreo está midiendo la rugosidad del DSM —ruido, vegetación, bordes de tejado— y no
  el recorrido que le interesa al usuario. Por eso el supuesto original del spec ("paso = resolución
  nativa del modelo") no se sostiene y por eso la cifra **carece de sentido si no va acompañada del
  paso con el que se calculó**.
  El valor por defecto de 0,25 m es del orden de la escala de un paso humano, filtra el ruido de un
  DSM centimétrico y mantiene el volumen de puntos manejable (≈ 4 puntos/m). En DEM de baja
  resolución (1 m/px o más) manda la resolución nativa, porque densificar por debajo del píxel solo
  reproduce escalones del vecino más próximo.
- **Impacto en el spec**: obliga a matizar FR-014, FR-015 y FR-017, y a reformular SC-004 (una
  comparación con una herramienta externa solo es válida a igualdad de paso). Recogido en la
  actualización del spec de esta misma fecha.
- **Alternativas descartadas**: paso fijo igual a la resolución (produce longitudes infladas y no
  reproducibles entre tareas de distinta resolución); suavizar el DEM antes de medir (inventaría
  cotas, contra FR-021); interpolación bilineal (mismo problema, además de enmascarar el nodata).

## D5 — No persistir la geometría densificada

- **Decisión**: persistir únicamente los vértices con su cota, las métricas y los metadatos de
  muestreo. La versión densificada se calcula bajo demanda en cada petición que la necesite.
- **Rationale (medido)**: para el tramo de 188 m, la densificada al paso nativo ocupa **288,4 KB de
  JSON** (8 489 puntos); a 0,25 m, **25,7 KB**; a 1 m, **6,5 KB**. Una tarea con una decena de
  líneas kilométricas haría crecer el `PluginDatum` hasta varios MB de `jsonb` por tarea, sin
  ganancia: recalcularla cuesta **0,014 s** al paso por defecto. Persistirla además crearía un
  segundo estado que se desincroniza en cuanto cambia el paso o el DEM.
- **Cumplimiento de FR-038**: el contrato sigue entregando la densificada al consumidor —la calcula
  el plugin, no el consumidor—, que es lo que el requisito exige.

## D6 — Ejecución síncrona: sin Celery

- **Decisión**: el muestreo se resuelve dentro de la propia petición HTTP, sin `run_function_async`
  ni sondeo de estado.
- **Rationale (medido)**: en el peor caso admitido por el límite de D4 (20 000 puntos) el muestreo
  ronda **0,3–0,8 s**, y el caso típico al paso por defecto está en **decenas de milisegundos**.
  El aparato asíncrono que usan `viewshed` y `realign` existe porque allí las operaciones duran
  minutos (48 s solo el pipeline PDAL de 003); aquí introduciría sondeo, estados intermedios y
  cancelación para ahorrar centésimas de segundo. El límite duro de puntos es lo que garantiza que
  esta decisión siga siendo válida (FR-023).
- **Alternativa descartada**: asíncrono con `run_function_async` — complejidad injustificada, y
  además obligaría a que la función se ejecute por *source* en un espacio de nombres vacío, con
  imports absolutos dentro, para nada.

## D7 — Persistencia: `GlobalDataStore`, un documento por tarea

- **Decisión**: un documento JSON por tarea en el `GlobalDataStore` del framework, con espacio de
  nombres `annotations` y clave `task_<pk>`, replicando `coreplugins/realign/store.py`.
- **Rationale**: `PluginDatum.json_value` es un `JSONField` de `django.contrib.postgres`
  (`app/models/plugin_datum.py:13`), es decir `jsonb` nativo. Con `user=None` el documento es global
  y lo comparten todos los usuarios con acceso a la tarea, que es exactamente FR-025. No hay modelos
  ni migraciones nuevas, como exige el Principio I, y es el patrón ya rodado en el fork.
- **Limitación asumida**: el ciclo leer-modificar-escribir puede perder una edición concurrente, el
  mismo riesgo que `realign` ya documenta y que el spec acepta explícitamente al dejar la fusión de
  ediciones fuera de alcance.

## D8 — Borrado en cascada mediante la señal `task_removed`

- **Decisión**: un receptor de `app.plugins.signals.task_removed` elimina el documento de la tarea.
- **Rationale**: la señal la emite el core en `app/models/task.py:1411` con `send_robust`, y hay
  precedente de uso en un plugin: `coreplugins/cesiumion/api_views.py:146` la escucha con
  `@receiver(..., dispatch_uid=...)`. Cubre FR-027 sin tocar el core. El `dispatch_uid` evita
  registros duplicados al recargarse el módulo.

## D9 — Permisos: ver con `view_project`, editar con `change_project`

- **Decisión**: todas las vistas heredan de `TaskView` y llaman a `get_and_check_task`; las que
  modifican añaden `check_project_perms(request, task.project, ('change_project',))`.
- **Rationale**: `get_and_check_task` (`app/api/tasks.py:460-470`) solo valida `view_project`, y
  únicamente cuando la tarea o el proyecto no son públicos, de modo que **por sí solo no protege la
  escritura**. `realign/api.py` resuelve esto exactamente así en sus seis endpoints de escritura
  (líneas 151, 174, 186, 236, 480, 519). Es el criterio que FR-025 manda replicar.

## D10 — Selección del modelo de elevación y detección de disponibilidad

- **Decisión**: usar `task.dsm_extent` / `task.dtm_extent` para saber qué hay, y
  `task.get_asset_download_path("dsm.tif" | "dtm.tif")` para resolver la ruta. Preseleccionar DSM.
- **Rationale**: es el patrón exacto de `coreplugins/viewshed/api.py:103-108`. Los *extent* son
  campos de la base de datos, así que la comprobación de disponibilidad no toca el disco. Verificado
  sobre la tarea de referencia: DSM y DTM **comparten CRS (EPSG:32719), resolución (0,0222 m) y
  tamaño (14145 × 29379)**, así que el paso por defecto y los límites no dependen de cuál se elija.

## D11 — Cálculo de longitudes en un CRS proyectado en metros

- **Decisión**: calcular ambas longitudes en el CRS proyectado del DEM cuando la línea es sobre el
  terreno, de modo que planta y terreno sean coherentes entre sí. Para líneas planas en tareas sin
  DEM, proyectar al CRS de la tarea (`task.epsg`) con `rasterio.warp.transform`, y si tampoco existe,
  al UTM correspondiente al centroide de la línea.
- **Rationale**: el DEM de referencia declara `linear_units = metre`, así que la distancia euclídea
  en ese espacio ya está en metros y no hace falta cálculo geodésico. Mantener las dos longitudes en
  el mismo espacio evita que "planta" y "terreno" procedan de dos métricas distintas, que es de
  donde salen las incoherencias difíciles de explicar al usuario. `app/geoutils.py` ya expone
  `get_rasterio_to_meters_factor` para los CRS cuya unidad no sea el metro.

## D12 — Detección de muestreo obsoleto

- **Decisión**: guardar junto al muestreo la marca de tiempo de modificación del archivo del DEM y
  compararla al leer; si difiere, la respuesta marca el muestreo como obsoleto.
- **Rationale**: cubre FR-020 sin depender de eventos de reproceso ni de estado adicional, y sin
  releer el ráster: basta un `os.stat`. Un reproceso reescribe `dsm.tif`, de modo que la marca cambia
  siempre que el dato cambia.

---

## Riesgos y puntos de atención

1. **El bus de anotaciones corta en el primer *truthy*** (`ApiFactory.js:95-102`). Devolver `true`
   indiscriminadamente desde los manejadores del plugin rompería a cualquier otro productor de
   anotaciones futuro. Los manejadores deben identificar sus propios layers y devolver `false` en
   caso contrario.
2. **`Map.jsx:1148-1150` da de baja el manejador equivocado** (`offAnnotationDeleted` recibe
   `handleAddAnnotation`). Es un defecto del core que solo afecta al desmontaje del mapa; no se
   corrige aquí porque tocar el core violaría el Principio I. Conviene tenerlo presente si aparecen
   manejadores duplicados al navegar entre mapas.
3. **Leaflet 1.3.1 es antiguo**; cualquier librería de mapas que se plantee en el futuro debe
   verificarse contra esa versión, no contra la última.
4. **La longitud sobre el terreno es sensible al paso** (D4). Debe presentarse siempre junto al paso
   empleado, o el usuario comparará cifras no comparables.
