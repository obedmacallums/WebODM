---

description: "Task list for feature implementation"
---

# Tasks: Análisis de visibilidad (viewshed) desde un punto en la vista 2D

**Input**: Design documents from `/specs/001-viewshed-analysis/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md (todos presentes)

**Tests**: Solicitados explícitamente por plan.md ("Testing: Django tests en
`coreplugins/viewshed/tests.py`, ejecutados en Docker") y por quickstart.md (sección 3).
Se incluyen tareas de test.

**Organization**: Tareas agrupadas por user story (US1/US2/US3 de spec.md) para permitir
implementación y prueba independiente de cada una. Patrón de referencia verificado en el
repo: `coreplugins/contours/` (estructura de plugin, `api.py`, `plugin.py`, `main.js`).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Se puede ejecutar en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: User story a la que pertenece la tarea (US1, US2, US3)
- Rutas de archivo exactas en cada descripción

## Path Conventions

Plugin autocontenido en `coreplugins/viewshed/` (ver Project Structure de plan.md):

```text
coreplugins/viewshed/
├── __init__.py
├── manifest.json
├── plugin.py
├── api.py
├── tests.py
└── public/
    ├── main.js
    ├── Viewshed.jsx
    ├── Viewshed.scss
    ├── ViewshedPanel.jsx
    ├── ViewshedPanel.scss
    └── icon.svg
```

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Crear el esqueleto del plugin siguiendo la Convención III de la constitución.

- [X] T001 Crear directorio `coreplugins/viewshed/` con `__init__.py` vacío (paquete Python), calcado de `coreplugins/contours/__init__.py`
- [X] T002 [P] Crear `coreplugins/viewshed/manifest.json` (nombre "Viewshed", descripción, versión "1.0.0", autor, `webodmMinVersion` igual al de `coreplugins/contours/manifest.json`, tags `["viewshed", "visibility", "dsm", "dtm"]`)
- [X] T003 [P] Crear `coreplugins/viewshed/public/icon.svg` (icono del control del mapa; puede partir de un ícono simple de "ojo"/visibilidad)

**Checkpoint**: estructura de directorios y metadatos del plugin listos; sin lógica aún.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Registrar el plugin en el framework (montaje de endpoints y assets JS) antes
de implementar cualquier user story. Sin este registro ninguna historia es verificable.

**⚠️ CRITICAL**: ninguna user story puede probarse end-to-end sin esta fase completa.

- [X] T004 Crear `coreplugins/viewshed/api.py` con las clases vacías `TaskViewshedGenerate(TaskView)` (con método `post` que aún no calcula, solo retorna `Response({'error': 'not implemented'})`) y `TaskViewshedDownload(GetTaskResult)` (`pass`, igual a `TaskContoursDownload` en `coreplugins/contours/api.py`), importando `TaskView`/`GetTaskResult` desde `app.plugins.views`
- [X] T005 Crear `coreplugins/viewshed/plugin.py` con `class Plugin(PluginBase)`: `include_js_files` → `['main.js']`, `build_jsx_components` → `['Viewshed.jsx']`, `api_mount_points` → monta `task/(?P<pk>[^/.]+)/viewshed/generate` a `TaskViewshedGenerate.as_view()` y `task/[^/.]+/viewshed/download/(?P<celery_task_id>.+)` a `TaskViewshedDownload.as_view()` (mismo patrón que `coreplugins/contours/plugin.py`)
- [X] T006 [P] Crear `coreplugins/viewshed/public/main.js` que registre `PluginsAPI.Map.willAddControls(['viewshed/build/Viewshed.js', 'viewshed/build/Viewshed.css'], ...)` y agregue el control al mapa solo cuando `args.tiles` referencie una única tarea (copiar y adaptar `coreplugins/contours/public/main.js`)
- [X] T007 Habilitar el plugin en el entorno de desarrollo local (`./webodm.sh restart --build` o `docker compose up -d --build`) y confirmar en `docker compose logs webapp | grep -i viewshed` que carga y compila sin errores (primera mitad de quickstart.md sección 1)

**Checkpoint**: el plugin aparece registrado (endpoints montados, JS resuelto); base lista para implementar US1.

---

## Phase 3: User Story 1 - Generar zonas visibles desde un punto (Priority: P1) 🎯 MVP

**Goal**: el usuario activa la herramienta en la vista 2D, hace clic en un punto y ve
sobre el mapa las zonas visibles desde ese punto según la topografía, con altura de
observador por defecto de 1,60 m (FR-001 a FR-004, FR-006, FR-009 a FR-012).

**Independent Test**: con una tarea procesada con DSM, activar la herramienta, hacer clic
en un punto y verificar que aparece una capa de zonas visibles coherente con el terreno.

### Tests for User Story 1 ⚠️

> Escribir estas pruebas primero y confirmar que fallan antes de implementar `calc_viewshed`/`TaskViewshedGenerate`.

- [X] T008 [P] [US1] Crear `coreplugins/viewshed/tests.py` con caso `ViewshedApiTest(BootTestCase)` (o base equivalente usada por `app/tests/test_api_task.py`) que cubra: tarea sin DSM/DTM → `generate` responde `{'error': ...}` (FR-010); tarea con permisos insuficientes → 403/404 (FR-012) — usar fixtures/patrón de `app/tests/test_api_task.py` para crear proyecto/tarea de prueba
- [X] T009 [US1] Añadir a `coreplugins/viewshed/tests.py` un test de éxito para `calc_viewshed()` usando un DSM de prueba pequeño (GeoTIFF sintético generado en el propio test con `osgeo.gdal`/`numpy`, sin depender de datasets externos): verifica que retorna `{'file': <ruta existente>}` y que el archivo es un GeoJSON `FeatureCollection` válido

### Implementation for User Story 1

- [X] T010 [US1] Implementar `calc_viewshed(dem, lat, lng, observer_height, epsg)` en `coreplugins/viewshed/api.py`: localizar binarios `gdal_viewshed`/`gdal_polygonize.py`/`ogr2ogr` con `shutil.which()` (error claro si falta alguno); transformar `(lat, lng)` de EPSG:4326 al CRS del DEM con `osgeo.osr`; validar que el punto cae dentro del extent y no es nodata (D3/D9 de research.md); invocar `gdal_viewshed` por `subprocess` con `-ox/-oy` (punto transformado), `-oz <observer_height>`, `-tz 0`, sin `-md`; en archivo temporal bajo `settings.MEDIA_TMP` (patrón `tempfile.mkdtemp('_viewshed', dir=settings.MEDIA_TMP)` de `calc_contours`)
- [X] T011 [US1] Extender `calc_viewshed` en `coreplugins/viewshed/api.py` para poligonizar el raster de salida con `gdal_polygonize.py` y reproyectar/convertir a GeoJSON EPSG:4326 con `ogr2ogr` (D5 de research.md); retornar `{'file': outfile}` en éxito o `{'error': <mensaje>}` en cualquier fallo de subprocess (`returncode != 0`)
- [X] T012 [US1] Implementar `TaskViewshedGenerate.post` en `coreplugins/viewshed/api.py`: `task = self.get_and_check_task(request, pk)` (FR-012); resolver DEM con DSM preferido (`task.dsm_extent` + `get_asset_download_path("dsm.tif")`), DTM como respaldo (`task.dtm_extent` + `get_asset_download_path("dtm.tif")`); si ninguno existe, `Response({'error': _('La tarea no tiene modelo de elevación.')})` (FR-001/FR-010); parsear `lat`/`lng` del body, validar rangos (−90/90, −180/180); leer `observer_height = float(request.data.get('observer_height', 1.6))` con validación básica `0 ≤ h ≤ 500` (FR-004/FR-005 — el default funcional ya vive en US1; el campo editable en la UI llega en US2/T027); lanzar `run_function_async(calc_viewshed, dem, lat, lng, observer_height, task.epsg or 4326).task_id` y responder `{'celery_task_id': ...}` (patrón exacto de `TaskContoursGenerate.post`)
- [X] T013 [US1] Aplicar el orden de validación server-side de data-model.md en `TaskViewshedGenerate.post`: permisos → disponibilidad de DEM → tipos/rangos de `lat`/`lng`/`observer_height` → punto dentro de extent y no-nodata → solo entonces `run_function_async` (evita cálculos costosos con datos inválidos)
- [X] T014 [P] [US1] Crear `coreplugins/viewshed/public/Viewshed.jsx`: `L.Control` con botón que alterna un panel (`ViewshedPanel`), calcado de `ContoursButton`/`export default L.Control.extend(...)` en `coreplugins/contours/public/Contours.jsx`, usando `public/icon.svg` (T003) en vez del ícono de contours
- [X] T015 [P] [US1] Crear `coreplugins/viewshed/public/Viewshed.scss` con los estilos del botón del control (adaptar selectores de `coreplugins/contours/public/Contours.scss` a la clase `leaflet-control-viewshed`)
- [X] T016 [US1] Crear `coreplugins/viewshed/public/ViewshedPanel.jsx` (esqueleto): componente React con `props.map`/`props.tasks`/`props.isShowed`/`props.onClose` (mismas propTypes que `ContoursPanel`), estado inicial `{error, loading: false, capturingPoint: false, resultLayer: null}`
- [X] T017 [US1] En `ViewshedPanel.jsx`, implementar el modo de captura de clic sobre el mapa: al activar la herramienta, registrar `this.props.map.on('click', this.handleMapClick)`; `handleMapClick(e)` toma `e.latlng.lat/lng`, desactiva el modo de captura y dispara el análisis (FR-002); limpiar el listener en `componentWillUnmount` (patrón de cleanup de `ContoursPanel.componentWillUnmount`)
- [X] T018 [US1] En `ViewshedPanel.jsx`, implementar `generateViewshed(lat, lng, observerHeight)`: POST a `` /api/plugins/viewshed/task/${taskId}/viewshed/generate `` con `{lat, lng, observer_height: observerHeight}`, luego `Workers.waitForCompletion(result.celery_task_id, error => ...)` igual que `ContoursPanel.generateContours` (D4/D6 de research.md); mostrar spinner/indicador de progreso mientras `loading` es true (FR-009) sin bloquear el mapa
- [X] T019 [US1] En `ViewshedPanel.jsx`, al completar el job sin error, cargar el GeoJSON desde `` /api/plugins/viewshed/task/${taskId}/viewshed/download/${celery_task_id} `` con `$.getJSON` y agregarlo como capa `L.geoJSON` al mapa con estilo semitransparente que distinga visualmente las zonas visibles (FR-006), guardando la referencia en `this.state.resultLayer`
- [X] T020 [US1] En `ViewshedPanel.jsx`, mostrar mensajes de error claros y accionables (usar `ErrorMessage` de `webodm/components/ErrorMessage`, patrón de `ContoursPanel`) para: sin modelo de elevación, punto fuera de cobertura, y cualquier error de dominio devuelto por el backend (FR-010) — cero fallos silenciosos
- [X] T021 [US1] Verificar la condición de disponibilidad de la herramienta (FR-001): en `ViewshedPanel.jsx`, al montar, consultar `` /api/projects/${project}/tasks/${id}/ `` (patrón `componentDidUpdate` de `ContoursPanel`) y deshabilitar/ocultar la herramienta con mensaje si `available_assets` no incluye `dsm.tif` ni `dtm.tif`
- [X] T022 [US1] Ejecutar `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.viewshed.tests` (o `./run_tests_in_docker.sh backend coreplugins.viewshed.tests`) y confirmar exit code 0, mostrando la salida completa (regla `verification-before-completion`)
- [X] T023 [US1] Verificación de worker (Principio IV.3, obligatoria): con el stack levantado, lanzar un análisis real desde la UI, y confirmar en `docker compose logs worker --tail 50 | grep -iE "viewshed|error"` que el job corrió sin `ImportError`/`ModuleNotFoundError`/fallos de GDAL y que el resultado llegó al mapa (escenario 1 de quickstart.md, sección 2 y 4)

**Checkpoint**: US1 completa y verificable de forma independiente — MVP funcional.

---

## Phase 4: User Story 2 - Ajustar la altura del observador (Priority: P2)

**Goal**: el usuario puede cambiar la altura del observador antes de lanzar el análisis
(default 1,60 m) y el resultado refleja esa altura, con validación de rango (FR-004, FR-005).

**Independent Test**: ejecutar dos análisis desde el mismo punto con alturas distintas
(1,60 m y 30 m) y verificar que el de mayor altura produce un área visible mayor o igual.

### Tests for User Story 2 ⚠️

- [X] T024 [P] [US2] Añadir a `coreplugins/viewshed/tests.py` casos para `TaskViewshedGenerate.post` con `observer_height` inválido: negativo, no numérico, y mayor a 500 → debe responder `{'error': ...}` sin lanzar `run_function_async` (FR-005)
- [X] T025 [P] [US2] Añadir a `coreplugins/viewshed/tests.py` un caso que compare, sobre el mismo DSM sintético de T009, el área resultante de `calc_viewshed` con `observer_height=1.6` vs `observer_height=30`, verificando que el área (conteo de features/celdas) con 30 m es mayor o igual

### Implementation for User Story 2

- [X] T026 [US2] Refinar la validación de `observer_height` en `TaskViewshedGenerate.post` (`coreplugins/viewshed/api.py`) con mensajes de error específicos por caso (no numérico, negativo, mayor a 500) en vez del mensaje genérico de T012; la lectura con default `1.6` ya existe desde US1 (T012) — esta tarea solo mejora el texto/granularidad del error (FR-005) — depende de T012
- [X] T027 [US2] En `ViewshedPanel.jsx`, agregar el campo de altura del observador: `<input type="number">` con valor por defecto `1.60` (visible siempre, incluso sin modificar — FR-004), pasado como `observer_height` en el POST de T018
- [X] T028 [US2] En `ViewshedPanel.jsx`, validar el campo de altura en el cliente antes de habilitar el botón de generar (numérico, 0–500) usando `Utils.isNumeric` (como en `ContoursPanel.getFormValues`/`disabled`), mostrando el motivo del rechazo si es inválido (espejo cliente de FR-005, defensa en profundidad de la validación server-side de T026)

**Checkpoint**: US1 y US2 funcionan de forma independiente y combinada.

---

## Phase 5: User Story 3 - Gestionar el resultado en el mapa (Priority: P3)

**Goal**: el usuario puede quitar la capa de resultado, y un nuevo análisis reemplaza al
anterior automáticamente (FR-007, FR-008).

**Independent Test**: generar un análisis, quitarlo y verificar que el mapa queda limpio;
generar dos análisis consecutivos y verificar que solo se muestra el último.

### Tests for User Story 3 ⚠️

- [X] T029 [P] [US3] Añadir a `coreplugins/viewshed/tests.py` (o a un test de frontend si el proyecto tiene runner JS) un caso que documente el contrato: como no hay endpoint de "clear", esta historia es puramente de estado de cliente — verificar mediante inspección de `ViewshedPanel.jsx` en revisión de código/test manual de quickstart.md escenario 5 (no requiere test backend adicional)

### Implementation for User Story 3

- [X] T030 [US3] En `ViewshedPanel.jsx`, antes de agregar una nueva capa de resultado (T019), remover la capa anterior si `this.state.resultLayer` existe (`this.props.map.removeLayer(this.state.resultLayer)`), garantizando una sola capa activa a la vez (FR-008) — depende de T019
- [X] T031 [US3] En `ViewshedPanel.jsx`, agregar un botón/acción "Quitar" visible solo cuando hay `resultLayer` activo, que remueva la capa del mapa y limpie `this.state.resultLayer` (FR-007), siguiendo el patrón de `handleRemovePreview` de `ContoursPanel`
- [X] T032 [US3] En `ViewshedPanel.jsx`, cancelar/descartar la respuesta de un análisis en curso si el usuario lanza uno nuevo antes de que termine (abortar el `$.ajax`/polling anterior en `componentWillUnmount`-style o guardando la referencia, patrón `this.generateReq.abort()` de `ContoursPanel`), evitando resultados mezclados (edge case del spec)

**Checkpoint**: las tres user stories funcionan de forma independiente y en conjunto.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: cierre de calidad transversal a las tres historias.

- [X] T033 [P] Revisar textos de usuario (`_(...)`) en `coreplugins/viewshed/api.py` y `coreplugins/viewshed/public/ViewshedPanel.jsx` para que todos los mensajes de error sean claros y accionables (FR-010, SC-003)
- [X] T034 Ejecutar el checklist funcional completo de `specs/001-viewshed-analysis/quickstart.md` sección 2 (los 6 escenarios de la tabla) contra el stack en Docker y registrar el resultado de cada uno
- [X] T035 Confirmar criterios de éxito medibles de quickstart.md sección 5 (SC-001 ≤ 3 interacciones, SC-002 < 15 s en dataset típico) con evidencia (capturas o logs con timestamps)
- [X] T036 Ejecutar de nuevo `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.viewshed.tests` tras todos los cambios y confirmar exit code 0 (regla `verification-before-completion`, cierre de feature)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — puede iniciar de inmediato
- **Foundational (Phase 2)**: depende de Setup — BLOQUEA todas las user stories
- **User Stories (Phase 3+)**: todas dependen de Foundational
  - US1 (P1) no depende de otras historias
  - US2 (P2) depende de que existan `TaskViewshedGenerate.post` (T012) y `ViewshedPanel.jsx` (T016-T019) de US1 — extiende esos mismos puntos, no es paralela a US1 en la práctica aunque sí lo es conceptualmente en spec.md
  - US3 (P3) depende de que exista la capa de resultado de US1 (T019) para poder gestionarla
- **Polish (Phase 6)**: depende de que las historias deseadas estén completas

### User Story Dependencies

- **US1**: fundacional para el resto; sin dependencias de otras historias
- **US2**: modifica/extiende archivos creados en US1 (`api.py`, `ViewshedPanel.jsx`) — secuencial respecto a US1 en este plugin (un solo endpoint, un solo panel), aunque la historia es independientemente probable una vez integrada
- **US3**: modifica/extiende `ViewshedPanel.jsx` de US1 — secuencial respecto a US1 por la misma razón

### Within Each User Story

- Tests antes de la implementación (T008-T009 antes de T010-T021; T024-T025 antes de T026-T028)
- Backend (`calc_viewshed`, `TaskViewshedGenerate`) antes del frontend que lo consume
- Implementación core antes de la verificación de worker/quickstart

### Parallel Opportunities

- T002 y T003 en paralelo (archivos distintos, Setup)
- T008 y T009 en paralelo (mismo archivo `tests.py` pero casos independientes — si se prefiere estrictamente sin conflictos, ejecutar T008 antes de T009 en el mismo archivo)
- T014 y T015 en paralelo (archivos distintos: `.jsx` y `.scss`)
- T024 y T025 en paralelo (casos de test independientes)

---

## Parallel Example: User Story 1

```bash
# Tests de US1 (backend), en paralelo:
Task: "Crear coreplugins/viewshed/tests.py con casos de error de disponibilidad de DEM/permisos"
Task: "Añadir test de éxito para calc_viewshed() con DSM sintético"

# Frontend base de US1, en paralelo:
Task: "Crear coreplugins/viewshed/public/Viewshed.jsx (control Leaflet)"
Task: "Crear coreplugins/viewshed/public/Viewshed.scss"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Completar Phase 1: Setup
2. Completar Phase 2: Foundational (bloquea todo lo demás)
3. Completar Phase 3: User Story 1
4. **DETENER y VALIDAR**: correr `coreplugins/viewshed/tests.py` en Docker + escenarios 1, 2, 6 de quickstart.md
5. Con esto ya hay un plugin funcional con altura fija de 1,60 m — MVP entregable

### Incremental Delivery

1. Setup + Foundational → base del plugin registrada y cargando
2. + US1 → primer análisis de visibilidad funcional → validar independientemente (MVP)
3. + US2 → altura configurable con validación → validar independientemente
4. + US3 → gestión de capa (quitar/reemplazar) → validar independientemente
5. + Polish → checklist completo de quickstart.md y cierre de verificación

---

## Notes

- [P] = archivos distintos, sin dependencias entre sí
- [Story] mapea cada tarea a su user story para trazabilidad con spec.md
- Cero dependencias nuevas en todo el plan (Principio IV, nivel 0) — no hay tareas de `requirements.txt` ni `Dockerfile`
- La verificación de worker (T023) es NO NEGOCIABLE según Principio IV.3 de la constitución
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida (regla global `verification-before-completion`)
- Evitar: tareas vagas, conflictos de archivo simultáneos, dependencias cruzadas entre historias que rompan la independencia declarada en spec.md
