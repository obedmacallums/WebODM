# Research: Análisis de visibilidad (viewshed)

**Feature**: 001-viewshed-analysis | **Date**: 2026-07-21

Todas las incógnitas del Technical Context quedaron resueltas. Fuentes: código real del
repo (patrones verificados en `coreplugins/contours/`, `app/plugins/views.py`,
`app/plugins/plugin_base.py`) e inventario de entorno (`docs/entorno-plugins.md`).

## D1. Motor de cálculo del viewshed

- **Decision**: `gdal_viewshed` (CLI de GDAL 3.4.x, ya en la imagen) invocado por
  `subprocess` dentro de la función asíncrona que corre en el worker, con
  `shutil.which()` para localizar el binario y manejo de errores por `returncode`.
- **Rationale**: GDAL 3.4 incluye `gdal_viewshed` (algoritmo de Wang et al.); cero
  dependencias nuevas (Principio IV nivel 0). El patrón subprocess es exactamente el que
  usa `contours` (`calc_contours` llama `gdal_contour`/`ogr2ogr` por subprocess), lo que
  da aislamiento de memoria en el worker Celery y errores capturables.
- **Alternatives considered**:
  - Bindings Python `osgeo.gdal.ViewshedGenerate()` — viable (existen desde GDAL 3.1),
    pero rompe la simetría con el patrón de referencia y mantiene el raster en memoria
    del proceso worker; sin ventaja material.
  - Implementación propia con numpy/rasterio — reinventar un algoritmo no trivial
    (líneas de vista con curvatura); rechazada.
  - PDAL — orientado a nubes de puntos, no a viewshed sobre DEM; no aplica.

## D2. Parámetros del cálculo

- **Decision**: `-ox/-oy` = punto del clic transformado al CRS del DEM; `-oz` = altura
  del observador sobre el suelo (default 1,60 m; validación 0–500 m); `-tz 0` (altura de
  objetivo 0, según Assumptions del spec); sin `-md` (max distance) → cubre toda la
  extensión del DEM (FR-011); coeficiente de curvatura por defecto de GDAL (irrelevante
  a escala de levantamientos con dron).
- **Rationale**: mapea 1:1 los FR-003/004/005/011 del spec sin superficie de
  configuración extra.
- **Alternatives considered**: exponer radio máximo y altura de objetivo — fuera de
  alcance v1 declarado en el spec.

## D3. Fuente de elevación y validaciones

- **Decision**: DSM preferido (`task.dsm_extent` + `get_asset_download_path("dsm.tif")`),
  DTM como respaldo si no hay DSM; si no existe ninguno → error claro (FR-010). El punto
  del clic se transforma de EPSG:4326 (Leaflet) al CRS del DEM con `osgeo.osr`; si cae
  fuera del extent o sobre nodata → error claro antes de lanzar el cálculo.
- **Rationale**: DSM incluye obstáculos (edificios/vegetación) = visibilidad realista,
  como asume el spec; el patrón de chequeo `dsm_extent`/`dtm_extent` es el de `contours`
  (`api.py:121-124`).
- **Alternatives considered**: dejar elegir capa al usuario (como hace contours) —
  pospuesto; el spec fija superficie realista por defecto y menos fricción de UI.

## D4. Ejecución asíncrona y progreso

- **Decision**: `run_function_async(calc_viewshed, ...)` (de `app.plugins.worker`) →
  devuelve `celery_task_id`; el frontend hace polling con la clase existente
  `Workers.waitForCompletion` (`app/static/app/js/classes/Workers.js`) y descarga el
  resultado desde un endpoint del plugin que extiende `GetTaskResult`.
- **Rationale**: es la tubería asíncrona oficial del framework para plugins (la usa
  `contours`); cumple FR-009 (UI no bloqueante + progreso) sin infraestructura nueva y
  ejecuta el cálculo en el contenedor worker (que comparte imagen con webapp → GDAL
  disponible, Principio IV.3 verificable).
- **Alternatives considered**: cálculo síncrono en la request — bloquearía la UI y el
  gunicorn worker con DEMs grandes; rechazado.

## D5. Formato y entrega del resultado

- **Decision**: poligonizar las celdas visibles del raster de salida
  (`gdal_polygonize.py`) y reproyectar/simplificar a **GeoJSON** en EPSG:4326
  (`ogr2ogr`), archivo temporal en `settings.MEDIA_TMP`; el frontend lo agrega como capa
  `L.geoJSON` con estilo semitransparente y leyenda. Plan B documentado: si con datasets
  reales la poligonización resulta pesada o fragmentada, cambiar a PNG georreferenciado +
  `L.imageOverlay` (decisión revisable en implementación sin afectar contratos: el
  endpoint de descarga serviría otro content-type).
- **Rationale**: reutiliza el patrón de entrega de archivo de `contours`
  (`{'file': path}` + `GetTaskResult`); GeoJSON da estilización nativa en Leaflet,
  distinción visual clara (FR-006) y dejaría exportación casi gratis en una versión
  futura.
- **Alternatives considered**: servir el GeoTIFF crudo (el frontend no lo renderiza
  nativamente); tiles dinámicos (sobredimensionado para un resultado efímero).

## D6. Integración con la vista 2D

- **Decision**: `main.js` usa `PluginsAPI.Map.willAddControls` para montar un control
  Leaflet (`Viewshed.jsx` compilado a `build/` por `build_jsx_components`); el panel
  (`ViewshedPanel.jsx`) activa el modo de captura de clic sobre el mapa, muestra el campo
  de altura con default 1,60 m, el progreso y el botón de limpiar capa (FR-007/008:
  mantiene una sola capa de resultado y la reemplaza en cada análisis).
- **Rationale**: patrón exacto de `contours/public/main.js` (verificado); un solo punto
  de integración con el core, vía la API pública de plugins.
- **Alternatives considered**: inyectar en el sidebar de la vista del mapa — no existe
  punto de extensión estable para eso; rechazado.

## D7. Permisos y seguridad

- **Decision**: los endpoints extienden `TaskView` del framework y llaman
  `get_and_check_task(request, pk)` antes de cualquier operación (FR-012); los
  parámetros `lat`, `lng`, `observer_height` se validan server-side (tipos y rangos)
  además de la validación de UI (FR-005).
- **Rationale**: `get_and_check_task` aplica los permisos por-objeto existentes
  (django-guardian) — mismo mecanismo que todos los coreplugins.
- **Alternatives considered**: ninguna — es el mecanismo único del framework.

## D8. Dependencias

- **Decision**: **ninguna dependencia nueva**. Sin `requirements.txt` en el plugin, sin
  cambios al `Dockerfile`.
- **Rationale**: todo lo necesario (gdal-bin con `gdal_viewshed` y `gdal_polygonize.py`,
  `ogr2ogr`, bindings `osgeo`, Leaflet, React) ya está en la imagen según
  `docs/entorno-plugins.md`. Es el nivel 0 de la escalera del Principio IV — aun así, la
  verificación del worker (Principio IV.3) se mantiene en `quickstart.md` porque el
  cálculo corre en ese contenedor.
