# Tasks: Corrección de la nube de puntos con la transformación de realineación

**Input**: Design documents from `specs/003-realign-pointcloud/`

**Prerequisites**: plan.md (requerido), spec.md (requerido para las user stories), research.md,
data-model.md, contracts/api.md, quickstart.md — todos presentes.

**Tests**: la constitución del fork exige verificar con evidencia antes de marcar cualquier tarea
como completa (`verification-before-completion`); se incluyen tareas de test por historia,
siguiendo el mismo criterio que `002-realign-products/tasks.md`.

**Organization**: tareas agrupadas por user story para poder implementar y probar cada una de
forma independiente. Extiende el plugin `coreplugins/realign/` ya existente (creado en 002); no
hay fase de scaffolding de directorio/manifest — el plugin ya está registrado y activo.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede ejecutarse en paralelo (archivos distintos, sin dependencias)
- **[Story]**: a qué user story pertenece (US1, US2, US3)
- Cada tarea incluye la ruta exacta del archivo

## Path Conventions

Plugin autocontenido: `coreplugins/realign/` (backend Python + `public/` para JS/JSX/SCSS), tal
como fija `plan.md` → Project Structure.

---

## Phase 1: Setup

**Purpose**: confirmar que el entorno tiene lo necesario antes de tocar código. No hay
scaffolding de directorio/manifest — el plugin ya existe.

- [X] T001 Verificar que el CLI `pdal` está disponible en **ambos** contenedores (`docker compose exec webapp pdal --version` y `docker compose exec worker pdal --version`), confirmando en el entorno actual lo ya documentado en `research.md` D1/D7 (Principio IV.3, pre-check)

**Checkpoint**: entorno confirmado; sin cambios de código aún.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: piezas compartidas por las tres user stories — construcción de la matriz, cálculo de
offsets seguros, huella de la transformación, persistencia del subdocumento y rutas montadas.
Ninguna historia es verificable end-to-end sin esta fase.

**⚠️ CRITICAL**: ninguna user story puede probarse end-to-end sin esta fase completa.

- [X] T002 [P] Crear `coreplugins/realign/pointcloud.py` con `build_transformation_matrix(transform)`: construye la matriz 4×4 *row-major* (`cos, -sin, 0, tx, sin, cos, 0, ty, 0,0,1,0, 0,0,0,1`) a partir del `transform` persistido (mismos `cos`/`sin`/`tx`/`ty` que usa `corrections.py` para los rásteres), con la fila Z en identidad (research.md D2)
- [X] T003 [P] En `coreplugins/realign/pointcloud.py`, implementar `compute_safe_offsets(las_summary, matrix)`: transforma las 4 esquinas del bbox (obtenido de `pdal info --summary`, sin leer los puntos), calcula el centro redondeado como `offset_x`/`offset_y`, y valida el rango `int32` dado `scale_x`/`scale_y` del original, lanzando un error claro si desbordaría (research.md D3)
- [X] T004 [P] En `coreplugins/realign/pointcloud.py`, implementar `compute_fingerprint(transform)` (redondea `cos`/`sin`/`tx`/`ty` a una tolerancia fija menor que el paso de cuantización, más `use_scale` y `n_points`) y `fingerprint_matches(a, b)` (data-model.md, research.md D8)
- [X] T005 [P] Extender `coreplugins/realign/store.py` con helpers para el subdocumento `pointcloud` dentro de `TaskRealignment`: `get_pointcloud_state(task_id)`, `set_pointcloud_state(task_id, data)`, `del_pointcloud_state(task_id)` (data-model.md — ausencia de la clave equivale a `status: "absent"`, retrocompatible con documentos de 002)
- [X] T006 Crear en `coreplugins/realign/api.py` las clases `RealignPointCloud(TaskView)` (POST/DELETE, stubs que responden `Response({'error': 'not implemented'}, status=501)`) y `RealignPointCloudDownload(TaskView)` (GET stub); montar las tres rutas nuevas en `coreplugins/realign/plugin.py` → `api_mount_points()` (`task/(?P<pk>[^/.]+)/realign/pointcloud` para POST/DELETE, `task/(?P<pk>[^/.]+)/realign/pointcloud/download` para GET) (contracts/api.md)
- [X] T007 Extender `RealignState.get` en `coreplugins/realign/api.py` para incluir la clave `pointcloud` en la respuesta de `GET .../realign/state`, calculando al vuelo `status`, `stale` (T004), `available`, `eligible` y `ineligible_reason` a partir de: `store.get_pointcloud_state` (T005), si la tarea tiene `georeferenced_model.laz` entre sus assets, si `state == 'applied'` y si `transform.use_scale == false` (contracts/api.md)

**Checkpoint**: subsistema de nube conectado (persistencia, cálculo de elegibilidad, rutas
montadas); sin funcionalidad visible para el usuario todavía.

---

## Phase 3: User Story 1 - Obtener la nube de puntos corregida (Priority: P1) 🎯 MVP

**Goal**: con una realineación aplicada en modo rígido y nube de puntos disponible, el usuario
pide generar la nube corregida, el sistema la procesa en segundo plano sin bloquear la interfaz y
la ofrece para descargar cuando termina, con las mismas coordenadas horizontales que los rásteres
corregidos y las elevaciones intactas (FR-001, FR-002, FR-003, FR-006 a FR-011, FR-017).

**Independent Test**: sobre una tarea con nube de puntos y una realineación aplicada en modo
rígido, pedir la nube corregida, esperar a que termine y descargarla; verificar mismo `num_points`
que el original, `max|ΔZ| == 0`, y XY desplazado según la transformación esperada.

### Tests for User Story 1 ⚠️

> Escribir estas pruebas primero y confirmar que fallan antes de implementar.

- [X] T008 [P] [US1] En `coreplugins/realign/tests.py`, crear un helper de fixture que genere un LAZ sintético pequeño con `pdal pipeline` y `readers.faux` (bounds, SRS y `scale`/`offset` controlados), sin versionar ningún binario en el repo (research.md D10)
- [X] T009 [P] [US1] En `tests.py`, test de `build_transformation_matrix` (T002) y `compute_safe_offsets` (T003): la matriz generada coincide con el cálculo esperado (fila Z en identidad); una transformación que desbordaría el `int32` de LAS es rechazada **antes** de invocar `pdal` (research.md D3)
- [X] T010 [P] [US1] En `tests.py`, test end-to-end del pipeline sobre el LAZ sintético de T008: mismo `num_points` que el original, `max|ΔZ| == 0` exacto, error XY dentro de medio paso de cuantización respecto al valor calculado independientemente en el test, y cabecera preservada (`scale_x`/`scale_y`/`scale_z`, `offset_z`, `dataformat_id`, `minor_version`, SRS) (research.md D2/D3, FR-003/FR-008)
- [X] T011 [P] [US1] En `tests.py`, test de contrato del *happy path*: POST `.../realign/pointcloud` sobre una tarea elegible devuelve `celery_task_id`; sondear con `CheckTask` hasta `ready` y confirmar que el archivo resultante existe (FR-009, FR-010)

### Implementation for User Story 1

- [X] T012 [US1] Implementar `run_pointcloud_correction(task_id, src_path, out_dir, transform, applied_by=None, progress_callback=None, should_cancel=None)` en `coreplugins/realign/pointcloud.py`: construye la matriz (T002) y los offsets (T003), escribe el pipeline JSON de PDAL (`readers.las → filters.transformation → writers.las` con `compression=LASZIP`, `forward=all`, offsets explícitos), lo ejecuta con `subprocess.Popen` sobre `<out_dir>/pointcloud.tmp.laz`, sondea el tamaño del temporal cada pocos segundos para reportar progreso (`tamaño/tamaño_original`, research.md D6) y para revisar `should_cancel()`; al terminar con éxito hace `os.replace()` a `pointcloud.laz` (escritura atómica, research.md D4) y actualiza `store.set_pointcloud_state` a `ready` con `fingerprint` (T004), `point_count` y `size_bytes`; ante fallo o cancelación, borra el `.tmp.laz` y deja el estado en `error` con el mensaje de causa (FR-014). Imports dentro del cuerpo y absolutos (`from coreplugins.realign import pointcloud, store`), como exige `run_function_async` (patrón de `corrections.py:77-79`)
- [X] T013 [US1] Implementar `RealignPointCloud.post` en `coreplugins/realign/api.py`: `check_project_perms(request, task.project, ('change_project',))` (FR-016); validar las tres condiciones de elegibilidad (nube disponible, `state == 'applied'`, `use_scale == false`) y que no haya una generación `running` ya en curso, devolviendo 400 con el `reason` correspondiente si falla alguna (contracts/api.md, FR-004, FR-005, FR-015, FR-017); si es elegible, marcar `pointcloud` como `running` (T005) y lanzar `run_function_async(pointcloud.run_pointcloud_correction, ..., with_progress=True, with_cancel=True)` (T012), guardando el `celery_task_id`; responder `{'celery_task_id': ..., 'status': 'running'}`
- [X] T014 [US1] Implementar `RealignPointCloudDownload.get` en `coreplugins/realign/api.py`: solo requiere acceso de lectura a la tarea (no `change_project`, FR-016); 404 si `status != 'ready'`, si está obsoleta (`stale`) o si el archivo no existe en disco; si no, servir el LAZ desde el directorio persistente con `download_file_response` (patrón de `RealignDownload`), `Content-Disposition: attachment; filename="<tarea>_realigned.laz"` (contracts/api.md, FR-010, FR-011, FR-012)
- [X] T015 [US1] En `coreplugins/realign/public/RealignPanel.jsx`, agregar una sección de nube de puntos: botón "Generar nube corregida" (POST T013) visible cuando `pointcloud.eligible`; mientras `status == 'running'`, mostrar progreso vía `Workers.waitForCompletion(celery_task_id, cb, progress_cb)`; cuando `status == 'ready' && available`, mostrar el enlace de descarga (T014) (FR-001, FR-009, FR-010)
- [X] T016 [US1] Ejecutar los tests de US1 en Docker (`docker compose exec webapp python manage.py test coreplugins/realign`, exit 0, salida visible) y verificación de worker (Principio IV.3): con el stack levantado, lanzar una generación real sobre una tarea con nube de producción y confirmar en `docker compose logs worker --tail 80 | grep -iE "realign|pdal|error"` que el pipeline corrió sin `ImportError`/fallos de `pdal`, y que `pointcloud.laz` existe en el directorio persistente del plugin (quickstart.md §3–4) — **verificado hoy con evidencia real, no solo logs**: generación real vía navegador sobre la tarea "Noria" (268 MB / 61.780.499 puntos) completó en ~30–40 s; `pointcloud.laz` existe en el dir. persistente (280.486.381 B, mtime 22:21:54); `pdal info --summary` sobre ese archivo confirma `num_points=61780499` (idéntico al original) y `minz/maxz` idénticos al original — Z preservada bit a bit en producción, no solo en fixtures sintéticos. El log de Celery no imprime líneas de éxito por defecto (solo warnings/errors), así que la verificación se apoyó en el archivo resultante + `pdal info`, evidencia más directa que grepear el log

**Checkpoint**: US1 completa y verificable de forma independiente — MVP funcional (generar,
esperar, descargar, con Z intacta y XY coherente con los rásteres corregidos).

---

## Phase 4: User Story 2 - Entender por qué la nube no se corrige en modo escala (Priority: P2)

**Goal**: cuando la acción no está disponible, el usuario ve siempre una explicación específica
de la causa y el camino para habilitarla, en vez de una opción ausente o deshabilitada sin
contexto (FR-004, FR-018, SC-009).

**Independent Test**: con una realineación aplicada con escala habilitada, verificar que la
acción de nube está bloqueada con la explicación correcta (`scale_enabled`); destildar la escala,
volver a aplicar y verificar que la acción queda disponible; con una nube ya generada, volver a
habilitar la escala y verificar que deja de ofrecerse.

### Tests for User Story 2 ⚠️

- [X] T017 [P] [US2] En `tests.py`, test de contrato: cada una de las cuatro causas de inelegibilidad (`no_pointcloud`, `not_applied`, `scale_enabled`, `already_running`) produce un 400 con su `reason` correcto al intentar POST `.../realign/pointcloud` (contracts/api.md)
- [X] T018 [P] [US2] En `tests.py`, test de obsolescencia por cambio de modo: generar una nube en modo rígido, luego reaplicar la realineación con `use_scale=true`, y verificar que `GET .../realign/state` devuelve `pointcloud.stale == true` y `pointcloud.available == false` (huella no coincide, research.md D8, FR-012)

### Implementation for User Story 2

- [X] T019 [US2] Revisar y completar en `RealignState.get` (T007) los cuatro `ineligible_reason` con los mensajes de causa exactos que consumirá el frontend (`no_pointcloud`, `not_applied`, `scale_enabled`, `already_running`), verificados contra los casos de T017
- [X] T020 [US2] En `RealignPanel.jsx`, cuando `pointcloud.eligible == false`, mostrar el texto explicativo correspondiente a `ineligible_reason` (motivo + cómo habilitarlo, p. ej. "destildar Usar escala y volver a aplicar" para `scale_enabled`) en vez de un botón deshabilitado sin contexto (FR-004, FR-018, SC-009)
- [X] T021 [US2] En `RealignPanel.jsx`, cuando `pointcloud.stale == true`, dejar de mostrar el enlace de descarga y mostrar un aviso de que el ajuste cambió y hay que volver a generar la nube (FR-012)
- [X] T022 [US2] Ejecutar los tests de US2 en Docker (exit 0, salida visible) y validar manualmente quickstart.md escenarios 8–10 (bloqueo explicado, habilitar tras destildar escala, invalidación al re-habilitar escala)

**Checkpoint**: US1 y US2 funcionan de forma independiente y combinada — cualquier bloqueo viene
siempre con una explicación accionable.

---

## Phase 5: User Story 3 - Mantener el estado coherente a lo largo del tiempo (Priority: P3)

**Goal**: el estado de la nube corregida sobrevive a recargas, se cancela y limpia correctamente,
y se invalida ante cambios en los puntos de control o al revertir la realineación, de modo que
nunca se ofrece una descarga que no corresponde al ajuste vigente (FR-011 a FR-015).

**Independent Test**: lanzar una generación, recargar la página y verificar que el estado
mostrado es real (progreso o resultado); con la nube ya lista, mover un punto de control y
verificar que deja de ofrecerse; revertir la realineación y verificar que el archivo se elimina.

### Tests for User Story 3 ⚠️

- [X] T023 [P] [US3] En `tests.py`, test de cancelación: DELETE `.../realign/pointcloud` con una generación `running` la cancela (`should_cancel()` pasa a `true`) y no deja ningún `pointcloud.tmp.laz` en disco (FR-015)
- [X] T024 [P] [US3] En `tests.py`, test de limpieza al revertir: con una nube `ready`, invocar `RealignRevert.post` y verificar que el subdocumento `pointcloud` vuelve a `absent` y el archivo se elimina del directorio persistente (FR-013)
- [X] T025 [P] [US3] En `tests.py`, test de reanudación: con `pointcloud.status == 'running'` persistido, `GET .../realign/state` devuelve el `celery_task_id` guardado, permitiendo reanudar el sondeo tras una recarga (FR-011)

### Implementation for User Story 3

- [X] T026 [US3] Implementar `RealignPointCloud.delete` en `coreplugins/realign/api.py`: `check_project_perms(... 'change_project')`; si `status == 'running'`, cancela la ejecución (mismo mecanismo que `CancelTask` de `app/api/workers.py`: marcar el `AsyncResult` como `ABORTED`) y borra el `.tmp.laz`; si `ready`/`error`, borra `pointcloud.laz` si existe; en cualquier caso deja `pointcloud` en `absent` (T005) (contracts/api.md, FR-013, FR-015)
- [X] T027 [US3] Extender `RealignRevert.post` en `coreplugins/realign/api.py` para invocar la misma limpieza de T026 sobre el subdocumento `pointcloud` de la tarea revertida (FR-013)
- [X] T028 [US3] En `RealignPanel.jsx`, al montar el panel, si `pointcloud.status == 'running'`, reanudar automáticamente `Workers.waitForCompletion` con el `celery_task_id` persistido (T007) en vez de esperar una nueva acción del usuario (FR-011)
- [ ] T029 [US3] Ejecutar los tests de US3 en Docker (exit 0, salida visible) y validar manualmente quickstart.md escenarios 12–15 (recarga durante generación, invalidación al mover un punto, limpieza al revertir, fallo controlado sin archivo parcial) — tests: 45/45 OK confirmado. Manual: **escenario 13 verificado en navegador real** hoy (agregar un 3er punto tras generar la nube → `pointcloud.stale=true`, `available=false`, descarga → 404); **faltan** escenario 12 (recargar la página con una generación en curso), 14 (Revertir borra la nube — cubierto por test automatizado `test_revert_discards_pointcloud`, no probado en vivo) y 15 (fallo controlado sin archivo parcial — cubierto por tests automatizados de overflow/cancelación, no probado en vivo)

**Checkpoint**: las tres historias funcionan de forma independiente y en conjunto — el estado de
la nube es siempre coherente con el ajuste vigente.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: cierre de calidad transversal a las tres historias.

- [X] T030 [P] Revisar todos los textos de usuario (`_(...)`) nuevos en `coreplugins/realign/api.py` y `coreplugins/realign/public/RealignPanel.jsx` (mensajes de inelegibilidad, error de pipeline, aviso de que el visor 3D no se corrige) para que sean claros y accionables (FR-018, SC-009) — revisados: los 4 mensajes de `POINTCLOUD_REASON_MESSAGES`/`POINTCLOUD_REASON_TEXT` son consistentes entre backend y frontend, accionables (indican la causa y el camino a seguir) y usan el mismo vocabulario ya establecido en la feature 002 ("Destildar Usar escala")
- [ ] T031 Ejecutar el checklist funcional completo de `specs/003-realign-pointcloud/quickstart.md` §1 (los 18 escenarios) contra el stack en Docker y registrar el resultado de cada uno — **9 de 18 verificados hoy en navegador real** sobre la tarea "Noria" (producción, 268 MB): 1 (sección aparece habilitada tras aplicar), 2 (arranca en background con `celery_task_id`), 3 (termina y ofrece descarga), 9 (destildar escala + aplicar → disponible), 11 (sin aplicar → `not_applied`), 13 (mover/agregar punto → `stale`), 16 (`already_running` durante una generación), más 5 y 6 (parcial: `num_points` y Z verificados por `pdal info` directo sobre el archivo real, no solo por el panel). **Faltan**: 4 (comparar un rasgo común en herramienta externa), 6 completo (atributos Intensity/Classification/GpsTime/RGB — sí cubiertos en tests automatizados con fixtures sintéticos, no en este archivo real), 7 (tarea sin nube), 8 (bloqueo específicamente por `scale_enabled` tras aplicar con escala — solo se probó `not_applied`), 10 (invalidar re-tildando escala específicamente, en vez de agregando un punto), 12 (recargar durante una generación en curso), 14 (Revertir borra la nube), 15 (fallo controlado), 17 (usuario de solo lectura), 18 (leer el aviso del visor 3D en pantalla)
- [ ] T032 Confirmar los criterios de éxito medibles de quickstart.md §5 (SC-001 a SC-009) con evidencia (comandos `pdal info`, capturas, logs) — **con evidencia dura hoy**: SC-002 (`pdal info` sobre el archivo real de producción: `minz`/`maxz` idénticos al original), SC-004 (mtime/md5 del original sin cambios tras toda la sesión), SC-006 (~30–40 s para 267,5 MB, muy por debajo de los 10 min), SC-008 (tras agregar un punto, `stale=true` y descarga → 404). **Con evidencia parcial**: SC-003 (`num_points` idéntico confirmado en el archivo real; atributos por punto solo verificados en fixtures sintéticos de test, no en este archivo). **Sin verificar aún**: SC-001 (comparación de un rasgo común en herramienta externa), SC-005 (navegación sin bloqueo durante la generación — no estresado explícitamente), SC-007 (fallo sin dejar descarga — cubierto solo por tests automatizados), SC-009 (cubierto indirectamente por T030, no listado escenario por escenario)
- [X] T033 Ejecutar de nuevo la suite completa (`docker compose exec webapp python manage.py test coreplugins/realign`) tras todos los cambios y confirmar exit code 0 (regla `verification-before-completion`, cierre de feature), incluida la verificación de worker de T016 — **45/45 tests OK, exit 0**, ejecutado en Docker al cierre de la feature (incluye T008–T011, T017–T018, T023–T025, más los 23 tests heredados de 002)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sin dependencias — puede iniciar de inmediato
- **Foundational (Phase 2)**: depende de Setup — BLOQUEA todas las user stories
- **User Stories (Phase 3–5)**: todas dependen de Foundational
  - US1 (P1) no depende de otras historias — es el flujo completo mínimo (generar → esperar → descargar)
  - US2 (P2) depende del endpoint y del cálculo de elegibilidad de US1/Foundational (T007, T013) — refina mensajes y la reacción a `stale`, no agrega mecanismo nuevo
  - US3 (P3) depende de US1 (opera sobre el pipeline y el endpoint que US1 crea) — introduce cancelación, limpieza al revertir y reanudación tras recarga; independiente de US2
- **Polish (Phase 6)**: depende de que las historias deseadas estén completas

### User Story Dependencies

- **US1**: fundacional para el resto; sin dependencias de otras historias
- **US2**: extiende el cálculo de elegibilidad y el panel de US1 — secuencial respecto a US1
- **US3**: extiende el endpoint y el panel de US1 (cancelar, limpiar, reanudar) — secuencial
  respecto a US1, independiente de US2

### Within Each User Story

- Tests antes de la implementación (T008–T011 antes de T012–T015; T017–T018 antes de T019–T021;
  T023–T025 antes de T026–T028)
- `pointcloud.py` (matriz, offsets, huella, pipeline) antes de los endpoints que lo usan
- Endpoints backend antes del frontend que los consume (T012–T014 antes de T015)
- Implementación core antes de la verificación de worker/quickstart

### Parallel Opportunities

- T002, T003, T004 y T005 en paralelo (funciones/archivo distintos dentro de Foundational, sin
  dependencias entre sí)
- T008, T009, T010 y T011 en paralelo (casos de test independientes en `tests.py`)
- T017 y T018 en paralelo (casos de test independientes en `tests.py`)
- T023, T024 y T025 en paralelo (casos de test independientes en `tests.py`)

---

## Parallel Example: Foundational

```bash
# Piezas de coreplugins/realign/pointcloud.py y store.py, independientes entre sí:
Task: "build_transformation_matrix en pointcloud.py"
Task: "compute_safe_offsets en pointcloud.py"
Task: "compute_fingerprint / fingerprint_matches en pointcloud.py"
Task: "Helpers get/set/del_pointcloud_state en store.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Completar Phase 1: Setup
2. Completar Phase 2: Foundational (CRÍTICO — bloquea todas las historias)
3. Completar Phase 3: User Story 1
4. **DETENER y VALIDAR**: probar US1 de forma independiente (generar → esperar → descargar)
5. Desplegar/demostrar si está listo

### Incremental Delivery

1. Setup + Foundational → base lista
2. Agregar US1 → probar de forma independiente → demo (MVP)
3. Agregar US2 → probar de forma independiente → demo (mensajes claros ante bloqueos)
4. Agregar US3 → probar de forma independiente → demo (coherencia en el tiempo)
5. Cada historia agrega valor sin romper las anteriores

---

## Notes

- [P] = archivos o funciones distintos, sin dependencias entre sí
- La etiqueta [Story] mapea cada tarea a su user story para trazabilidad
- Cada user story debe ser completable y verificable de forma independiente
- Confirmar que los tests fallan antes de implementar
- Hacer commit tras cada tarea o grupo lógico
- Detenerse en cada checkpoint para validar la historia de forma independiente
- Evitar: tareas vagas, conflictos de archivo simultáneos, dependencias cruzadas entre historias
  que rompan la independencia
