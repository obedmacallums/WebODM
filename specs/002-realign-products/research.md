# Phase 0 — Research: plugin `realign`

Decisiones técnicas para la realineación manual de productos ráster 2D. Todas verificadas
contra el código real del repo (`app/api/tiler.py`, `app/plugins/*`, `coreplugins/viewshed/`)
y el inventario de `docs/entorno-plugins.md`. **Ninguna requiere dependencias nuevas.**

## D1 — Modelo matemático de la transformación

- **Decisión**: transformación de **similitud** (traslación + rotación + escala uniforme)
  ajustada por mínimos cuadrados con el algoritmo de **Umeyama** (SVD sobre las covarianzas de
  los pares origen→destino). Con 1 par: solo traslación (rotación=0, escala=1). Con 2+ pares:
  ajuste completo. Residuo por punto = distancia entre el destino marcado y la imagen del
  origen bajo la transformación; RMSE = raíz de la media de los residuos al cuadrado.
- **Rationale**: la similitud corrige el desajuste típico (desplazamiento + giro + escala) sin
  deformar la imagen (conforme). Umeyama es cerrado, estable y trivial en numpy; no necesita
  iteración. El error por punto y el RMSE son la métrica estándar de un georreferenciador.
- **Alternativas descartadas**: afín/polinomial/TPS (spec fija similitud; deforman y son fáciles
  de sobreajustar); Procrustes sin escala (no corrige diferencias de escala); ajuste iterativo
  (innecesario para un modelo cerrado).
- **Dónde corre**: en el **cliente** (JS, `public/similarity.js`) para previsualización y
  residuos en vivo sin ida y vuelta (SC-002 < 1 s); en el **backend** (`transform.py`, numpy)
  para el cálculo autoritativo al aplicar. Ambas implementaciones se validan con tests de
  paridad sobre los mismos casos (traslación pura, similitud conocida, caso degenerado).

## D2 — Cálculo en el CRS correcto

- **Decisión**: los puntos se capturan en coordenadas del mapa (EPSG:4326, lat/lng de Leaflet).
  El ajuste de similitud se realiza en un **plano métrico local**: se proyectan origen y destino
  al CRS proyectado de la tarea (`task.epsg`, el mismo de los rásteres) o, si no procede, a un
  UTM/aeqd local; se ajusta la similitud ahí y se aplica al ráster en ese CRS.
- **Rationale**: una similitud debe ajustarse en un espacio métrico, no en grados (lat/lng no es
  isótropo). El patrón de reproyección con `osr` ya está en `coreplugins/viewshed/api.py`
  (`osr.CoordinateTransformation`, `SetAxisMappingStrategy(OAMS_TRADITIONAL_GIS_ORDER)`), que se
  reutiliza aquí.
- **Alternativas descartadas**: ajustar en grados (distorsión por latitud); Web Mercador global
  (escala variable con la latitud; el CRS proyectado de la tarea es más fiel localmente).

## D3 — Previsualización en Leaflet (sin tocar archivos)

- **Decisión**: aplicar una **matriz CSS afín** (`transform: matrix(a,b,c,d,e,f)`) sobre el
  contenedor/`pane` de las capas ráster (ortofoto/DSM/DTM) para desplazarlas, rotarlas y
  escalarlas en tiempo real. La matriz se deriva de la similitud convertida a espacio de píxeles
  de pantalla al zoom actual y se recalcula en los eventos `zoomend`/`moveend` del mapa. Todas
  las capas ráster se transforman juntas (comparten georreferenciación, FR-007).
- **Rationale**: las `TileLayer` de Leaflet son axis-aligned y no rotan de forma nativa; una
  similitud en coordenadas proyectadas se corresponde con una similitud en píxeles de pantalla a
  zoom fijo, expresable como matriz CSS. Es instantáneo, no genera tráfico ni archivos y es
  totalmente reversible (quitar el `transform`). El frontend recibe `args.map` y `args.tiles`
  desde `PluginsAPI.Map.willAddControls` (verificado en `coreplugins/viewshed/public/main.js`),
  suficiente para localizar y transformar las capas sin tocar el core.
- **Riesgo / mitigación (validar primero)**: es la pieza de mayor riesgo. La transformación CSS
  es una aproximación en pantalla (Web Mercator no es perfectamente conforme a gran escala), pero
  para correcciones locales pequeñas el error visual es despreciable. Se valida en la primera
  iteración con un caso de traslación+rotación conocido. La previsualización es **solo visual**;
  la georreferenciación real la produce el pipeline de D5.
- **Alternativas descartadas**: re-tilear en servidor por cada arrastre (lento, rompe SC-002);
  `ImageOverlay`/`L.ImageOverlay.Rotated` (una imagen estática, sin tiles ni zoom nativo);
  librería frontend nueva de rotación de tiles (dependencia nueva, viola YAGNI y Principio IV).

## D4 — Aplicar: pipeline de corrección de rásteres (worker, GDAL)

- **Decisión**: para cada producto ráster 2D disponible (`orthophoto.tif`, `dsm.tif`,
  `dtm.tif`), ejecutar de forma **asíncrona en el worker** (`run_function_async`, patrón viewshed):
  1. Componer la nueva geotransformación afín: `GT_new = S ∘ GT_orig`, donde `S` es la similitud
     ajustada en el CRS de la tarea (bakea traslación+rotación+escala como geotransform rotado,
     **sin remuestrear**).
  2. `gdalwarp` del ráster con geotransform rotado a un **COG north-up** (driver `COG`,
     remuestreo `bilinear` para ortofoto, `near` para DEM), escrito en el directorio persistente
     del plugin.
  - El cálculo **siempre parte del asset original** de la tarea (FR-010, sin acumulación).
- **Rationale**: el geotransform de un GeoTIFF admite rotación (coeficientes GT[2]/GT[4]), así que
  la similitud se representa exactamente; el `gdalwarp` final devuelve un COG north-up estándar que
  el tiler (rio-tiler `COGReader`) y las descargas consumen sin sorpresas. GDAL CLI y el driver COG
  están en la imagen (`docs/entorno-plugins.md`) → **cero dependencias nuevas**. El patrón de
  `subprocess` a binarios GDAL ya existe en `coreplugins/viewshed/api.py`.
- **Alternativas descartadas**: reescribir solo el geotransform sin `gdalwarp` (deja un COG con
  geotransform rotado que algunos consumidores no manejan bien); `gdalwarp` con GCPs/`-tps` (haría
  un ajuste afín/TPS, no la similitud que fija la spec); reproyectar vía rasterio en Python puro
  (equivalente pero reimplementa lo que el CLI ya hace bien).

## D5 — Mostrar y descargar los productos corregidos sin tocar el core

- **Decisión**: el plugin **sirve sus propios tiles y descargas** de los productos corregidos:
  - `GET .../realign/task/<pk>/tiles/<type>/<z>/<x>/<y>.png` — render con rio-tiler `COGReader`
    sobre el COG corregido en el directorio persistente (mismo `rescale` por defecto que el core:
    ortofoto `0,255`, DEM `0,1000`).
  - `GET .../realign/task/<pk>/tilejson/<type>` — TileJSON con bounds leídos del COG corregido.
  - `GET .../realign/task/<pk>/download/<type>` — descarga del `.tif` corregido.
  - En estado **aplicado**, el frontend del plugin sustituye en el mapa la capa del core por la
    capa de tiles del plugin (y ofrece la descarga corregida); en **revertido**, restaura la capa
    original del core.
- **Rationale**: el tiler del core resuelve siempre `task.get_asset_download_path("<type>.tif")`
  (verificado en `app/api/tiler.py: get_raster_path`) y sus bounds vienen de `task.*_extent` (BD);
  el plugin no puede cambiar eso sin editar el core (Principio I). Servir los corregidos desde el
  plugin mantiene el core intacto y no es destructivo. rio-tiler ya está en la imagen; el core usa
  el mismo `COGReader` (`app/api/tiler.py`), así que el render es consistente.
- **Alternativas descartadas**: sobrescribir los assets de la tarea (destructivo, viola FR-009 y
  toca archivos gestionados por el core); actualizar `task.*_extent` en BD (edita el modelo del
  core, Principio I); renderizar el COG en el cliente con `georaster-layer-for-leaflet`
  (dependencia frontend nueva).

## D6 — Persistencia del estado por tarea

- **Decisión**: `GlobalDataStore` del plugin (namespace `realign`) con key `task_<pk>` y
  `set_json`/`get_json` (modelo `PluginDatum.json_value`). Guarda: lista de pares de puntos
  (origen y destino en lat/lng + proyectados), parámetros de la transformación, residuos y RMSE,
  estado (`previewing`/`applied`/`reverted`), rutas de los productos corregidos, productos
  afectados y marca de tiempo/usuario.
- **Rationale**: `GlobalDataStore` (user=None) hace el estado visible para **todos** los usuarios
  con acceso a la tarea (FR-012), a diferencia de `UserDataStore`. La clave por `pk` da un estado
  por tarea. Es el mecanismo del framework para datos persistentes (Principio: `plugin_data_store`);
  verificado en `app/plugins/data_store.py` y `plugin_base.get_global_data_store()`.
- **Alternativas descartadas**: `UserDataStore` (no compartiría entre usuarios); un modelo Django
  propio con migración (añade migraciones al fork; innecesario, `PluginDatum` basta); guardar solo
  en archivos (perdería consultabilidad y atomicidad del estado).

## D7 — Permisos

- **Decisión**: lectura/previsualización usa el `get_and_check_task` estándar (permiso de vista).
  **Aplicar** y **Revertir** (y guardar el estado) exigen
  `check_project_perms(request, task.project, ('change_project',))`.
- **Rationale**: es exactamente el patrón que usa el core para operaciones de escritura sobre
  tareas (verificado en `app/api/tasks.py`, múltiples usos de `('change_project',)`), y satisface
  FR-014 sin inventar un modelo de permisos nuevo.
- **Alternativas descartadas**: sin control (viola FR-014); object-level permissions por tarea (el
  core usa permisos a nivel de proyecto; seguir esa convención).

## D8 — Diseño abierto a la nube de puntos (FR-017)

- **Decisión**: representar la transformación como una entidad independiente del tipo de dato
  (parámetros de similitud + CRS de referencia) en `transform.py`/`store.py`, separada del pipeline
  de rásteres (`corrections.py`). El estado persistido lista "productos afectados" de forma
  genérica.
- **Rationale**: una etapa futura aplicará la misma similitud a `georeferenced_model.laz` (p. ej.
  con el CLI `pdal` por `subprocess`, ya en la imagen) reutilizando la transformación sin rehacer
  la UI ni la persistencia. Mantener la transformación desacoplada del ráster evita reescribir el
  núcleo del plugin en la fase 2.
- **Alternativas descartadas**: acoplar la transformación al pipeline ráster (obligaría a
  refactorizar al añadir la nube de puntos).

## Resumen de dependencias

**Nivel 0 de la escalera del Principio IV — cero dependencias nuevas.** GDAL 3.4 (CLI + driver
COG + bindings `osgeo`), `numpy` 1.26 y `rio-tiler` 2.1 ya están en la imagen compartida
webapp↔worker (`docs/entorno-plugins.md`). No se toca `requirements.txt` global ni el `Dockerfile`.
La verificación obligatoria del arranque del worker ejecutando el pipeline de corrección se
documenta en `quickstart.md`.
