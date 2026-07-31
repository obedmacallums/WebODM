# Tasks: Etiquetado de ortofotos y exportación de datasets de entrenamiento

**Input**: Documentos de diseño de `/specs/009-training-dataset-labeling/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: SÍ se incluyen. El plan define la suite del plugin (`plan.md` §Project Structure) y
`quickstart.md` la usa como criterio de aceptación, así que las tareas de test son parte del
entregable, no opcionales.

**Organization**: las tareas se agrupan por historia de usuario para poder implementarlas y
probarlas de forma independiente.

## Alcance de esta entrega

Esta entrega implementa **US1 + US2** (`plan.md` §Alcance de esta entrega). US3, US4 y US5 quedan
recogidas al final como fases aplazadas, **sin checkbox a propósito**: no forman parte de este
tasks.md ejecutable y `/speckit-implement` no debe tocarlas.

Requisitos cubiertos: FR-001 a FR-017, FR-022 a FR-031, FR-035 a FR-038.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede ejecutar en paralelo (ficheros distintos, sin dependencias pendientes)
- **[Story]**: a qué historia pertenece la tarea (US1, US2)
- Cada descripción lleva la ruta exacta del fichero

## Path Conventions

Plugin de WebODM. Todo el código nuevo vive bajo `coreplugins/training/` (FR-035). No se toca
`app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/` ni ningún script de raíz.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dejar el plugin cargando en WebODM, aunque todavía no haga nada.

- [X] T001 Crear el árbol del plugin en `coreplugins/training/` con los subdirectorios `public/`, `public/tests/`, `templates/` y `tests/`, más `coreplugins/training/__init__.py` vacío
- [X] T002 [P] Escribir `coreplugins/training/manifest.json` con `name: "Training"`, `webodmMinVersion: "3.2.5"`, descripción, versión `1.0.0`, autor y tags, siguiendo `coreplugins/annotations/manifest.json`
- [X] T003 Escribir el esqueleto de `coreplugins/training/plugin.py`: `Plugin(PluginBase)` con `main_menu()` (entrada `Menu(_("Training"), self.public_url(""), ...)`, precedente `coreplugins/task-manager/plugin.py`), `app_mount_points()` con `MountPoint('$', index_view)`, `include_js_files()` → `['main.js']`, `build_jsx_components()` → `['Training.jsx']` y `api_mount_points()` devolviendo lista vacía por ahora
- [X] T004 Crear `coreplugins/training/tests/__init__.py` con la reexportación `from .test_plugin import *  # noqa: F401,F403`, copiando el docstring explicativo de `coreplugins/road/tests/__init__.py` (un módulo no reexportado **no se ejecuta** y la suite sigue en verde — pasó en `008`)
- [X] T005 Escribir `coreplugins/training/tests/test_plugin.py`: el plugin se carga, `manifest.json` es válido, y toda ruta de `api_mount_points()` termina en `$` (FR-035, convención de `rest-api.md`)

**Checkpoint**: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests` pasa y el plugin aparece en el menú principal.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: entidades y persistencia que US1 y US2 necesitan por igual.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta que esta fase esté completa.

- [X] T006 [P] Escribir `coreplugins/training/models.py` con las entidades puras (sin ORM de Django) `Dataset`, `Clase`, `Etiqueta` y `TareaDeDataset` según `data-model.md`, incluidas sus validaciones: ≥2 clases, índices consecutivos desde 0 (FR-003), clase 0 = fondo (FR-004), `resolution_cm_px > 0` con defecto 10,0 (FR-005), `tile_size_px` con defecto 512 (FR-024), `min_labeled_fraction` 0,01 y `min_valid_fraction` 0,50 (FR-027), y `schema_version = 1`
- [X] T007 Escribir `coreplugins/training/store.py`: `NAMESPACE = 'training'`, `LOCK_NAMESPACE = 0x74726169` (`'trai'`, distinto del `0x726F6164` de `road` y del `0x616E6E6F` de `annotations` para que los plugins no se bloqueen entre sí), y `document_lock()` con `pg_advisory_xact_lock` copiado de `coreplugins/annotations/store.py:31-40`, incluido el ajuste de `crc32` sin signo a int4 con signo
- [X] T008 Añadir a `coreplugins/training/store.py` el índice de datasets en `GlobalDataStore('training')`: clave `dataset_<id>` para cada uno y clave `datasets` con la lista de identificadores, más `create/list/get/update/delete` (D2, FR-016)
- [X] T009 Añadir a `coreplugins/training/store.py` la persistencia de etiquetas: un JSON por par (dataset, tarea) en `get_plugins_persistent_path('training', 'datasets', '<dataset_id>')/<task_id>.json`, con lectura, escritura bajo `document_lock` y asignación de `order` monótono creciente (FR-011, FR-012, FR-017)
- [X] T010 Añadir a `coreplugins/training/store.py` el cálculo **derivado** de `available` por tarea (la tarea existe y conserva ortofoto), sin persistirlo nunca: un valor guardado quedaría obsoleto en cuanto la tarea se borrase por otra vía (`data-model.md` §Tarea del dataset)
- [X] T011 Escribir `coreplugins/training/tests/test_store.py`: validaciones de `models.py`, ciclo CRUD del índice, aislamiento de etiquetas entre tareas del mismo dataset, `order` monótono, y que leer un dataset con una tarea borrada devuelve `available: false` en vez de fallar (invariante 5 de `data-model.md`)
- [X] T012 Reexportar `test_store` en `coreplugins/training/tests/__init__.py` y comprobar que el módulo corre por su nombre con `webodm.sh test backend coreplugins.training.tests.test_store`

**Checkpoint**: fundación lista — US1 y US2 pueden empezar.

---

## Phase 3: User Story 1 - Etiquetar la ortofoto a mano (Priority: P1) 🎯 MVP

**Goal**: crear un dataset con sus clases y dibujar sobre la ortofoto con polígonos, pincel y
borrador, con todo persistido y recuperable.

**Independent Test**: crear un dataset sobre una tarea, dibujar polígonos y trazos de dos clases,
recargar la página y comprobar que todo sigue ahí con sus clases y su orden (`quickstart.md`
Escenario 1).

### Tests for User Story 1 ⚠️

> Escribir estos tests ANTES de la implementación y comprobar que fallan.

- [X] T013 [P] [US1] Tests de la API de datasets en `coreplugins/training/tests/test_api_datasets.py`: alta, listado, detalle con `available` por tarea, `PATCH` y `DELETE`, y los códigos de error de `contracts/rest-api.md` — `no_orthophoto` (400), `too_few_classes` (400), `bad_class_indexes` (400), `bad_resolution` (400), `class_in_use` (409, con `label_count`, FR-006) y `dataset_has_labels` (409 al cambiar la resolución)
- [X] T014 [P] [US1] Tests de la API de etiquetas en `coreplugins/training/tests/test_api_labels.py`: `POST`/`PATCH`/`DELETE`, `order` devuelto en la respuesta, simplificación aplicada al guardar (FR-015), y los errores `unknown_class` (400), `bad_radius` (400), `bad_geometry` (400) y `task_not_in_dataset` (404)
- [X] T015 [P] [US1] Reexportar `test_api_datasets` y `test_api_labels` en `coreplugins/training/tests/__init__.py`

### Implementación backend

- [X] T016 [US1] Implementar `DatasetList` y `DatasetDetail` en `coreplugins/training/api.py` (GET/POST/GET/PATCH/DELETE) sobre `store.py`, con permisos de usuario autenticado y filtrado de tareas por acceso al proyecto, como hacen `road` y `annotations`
- [X] T017 [US1] Implementar `LabelList` y `LabelDetail` en `coreplugins/training/api.py` en el contexto (dataset, tarea), tomando `document_lock` en toda escritura y devolviendo el `order` asignado para que el frontend no tenga que releer la lista
- [X] T018 [US1] Implementar la simplificación al guardar en `coreplugins/training/api.py` (o helper en `models.py`): tolerancia igual a `resolution_cm_px` (FR-015). **Ojo**: las etiquetas se guardan en coordenadas geográficas (D4) y la tolerancia está en metros, así que hay que convertir la tolerancia a grados antes de simplificar — aplicarla cruda equivaldría a simplificar con una tolerancia cinco órdenes de magnitud mayor
- [X] T019 [US1] Implementar el borrador en `coreplugins/training/api.py` y `models.py`: una etiqueta con `class_index = null` que al rasterizar devuelve esos píxeles a «ignorar», distinto de pintar clase 0 (FR-014, `data-model.md` §Etiqueta)
- [X] T020 [US1] Registrar en `coreplugins/training/plugin.py` los `MountPoint` de datasets y etiquetas de `contracts/rest-api.md`, todos anclados con `$` y con las rutas literales **antes** que los patrones con identificador

### Implementación frontend — página global

- [X] T021 [P] [US1] Escribir `coreplugins/training/templates/index.html`, la página de gestión de datasets, siguiendo `coreplugins/task-manager/templates/index.html`
- [X] T022 [P] [US1] Escribir `coreplugins/training/public/datasets.js`: listar, crear (nombre, clases con nombre/color, resolución, tamaño de tesela, tareas) y borrar datasets contra la API; los colores por defecto de las clases evitan la escala verde/amarillo/rojo que `road` usa para la pendiente (FR-007)

### Implementación frontend — panel sobre el mapa

- [X] T023 [P] [US1] Escribir `coreplugins/training/public/main.js`: engancha el panel al mapa con `PluginsAPI`, como `coreplugins/road/public/main.js`
- [X] T024 [US1] Escribir `coreplugins/training/public/Training.jsx` y `coreplugins/training/public/TrainingPanel.jsx`: selección del dataset, selección de clase activa, control de radio del pincel y modo (polígono / pincel / borrador / selección)
- [X] T025 [US1] Escribir `coreplugins/training/public/LabelEditor.js` — modo polígono: trazado, arrastre de vértices, inserción y borrado, extendiendo el enfoque de `coreplugins/annotations/public/PolylineEditor.js` (un polígono es una polilínea cerrada) y silenciando el popup de la ortofoto del core vía `PluginsAPI.Map.onHandleClick` (D10)
- [X] T026 [US1] Añadir a `coreplugins/training/public/LabelEditor.js` el modo pincel: captura de arrastre continuo, desactivación del `dragging` del mapa mientras se pinta, y previsualización del radio **en metros sobre el terreno**, constante al hacer zoom (FR-010). Es la parte sin precedente en el repositorio (D10) y la de estimación más incierta
- [X] T027 [US1] Añadir a `coreplugins/training/public/LabelEditor.js` el modo borrador, que crea etiquetas con `class_index = null` y se dibuja de forma visiblemente distinta de la clase 0 (FR-014)
- [X] T028 [P] [US1] Escribir `coreplugins/training/public/labelLayer.js`: dibuja las etiquetas existentes sobre Leaflet con el color de su clase, los trazos con grosor derivado de `radius_m` en metros de terreno, y respetando el `order` en el apilado (FR-012)

### Tests de frontend

- [X] T029 [P] [US1] Escribir `coreplugins/training/public/tests/harness.js` resolviendo `jsdom` y `leaflet` del contenedor, copiando `coreplugins/road/public/tests/harness.js`
- [X] T030 [P] [US1] Escribir `coreplugins/training/public/tests/brushRadius.test.js`: el radio dibujado corresponde a los mismos metros de terreno a dos niveles de zoom distintos (FR-010)
- [X] T031 [P] [US1] Escribir `coreplugins/training/public/tests/labelLayer.test.js`: el apilado respeta `order` y cada clase usa su color
- [X] T032 [US1] Escribir `coreplugins/training/tests/test_frontend.py` que lanza los `.test.js` con `node`, con el `skipUnless` de `coreplugins/road/tests/test_frontend.py`, y reexportarlo en `coreplugins/training/tests/__init__.py`

**Checkpoint**: US1 completa e independientemente probable — se puede etiquetar y lo etiquetado sobrevive a la recarga, aunque todavía no se pueda exportar.

---

## Phase 4: User Story 2 - Exportar el dataset para entrenar fuera (Priority: P1)

**Goal**: convertir un dataset etiquetado en un `.zip` descargable con teselas, máscaras y
manifiesto, generado de forma asíncrona y sin construirse en memoria.

**Independent Test**: exportar un dataset etiquetado, descomprimirlo y comprobar que el manifiesto
describe exactamente el contenido y que las máscaras coinciden píxel a píxel con lo dibujado
(`quickstart.md` Escenario 3).

### Tests for User Story 2 ⚠️

> Escribir estos tests ANTES de la implementación y comprobar que fallan. Todos usan datos
> sintéticos: ninguno necesita una ortofoto real.

- [X] T033 [P] [US2] Escribir `coreplugins/training/tests/test_tiling.py`: la rejilla de una extensión conocida a una resolución dada produce el número esperado de teselas, con `transform` y `bounds` correctos por tesela, y es determinista entre dos llamadas
- [X] T034 [P] [US2] Escribir `coreplugins/training/tests/test_rasterize.py` con las invariantes 1–3 de `data-model.md`: un píxel sin etiqueta encima sale **255** y nunca 0 (FR-026); con solape gana la etiqueta de mayor `order` (FR-012); un trazo de radio *r* cubre el área de su `buffer` dentro del error de discretización (medido en D8: 118,14 m² frente a 118,25 m²); y el borrador devuelve la zona a 255
- [X] T035 [P] [US2] Escribir `coreplugins/training/tests/test_export.py`: el manifiesto declara todos los campos de `contracts/dataset-package.md`; los filtros de FR-027 descartan las teselas por debajo de `min_labeled_fraction` y `min_valid_fraction`; una tarea no disponible se excluye sin romper la exportación de las demás (invariante 5); y dos exportaciones sin cambios producen el mismo conjunto de teselas y el mismo manifiesto salvo marcas de tiempo (FR-031, invariante 6)
- [X] T036 [P] [US2] Reexportar `test_tiling`, `test_rasterize` y `test_export` en `coreplugins/training/tests/__init__.py`

### Implementación backend

- [X] T037 [P] [US2] Escribir `coreplugins/training/tiling.py`: rejilla de teselas cuadradas de `tile_size_px` sobre la extensión de una ortofoto a `resolution_cm_px`, devolviendo por tesela su fila, columna, ventana nativa, `transform` de salida y `bounds` en coordenadas geográficas. La ventana nativa se calcula en el CRS propio de la ortofoto (D4)
- [X] T038 [P] [US2] Escribir `coreplugins/training/rasterize.py`: dada una tesela y las etiquetas que la intersecan, produce un `uint8` de `tile_size_px²` relleno a 255 y pinta en orden ascendente de `order`; los trazos se convierten a superficie con `buffer()` del GEOS de GeoDjango **en el CRS métrico de la ortofoto** (FR-012b) y se alimentan a `rasterio.features.rasterize` en formato GeoJSON, como ya hace `road` (D8). Nunca se construye una máscara global (D5)
- [X] T039 [US2] Escribir `coreplugins/training/export.py`: recorre las teselas, lee las bandas RGB remuestreadas con `raster.read(indexes, window=..., out_shape=(3, N, N))` (D6), calcula `valid_fraction` con la banda alfa (D7), descarta según FR-027, escribe imagen y máscara como PNG (RGB de 3 canales y un canal de 8 bits sin paleta) y las va añadiendo al `.zip` en disco bajo `get_plugins_persistent_path`, sin acumular el paquete en memoria (FR-030)
- [X] T040 [US2] Añadir a `coreplugins/training/export.py` la construcción de `manifest.json` según `contracts/dataset-package.md`: `schema_version`, bloque `dataset`, `resolution_cm_px`, `tile_size_px`, `ignore_index: 255`, `classes`, `source_tasks` con `native_resolution_cm_px` y `crs`, y por tesela `image`, `label`, `task_id`, `row`, `column`, `bounds`, `labeled_fraction`, `valid_fraction` y `class_pixels` (sin incluir el 255) — FR-028, FR-029
- [X] T041 [US2] Implementar en `coreplugins/training/api.py` los endpoints de exportación de `contracts/rest-api.md`: `POST exports$` (202 con `export_id` y `celery_task_id`), `GET exports$` (estado y progreso), `GET exports/<id>/download$` y `DELETE exports/<id>$` (cancela si corre, borra el paquete si terminó), con el patrón de `coreplugins/road/api.py:338-379` y los errores `nothing_to_export`, `no_available_tasks`, `export_not_ready` (409) y `all_tiles_filtered` (400, con el recuento)
- [X] T042 [US2] Lanzar la exportación con `run_function_async(..., with_progress=True, with_cancel=True)` desde `coreplugins/training/api.py`, persistiendo `celery_task_id` y reportando progreso por tesela. **La función despachada debe ser self-contained**: `run_function_async` la recompila por código fuente con `ns = {}`, sin los globals de su módulo, así que sus imports van **dentro del cuerpo y son absolutos** (`from coreplugins.training import export, store`), nunca relativos ni por nombre libre. Las dependencias pesadas (`rasterio`, `numpy`, `PIL`) se importan en `export.py` y se alcanzan a través del módulo. Patrón exacto: `coreplugins/road/compute.py:744-761` (D9, Principio IV paso 3)
- [X] T043 [US2] Servir la descarga en `coreplugins/training/api.py` como respuesta con `Content-Disposition` sobre el fichero ya construido en disco, como `coreplugins/road/api.py:598-602` — nunca generado durante la petición (FR-030)
- [X] T044 [US2] Registrar en `coreplugins/training/plugin.py` los `MountPoint` de exportación, con `exports$` y las rutas literales antes del patrón de `<export_id>`, todas ancladas con `$`

### Implementación frontend

- [X] T045 [US2] Añadir a `coreplugins/training/public/datasets.js` el lanzamiento de la exportación, el sondeo del progreso, el enlace de descarga y la cancelación, sin bloquear la interfaz (FR-030, Escenario 6 de US2)
- [X] T046 [P] [US2] Añadir a `coreplugins/training/public/TrainingPanel.jsx` el estado de la exportación en curso del dataset activo, para que el progreso sea visible también desde el mapa

**Checkpoint**: US1 y US2 funcionan de forma independiente — se etiqueta y se obtiene un paquete descargable.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [X] T047 [P] Escribir `coreplugins/training/README.md`: qué hace el plugin, cómo se lanza su suite, y el enlace al contrato del paquete en `specs/009-training-dataset-labeling/contracts/dataset-package.md`
- [X] T048 Verificar la reexportación de la suite: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests` y cada módulo por su nombre; el total de la suite debe subir **exactamente** en el número de tests nuevos (`quickstart.md` §Suite completa)
- [X] T049 Ejecutar `quickstart.md` Escenarios 1, 2 y 3 sobre la tarea Mina La Coipa y registrar la salida: valores de máscara dentro de `{0, 1, 255}`, tantas imágenes como máscaras como entradas en `tiles`
- [X] T050 Ejecutar `quickstart.md` Escenario 4 — verificación del worker con Celery real (Principio IV paso 3, NO NEGOCIABLE): `docker compose restart webapp worker`, lanzar una exportación y comprobar `docker compose logs worker --since 10m | grep -cE "NameError|ImportError|AttributeError|Traceback"` → **0**, con la exportación en `completed` y `error: null`. Sin esta evidencia la feature no está completa
- [X] T051 Ejecutar `quickstart.md` Escenario 5 y registrar en `research.md` el coste real de exportar la mina: tiempo total, teselas que superaron los filtros frente a las 616 de la rejilla completa, tamaño del `.zip` y memoria máxima del worker (riesgo abierto 3 de `research.md`)
- [X] T052 Ejecutar `quickstart.md` Escenario 6: quitar o borrar la tarea del dataset y comprobar que el dataset sigue abriéndose y la excluye en vez de fallar
- [X] T053 Ejecutar `quickstart.md` Escenario 7 (no regresión, FR-036): `webodm.sh test backend coreplugins.road.tests` y `coreplugins.annotations.tests`, ambas en `OK`
- [X] T054 Comprobar FR-038 desde la administración de plugins (`/admin/plugins/`): deshabilitar `training` y verificar que WebODM y el resto de plugins siguen funcionando igual; los datasets y etiquetas quedan como datos inertes bajo `get_plugins_persistent_path('training', ...)`
- [ ] T055 Medir SC-004 con el panel de `coreplugins/training/public/TrainingPanel.jsx` sobre una pista de tierra de ~100 m: pintarla con pincel debe llevar menos tiempo que dibujarla con polígonos. Registrar ambas cifras en `specs/009-training-dataset-labeling/research.md`; es la única justificación del coste del pincel (D10)

---

## Fases aplazadas (fuera de esta entrega)

Recogidas aquí para no perderlas; **sin checkbox a propósito**, porque no forman parte de este
tasks.md ejecutable. Al abordarlas se generarán sus tareas con numeración propia.

**US3 — Reunir varias tareas en un mismo dataset (P2)**. El modelo de datos ya lo soporta (FR-002,
T006–T010); falta la interfaz de añadir y quitar tareas, y el filtrado de etiquetas por tarea en el
panel. Fuera del camino crítico porque una sola tarea —la mina— aporta 616 de las 912 teselas (D11).

**US4 — Traer etiquetas hechas fuera (P2)**. FR-018 a FR-021: subida de GeoJSON, mapeo de una
propiedad a las clases, reproyección al CRS del dataset, rechazo con motivo exacto y recuento de
geometrías fuera de la extensión.

**US5 — Saber si el dataset sirve antes de gastar horas de GPU (P3)**. FR-032 a FR-034: resumen con
teselas previstas y superficie por clase, advertencia por ausencia de clase 0 y por volumen
insuficiente, sin impedir exportar.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias, empieza de inmediato
- **Foundational (Phase 2)**: depende de Setup — BLOQUEA ambas historias
- **US1 (Phase 3)** y **US2 (Phase 4)**: dependen de Foundational
- **Polish (Phase 5)**: depende de US1 y US2

### User Story Dependencies

- **US1 (P1)**: puede empezar tras la Phase 2. Sin dependencias de otras historias
- **US2 (P1)**: puede empezar tras la Phase 2 y es probable de forma independiente con etiquetas
  sintéticas insertadas por `store.py` — no necesita el editor de US1. Para la validación manual de
  `quickstart.md` sí necesita etiquetas reales, es decir US1

### Within Each User Story

- Los tests van antes de la implementación y deben fallar primero
- `models.py` y `store.py` (Phase 2) antes que `api.py`
- `tiling.py` y `rasterize.py` antes que `export.py` (T037, T038 → T039)
- `export.py` antes que los endpoints de exportación (T039, T040 → T041)
- Backend antes que el frontend que lo consume (T016, T017 → T022, T024)

### Parallel Opportunities

- **Phase 1**: T002 en paralelo con T003
- **Phase 2**: T006 en paralelo con T007 (ficheros distintos); T008–T010 son secuenciales entre sí
  porque tocan `store.py`
- **Phase 3**: los tests T013–T015 en paralelo; después T021, T022, T023 y T028 en paralelo (cuatro
  ficheros distintos); T025–T027 son secuenciales porque comparten `LabelEditor.js`; los tests JS
  T029–T031 en paralelo
- **Phase 4**: los tests T033–T036 en paralelo; T037 y T038 en paralelo; T046 en paralelo con T045
- **Entre historias**: con dos personas, una toma US1 y otra US2 en cuanto termine la Phase 2

---

## Parallel Example: User Story 2

```bash
# Los tests de US2 primero, todos a la vez (ficheros distintos, datos sintéticos):
Task: "Escribir tests de rejilla en coreplugins/training/tests/test_tiling.py"
Task: "Escribir tests de invariantes de máscara en coreplugins/training/tests/test_rasterize.py"
Task: "Escribir tests de manifiesto y filtros en coreplugins/training/tests/test_export.py"

# Después, los dos módulos de cálculo, que no se tocan entre sí:
Task: "Escribir la rejilla de teselas en coreplugins/training/tiling.py"
Task: "Escribir el rasterizado por tesela en coreplugins/training/rasterize.py"
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1: Setup
2. Phase 2: Foundational (CRÍTICA — bloquea todo)
3. Phase 3: US1
4. **PARAR Y VALIDAR**: `quickstart.md` Escenarios 1 y 2. Se puede etiquetar y lo etiquetado
   sobrevive

En este punto el usuario ya puede empezar a etiquetar la mina mientras se construye la exportación.
Es trabajo suyo que no se pierde y que no depende de US2.

### Incremental Delivery

1. Setup + Foundational → fundación lista
2. US1 → validar → el usuario puede etiquetar (MVP)
3. US2 → validar → hay paquete de entrenamiento; **la entrega no está completa sin T050**, la
   verificación del worker con Celery real
4. Las fases aplazadas (US3, US4, US5) llegan después sin romper nada de lo anterior

### Riesgos que esta ordenación asume

- **El pincel (T026) no tiene precedente en el repositorio** (D10). Es la tarea de estimación más
  incierta de la entrega y conviene atacarla pronto dentro de US1, no al final
- **T050 no lo cubre ningún test** (D9). Es evidencia de ejecución real, no de suite

---

## Notes

- `[P]` = ficheros distintos, sin dependencias pendientes
- La etiqueta `[Story]` mapea cada tarea a su historia para poder rastrearla
- Verificar que los tests fallan antes de implementar
- **Nunca** `./run_tests_in_docker.sh`: hace `docker compose down -v` y destruiría las tareas reales
  del usuario. Los tests corren contra el stack vivo con
  `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests`
- Todo módulo de test nuevo debe reexportarse en `tests/__init__.py` o **no se ejecuta y la suite
  sigue en verde** (pasó en `008`)
- Commit tras cada tarea o grupo lógico
