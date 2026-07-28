---

description: "Task list for 005-road-metrics"
---

# Tasks: características geométricas de caminos (`road`)

**Input**: Design documents from `/specs/005-road-metrics/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **SÍ se incluyen**. No es una preferencia: la constitución del fork exige que ninguna
tarea se marque completa sin ejecutar el comando que la verifica, y [research.md D16](./research.md)
fija la estrategia de prueba de esta feature. La detección de bordes es la parte que puede
equivocarse en silencio y se prueba de forma exacta con perfiles sintéticos.

**Organization**: agrupadas por historia de usuario, en orden de prioridad, para que cada una sea
implementable y verificable por separado.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia a la que pertenece (US1–US5)
- Cada tarea indica su archivo exacto

## Path Conventions

Plugin de WebODM: todo cuelga de `coreplugins/road/` (backend en la raíz del paquete, frontend en
`public/`, tests en `tests/`), según la estructura fijada en [plan.md](./plan.md). El único archivo
fuera del plugin es la ampliación de `coreplugins/realign/` (US5).

**Decisión de estructura de tests**: a diferencia de `annotations` y `realign`, que usan un
`tests.py` plano de ~1.000 líneas, `road` usa un **paquete** `coreplugins/road/tests/`. Esta feature
tiene más superficie a cubrir y los módulos separados permiten trabajar en varios en paralelo. La
etiqueta de ejecución no cambia: `webodm.sh test backend coreplugins.road.tests`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: que el plugin exista, cargue y sea desplegable antes de escribir lógica.

- [X] T001 Crear el paquete del plugin: `coreplugins/road/__init__.py` (vacío pero **imprescindible**: sin él el paquete no se importa y el plugin desaparece del listado sin error) y `coreplugins/road/manifest.json` con `name: "Road"`, `webodmMinVersion: "3.2.5"`, versión, autor y tags, siguiendo el formato de `coreplugins/annotations/manifest.json`
- [X] T002 Crear `coreplugins/road/plugin.py` con `class Plugin(PluginBase)`: `include_js_files() -> ['main.js']`, `build_jsx_components() -> ['Road.jsx']` y `api_mount_points()` vacío por ahora; más `coreplugins/road/public/main.js` y `coreplugins/road/public/icon.svg` mínimos para que el control se registre en el mapa
- [X] T003 [P] Crear el paquete de tests `coreplugins/road/tests/__init__.py` y verificar que el runner lo descubre: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests` debe ejecutar 0 tests **sin errores de importación** (si el paquete no se descubriera, pasar a `tests.py` plano como los plugins hermanos)
- [X] T004 [P] Crear `coreplugins/road/README.md` describiendo qué hace el plugin, sus rutas y cómo correr sus tests, siguiendo el formato de `coreplugins/annotations/README.md`
- [X] T005 Desplegar y comprobar la carga: `docker compose cp coreplugins/road webapp:/webodm/coreplugins/road && docker compose restart webapp`, y verificar con `get_plugin_by_name('road')` según [quickstart.md](./quickstart.md)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, acceso al DEM y matemática de perfiles. Todo esto lo consume US1 y lo
reutilizan las demás.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta que esta fase esté completa.

- [X] T006 Implementar `coreplugins/road/store.py`: `GlobalDataStore('road')` con clave `task_<pk>`, `get_document`/`set_document`, `document_lock` con advisory lock de PostgreSQL (copiar el patrón de `coreplugins/annotations/store.py`, cambiando la constante de namespace del lock), y las operaciones de índice `list_analyses`/`get_analysis`/`upsert_analysis`/`remove_analysis`, todas dentro del lock
- [X] T007 Añadir a `coreplugins/road/store.py` el candado de ejecución y el almacén de tramos: `acquire_running`/`release_running`/`get_running` comprobando y escribiendo **dentro** del mismo `document_lock` ([research.md D10](./research.md)), incluida la liberación del candado obsoleto cuando su `AsyncResult` ya está `ready()`; y `write_segments`/`read_segments`/`delete_segments` sobre `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json` con escritura atómica (temporal + `os.replace`)
- [X] T008 [P] Implementar `coreplugins/road/sources.py`: modelos disponibles por `task.dsm_extent`/`task.dtm_extent` sin tocar disco, modelo por defecto (DTM y si no DSM), ruta del ráster, resolución y factor a metros con `app.geoutils.get_rasterio_to_meters_factor`, unidad vertical, e `is_stale(task, analysis)` por comparación de `st_mtime` ([research.md D12](./research.md)). La variante `realigned` se añade en US5: aquí solo `original`
- [X] T009 [P] Implementar `coreplugins/road/geometry.py`: proyección de los vértices al CRS del DEM con `rasterio.warp.transform` (patrón de `annotations/geometry.py`), validación de vértices, longitud en planta, tramificación por progresiva conservando la longitud real del último tramo, punto medio de cada tramo y vector perpendicular unitario a su cuerda con lados izquierdo/derecho según el sentido de avance ([research.md D6](./research.md))
- [X] T010 [P] Implementar `coreplugins/road/profile.py`, **sin entrada/salida**: `detect_edges(distances, elevations, threshold, min_consecutive)` recorriendo cada lado desde el eje hacia afuera y devolviendo el borde o el motivo (`no_break` / `no_data`) ([research.md D3](./research.md)); `fit_grade(stations, elevations)` por mínimos cuadrados con numpy, en % y grados ([research.md D4](./research.md)); y `cross_slope(distances, elevations, left, right)` restringido a la calzada ([research.md D5](./research.md))
- [X] T011 Implementar `coreplugins/road/api.py` base: `TaskView` con `get_and_check_task`, helper de respuesta de error uniforme `{"error", "code"}` con los códigos de [contracts/rest-api.md](./contracts/rest-api.md), y la vista `GET task/<pk>/capabilities` (modelos, defectos, rangos, `annotations_available: false` de momento); registrar la ruta en `plugin.py` anclando el patrón con `$`
- [X] T012 [P] Implementar `coreplugins/road/signals.py`: receptor de `task_removed` que borra el documento del DataStore y el directorio de tramos de la tarea, e importarlo desde `plugin.py` con el comentario `# noqa: F401` (patrón de `annotations/signals.py`)
- [X] T013 Crear las fixtures compartidas de test en `coreplugins/road/tests/base.py`: clase base sobre `BootTestCase` que crea proyecto, tarea y permisos, y un generador de DEM sintético con `rasterio` en directorio temporal capaz de producir un camino de geometría conocida —calzada plana de ancho fijo, taludes a ambos lados, rampa de pendiente conocida y zonas `nodata`— reutilizando el enfoque de `coreplugins/annotations/tests.py`
- [X] T014 [P] Escribir `coreplugins/road/tests/test_profile.py` contra perfiles sintéticos en memoria: ancho exacto con taludes simétricos y asimétricos, borde en un solo lado, perfil sin quiebre (`no_break`), perfil truncado por `nodata` (`no_data`), pendiente longitudinal exacta sobre rampa conocida, pendiente resistente al ruido, y pendiente transversal con peralte conocido
- [X] T015 [P] Escribir `coreplugins/road/tests/test_geometry.py`: cobertura completa del eje sin huecos ni solapamientos, `station_end` de cada tramo igual al `station_start` del siguiente, último tramo con su longitud real, eje más corto que un tramo produce un único tramo, perpendicular correcta y lado izquierdo consistente con el sentido de trazado

**Checkpoint**: la matemática está probada de forma exacta y la persistencia funciona. Se puede
empezar cualquier historia.

---

## Phase 3: User Story 1 - Pendientes y anchos por tramo desde un eje ya trazado (Priority: P1) 🎯 MVP

**Goal**: elegir una polilínea 2D de la tarea, lanzar el análisis con los valores por defecto, verlo
progresar y obtener el camino dividido en tramos de 5 m coloreados por pendiente, con todas sus
métricas al hacer clic.

**Independent Test**: sobre una tarea con DEM y una polilínea 2D trazada, lanzar con parámetros por
defecto y verificar que aparecen tramos de 5 m cubriendo el eje, coloreados en tres rangos, que un
clic muestra las cuatro métricas, y que los tramos sin borde se distinguen y no muestran ancho.

### Tests for User Story 1

> Escribir primero y comprobar que fallan antes de implementar.

- [X] T016 [P] [US1] Escribir `coreplugins/road/tests/test_axis.py`: eje obtenido del contrato de `annotations` (solo `mode == "flat"`), copia propia de la geometría, y degradación a lista vacía con el plugin ausente, deshabilitado o de contrato mayor, usando `mock` sobre `get_plugin_by_name`
- [X] T017 [P] [US1] Escribir `coreplugins/road/tests/test_compute.py` con el DEM sintético de T013: el pipeline completo produce el número esperado de tramos, ancho y pendiente correctos en la zona conocida, tramos `no_coverage` donde el DEM no cubre el eje, y los invariantes de coherencia de [data-model.md §6](./data-model.md) se cumplen en todos los tramos
- [X] T018 [P] [US1] Escribir `coreplugins/road/tests/test_api_analyses.py`: `POST` crea y devuelve `202` con `analysis_id`, `GET` del índice y del detalle, `409 analysis_running` al lanzar con otro en curso, `POST cancel` deja `status: "canceled"` sin archivo de tramos, `400 no_elevation_model` en tarea sin DEM, y que escribir sin `change_project` no funciona

### Implementation for User Story 1

- [X] T019 [US1] Implementar `coreplugins/road/axis.py`: `axes_from_annotations(task_id)` vía `get_plugin_by_name('annotations')` con comprobación de `contract_version() <= 2` y degradación silenciosa ([contracts/consumed-contracts.md §1](./contracts/consumed-contracts.md)), y construcción del `AxisSource` con su copia de vértices y su `plan_length`
- [X] T020 [US1] Implementar `coreplugins/road/compute.py`: función `run_analysis` **self-contained** —todos los `import` dentro del cuerpo y absolutos (`from coreplugins.road import ...`), sin imports relativos ni referencias a globals del módulo, siguiendo el aviso literal de `coreplugins/realign/corrections.py`— que recorre el eje por bloques de tramos, lee una ventana de ráster por bloque a un array numpy y resuelve las muestras por indexación vectorizada ([research.md D2](./research.md))
- [X] T021 [US1] Añadir a `coreplugins/road/compute.py` el progreso y la cancelación: `progress_callback(status, perc)` una vez por bloque, `should_cancel()` en el mismo punto envuelto en `try/except` (bajo `CELERY_TASK_ALWAYS_EAGER` no hay backend de resultados), y al terminar escribir los tramos, el `summary` y el estado final, liberando siempre el candado `running`
- [X] T022 [US1] Implementar en `coreplugins/road/api.py` las vistas de análisis: `POST task/<pk>/analyses` (valida, toma el candado, lanza con `run_function_async(..., with_progress=True, with_cancel=True)` y responde `202`), `GET task/<pk>/analyses`, `GET task/<pk>/analyses/<id>` con sus tramos, y `POST task/<pk>/analyses/<id>/cancel` con el aborto por `TestSafeAsyncResult` del patrón de `realign`; registrar las rutas en `plugin.py`
- [X] T023 [US1] Completar `GET capabilities` en `coreplugins/road/api.py` con la lista de ejes disponibles y `annotations_available`, ahora que `axis.py` existe
- [X] T024 [P] [US1] Crear el control del mapa: `coreplugins/road/public/Road.jsx` (control Leaflet con botón, patrón de `annotations/public/Annotations.jsx`), `coreplugins/road/public/Road.scss`, y `coreplugins/road/public/panelStacking.js` copiado del helper que ya comparten los plugins del fork
- [X] T025 [P] [US1] Implementar `coreplugins/road/public/segmentStyle.js`: función **pura** que dada una pendiente y los dos umbrales devuelve el color, más el estilo distinguible de los tramos sin dato ([research.md D15](./research.md))
- [X] T026 [US1] Implementar `coreplugins/road/public/roadBridge.js`: publicar el análisis como un `L.FeatureGroup` con una polilínea por tramo vía `PluginsAPI.Map.addAnnotation`, manejadores de alternar y borrar que **devuelven `false` sobre layers ajenos**, y popup por tramo con todas sus métricas ([contracts/consumed-contracts.md §3](./contracts/consumed-contracts.md))
- [X] T027 [US1] Implementar `coreplugins/road/public/RoadPanel.jsx` y su `RoadPanel.scss`: selector de eje y de modelo, botón de calcular, barra de progreso con sondeo, botón de cancelar, listado de análisis de la tarea y mensajes de error del contrato
- [X] T028 [P] [US1] Escribir los tests de frontend `coreplugins/road/public/tests/segmentStyle.test.js` y `roadBridge.test.js` sobre el harness jsdom + Leaflet de `annotations/public/tests/harness.js`, y engancharlos desde `coreplugins/road/tests/test_frontend.py` con el patrón `subprocess` + `skipUnless` de `annotations/tests.py`
- [X] T029 [US1] **Verificación en worker real** (Principio IV, no negociable): copiar el plugin también al contenedor `worker`, reiniciarlo, lanzar un análisis sobre una tarea real y mostrar el log del worker completándolo sin `ImportError` ni `NameError`, según [quickstart.md](./quickstart.md#verificación-del-worker-principio-iv-no-negociable)

**Checkpoint**: US1 entrega valor completa por sí sola — el usuario ya sabe dónde su camino es
empinado y cuánto mide de ancho. Es el MVP.

---

## Phase 4: User Story 2 - Llevarse el análisis a una herramienta externa (Priority: P2)

**Goal**: descargar el análisis en CSV para hoja de cálculo y en GeoJSON para QGIS, con tramos,
transversales, puntos de borde y los parámetros del cálculo.

**Independent Test**: sobre un análisis ya calculado, descargar ambos archivos y comprobar que el
CSV tiene una fila por tramo con las celdas sin dato vacías, y que el GeoJSON abre en QGIS con las
tres familias de entidades.

### Tests for User Story 2

- [X] T030 [P] [US2] Escribir `coreplugins/road/tests/test_export.py`: el CSV tiene cabecera y una fila por tramo, las celdas sin dato van **vacías** y no a cero, el GeoJSON valida como `FeatureCollection` con las entidades `segment`, `cross_section` y `edge`, ambos incluyen los parámetros del análisis, y el nombre del archivo lleva tarea y análisis pasados por `slugify`

### Implementation for User Story 2

- [X] T031 [US2] Implementar `coreplugins/road/export.py`: `to_csv(analysis, segments)` con las columnas exactas de [contracts/rest-api.md](./contracts/rest-api.md) y el bloque de comentarios `#` con los parámetros, y `to_geojson(analysis, segments)` con las tres familias de entidades distinguidas por `kind`
- [X] T032 [US2] Añadir a `coreplugins/road/api.py` la vista `GET task/<pk>/analyses/<id>/export?format=csv|geojson` con `Content-Disposition: attachment` y `410 result_missing` si el archivo de tramos no está; registrar la ruta en `plugin.py`
- [X] T033 [US2] Añadir los botones de descarga CSV y GeoJSON a `coreplugins/road/public/RoadPanel.jsx`, encadenando descargas con un enlace temporal por archivo (el truco de `annotationsBridge.js`: `window.location.href` solo atiende una a la vez)

**Checkpoint**: US1 y US2 funcionan de forma independiente.

---

## Phase 5: User Story 3 - Ajustar los parámetros al camino concreto (Priority: P3)

**Goal**: cambiar los parámetros de cálculo y recalcular, mover los umbrales del semáforo con
recoloreado inmediato y persistente, y eliminar análisis que ya no interesan.

**Independent Test**: cambiar los umbrales y ver el recoloreado sin recálculo, recargar y
comprobar que se conservan; después bajar el umbral de quiebre, recalcular y ver que cambia el
número de tramos con borde detectado.

### Tests for User Story 3

- [X] T034 [P] [US3] Escribir `coreplugins/road/tests/test_params.py`: cada parámetro fuera de rango devuelve `400 invalid_parameter` con el rango en el mensaje y **no** inicia cálculo, `sample_step` por debajo de la resolución del DEM se rechaza, `segment_length` menor que `sample_step` se rechaza, y la estimación de `POST .../estimate` coincide con el número de tramos y muestras que el análisis produce realmente
- [X] T035 [P] [US3] Escribir `coreplugins/road/tests/test_lifecycle.py`: `PATCH` de `color_thresholds` no cambia ningún tramo ni el `updated_at` del cálculo, `PATCH` de un campo no permitido devuelve `400`, relanzar sobre el mismo `(kind, ref)` sin `confirm` devuelve `409 confirmation_required` y con `confirm: true` **sustituye** conservando `id` y `name`, y `DELETE` borra índice y archivo de tramos

### Implementation for User Story 3

- [X] T036 [US3] Implementar la validación de parámetros en `coreplugins/road/sources.py` (o módulo `params.py` si crece): rangos de [data-model.md §4](./data-model.md), `sample_step` acotado por abajo a la resolución del DEM, coherencia `segment_length >= sample_step`, y mensajes que indiquen el rango admitido
- [X] T037 [US3] Implementar `POST task/<pk>/analyses/estimate` en `coreplugins/road/api.py` con el conteo aritmético y la duración estimada de [research.md D11](./research.md), y el flujo de `409 confirmation_required` en el `POST` de creación cuando la estimación supera el umbral de aviso o cuando `(kind, ref)` ya tiene análisis
- [X] T038 [US3] Implementar `PATCH task/<pk>/analyses/<id>` (solo `name` y `color_thresholds`) y `DELETE task/<pk>/analyses/<id>` en `coreplugins/road/api.py`, cancelando antes si estaba en curso; registrar las rutas en `plugin.py`
- [X] T039 [US3] Implementar la sustitución al recalcular en `coreplugins/road/store.py`: localizar el análisis por `(axis.kind, axis.ref)`, conservar `id` y `name`, reemplazar el resto y borrar el archivo de tramos anterior
- [X] T040 [US3] Añadir a `coreplugins/road/public/RoadPanel.jsx` el bloque de parámetros con sus valores por defecto y rangos tomados de `capabilities`, el diálogo de confirmación con la estimación, los controles de los dos umbrales del semáforo, y las acciones de recalcular y eliminar
- [X] T041 [US3] Conectar el recoloreado inmediato en `coreplugins/road/public/roadBridge.js`: al cambiar un umbral, `setStyle` sobre las polilíneas ya dibujadas usando `segmentStyle.js`, sin volver a pedir el análisis, y `PATCH` en segundo plano para persistir los umbrales
- [X] T042 [P] [US3] Añadir `coreplugins/road/public/tests/thresholdRecolor.test.js`: cambiar umbrales recolorea el grupo entero sin ninguna petición de datos, y los tramos sin dato conservan su estilo distinguible

**Checkpoint**: las tres primeras historias funcionan de forma independiente.

---

## Phase 6: User Story 4 - Analizar un eje que viene de fuera de WebODM (Priority: P4)

**Goal**: subir un GeoJSON con un `LineString` 2D y analizarlo igual que una anotación, con rechazos
que expliquen la causa concreta.

**Independent Test**: subir un GeoJSON válido sobre un camino de la tarea y obtener el mismo tipo de
resultado; después subir cada archivo inválido y comprobar que el mensaje identifica qué falla.

### Tests for User Story 4

- [X] T043 [P] [US4] Escribir `coreplugins/road/tests/test_upload.py`: un `LineString` válido produce análisis; un polígono, una colección con dos líneas, una línea de un solo vértice distinto, un `crs` declarado distinto de EPSG:4326 y una línea fuera de la extensión del DEM devuelven cada uno `400 invalid_axis` con un mensaje **distinto**; y con `annotations` ausente la vía del archivo sigue funcionando

### Implementation for User Story 4

- [X] T044 [US4] Implementar `axis_from_geojson(payload, task, model)` en `coreplugins/road/axis.py` con la validación en cascada de [research.md D13](./research.md), un error nombrado por causa, y el descarte silencioso de la tercera coordenada avisando en la respuesta
- [X] T045 [US4] Aceptar `multipart/form-data` en el `POST` de creación y en `estimate` dentro de `coreplugins/road/api.py`, con tope de tamaño de subida expuesto en `capabilities` como `max_upload_bytes`
- [X] T046 [US4] Añadir a `coreplugins/road/public/RoadPanel.jsx` el selector de archivo como alternativa al selector de anotación, con el mensaje explicativo cuando `annotations_available` es `false`

**Checkpoint**: las cuatro primeras historias funcionan de forma independiente.

---

## Phase 7: User Story 5 - Analizar sobre los productos realineados (Priority: P5)

**Goal**: elegir la variante realineada del DEM cuando la tarea tiene una realineación aplicada.

**Independent Test**: sobre una tarea realineada, comprobar que se ofrecen ambas variantes, analizar
con cada una y ver los tramos desplazados de forma coherente con la corrección aplicada.

### Tests for User Story 5

- [ ] T047 [P] [US5] Escribir `coreplugins/road/tests/test_variants.py`: con `realign` ausente o sin corregidos solo se ofrece `original`; pedir `realigned` sin realineación devuelve `400 unavailable_variant`; con corregidos presentes el análisis usa el archivo corregido y la variante queda registrada en el análisis y en la exportación
- [ ] T048 [P] [US5] Añadir a `coreplugins/realign/tests.py` la cobertura del contrato nuevo: `corrected_rasters` devuelve diccionario vacío sin realineación aplicada, tras revertir y cuando el archivo no está en disco, y devuelve las rutas existentes tras aplicar

### Implementation for User Story 5

- [ ] T049 [P] [US5] Crear `coreplugins/realign/contract.py` con `CONTRACT_VERSION = 1` y `corrected_rasters(task_id)`, reutilizando los helpers de rutas de su `api.py` y el criterio `state == 'applied'` más presencia real del archivo
- [ ] T050 [US5] Exponer el contrato en `coreplugins/realign/plugin.py` con `contract_version()` y `corrected_rasters(task_id)` delegando en `contract.py`, y documentarlo en la sección correspondiente de la documentación de `realign`
- [ ] T051 [US5] Consumir el contrato desde `coreplugins/road/sources.py`: variantes disponibles por modelo, resolución de la ruta según la variante elegida, y degradación a `original` si `realign` falta, está deshabilitado o expone un contrato mayor
- [ ] T052 [US5] Añadir el selector de variante a `coreplugins/road/public/RoadPanel.jsx`, mostrándolo solo cuando `capabilities` ofrece más de una para el modelo elegido

**Checkpoint**: las cinco historias funcionan de forma independiente.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T053 [P] Actualizar `coreplugins/road/README.md` con las rutas definitivas, los parámetros y sus rangos, y el comando de tests
- [ ] T054 [P] Revisar `docs/entorno-plugins.md` y anotar, si procede, el uso de lectura por ventanas con numpy como patrón disponible para plugins que muestreen rásteres de forma masiva
- [ ] T055 Calibrar la constante de muestras por segundo y el umbral de aviso en `coreplugins/road/compute.py` midiendo un análisis real, para que la estimación de [research.md D11](./research.md) se parezca al tiempo observado y el aviso dispare donde de verdad molesta
- [ ] T056 Verificar SC-002 con evidencia: ejecutar el escenario 1 de [quickstart.md](./quickstart.md) sobre un camino de 1 km con parámetros por defecto y mostrar el tiempo total por debajo de 2 minutos con progreso visible
- [ ] T057 Verificar SC-005 y SC-008 con evidencia: ejecutar los escenarios 3 y 5 de [quickstart.md](./quickstart.md) — recoloreado completo por debajo de 2 segundos sin recálculo, y cancelación devolviendo el control en menos de 5 segundos
- [ ] T058 Comprobar la convivencia en el bus del core entre `coreplugins/road/public/roadBridge.js` y `coreplugins/annotations/public/annotationsBridge.js`: con ambos plugins activos, una acción sobre una anotación ajena no pasa por los manejadores de `road` ni al revés
- [ ] T059 Ejecutar la validación manual completa de [quickstart.md](./quickstart.md) (10 escenarios) y anotar los resultados
- [ ] T060 Ejecutar la suite completa y mostrar su salida: `./run_tests_in_docker.sh`, más `webodm.sh test backend coreplugins.realign.tests` para confirmar que la ampliación de `realign` no rompió nada

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias.
- **Foundational (Phase 2)**: depende del Setup. **Bloquea todas las historias.**
- **US1 (Phase 3)**: depende de Foundational. Sin dependencias de otras historias.
- **US2 (Phase 4)**: depende de US1 — no hay nada que exportar sin análisis calculado.
- **US3 (Phase 5)**: depende de US1. Independiente de US2.
- **US4 (Phase 6)**: depende de US1 (reutiliza el `POST` de creación). Independiente de US2 y US3.
- **US5 (Phase 7)**: depende de US1. Independiente de US2, US3 y US4.
- **Polish (Phase 8)**: depende de las historias que se decidan entregar.

US2, US3, US4 y US5 son independientes **entre sí**: una vez cerrada US1, pueden abordarse en
cualquier orden o en paralelo. La dependencia de todas ellas con US1 es real, no organizativa: sin
un análisis calculado no hay nada que exportar, reconfigurar ni recalcular.

### Within Each User Story

- Los tests van primero y deben fallar antes de implementar.
- `store` y `sources` antes que `compute`; `compute` antes que las vistas; las vistas antes que el
  frontend que las consume.
- La verificación en worker (T029) cierra US1: es la única prueba que cubre el requisito
  self-contained de la función asíncrona.

### Parallel Opportunities

- **Phase 1**: T003 y T004 en paralelo.
- **Phase 2**: T008, T009, T010 y T012 en paralelo (módulos independientes, ninguno importa a otro);
  después T014 y T015 en paralelo. T006 y T007 tocan el mismo archivo: van en serie.
- **US1**: T016, T017 y T018 en paralelo (tests); T024 y T025 en paralelo (frontend sin dependencias
  entre sí); T028 en paralelo con el backend restante.
- **US3**: T034 y T035 en paralelo; T042 en paralelo con el resto del frontend.
- **US5**: T047, T048 y T049 en paralelo.
- **Phase 8**: T053 y T054 en paralelo.

---

## Parallel Example: Phase 2

```bash
# Los cuatro módulos base no se importan entre sí:
Task: "Implementar sources.py: modelos, rutas, resolución, obsolescencia"
Task: "Implementar geometry.py: proyección, progresivas, tramificación, transversales"
Task: "Implementar profile.py: detección de bordes y ajustes de pendiente"
Task: "Implementar signals.py: borrado en cascada por task_removed"
```

## Parallel Example: User Story 1 (tests primero)

```bash
Task: "test_axis.py: eje desde annotations y degradación sin el plugin"
Task: "test_compute.py: pipeline completo sobre DEM sintético e invariantes de tramo"
Task: "test_api_analyses.py: crear, consultar, cancelar, 409 de concurrencia, permisos"
```

---

## Implementation Strategy

### MVP (solo US1)

1. Phase 1: Setup — el plugin existe y carga.
2. Phase 2: Foundational — persistencia, DEM y matemática probada.
3. Phase 3: US1 — análisis, capa coloreada y métricas por tramo.
4. **Parar y validar**: escenarios 1, 2 y 3 de [quickstart.md](./quickstart.md), más la verificación
   en worker (T029).
5. En este punto la feature ya resuelve el problema original: saber dónde el camino es empinado y
   cuánto mide de ancho.

### Entrega incremental

1. Foundational listo → nada visible todavía.
2. **+US1** → MVP demostrable.
3. **+US2** → el resultado se convierte en entregable para un cliente.
4. **+US3** → utilizable en caminos que no encajan con los valores por defecto.
5. **+US4** → ejes de topografía o de proyecto.
6. **+US5** → coherencia con tareas realineadas.

Cada incremento se sostiene sin los siguientes y no rompe los anteriores.

---

## Notes

- Las tareas `[P]` tocan archivos distintos y no dependen de trabajo pendiente.
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida,
  incluido el exit code — es requisito de la constitución del fork, no una recomendación.
- Los tests oficiales se corren **dentro de Docker**. En el Mac solo tests ligeros; nunca instalar
  GDAL, rasterio ni PDAL en el host.
- Recordatorio del despliegue: `coreplugins/` va horneado en la imagen, así que cada cambio necesita
  `docker compose cp` a **webapp y worker** más su reinicio para verse.
- Commit por tarea o por grupo lógico.
