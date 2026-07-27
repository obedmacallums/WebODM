# Tasks: Polilíneas anotadas sobre el mapa 2D, planas o sobre el terreno

**Input**: Design documents from `specs/004-polyline-annotations/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/rest-api.md`, `contracts/plugin-contract.md`, `quickstart.md`

**Tests**: se incluyen. Los exige la cobertura mínima de `quickstart.md` §2 y el flujo de desarrollo de la Constitución ("ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida"). Se ejecutan siempre en Docker: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.annotations.tests`.

**Organization**: agrupadas por historia de usuario para poder implementar y validar cada una por separado.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia a la que pertenece (US1–US5)
- Todas las rutas son relativas a la raíz del repositorio

## Path Conventions

Plugin nuevo bajo `coreplugins/annotations/` (backend Python + `public/` para los assets de frontend), según la sección *Source Code* de `plan.md`. No se toca ningún archivo fuera de ese directorio y de `specs/004-polyline-annotations/`.

---

## Phase 1: Setup

**Purpose**: esqueleto del plugin reconocible por el cargador de WebODM

- [X] T001 Crear `coreplugins/annotations/__init__.py` con la línea `from .plugin import *` (requisito del cargador: el core hace `getattr(package, "Plugin")`; un archivo vacío rompe la instanciación)
- [X] T002 [P] Crear `coreplugins/annotations/manifest.json` con nombre, descripción, versión `1.0.0`, autor y `webodmMinVersion` (tomar `coreplugins/viewshed/manifest.json` como referencia)
- [X] T003 Crear `coreplugins/annotations/plugin.py` con `class Plugin(PluginBase)` declarando `include_js_files()` → `['main.js']` y `build_jsx_components()` → `['Annotations.jsx']`, con `api_mount_points()` aún vacío
- [X] T004 [P] Crear `coreplugins/annotations/public/icon.svg` y los archivos vacíos `coreplugins/annotations/public/Annotations.scss` y `coreplugins/annotations/public/AnnotationsPanel.scss`
- [X] T005 Verificar el despliegue siguiendo `quickstart.md` §1: copiar el plugin al contenedor, reiniciar `webapp` y comprobar `INFO Registered [coreplugins.annotations.plugin]` en los logs

**Checkpoint**: el plugin se carga en WebODM aunque todavía no haga nada

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: persistencia, geometría y andamiaje de API/tests que todas las historias necesitan

**⚠️ CRITICAL**: ninguna historia puede empezar hasta terminar esta fase

- [X] T006 Implementar `coreplugins/annotations/store.py` con el documento por tarea del `GlobalDataStore` (espacio `annotations`, clave `task_<pk>`, `version: 1`): `get_document`, `set_document`, `del_document`, `list_polylines`, `get_polyline`, `upsert_polyline`, `remove_polyline`, tratando la ausencia de documento como lista vacía (`data-model.md`)
- [X] T007 [P] Implementar `coreplugins/annotations/geometry.py`: validación de vértices (mínimo 2 distintos, máximo 500), proyección de EPSG:4326 al CRS métrico con `rasterio.warp.transform` y cálculo de la longitud en planta (`research.md` D11)
- [X] T008 [P] Crear `coreplugins/annotations/tests.py` con el andamiaje del patrón de `coreplugins/realign/tests.py`: `BootTestCase`, `APIClient`, helpers de proyecto y tarea, `assign_perm` de guardian, y un generador de DEM sintéticos con `rasterio` (uno normal y otro con parche de `nodata`)
- [X] T009 Añadir en `coreplugins/annotations/api.py` la base de vistas: clase común sobre `TaskView`, resolución con `get_and_check_task`, comprobación de escritura con `check_project_perms(..., ('change_project',))`, formato de error `{"error": ...}` y serialización de una polilínea al esquema de `contracts/rest-api.md`
- [X] T010 Registrar en `coreplugins/annotations/plugin.py` los `MountPoint` de `task/(?P<pk>[^/.]+)/polylines` y `task/(?P<pk>[^/.]+)/polylines/(?P<polyline_id>[^/.]+)`
- [X] T011 [P] Crear `coreplugins/annotations/public/main.js` enganchado a `PluginsAPI.Map.willAddControls`, que solo añade el control cuando `args.tiles` contiene exactamente una tarea (FR-031), siguiendo `coreplugins/viewshed/public/main.js`

**Checkpoint**: persistencia y API base listas; las historias pueden arrancar

---

## Phase 3: User Story 1 - Trazar y conservar una polilínea sobre el mapa (Priority: P1) 🎯 MVP

**Goal**: el usuario traza una polilínea plana, la nombra y la conserva; aparece en el panel de capas nativo y sobrevive a recargas.

**Independent Test**: trazar una polilínea de tres vértices en una tarea con ortofoto, nombrarla, recargar la página y comprobar que reaparece igual; verla desde otro usuario con acceso; comprobar que un trazado de un solo vértice se rechaza.

### Tests for User Story 1 ⚠️

- [X] T012 [P] [US1] Tests de creación y listado en `coreplugins/annotations/tests.py`: alta correcta, rechazo con menos de dos vértices distintos, rechazo por exceso de vértices, nombre por defecto cuando llega vacío (FR-002, FR-003)
- [X] T013 [P] [US1] Tests de permisos en `coreplugins/annotations/tests.py`: lectura con `view_project`, escritura sin `change_project` devuelve 404, tarea pública accesible (FR-025)
- [X] T014 [P] [US1] Test de borrado en cascada en `coreplugins/annotations/tests.py`: emitir `task_removed` y comprobar que la clave del `GlobalDataStore` desaparece (FR-027)

### Implementation for User Story 1

- [X] T015 [US1] Implementar `GET` y `POST` de `task/<pk>/polylines` en `coreplugins/annotations/api.py` según `contracts/rest-api.md` (modo `flat`, validación, `201` con la polilínea creada)
- [X] T016 [US1] Implementar `DELETE task/<pk>/polylines/<id>` en `coreplugins/annotations/api.py` (`204`, `404` si no existe)
- [X] T017 [P] [US1] Crear `coreplugins/annotations/signals.py` con el receptor de `app.plugins.signals.task_removed` y `dispatch_uid="annotations_on_task_removed"`, importado desde `coreplugins/annotations/plugin.py` (patrón de `coreplugins/cesiumion/api_views.py:146`)
- [X] T018 [P] [US1] Implementar el trazado en `coreplugins/annotations/public/PolylineEditor.js`: vértices por clicks sucesivos sobre `L.Polyline`, finalización explícita, cancelación con `Escape` y longitud acumulada en curso convertida con `webodm/classes/Units` (FR-001, FR-006)
- [X] T019 [US1] Implementar `coreplugins/annotations/public/annotationsBridge.js`: publicar con `PluginsAPI.Map.addAnnotation(layer, name, task, stored)`, y manejadores `onToggleAnnotation` y `onDeleteAnnotation` que emitan `annotationDeleted` tras confirmar el borrado en el servidor, **devolviendo `false` sobre layers ajenos** (`contracts/plugin-contract.md` §2.2 y §2.3)
- [X] T020 [US1] Crear `coreplugins/annotations/public/Annotations.jsx` con el control Leaflet y el botón que abre el panel (patrón de `coreplugins/viewshed/public/Viewshed.jsx`)
- [X] T021 [US1] Crear `coreplugins/annotations/public/AnnotationsPanel.jsx` con la lista de polilíneas, el campo de nombre al finalizar un trazado y el guardado contra la API
- [X] T022 [US1] Cargar las polilíneas persistidas al abrir el mapa y publicarlas como anotaciones con `stored = true`, en `coreplugins/annotations/public/AnnotationsPanel.jsx` (FR-024, FR-028)
- [X] T023 [P] [US1] Dar estilo al control y al panel en `coreplugins/annotations/public/Annotations.scss` y `coreplugins/annotations/public/AnnotationsPanel.scss`
- [X] T024 [US1] Mostrar el aviso de "abre una sola tarea para trazar" cuando el mapa tenga varias, en `coreplugins/annotations/public/AnnotationsPanel.jsx` (escenario 7 de la US1)

**Checkpoint**: US1 completa y verificable por sí sola — MVP entregable

---

## Phase 4: User Story 2 - Obtener la línea con la elevación del terreno (Priority: P2)

**Goal**: la polilínea puede llevar cotas del DSM/DTM, con longitud sobre el terreno, desnivel acumulado y el paso de densificación con el que se calcularon.

**Independent Test**: trazar en modo sobre el terreno sobre una tarea con DSM una línea que cruce un desnivel conocido y comprobar que la longitud sobre el terreno supera a la de planta de forma coherente; comprobar que en una tarea sin DEM el modo no se ofrece y se explica.

### Tests for User Story 2 ⚠️

- [X] T025 [P] [US2] Tests de densificación en `coreplugins/annotations/tests.py`: paso por defecto `max(resolución, 0.25)`, rechazo de pasos fuera de rango y tope de 20 000 puntos (FR-014, FR-023)
- [X] T026 [P] [US2] Tests de cobertura incompleta en `coreplugins/annotations/tests.py`: vértice fuera del ráster y hueco de `nodata` devuelven `422` con `missing_ranges` correcto y **no persisten nada** (FR-021, FR-022)
- [X] T027 [P] [US2] Tests de métricas en `coreplugins/annotations/tests.py`: `surface_length >= plan_length`, y que cambia al cambiar el paso sobre el mismo trazado (FR-015)
- [X] T028 [P] [US2] Test de tarea sin DEM en `coreplugins/annotations/tests.py`: `GET .../elevation` devuelve `available: []` y crear en modo `draped` responde `400` (FR-009)

### Implementation for User Story 2

- [X] T029 [US2] Implementar en `coreplugins/annotations/elevation.py` la detección de modelos disponibles vía `task.dsm_extent` / `task.dtm_extent`, la resolución de rutas con `task.get_asset_download_path` y la lectura de resolución, `nodata` y unidad vertical del ráster (`research.md` D10)
- [X] T030 [US2] Implementar en `coreplugins/annotations/elevation.py` la densificación al paso indicado y el muestreo con `rasterio` `sample()`, con transformación de coordenadas mediante `rasterio.warp.transform` (`research.md` D3)
- [X] T031 [US2] Implementar en `coreplugins/annotations/elevation.py` la detección de ausencia de dato (`z == nodata` o `NaN`) y la construcción de `missing_ranges` normalizados `[0,1]`, abortando el muestreo completo sin rellenar cotas (FR-021, FR-022)
- [X] T032 [US2] Implementar en `coreplugins/annotations/elevation.py` el cálculo de `surface_length`, `elevation_gain`, `sample_count` y `vertex_z` sobre la densificada (`data-model.md`, entidad `ElevationSampling`)
- [X] T033 [US2] Implementar `GET task/<pk>/elevation` en `coreplugins/annotations/api.py` con las capacidades de `contracts/rest-api.md` (modelos, resolución, paso por defecto, rango y límites) y registrar su `MountPoint` en `coreplugins/annotations/plugin.py`
- [X] T034 [US2] Extender el `POST task/<pk>/polylines` de `coreplugins/annotations/api.py` para admitir `mode: "draped"` con `model` y `step`, persistiendo el bloque `elevation` completo
- [X] T035 [US2] Añadir en `coreplugins/annotations/public/AnnotationsPanel.jsx` el selector de modo, el de modelo (DSM/DTM) y el control del paso, deshabilitando el modo sobre el terreno con explicación cuando no haya DEM (FR-009, FR-010, FR-016)
- [X] T036 [US2] Mostrar en `coreplugins/annotations/public/AnnotationsPanel.jsx` la longitud sobre el terreno, la longitud en planta y el desnivel acumulado en las unidades del usuario, **siempre acompañados del paso empleado** (FR-015)
- [X] T037 [US2] Implementar en `coreplugins/annotations/public/AnnotationsPanel.jsx` el tratamiento de la respuesta `422`: resaltar los tramos de `missing_ranges` sobre el mapa y ofrecer guardar en modo plano o corregir el trazado (FR-022)

**Checkpoint**: US1 y US2 funcionan de forma independiente

---

## Phase 5: User Story 3 - Exportar las polilíneas para usarlas fuera de WebODM (Priority: P3)

**Goal**: descargar todas las polilíneas de la tarea en GeoJSON, con cotas y atributos, desde el plugin y desde el botón nativo del panel de anotaciones.

**Independent Test**: con una polilínea plana y otra elevada, descargar el archivo y abrirlo en QGIS comprobando geometrías, cotas y atributos.

### Tests for User Story 3 ⚠️

- [X] T038 [P] [US3] Tests de exportación en `coreplugins/annotations/tests.py`: `LineString` de dos ordenadas para las planas y de tres para las elevadas, propiedades completas y omitidas según el modo, y variante `geometry=densified` (FR-032 a FR-034)

### Implementation for User Story 3

- [X] T039 [US3] Implementar en `coreplugins/annotations/contract.py` la construcción de la `FeatureCollection` con las propiedades de `contracts/rest-api.md` (`plan_length_m`, `surface_length_m`, `elevation_gain_m`, `elevation_model`, `densify_step_m`, `vertical_unit`, `sampled_at`)
- [X] T040 [US3] Implementar `GET task/<pk>/polylines/export` en `coreplugins/annotations/api.py` con el parámetro `geometry` y la respuesta `application/geo+json` con `Content-Disposition: attachment`, registrando su `MountPoint` en `coreplugins/annotations/plugin.py`
- [X] T041 [US3] Implementar `onDownloadAnnotations` en `coreplugins/annotations/public/annotationsBridge.js` devolviendo `true` para `"geojson"`, que es lo que rellena el `// TODO?` de `LayersControlAnnotations.jsx:127` (FR-032)
- [X] T042 [US3] Añadir el botón de exportación con selector de geometría (vértices o densificada) en `coreplugins/annotations/public/AnnotationsPanel.jsx` (FR-034)
- [X] T043 [US3] Validar en QGIS el archivo exportado siguiendo `quickstart.md` §3 y dejar constancia del resultado (FR-035, SC-005) — **sustituido por `ogrinfo` (GDAL, el motor vectorial de QGIS)**: sin QGIS instalado en este entorno, se validó con datos reales de la tarea `dae96abf-…` que el GeoJSON exportado abre como `3D Line String`, CRS EPSG:4326 implícito y con todos los campos de `contracts/rest-api.md` presentes (ver transcripción de la sesión)

**Checkpoint**: US1, US2 y US3 funcionan de forma independiente

---

## Phase 6: User Story 4 - Corregir y reorganizar lo ya trazado (Priority: P4)

**Goal**: editar geometría y nombre, convertir entre modos en ambos sentidos y volver a muestrear, con recálculo automático de las magnitudes.

**Independent Test**: mover un vértice de una línea elevada a una zona de cota distinta y comprobar el recálculo; convertir una plana a elevada y verificar que el trazado en planta no cambia.

### Tests for User Story 4 ⚠️

- [X] T044 [P] [US4] Tests de `PATCH` en `coreplugins/annotations/tests.py`: renombrado puro sin re-muestreo, cambio de geometría con re-muestreo, y **atomicidad** — si el trazado nuevo pierde cobertura, la polilínea queda intacta (FR-004, FR-019)
- [X] T045 [P] [US4] Tests de `elevate` y `flatten` en `coreplugins/annotations/tests.py`: conversión en ambos sentidos conservando `vertices` byte a byte, idempotencia de `flatten` y rechazo de `elevate` sin cobertura (FR-011, escenario 8 de la US4)
- [X] T046 [P] [US4] Test de muestreo obsoleto en `coreplugins/annotations/tests.py`: alterar el `mtime` del DEM y comprobar que la respuesta marca `stale: true` (FR-020)

### Implementation for User Story 4

- [X] T047 [US4] Implementar `PATCH task/<pk>/polylines/<id>` en `coreplugins/annotations/api.py` con re-muestreo condicional y semántica de todo o nada (`data-model.md`, transiciones)
- [X] T048 [US4] Implementar `POST .../elevate` y `POST .../flatten` en `coreplugins/annotations/api.py` y registrar sus `MountPoint` en `coreplugins/annotations/plugin.py` (FR-011, FR-020)
- [X] T049 [P] [US4] Implementar en `coreplugins/annotations/elevation.py` el estado derivado `stale` comparando `source_mtime` con `os.stat` del DEM (`research.md` D12)
- [X] T050 [US4] Implementar en `coreplugins/annotations/public/PolylineEditor.js` la edición de vértices: arrastre para mover, click izquierdo sobre la línea para insertar en el tramo y click derecho sobre un vértice para eliminarlo, rechazando quedarse por debajo de dos vértices (FR-004)
- [X] T051 [US4] Añadir en `coreplugins/annotations/public/AnnotationsPanel.jsx` las acciones de elevar, aplanar y volver a muestrear, con el aviso visible cuando el muestreo esté obsoleto (FR-011, FR-020)
- [X] T052 [US4] Implementar el renombrado en `coreplugins/annotations/public/annotationsBridge.js` emitiendo `PluginsAPI.Map.updateAnnotation(layer, name)` tras guardar, y verificar que el borrado desde el panel de capas del core funciona de extremo a extremo (FR-029, escenario 6 de la US4)

**Checkpoint**: las cuatro primeras historias funcionan de forma independiente

---

## Phase 7: User Story 5 - Reutilizar las polilíneas desde otro plugin (Priority: P5)

**Goal**: contrato estable y versionado para que otro plugin obtenga geometría lista para usar, y pueda elevar una línea plana sin duplicarla.

**Independent Test**: desde el shell de Django, obtener el plugin con `get_plugin_by_name("annotations")` y ejercitar `get_polylines`, `get_densified` y `elevate` sin pasar por la interfaz.

### Tests for User Story 5 ⚠️

- [X] T053 [P] [US5] Tests del contrato Python en `coreplugins/annotations/tests.py`: `contract_version()`, `get_polylines`, `get_polyline`, `get_densified` y `elevate` sobre una línea plana sin que se cree una polilínea nueva (FR-036 a FR-039)
- [X] T054 [P] [US5] Tests del endpoint `densified` en `coreplugins/annotations/tests.py`: recálculo con `step` alternativo, rechazo sobre polilíneas planas y rechazo por exceso de puntos (FR-038, FR-023)

### Implementation for User Story 5

- [X] T055 [US5] Implementar `coreplugins/annotations/contract.py` con `CONTRACT_VERSION = 1`, las funciones públicas y las excepciones `IncompleteCoverage` y `LimitExceeded` (`contracts/plugin-contract.md` §1.1)
- [X] T056 [US5] Exponer en `coreplugins/annotations/plugin.py` los métodos públicos `contract_version`, `get_polylines`, `get_polyline`, `get_densified` y `elevate` delegando en `contract.py`
- [X] T057 [US5] Implementar `GET task/<pk>/polylines/<id>/densified` en `coreplugins/annotations/api.py` y registrar su `MountPoint` en `coreplugins/annotations/plugin.py`
- [X] T058 [US5] Documentar el contrato y un ejemplo de consumo en `coreplugins/annotations/README.md`, enlazando a `specs/004-polyline-annotations/contracts/plugin-contract.md`

**Checkpoint**: las cinco historias completas

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T059 [P] Envolver con `gettext_lazy` los mensajes del backend en `coreplugins/annotations/api.py` y con `_` de `webodm/classes/gettext` los textos del frontend en `coreplugins/annotations/public/AnnotationsPanel.jsx` — **ya satisfecho**: verificado con un barrido de todas las cadenas de texto de usuario en `api.py`, `AnnotationsPanel.jsx` y `Annotations.jsx`, todas ya envueltas desde las fases anteriores
- [X] T060 [P] Añadir en `coreplugins/annotations/tests.py` el test que protege la regla del bus: los manejadores devuelven `false` ante un layer ajeno y no cortan la cadena (`contracts/plugin-contract.md` §2.3, riesgo 1 de `research.md`) — sin entorno de tests JS para plugins en este fork (`jest.config.js` solo cubre `app/static/app/js`, archivo del core), se verifica de forma estática sobre el código fuente de `annotationsBridge.js` en `AnnotationsBusRuleTest`
- [X] T061 Ejecutar los gates de la Constitución de `quickstart.md` §4 y adjuntar su salida: sin cambios en el core, sin dependencias nuevas y `rasterio` disponible en `webapp` **y** en `worker` — los cuatro gates pasan: `git diff --stat master -- requirements.txt Dockerfile docker-compose.yml` vacío, sin `requirements.txt`/`package.json` propios del plugin, `git diff --name-only master -- app/ webodm/ worker/ nodeodm/ nginx/` vacío, `rasterio 1.3.10` importable en `webapp` y `worker`
- [X] T062 Verificar SC-010 desactivando el plugin desde *Administration → Plugins*: el mapa 2D y el panel de capas siguen operativos y la consola del navegador queda limpia — verificado en el navegador sobre el proyecto `geocom` (tarea real): con el plugin deshabilitado, el control de Annotations desaparece de la barra del mapa, el panel de capas (Cameras/Plant Health/Orthophoto/Surface Model) funciona con normalidad y `read_console_messages` no reporta errores; reactivado el plugin al terminar
- [X] T063 Recorrer la validación manual completa de `quickstart.md` §3 para las cinco historias y registrar el resultado de cada una — hecho en el navegador y por shell de Django sobre datos reales (proyecto `los presidentes`, tarea `Noria` con DSM+DTM):
  - **US1**: trazado de 3 vértices, guardado, recarga de página (persiste con las mismas métricas), renombrado (persistido, verificado por shell), borrado desde el panel de capas nativo (verificado que el documento queda vacío en el store)
  - **US2**: modo "Sobre el terreno" por defecto al haber DEM, Terreno/Planta/Desnivel mostrados con el paso; valores reales: Terreno 644,128 m vs Planta 310,6 m
  - **US3**: exportación desde el botón nativo del panel, validada con `ogrinfo` (GDAL) sobre el GeoJSON real: `3D Line String`, EPSG:4326 implícito, todas las propiedades de `contracts/rest-api.md` presentes
  - **US4**: edición de geometría (arrastre de vértice con recálculo automático: Terreno pasó de 644,128 a 803,353 m), Aplanar/Elevar/Volver a muestrear, borrado desde el panel de capas del core
  - **US5**: reproducido exactamente el ejemplo del shell de `quickstart.md` §3 contra la tarea real: `contract_version() == 1`, `get_polylines`, `get_densified` con `sample_count`/`step`/`model` correctos
  - **Hallazgos durante la validación, corregidos en el mismo plugin**:
    - Conflicto de z-index con otros controles del mapa (p. ej. Contours), igual al que ya se había resuelto en `realign`: `.leaflet-control-annotations` heredaba `z-index: 800` del CSS base de Leaflet porque la regla propia no llevaba `!important`; se corrigió en `Annotations.scss` siguiendo el mismo patrón que `viewshed`/`objdetect`/`realign`/`contours`
    - Bug de duplicación: `handleElevate` volvía a publicar la anotación (`this.publish(...)`) tras `elevate`/re-muestreo, creando un `L.Polyline` y una entrada nuevos en el panel de capas del core sin retirar los anteriores; corregido en `AnnotationsPanel.jsx` quitando esa llamada redundante (el layer no cambia de geometría, solo su metadata) y verificado que tras Aplanar+Elevar+Volver a muestrear solo queda una entrada
    - A pedido del usuario, se añadió scroll vertical propio a la lista de polilíneas (`.annotations-list-wrapper`, patrón de `realign-points-wrapper`)
    - Popup del ortomosaico abriéndose en cada click del trazado: el core abre el popup del tile layer desde su propio handler `map.on('click')` cuando el punto cae dentro de los bounds (`app/static/app/js/components/Map.jsx:963-975`), y su `autoPan` desplazaba el mapa a mitad del recorrido. El core ya prevé el caso en la primera línea de ese handler (`if (PluginsAPI.Map.handleClick(e)) return;`), así que `PolylineEditor` registra un callback en `onHandleClick` que devuelve `true` **solo** mientras el trazado está activo (regla del bus: `false` en cualquier otro caso), más un guard `popupopen` para los popups que no pasan por ahí (marcadores de fotos/GCP). Un primer intento por la vía de `unbindPopup`/`bindPopup` quedó descartado: rompía `updatePopupFor` del core (`popup.getContent()` sobre `null`), y como su handler corre antes que el del plugin, la excepción impedía además que se registrara el vértice. Verificado en vivo sobre la ortofoto: 4 clicks → 4 vértices, ningún popup, consola sin errores; y con el trazado inactivo (antes y después) el popup del core se abre con normalidad
    - Marcadores de vértice huérfanos: al borrar u ocultar una polilínea mientras estaba en modo *Editar geometría*, la línea desaparecía pero sus manejadores (marcadores del mapa, no hijos del layer) quedaban flotando apuntando a un layer ya removido. `PolylineEditor.startEditing` escucha ahora el evento `remove` del layer y avisa al panel (`onStop`) para soltar el modo edición. Censo de layers antes del arreglo: `{polylines:1, markers:5}` → tras borrar `{polylines:0, markers:5}`; después: `{polylines:1, markers:5}` → `{polylines:0, markers:0}`, y `editingGeometryId` pasa a `null` tanto al borrar como al ocultar desde el panel de capas del core
  - **No verificable en este entorno**: no hay una tarea sin DEM ni un proyecto multi-tarea disponibles para repetir en vivo el escenario 5 de la US1/US2 (control de trazado oculto, aviso "sin modelo de elevación"); esos caminos ya están cubiertos por tests automatizados (T028) y por revisión de código sin cambios en esta sesión
- [X] T064 [P] Corregir la fila de `pyproj` en `docs/entorno-plugins.md`: figura como no disponible y está instalado (3.6.1), aunque esta feature no lo use por no estar declarado en `requirements.txt` — confirmado con `import pyproj` en `webapp` y `worker` (3.6.1 en ambos); movido de "No disponible" a la tabla de nivel Python con la aclaración de que es una dependencia transitiva no declarada

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias
- **Foundational (Phase 2)**: depende de Setup — **bloquea todas las historias**
- **User Stories (Phase 3–7)**: dependen de Foundational; después pueden abordarse en orden de prioridad o en paralelo
- **Polish (Phase 8)**: depende de las historias que se quieran cerrar

### User Story Dependencies

- **US1 (P1)**: solo depende de Foundational. Es el MVP
- **US2 (P2)**: solo depende de Foundational. Reutiliza el `POST` de US1 pero es verificable por separado
- **US3 (P3)**: depende de Foundational; con US2 hecha la exportación además lleva cotas, sin ella exporta solo líneas planas
- **US4 (P4)**: depende de Foundational; sus conversiones de modo requieren US2 para ser observables
- **US5 (P5)**: depende de Foundational; el contrato entrega más valor con US2, pero funciona con líneas planas

### Within Each User Story

- Los tests se escriben antes y deben fallar antes de implementar
- Backend antes que frontend: la interfaz consume endpoints ya existentes
- En el backend: `store` y `geometry` → `elevation` → `api` → `plugin` (registro de rutas)

### Parallel Opportunities

- T002 y T004 en Setup
- T007, T008 y T011 en Foundational (archivos distintos y sin dependencias entre sí)
- Todos los tests de una misma historia marcados [P], al vivir en secciones distintas de `tests.py`, siempre que se escriban antes de tocar implementación
- T017, T018 y T023 dentro de US1; T049 dentro de US4
- Con varias personas, US2 a US5 pueden abordarse simultáneamente una vez cerrada la Foundational

---

## Parallel Example: Foundational

```bash
# Piezas independientes entre sí, todas en archivos distintos:
Task: "Implementar geometry.py en coreplugins/annotations/geometry.py"
Task: "Crear el andamiaje de tests en coreplugins/annotations/tests.py"
Task: "Crear main.js con la detección de tarea única en coreplugins/annotations/public/main.js"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Fase 1: Setup
2. Fase 2: Foundational (bloquea todo lo demás)
3. Fase 3: US1
4. **PARAR Y VALIDAR**: trazar, guardar, recargar, comprobar el panel de capas y el borrado en cascada
5. En este punto el plugin ya aporta valor: anotaciones planas persistentes sobre el mapa

### Incremental Delivery

1. Setup + Foundational → base lista
2. US1 → validar → entregable (MVP)
3. US2 → validar → las líneas ya llevan elevación, que es el caso de uso principal
4. US3 → validar → las líneas salen de WebODM
5. US4 → validar → deja de hacer falta redibujar para corregir
6. US5 → validar → otros plugins pueden construirse encima

### Notas de riesgo

- **El bus de anotaciones corta en el primer *truthy*** (`ApiFactory.js:95-102`): T019, T041 y T052 tocan manejadores del bus y todos deben devolver `false` ante layers ajenos. T060 lo blinda con un test
- **La longitud sobre el terreno depende del paso** (`research.md` D4): T036 debe mostrar siempre el paso junto a la cifra, o el usuario comparará valores no comparables
- **Cobertura incompleta nunca se rellena** (FR-021, FR-022): T031 aborta el muestreo entero; T026 y T045 lo verifican
- **El worker necesita el plugin copiado** para que el receptor de `task_removed` funcione (`quickstart.md` §1), lo comprueba T061

---

## Phase 9: Rediseño 2D/3D (contrato v2, posterior a la entrega inicial)

Cambio pedido tras probar la feature en vivo: la distinción entre polilíneas planas y sobre el
terreno era demasiado tenue (un radio dentro del formulario, más botones de conversión en cada
fila) y se prestaba a confusión. Se sustituye por dos tipos explícitos y **inmutables**.

- [X] T065 Separar la creación en dos botones, *Polilínea 2D* y *Polilínea 3D* (`AnnotationsPanel.jsx`),
  con el de 3D inoperante y explicado cuando la tarea no tiene DEM. El toggle Plana/Sobre el terreno
  desaparece del formulario, que ahora solo confirma el tipo ya elegido — revisa FR-010
- [X] T066 Fijar el tipo al crear: se eliminan las vistas `PolylineElevate`/`PolylineFlatten`, sus
  rutas y `contract.elevate()`/`Plugin.elevate()`; `PATCH` con un `mode` distinto del actual responde
  `400`. `CONTRACT_VERSION` sube a `2` — revisa FR-011, FR-020 y retira FR-039
- [X] T067 Distintivo 2D/3D en cada fila de la lista y en el formulario de creación; la fila se puede
  seleccionar (`annotations-list-item-selected`) y los botones Elevar/Aplanar/Volver a muestrear
  desaparecen: solo queda *Editar geometría* — FR-012
- [X] T068 Exportación por polilínea: nuevo `GET task/<pk>/polylines/<id>/export`, nombre de archivo
  `<tarea>-<polilínea>-2d|3d.geojson` (`contract.export_filename`), y el botón del pie exporta la
  fila seleccionada. El selector Vértices/Densificada solo se muestra con una 3D seleccionada. La
  ruta de exportación completa se conserva para el botón del panel de capas del core — revisa FR-032
- [X] T069 Tests: fuera `PolylineElevateFlattenTest` y los dos tests de `elevate` del contrato;
  entran `PolylineTypeIsImmutableTest` (rutas eliminadas, `PATCH` rechazado, mismo `mode` aceptado),
  `SinglePolylineExportTest` (sufijo 2d/3d, una sola feature, 404, geometry inválido),
  `test_elevate_is_no_longer_part_of_the_contract` y `test_get_densified_matches_the_stored_sampling`.
  **53 tests, exit 0**
- [X] T070 Documentación al día: `README.md` del plugin (sección v1→v2), `contracts/rest-api.md`,
  `contracts/plugin-contract.md` y los FR revisados en `spec.md`
