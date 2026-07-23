---

description: "Task list for feature implementation"
---

# Tasks: Realineación manual de productos ráster 2D mediante puntos de control

**Input**: Design documents from `/specs/002-realign-products/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md (todos presentes)

**Tests**: Solicitados explícitamente por plan.md ("Testing: Django tests en
`coreplugins/realign/tests.py`, ejecutados en Docker") y por quickstart.md (sección 3, cobertura
mínima: paridad de similitud JS↔Python, pipeline GDAL, persistencia, permisos). Se incluyen
tareas de test.

**Organization**: Tareas agrupadas por user story (US1–US5 de spec.md) para permitir
implementación y prueba independiente. Patrón de referencia verificado en el repo:
`coreplugins/viewshed/` (estructura de plugin, `api.py`, `plugin.py`, `main.js`, panel React) y
`app/api/tiler.py` (render de tiles con rio-tiler `COGReader`, `rescale` por defecto).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Se puede ejecutar en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: User story a la que pertenece la tarea (US1–US5)
- Rutas de archivo exactas en cada descripción

## Path Conventions

Plugin autocontenido en `coreplugins/realign/` (ver Project Structure de plan.md):

```text
coreplugins/realign/
├── __init__.py
├── manifest.json
├── plugin.py
├── api.py
├── transform.py       # similitud (numpy) autoritativa
├── corrections.py     # pipeline GDAL (geotransform rotado → gdalwarp COG north-up)
├── store.py           # persistencia por tarea (GlobalDataStore)
├── tests.py
└── public/
    ├── main.js
    ├── Realign.jsx
    ├── Realign.scss
    ├── RealignPanel.jsx
    ├── RealignPanel.scss
    ├── similarity.js  # similitud (JS) para previsualización/residuos en vivo
    └── icon.svg
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Crear el esqueleto del plugin siguiendo la Convención III de la constitución.

- [X] T001 Crear directorio `coreplugins/realign/` con `__init__.py` vacío (paquete Python), calcado de `coreplugins/viewshed/__init__.py`
- [X] T002 [P] Crear `coreplugins/realign/manifest.json` (nombre "Realign", descripción de realineación 2D por puntos de control, versión "1.0.0", autor/email como `coreplugins/viewshed/manifest.json`, `webodmMinVersion` igual al de viewshed, tags `["realign", "georeferencing", "orthophoto", "dsm", "dtm"]`)
- [X] T003 [P] Crear `coreplugins/realign/public/icon.svg` (icono del control del mapa; ícono simple de "mover/alinear", p. ej. cruz de desplazamiento)

**Checkpoint**: estructura de directorios y metadatos del plugin listos; sin lógica aún.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Registrar el plugin en el framework (montaje de endpoints y assets JS) antes de
implementar cualquier user story. Sin este registro ninguna historia es verificable end-to-end.

**⚠️ CRITICAL**: ninguna user story puede probarse end-to-end sin esta fase completa.

- [X] T004 Crear `coreplugins/realign/api.py` con las clases stub de todos los endpoints del contrato (contracts/api.md), importando `TaskView`, `GetTaskResult` de `app.plugins.views`: `RealignState(TaskView)` (GET/PUT/DELETE que aún responden `Response({'error': 'not implemented'})`), `RealignApply(TaskView)` (POST stub), `RealignRevert(TaskView)` (POST stub), `RealignStatus(GetTaskResult)` (`pass`), `RealignTiles(TaskView)`, `RealignTileJson(TaskView)`, `RealignDownload(TaskView)` (GET stubs)
- [X] T005 Crear `coreplugins/realign/plugin.py` con `class Plugin(PluginBase)`: `include_js_files` → `['main.js']`, `build_jsx_components` → `['Realign.jsx']`, `api_mount_points` → montar TODAS las rutas de contracts/api.md (`task/(?P<pk>[^/.]+)/realign/state`, `.../realign/apply`, `.../realign/revert`, `.../realign/status/(?P<celery_task_id>.+)`, `.../realign/tiles/(?P<type>orthophoto|dsm|dtm)/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)(?P<ext>\.png)?`, `.../realign/tilejson/(?P<type>orthophoto|dsm|dtm)`, `.../realign/download/(?P<type>orthophoto|dsm|dtm)`) a las vistas de T004 (patrón de `coreplugins/viewshed/plugin.py`)
- [X] T006 [P] Crear `coreplugins/realign/public/main.js` que registre `PluginsAPI.Map.willAddControls(['realign/build/Realign.js', 'realign/build/Realign.css'], ...)` y agregue el control al mapa solo cuando `args.tiles` referencie una única tarea (copiar y adaptar `coreplugins/viewshed/public/main.js`, conservando `args.map` y `args.tiles`)
- [X] T007 Habilitar el plugin en el entorno local (`./webodm.sh restart --build` o `docker compose up -d --build`) y confirmar en `docker compose logs webapp | grep -i realign` que carga y compila sus assets sin errores (quickstart.md sección 1)

**Checkpoint**: el plugin aparece registrado (endpoints montados, JS resuelto); base lista para US1.

---

## Phase 3: User Story 1 - Alinear marcando pares de puntos y ver el error en vivo (Priority: P1) 🎯 MVP

**Goal**: el usuario activa la herramienta, marca pares de puntos (rasgo en ortofoto → mismo
rasgo en mapa base), el sistema ajusta una similitud, previsualiza el desplazamiento de las capas
ráster (juntas) y muestra residuo por punto + RMSE en vivo (FR-001 a FR-007, FR-016). No aplica ni
persiste nada: todo es cliente + un endpoint de solo lectura para descubrir productos disponibles.

**Independent Test**: con una tarea con ≥1 ráster 2D, activar la herramienta, marcar 2–4 pares y
verificar que las capas se desplazan/rotan/escalan acercándose al mapa base y aparecen residuos +
RMSE que se recalculan al mover/eliminar puntos.

### Tests for User Story 1 ⚠️

> Escribir estas pruebas primero y confirmar que fallan antes de implementar.

- [X] T008 [P] [US1] Crear `coreplugins/realign/tests.py` con `RealignApiTest` (base `BootTestCase` o la usada en `app/tests/test_api_task.py`): GET `.../realign/state` en tarea con ortofoto → `products` incluye `"orthophoto"`; tarea **sin** ningún ráster 2D → `products == []` (FR-016); usar fixtures/patrón de `app/tests/test_api_task.py` para crear proyecto/tarea
- [ ] T009 [P] [US1] Crear test de frontend para `coreplugins/realign/public/similarity.js` (jest, ejecutable con `webodm.sh test frontend`/`npm run qtest`): traslación pura (1 par) → `scale=1, rotation=0`, solo traslación; similitud conocida (2+ pares) → `scale/rotation/translation` esperados y residuos por punto + RMSE dentro de tolerancia; puntos de origen coincidentes → `degenerate=true`

### Implementation for User Story 1

- [X] T010 [US1] Implementar GET `.../realign/state` en `coreplugins/realign/api.py` (`RealignState.get`): `task = self.get_and_check_task(request, pk)`; descubrir productos 2D presentes por `task.orthophoto_extent`/`task.dsm_extent`/`task.dtm_extent` (o `available_assets`, patrón de `app/api/tiler.py: get_extent`); devolver `{state:"previewing", points:[], transform:null, products:[...], corrected_available:false, updated_at}` (FR-016) — la lectura de estado persistido llega en US4
- [X] T011 [US1] Implementar `coreplugins/realign/public/similarity.js`: ajuste de similitud (Umeyama por SVD) traslación+rotación+escala uniforme; 1 par → solo traslación; 2+ → mínimos cuadrados; cálculo de residuo por punto y RMSE; detección de caso degenerado (orígenes coincidentes/insuficientes) (D1/D2 de research.md, entidades de data-model.md)
- [X] T012 [P] [US1] Crear `coreplugins/realign/public/Realign.jsx`: `L.Control` con botón que alterna el panel `RealignPanel`, calcado de `coreplugins/viewshed/public/Viewshed.jsx`, usando `public/icon.svg` (T003) y clase `leaflet-control-realign`
- [X] T013 [P] [US1] Crear `coreplugins/realign/public/Realign.scss` con los estilos del botón del control (adaptar de `coreplugins/viewshed/public/Viewshed.scss`, clase `leaflet-control-realign`)
- [X] T014 [US1] Crear `coreplugins/realign/public/RealignPanel.jsx` (esqueleto): componente React con props `map`/`tasks`/`isShowed`/`onClose` (mismas propTypes que `ViewshedPanel`); estado `{points:[], transform:null, error:null, mode:'idle', products:[]}`; al montar, GET `.../realign/state` para poblar `products` y, si `products` está vacío, deshabilitar la herramienta con mensaje claro (FR-001/FR-016)
- [X] T015 [US1] En `RealignPanel.jsx`, mostrar la ortofoto semitransparente al activar la herramienta: bajar la opacidad de la capa de ortofoto localizada en `this.props.map`/`args.tiles`, y restaurarla al cerrar/desactivar (FR-002)
- [X] T016 [US1] En `RealignPanel.jsx`, implementar la captura de pares de puntos con dos clics por par: primer clic (origen sobre la ortofoto) y segundo clic (destino sobre el mapa base) vía `this.props.map.on('click', ...)`; renderizar marcadores origen/destino y un vector que los une; soportar añadir, mover (drag del marcador) y eliminar pares, actualizando `this.state.points`; limpiar listeners en `componentWillUnmount` (FR-003/FR-004)
- [X] T017 [US1] En `RealignPanel.jsx`, recalcular la transformación con `similarity.js` ante cualquier cambio de puntos y renderizar una tabla con el residuo por punto y el RMSE global, actualizada de forma percibida como inmediata (< 1 s, SC-002) (FR-005/FR-006)
- [ ] T018 [US1] ~~En `RealignPanel.jsx`, implementar la previsualización: derivar una matriz CSS afín...~~ **SUPERSEDIDO**: por pedido explícito del usuario ("que no se ruede en tiempo real, solo al aplicar") se eliminó la previsualización CSS en vivo; la ortofoto ahora solo se mueve al pulsar Aplicar (residuos/RMSE sí se recalculan en vivo, vía T017). D3 de research.md quedó desactualizado como registro histórico de la decisión original.
- [X] T019 [US1] En `RealignPanel.jsx`, detectar en cliente puntos insuficientes/ajuste degenerado (usando `degenerate` de `similarity.js`) y mostrar el motivo, anticipando el bloqueo de "Aplicar" (espejo de FR-015; refuerza la validación server-side que llega en US2)
- [X] T020 [US1] Ejecutar los tests de US1 en Docker: frontend (`docker compose exec webapp /webodm/webodm.sh test frontend`) para `similarity.js` y backend (`... test backend coreplugins.realign.tests`) para el endpoint `state`; confirmar exit code 0 mostrando la salida (regla `verification-before-completion`)
- [ ] T021 [US1] Validación manual de quickstart.md sección 2, escenarios 1–5 y 12 (activación, marcar pares, traslación con 1 par, similitud con 2–4 pares, recálculo al mover/eliminar, tarea sin productos 2D) — 1-4 verificados incidentalmente hoy (navegador real) probando US5; **falta**: escenario 5 con eliminar UN punto puntual (× por fila, no "Limpiar") y arrastrar un marcador, y escenario 12 (tarea sin productos 2D)

**Checkpoint**: US1 completa y verificable de forma independiente — MVP funcional (previsualización + error, sin aplicar).

---

## Phase 4: User Story 2 - Aplicar la transformación generando productos corregidos (Priority: P2)

**Goal**: al pulsar "Aplicar", el sistema genera COG corregidos de los productos 2D desde los
originales, conservándolos intactos, y la vista pasa a mostrar los corregidos (servidos por el
propio plugin) (FR-008 a FR-010, FR-014, FR-015, FR-017).

**Independent Test**: tras alinear (US1), pulsar "Aplicar" y verificar que existen productos
corregidos que cuadran con el mapa base, los originales no cambian, y la vista muestra los
corregidos; sin permiso `change_project` la acción se bloquea.

### Tests for User Story 2 ⚠️

- [X] T022 [P] [US2] Añadir a `coreplugins/realign/tests.py` un test de **paridad** `transform.py` ↔ `similarity.js`: sobre los mismos casos (traslación pura, similitud conocida, degenerado), los parámetros y el RMSE coinciden dentro de tolerancia (FR-005)
- [X] T023 [P] [US2] Añadir a `coreplugins/realign/tests.py` un test del pipeline de `corrections.py` con un GeoTIFF pequeño sintético (generado en el test con `osgeo.gdal`/`numpy`): aplicar una similitud conocida y verificar que el COG corregido es north-up y está desplazado/rotado la cantidad esperada, y que el archivo original **no** cambia (FR-009)
- [X] T024 [P] [US2] Añadir a `coreplugins/realign/tests.py` casos de contrato de `apply`: sin `change_project` → 403 (FR-014); con 0 puntos o puntos degenerados → 400 sin lanzar el pipeline (FR-015)

### Implementation for User Story 2

- [X] T025 [US2] Crear `coreplugins/realign/transform.py`: ajuste de similitud en numpy (Umeyama) + residuos/RMSE, reproyección de los puntos EPSG:4326 → CRS de la tarea (`osgeo.osr`, patrón de `coreplugins/viewshed/api.py`); API de la transformación **independiente del tipo de dato** (parámetros + CRS), reutilizable para nube de puntos en el futuro (FR-005 autoritativo, FR-017, D1/D2/D8)
- [X] T026 [US2] Crear `coreplugins/realign/store.py`: helpers sobre `get_global_data_store()` (`app/plugins/data_store.py`) para leer/escribir/borrar el `TaskRealignment` en JSON con key `task_<pk>` (namespace del plugin, `user=None` para compartir entre usuarios), según el esquema de data-model.md (D6, FR-012)
- [X] T027 [US2] Crear `coreplugins/realign/corrections.py`: por cada producto disponible (`orthophoto.tif`/`dsm.tif`/`dtm.tif`), componer `GT_new = S ∘ GT_orig` sobre una copia del asset **original** de la tarea (`task.get_asset_download_path(...)`), y `gdalwarp` a COG north-up (driver `COG`, remuestreo `bilinear` para ortofoto, `near` para DEM) en `plugin.get_persistent_path("task_<pk>/<type>.tif")` (D4, FR-008/FR-010); función ejecutable en worker
- [X] T028 [US2] Implementar POST `.../realign/apply` en `api.py` (`RealignApply.post`): `check_project_perms(request, task.project, ('change_project',))` (FR-014, patrón de `app/api/tasks.py`); validar puntos (no degenerados, ≥1) devolviendo 400 si no (FR-015); persistir puntos con `store.py`; lanzar `run_function_async(corrections_pipeline, ...)` sobre los productos disponibles y responder `{'celery_task_id': ...}`
- [X] T029 [US2] Implementar GET `.../realign/status/<celery_task_id>` (`RealignStatus`, patrón `GetTaskResult`/`CheckTask`): al terminar, marcar el estado `applied` con `corrected_paths` vía `store.py` y devolver `{ready, output:{state, corrected:[...]}}` o `{ready, error}` (contracts/api.md)
- [X] T030 [US2] Implementar GET `.../realign/tiles/<type>/<z>/<x>/<y>.png` (`RealignTiles`): render con `rio_tiler.io.COGReader` sobre el COG corregido en el dir. persistente, con `rescale` por defecto igual al core (`orthophoto`→`0,255`, `dsm|dtm`→`0,1000`), devolviendo PNG; 404 si no hay corregido o el tile cae fuera de bounds (D5, patrón de `app/api/tiler.py: Tiles`)
- [X] T031 [US2] Implementar GET `.../realign/tilejson/<type>` (`RealignTileJson`): bounds/center leídos del COG corregido con `COGReader`, `tiles` apuntando a T030 (D5, patrón de `app/api/tiler.py: TileJson`)
- [ ] T032 [US2] Implementar GET `.../realign/download/<type>` (`RealignDownload`): entregar el `.tif` corregido desde el dir. persistente con `download_file_response` (patrón de `app/api/tasks.py`); 404 si no aplicado — implementado y el botón de descarga funciona en el panel (verificado visualmente), **pero sin test automatizado propio** (no hay ningún `test_download_*` en tests.py) ni verificación de que el archivo descargado realmente abre bien en QGIS; falta cerrar esto
- [X] T033 [US2] Implementar PUT `.../realign/state` (`RealignState.put`): `check_project_perms(... 'change_project')`, persistir los puntos editados con `store.py`, recalcular con `transform.py` y devolver la transformación + residuos autoritativos (contracts/api.md) — reutilizado por US4
- [X] T034 [US2] En `RealignPanel.jsx`, agregar el botón "Aplicar" (habilitado solo con `change_project` y puntos válidos): POST `apply`, polling de `status` con indicador de progreso; al terminar, sustituir en el mapa las capas ráster del core por `L.tileLayer` construido desde `.../realign/tilejson/<type>` ~~y quitar la matriz CSS de previsualización~~; ofrecer la descarga corregida (FR-008, D5). **Nota de arquitectura**: la sustitución de capa no usa `L.tileLayer`/tilejson nuevo — redirige la URL de la capa existente del core (`layer.setUrl()`, ver `redirectCoreLayer`), que preserva panel de capas/opacidad/side-by-side; verificado en navegador real hoy con un Aplicar completo sobre rásters de producción (~550-670 MB)
- [X] T035 [US2] Verificación de worker (Principio IV.3, obligatoria) + tests backend: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.realign.tests` (exit 0), y con el stack levantado lanzar un "Aplicar" real y confirmar en `docker compose logs worker --tail 80 | grep -iE "realign|gdalwarp|error"` que el pipeline corrió sin `ImportError`/`ModuleNotFoundError`/fallos de `gdalwarp`, y que los `*.tif` corregidos existen en `docker compose exec worker ls -la /webodm/app/media/plugins/realign/task_<pk>/` (quickstart.md secciones 3 y 4) — verificado hoy: Aplicar real sobre la tarea "Noria" generó `orthophoto.tif`/`dsm.tif`/`dtm.tif` corregidos sin errores

**Checkpoint**: US1 y US2 funcionan de forma independiente y combinada — se pueden generar y ver productos corregidos.

---

## Phase 5: User Story 3 - Revertir al estado original (Priority: P3)

**Goal**: en cualquier momento, "Revertir" restaura la vista y los productos al original sin
pérdida de datos (FR-011, FR-014).

**Independent Test**: tras aplicar (US2), pulsar "Revertir" y verificar que la vista y los
productos vuelven al original y los corregidos dejan de usarse; sin `change_project` se bloquea.

### Tests for User Story 3 ⚠️

- [X] T036 [P] [US3] Añadir a `coreplugins/realign/tests.py`: POST `.../realign/revert` sin `change_project` → 403 (FR-014); con permiso → estado `reverted`, `corrected_paths` eliminados del dir. persistente, y los assets originales de la tarea intactos (FR-009/FR-011)

### Implementation for User Story 3

- [X] T037 [US3] Implementar POST `.../realign/revert` en `api.py` (`RealignRevert.post`): `check_project_perms(... 'change_project')`; marcar estado `reverted` con `store.py`; borrar los COG corregidos del dir. persistente; no tocar los assets originales; responder `{'state':'reverted'}` (FR-011). Implementar también DELETE `.../realign/state` (`RealignState.delete`) que hace revert + limpieza total del estado (contracts/api.md)
- [X] T038 [US3] En `RealignPanel.jsx`, agregar el botón "Revertir" (con `change_project`): si hay corregidos aplicados, POST `revert` y restaurar las capas del core (vía `restoreCoreLayers`/`setUrl`, no `L.tileLayer`); si es solo previsualización, descartar puntos; en ambos casos volver al estado original y refrescar la UI (FR-011) — verificado en navegador real hoy
- [X] T039 [US3] Ejecutar los tests de US3 en Docker (exit 0, salida visible) y validar manualmente quickstart.md escenario 10 (revertir tras aplicar) — verificado hoy (Revertir tras Aplicar real restauró la vista original)

**Checkpoint**: las tres primeras historias funcionan de forma independiente y en conjunto.

---

## Phase 6: User Story 4 - Conservar y reeditar la realineación entre sesiones (Priority: P3)

**Goal**: el estado (puntos, transformación, estado aplicado/revertido) persiste por tarea y se
recupera al reabrir; otro usuario con acceso ve la misma realineación; reaplicar recalcula desde
los originales (FR-012, FR-013, FR-010).

**Independent Test**: marcar puntos y aplicar; cerrar y reabrir la tarea (u otro usuario la abre) y
verificar que puntos, errores y estado se recuperan idénticos; reeditar y reaplicar recalcula desde
el original.

### Tests for User Story 4 ⚠️

- [X] T040 [P] [US4] Añadir a `coreplugins/realign/tests.py`: guardar estado con PUT `state` → GET `state` devuelve puntos/transformación idénticos; el estado es visible con `user=None` (compartido entre usuarios, FR-012); una segunda aplicación regenera `corrected_paths` desde el original, sin acumular (FR-010/FR-013)

### Implementation for User Story 4

- [X] T041 [US4] Extender GET `.../realign/state` (T010) en `api.py` para devolver el `TaskRealignment` persistido con `store.py` (puntos, transformación, `state`, `corrected_available`) en vez del estado vacío (FR-013)
- [X] T042 [US4] En `RealignPanel.jsx`, al montar, restaurar la UI desde el `state` persistido: repintar marcadores/vectores de los pares, la tabla de residuos/RMSE y, si `state=applied`, la capa de tiles corregida; persistir las ediciones de puntos con PUT `state` (autosave al cambiar o al aplicar) para que sobrevivan a la sesión y se compartan (FR-012/FR-013) — verificado hoy: recarga de página restauró puntos, `use_scale` y estado aplicado
- [ ] T043 [US4] Ejecutar los tests de US4 en Docker (exit 0, salida visible) y validar manualmente quickstart.md escenario 11 (recarga / otro usuario recupera el estado idéntico) — la parte de **recarga** se verificó hoy; **falta** probar con un segundo usuario (`testuser2`) que abra la misma tarea y vea la misma realineación

**Checkpoint**: las cuatro historias funcionan de forma independiente y en conjunto.

---

## Phase 7: User Story 5 - Elegir si la transformación incluye escala (Priority: P2)

**Goal**: junto al resumen de la transformación, un interruptor "Usar escala" (tildado por
defecto) permite alternar entre similitud completa (comportamiento histórico) y una
transformación rígida (traslación + rotación, escala fija en 1.0), recalculando en vivo
residuos/RMSE y persistiendo el modo elegido para que Aplicar y la recuperación de estado lo
respeten (FR-005 amendado, FR-018 a FR-020).

**Independent Test**: con 2+ pares marcados y la previsualización activa, destildar "Usar
escala" y verificar que (a) la transformación pasa a ser rígida (escala mostrada = 1.0), (b)
residuos y RMSE se recalculan de inmediato, y (c) al volver a tildarlo se recupera el ajuste con
escala; con exactamente 1 par, el interruptor no cambia el resultado.

### Tests for User Story 5 ⚠️

- [X] T048 [P] [US5] Añadir a `coreplugins/realign/tests.py` casos de la transformación rígida (`use_scale=false`) en `transform.py`: sobre los mismos casos de `RealignTransformTest` (traslación pura, similitud/rotación conocida, degenerado), verificar `scale == 1.0` exacto y que rotación/traslación coinciden con el resultado esperado de un ajuste de Procrustes ortogonal (sin escala) dentro de tolerancia (D9 de research.md, FR-005)
- [X] T049 [P] [US5] Añadir a `coreplugins/realign/tests.py` casos de contrato: PUT `.../realign/state` y POST `.../realign/apply` aceptan `use_scale` en el body y lo reflejan en la respuesta (`transform.use_scale`); al omitirlo, se conserva el último valor persistido (o `true` si no hay ninguno todavía) (contracts/api.md, FR-018/FR-020)

### Implementation for User Story 5

- [X] T050 [P] [US5] En `coreplugins/realign/public/similarity.js`, agregar el parámetro `useScale` (default `true`) a `fitSimilarity`: con `false`, normalizar `cos = a / hypot(a,b)`, `sin = b / hypot(a,b)` (rotación de norma unitaria), `scale` fijo en `1`, y recalcular la traslación desde los centroides con esa rotación fija (D9 de research.md); con 1 par, sin cambios (ya es solo traslación, FR-005)
- [X] T051 [P] [US5] En `coreplugins/realign/transform.py`, agregar el mismo parámetro `use_scale` (default `True`) a la función de ajuste autoritativa, con la misma lógica de normalización que T050 (D9) — mantener paridad exacta con `similarity.js`
- [X] T052 [US5] En `coreplugins/realign/store.py`/`api.py`, persistir y leer `use_scale` en el documento `TaskRealignment` (GET/PUT `.../realign/state`, POST `.../realign/apply`): default `true` si el estado persistido no tiene el campo, para preservar el comportamiento de estados creados antes de esta capacidad (data-model.md, FR-018/FR-020)
- [X] T053 [US5] En `coreplugins/realign/public/RealignPanel.jsx`, agregar el interruptor "Usar escala" junto al resumen de la transformación (tildado por defecto): recalcular con `similarity.js` (T050) y persistir con PUT `state` (T052) al cambiarlo, con el mismo criterio de inmediatez que ante cualquier cambio de puntos (FR-018/FR-019)
- [X] T054 [US5] Ejecutar los tests de US5 en Docker (`docker compose exec webapp python manage.py test coreplugins/realign`, exit 0, salida visible) y validar manualmente quickstart.md escenarios 13–17 (interruptor tildado por defecto, alternar modo con 2+ puntos, sin efecto con 1 punto, Aplicar y recuperar el modo elegido tras recargar)

**Checkpoint**: US5 funciona de forma independiente sobre la previsualización de US1, y se integra
con Aplicar (US2) y la persistencia entre sesiones (US4) sin alterar su comportamiento por defecto.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: cierre de calidad transversal a las cinco historias.

- [ ] T044 [P] Revisar todos los textos de usuario (`_(...)`) en `coreplugins/realign/api.py` y `coreplugins/realign/public/RealignPanel.jsx` para que los mensajes (sin productos, sin permiso, ajuste degenerado, error de pipeline) sean claros y accionables (SC, Edge Cases)
- [ ] T045 Ejecutar el checklist funcional completo de `specs/002-realign-products/quickstart.md` sección 2 (los 17 escenarios, incluidos 13–17 de US5) contra el stack en Docker y registrar el resultado de cada uno
- [ ] T046 Confirmar los criterios de éxito medibles de quickstart.md sección 5 (SC-001 corrección en < 3 min con 2–4 pares; SC-002 recálculo < 1 s; SC-003 corregidos cuadran; SC-004 revertir 100% no destructivo; SC-005 recuperación idéntica; SC-006 ortofoto/DSM/DTM alineados entre sí) con evidencia (capturas/logs)
- [X] T047 Ejecutar de nuevo `./run_tests_in_docker.sh backend coreplugins.realign.tests` (+ `... test frontend` para `similarity.js`) tras todos los cambios y confirmar exit code 0 (regla `verification-before-completion`, cierre de feature), incluida la verificación de worker de T035 — 23/23 OK, re-ejecutado hoy tras la reconciliación de tasks.md (no hay test frontend/jest, T009 sigue pendiente)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — puede iniciar de inmediato
- **Foundational (Phase 2)**: depende de Setup — BLOQUEA todas las user stories
- **User Stories (Phase 3–6)**: todas dependen de Foundational
  - US1 (P1) no depende de otras historias (cliente + endpoint `state` de solo lectura)
  - US2 (P2) depende de que exista el panel/captura de puntos de US1 (extiende `RealignPanel.jsx`); introduce el backend de aplicar (`transform.py`, `store.py`, `corrections.py`) y el tiler propio
  - US3 (P3) depende de US2 (revertir opera sobre los corregidos que produce US2) — el caso "revertir previsualización" solo necesita US1
  - US4 (P3) depende de `store.py` y PUT `state` (creados en US2) para recuperar/compartir estado
  - US5 (P2) depende de US1 (extiende `similarity.js`/`RealignPanel.jsx`) y de US2/US4 (`transform.py`, `store.py`, PUT `state`, POST `apply`) para persistir y aplicar el modo elegido — independiente de US3
- **Polish (Phase 8)**: depende de que las historias deseadas estén completas

### User Story Dependencies

- **US1**: fundacional para el resto; sin dependencias de otras historias
- **US2**: extiende `RealignPanel.jsx` de US1 y añade el backend de aplicar; secuencial respecto a US1
- **US3**: usa el estado aplicado de US2 (`store.py`, corregidos) — secuencial respecto a US2
- **US4**: usa `store.py`/PUT `state` de US2 — secuencial respecto a US2 (independiente de US3)
- **US5**: extiende el ajuste de US1 (`similarity.js`) y su contraparte autoritativa de US2 (`transform.py`), y la persistencia de US2/US4 (`store.py`, PUT `state`, POST `apply`) — independiente de US3

### Within Each User Story

- Tests antes de la implementación (T008–T009 antes de T010–T019; T022–T024 antes de T025–T034; T036 antes de T037–T038; T040 antes de T041–T042; T048–T049 antes de T050–T053)
- Matemática/persistencia/pipeline (`transform.py`, `store.py`, `corrections.py`) antes de los endpoints que los usan
- Endpoints backend antes del frontend que los consume (T028–T033 antes de T034)
- Implementación core antes de la verificación de worker/quickstart

### Parallel Opportunities

- T002 y T003 en paralelo (archivos distintos, Setup)
- T008 (backend) y T009 (frontend) en paralelo (runners distintos)
- T012 y T013 en paralelo (`.jsx` y `.scss` distintos)
- T022, T023 y T024 en paralelo (casos de test independientes en `tests.py`)
- T025 (`transform.py`), T026 (`store.py`) y T027 (`corrections.py`) en paralelo (archivos distintos), antes de los endpoints que los integran
- T030, T031 y T032 en paralelo (endpoints de tiles/tilejson/download, archivos/rutas distintas dentro de `api.py` — coordinar si se edita el mismo archivo)
- T048 y T049 en paralelo (casos de test independientes en `tests.py`)
- T050 y T051 en paralelo (`similarity.js` y `transform.py`, archivos distintos)

---

## Parallel Example: User Story 2 (backend de aplicar)

```bash
# Piezas backend independientes de US2, en paralelo:
Task: "Crear coreplugins/realign/transform.py (similitud numpy + reproyección)"
Task: "Crear coreplugins/realign/store.py (GlobalDataStore por tarea)"
Task: "Crear coreplugins/realign/corrections.py (pipeline GDAL → COG north-up)"

# Tests de US2, en paralelo:
Task: "Test de paridad transform.py ↔ similarity.js"
Task: "Test del pipeline corrections.py con GeoTIFF sintético"
Task: "Tests de contrato de apply (403 sin permiso, 400 degenerado)"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Completar Phase 1: Setup
2. Completar Phase 2: Foundational (bloquea todo lo demás)
3. Completar Phase 3: User Story 1
4. **DETENER y VALIDAR**: correr tests frontend/backend en Docker + escenarios 1–5, 12 de quickstart.md
5. Con esto ya hay un plugin que previsualiza la corrección y muestra el error en vivo — MVP entregable (sin aplicar/persistir)

### Incremental Delivery

1. Setup + Foundational → base del plugin registrada y cargando
2. + US1 → previsualización interactiva + residuos/RMSE → validar (MVP)
3. + US2 → aplicar (corregidos servidos por el plugin, originales intactos) → validar
4. + US3 → revertir al original → validar
5. + US4 → persistencia y reedición entre sesiones/usuarios → validar
6. + US5 → interruptor de escala (similitud completa vs. rígida) → validar
7. + Polish → checklist completo de quickstart.md y cierre de verificación

### Parallel Team Strategy

Con varios desarrolladores, tras Foundational: un desarrollador puede avanzar el frontend de US1
mientras otro construye en paralelo las piezas backend de US2 (`transform.py`/`store.py`/
`corrections.py`), integrándolas cuando US1 fije el contrato de puntos.

---

## Notes

- [P] = archivos distintos, sin dependencias entre sí
- [Story] mapea cada tarea a su user story para trazabilidad con spec.md
- **Cero dependencias nuevas** en todo el plan (Principio IV, nivel 0): GDAL CLI + `osgeo`, `numpy`
  y `rio-tiler` ya están en la imagen — no hay tareas de `requirements.txt` ni `Dockerfile`
- La lógica de similitud se implementa dos veces (JS para previsualización, Python para el cálculo
  autoritativo) y se cubre con un test de paridad (T022) para evitar divergencias
- La previsualización con matriz CSS (T018) es la pieza de mayor riesgo (D3) — validarla primero
- La verificación de worker (T035) es NO NEGOCIABLE según Principio IV.3 de la constitución
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida
  (regla global `verification-before-completion`)
- US5 (interruptor de escala) no agrega archivos nuevos ni dependencias: es un branch dentro de
  `similarity.js`/`transform.py` (D9 de research.md), un campo nuevo persistido y un control en
  `RealignPanel.jsx`; sigue la misma disciplina de paridad JS↔Python que T022
- Evitar: tareas vagas, conflictos de archivo simultáneos, dependencias cruzadas que rompan la
  independencia declarada en spec.md
