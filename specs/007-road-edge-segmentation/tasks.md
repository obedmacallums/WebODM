---

description: "Task list for 007-road-edge-segmentation"
---

# Tasks: borde por segmentación semántica de la ortofoto (`road`)

**Input**: Design documents from `/specs/007-road-edge-segmentation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **SÍ se incluyen**, mismo criterio que `006`: la constitución exige ejecutar el comando
que verifica cada tarea antes de darla por completa, y esta feature toca de nuevo la pieza que puede
equivocarse en silencio — un borde mal detectado sobre la ortofoto es un número plausible, no un
error. La detección (`profile.detect_edges_segmentation`) es una función pura y se prueba de forma
exacta contra máscaras sintéticas; la parte de E/S (`segmentation.py`) se prueba con un doble de
`geodeep`, sin depender de red ni del modelo real descargado (`plan.md`, Technical Context).

**Organization**: agrupadas por historia de usuario, en orden de prioridad.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia a la que pertenece (US1–US4)
- Cada tarea indica su archivo exacto

## Path Conventions

Todo cuelga de `coreplugins/road/`, sobre la estructura que dejaron `005` y `006`: backend en la
raíz del paquete, frontend en `public/`, tests de Python en `tests/` y de JS en `public/tests/`.
Ningún archivo fuera del plugin, y ninguno de `coreplugins/objdetect/` se modifica (solo se lee como
referencia de patrón — `research.md` D31).

**Recordatorio que muerde**: `coreplugins/` es un paquete de espacio de nombres; una clase de test
nueva que no se re-exporte desde `tests/__init__.py` **no se ejecuta y no falla** — pasa
desapercibida. Cada tarea que crea un archivo de test incluye su re-export.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: capturar el "antes" mientras todavía existe, igual que hizo `006/T001`.

- [X] T001 Exportar a CSV los análisis existentes en modo `break` y `surface` (reutilizar las tareas
      de referencia de `006` si siguen presentes: `Polideportivo María Puebla Vásquez`, `Noria`,
      `ruta de zona 1`) y versionarlos en `specs/007-road-edge-segmentation/baseline/`
      — hecho: 5 análisis reales exportados (todas las tareas con datos del plugin `road` en esta
      instancia tienen ortofoto, incluida `Polideportivo María Puebla Vásquez`).

**Checkpoint**: existe una referencia contra la que comparar. Sin esto, US4 no se puede demostrar
después con datos reales, solo con fixtures sintéticos.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: que el tercer valor de `edge_mode` exista, se valide, y la comprobación de
disponibilidad de ortofoto funcione, sin que ningún modo cambie de comportamiento todavía.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta que esta fase esté completa.

- [X] T002 [P] Añadir `EDGE_MODE_SEGMENTATION = 'segmentation'` a `EDGE_MODES` en
      `coreplugins/road/sources.py`, sin parámetros ni rangos nuevos (`007/FR-015`, `data-model.md
      §4`)
- [X] T003 [P] Añadir `NO_ORTHOPHOTO = 'no_orthophoto'` junto a `NO_BREAK`, `NO_DATA`,
      `BREAK_AT_AXIS` en `coreplugins/road/profile.py`, sin usarla todavía (`research.md` D29)
- [X] T004 [P] Cubrir que `edge_mode` admite `"segmentation"` y que un valor desconocido lista los
      tres modos en `coreplugins/road/tests/test_params.py`
- [X] T005 Comprobar disponibilidad de ortofoto **antes** de aceptar el análisis cuando
      `params.edge_mode == "segmentation"`, respondiendo `400 {"code": "no_orthophoto"}` si la tarea
      no tiene `orthophoto.tif`, en `coreplugins/road/api.py` (`AnalysisList.post`, mismo patrón que
      `no_elevation_model()`), según
      [contracts/rest-api-delta.md](./contracts/rest-api-delta.md#post-taskpkanalyses--edge_mode-admite-un-tercer-valor-con-una-comprobación-previa-nueva)
- [X] T006 [P] Cubrir el `400 no_orthophoto` sin ortofoto y el `202` normal con ortofoto, sin que se
      cree ningún análisis ni se toque el candado de ejecución en el caso de rechazo, en
      `coreplugins/road/tests/test_api_analyses.py`
- [X] T007 [P] Comprobar que `GET capabilities` publica los tres valores en `edge_modes` en
      `coreplugins/road/tests/test_api_capabilities.py` (resuelto por T002 vía
      `list(sources.EDGE_MODES)` en `api.py:235`, sin tocar `Capabilities.get`)

**Checkpoint**: el tercer modo existe como valor válido y la tarea sin ortofoto se rechaza pronto y
con claridad. Ningún tramo se calcula todavía.

---

## Phase 3: User Story 1 - Medir el ancho de una calle cuyo borde no tiene relieve (Priority: P1) 🎯 MVP

**Goal**: que el modo `segmentation` detecte bordes donde ni `break` ni `surface` encuentran nada,
porque el límite de la calzada es solo un cambio de textura en la ortofoto.

**Independent Test**: sobre un tramo sintético cuya máscara de segmentación marca un límite
calzada/no-calzada sin ningún escalón de elevación asociado, comprobar que el modo `segmentation`
reporta un ancho y que el mismo perfil en modo `break` o `surface` no lo hace (spec.md, User Story 1,
escenarios 1 y 2).

### Tests for User Story 1

> Escribir primero y comprobar que fallan antes de implementar.

- [X] T008 [P] [US1] Crear `coreplugins/road/tests/test_segmentation_edges.py` con los casos de
      `detect_edges_segmentation()` sobre máscaras binarias sintéticas —borde limpio a cada lado,
      pícher aislado de un solo píxel filtrado por `min_consecutive_samples`, calzada hasta el final
      del semiancho (`no_break`), eje ya sobre "no-calzada" (`break_at_axis`)— y re-exportar su clase
      desde `coreplugins/road/tests/__init__.py`
- [X] T009 [P] [US1] Crear `coreplugins/road/tests/test_segmentation.py` con el corredor del eje
      (buffer por `search_half_width` + margen, `research.md` D26) y la invocación a
      `geodeep.segment` sustituida por un doble que devuelve una máscara sintética — sin depender de
      red ni del modelo real — y re-exportar su clase desde `coreplugins/road/tests/__init__.py`

### Implementation for User Story 1

- [X] T010 [US1] Implementar `detect_edges_segmentation(distances, mask_values,
      min_consecutive)` en `coreplugins/road/profile.py`: mismo recorrido de `_scan_side_surface`
      sobre una señal binaria (última muestra conforme, corregido durante la implementación —
      `research.md` D30), mismos tres motivos reinterpretados más `NO_ORTHOPHOTO` cuando
      `mask_values` no cubre la muestra
- [X] T011 [US1] Implementar `build_corridor(vertices, half_width, crs)` en
      `coreplugins/road/segmentation.py` (módulo nuevo): buffer del eje completo, con el margen de
      `research.md` D26, devuelto como geometría lista para `gdalwarp -cutline`
- [X] T012 [US1] Implementar `run_segmentation(orthophoto_path, corridor, progress_callback=None)`
      en `coreplugins/road/segmentation.py`: recorte con `gdalwarp -of GTiff` (GTiff y no VRT como
      `objdetect`: `save_mask_to_raster` hereda el driver del archivo de entrada para escribir la
      máscara, y un VRT no admite escritura a través de él — hallazgo durante la implementación),
      import diferido de `geodeep.segment` con `try/except ImportError`, máscara georreferenciada
      guardada en un temporal bajo `settings.MEDIA_TMP` (`research.md` D31)
- [X] T013 [US1] Insertar la fase de segmentación en `compute.analyze()` de
      `coreplugins/road/compute.py`, antes del bucle de bloques: genera el corredor, llama a
      `segmentation.run_segmentation`, abre la máscara resultante con `rasterio` y reporta su propio
      tramo del `progress_callback` ya existente (`research.md` D27, `SEGMENTATION_PROGRESS_SHARE`
      = 40 %) — solo cuando `params['edge_mode'] == 'segmentation'`
- [X] T014 [US1] Muestrear la máscara abierta en T013 en los mismos offsets del perfil transversal
      que ya calcula `geometry.cross_section_points`, reutilizando el mecanismo de `_sample` (vecino
      más próximo, `NaN`/`None` sin cobertura) dentro de `_read_block` de
      `coreplugins/road/compute.py`
- [X] T015 [US1] Despachar a `detect_edges_segmentation` en `_section_result()` de
      `coreplugins/road/compute.py` cuando `edge_mode == 'segmentation'`, y calcular `cross_slope`
      sobre las muestras de elevación entre los bordes hallados, con el mismo criterio que ya usa
      `profile.cross_slope` en modo `break` (`007/FR-010`)
- [X] T016 [US1] Resolver la ruta de la ortofoto (`task.get_asset_download_path("orthophoto.tif")`,
      patrón de `objdetect.api.TaskObjDetect.post`) y pasarla hasta `compute.run_analysis` /
      `compute.analyze` solo cuando `edge_mode == 'segmentation'`, en `coreplugins/road/api.py`
- [X] T017 [P] [US1] Añadir la entrada `segmentation` a `EDGE_MODE_LABELS` en
      `coreplugins/road/public/RoadPanel.jsx` — el selector y el ocultamiento de
      `break_threshold`/`surface_tolerance` ya salen del mecanismo genérico existente
      (`plan.md`, Project Structure; `007/FR-015a`), sin lógica nueva
- [X] T018 [US1] Cubrir el modo `segmentation` de extremo a extremo sobre un DEM y una máscara
      sintéticos en `coreplugins/road/tests/test_compute.py`, demostrando que reporta ancho donde
      `break` y `surface` sobre el mismo perfil no lo hacen — hecho: `SegmentationModeTest`
      (medida donde `break` falla, control con `break`, `cross_slope` desde el DEM, cobertura
      parcial → `no_orthophoto`, parámetros de otros modos ignorados)

**Checkpoint**: el modo `segmentation` funciona sobre datos sintéticos y se puede elegir desde el
panel. Es el MVP: entrega el motivo de ser de la feature sin nada de lo que viene después.

---

## Phase 4: User Story 2 - No recibir un borde donde la ortofoto no permite reconocer la calzada (Priority: P2)

**Goal**: que la ausencia de fuente de datos —parcial (un tramo) o total (la etapa entera)— se
reporte con claridad y nunca como un número inventado.

**Independent Test**: con `geodeep` no disponible, lanzar un análisis en modo `segmentation` y
comprobar que termina en `status: "failed"` con un mensaje identificable, sin producir tramos, y que
un análisis en `break` o `surface` de la misma tarea sigue funcionando (spec.md, User Story 2,
escenario 3). Con la etapa de segmentación completada pero un tramo fuera de la cobertura de la
ortofoto, comprobar que ese tramo —y solo ese— lleva el motivo `no_orthophoto`.

### Tests for User Story 2

- [X] T019 [P] [US2] Cubrir en `coreplugins/road/tests/test_segmentation.py` que la ausencia de
      `geodeep` (`ImportError`) y un fallo del recorte con `gdalwarp` propagan un mensaje de error
      identificable, sin excepción sin manejar
- [X] T020 [P] [US2] Cubrir en `coreplugins/road/tests/test_compute.py` que un análisis completo en
      modo `segmentation` con `geodeep` no disponible termina en `status: "failed"` con `error` no
      vacío y **sin ningún tramo** producido (`research.md` D28, caso 1) — `SegmentationFailureTest`,
      más el control de que `break` sigue funcionando en la misma tarea
- [X] T021 [P] [US2] Añadir a `coreplugins/road/tests/test_segmentation_edges.py` el caso de
      cobertura parcial: la máscara no cubre la muestra del eje de un tramo dentro de un corredor por
      lo demás válido → motivo `no_orthophoto` en ese lado, sin afectar a los tramos vecinos
      (`research.md` D28, caso 2)

### Implementation for User Story 2

- [X] T022 [US2] Dejar que el fallo de `segmentation.run_segmentation` (T012, T019) se propague como
      excepción normal desde la fase de segmentación de `compute.analyze()` (T013), para que el
      manejo de errores **ya existente** de `compute.run_analysis` (`compute.py:709-716`) la capture
      y marque `status: "failed"` sin cambios de esquema — no se añade un mecanismo de error nuevo.
      Sin cambios de código: ya funcionaba así desde T013; T020 lo verifica.
- [X] T023 [US2] Verificar en `coreplugins/road/tests/test_compute.py` que la cobertura parcial de
      T021 se propaga hasta el tramo final como `left_reason`/`right_reason: "no_orthophoto"`, con
      `status: "no_edge"` y sin afectar a los tramos con cobertura completa del mismo análisis —
      `test_partial_mask_coverage_reports_no_orthophoto` (ya escrito en T018)

**Checkpoint**: un fallo total del modo `segmentation` se ve como un fallo del análisis, claro y sin
tramos a medias; un fallo parcial se ve tramo a tramo, con un motivo que no se confunde con los tres
ya existentes.

---

## Phase 5: User Story 3 - Saber que un borde viene del criterio de segmentación (Priority: P3)

**Goal**: que el modo de detección y el origen del borde (medido/inferido, `006`) sigan
distinguiéndose con el tercer modo, sin mecanismo nuevo.

**Independent Test**: consultar y exportar un análisis en modo `segmentation` y comprobar que
`edge_mode` viaja con el análisis y que los bordes hallados por este modo cuentan como `measured`,
exactamente igual que los otros dos (spec.md, User Story 3).

**⚠️ Depende de US1**: sin bordes producidos por el modo `segmentation` no hay nada que trazar.

### Tests for User Story 3

- [X] T024 [P] [US3] Cubrir en `coreplugins/road/tests/test_export.py` que un análisis en modo
      `segmentation`, incluidos tramos con motivo `no_orthophoto`, exporta a CSV y GeoJSON sin
      cambios de esquema — `export.py` no se modifica (`plan.md`, Project Structure); el test
      demuestra que no hacía falta — `SegmentationModeExportTest`
- [X] T025 [P] [US3] Cubrir en `coreplugins/road/tests/test_compute.py` que un borde hallado por el
      modo `segmentation` recibe `left_edge_source`/`right_edge_source: "measured"`, y que la
      pasada de coherencia (`006`) puede marcarlo `"inferred"` igual que a los otros dos modos
      (`007/FR-011`, `007/FR-012`) — `test_coherence_can_infer_a_segmentation_edge_too`

### Implementation for User Story 3

Ninguna: `left_edge_source`/`right_edge_source` ya se asignan en `_segment_metrics()` sin mirar
`edge_mode` (`compute.py:316-317`, sin cambios desde `006`), `edge_mode` ya viaja con el análisis
desde `006/FR-003`, y `export.py` ya exporta ambos como texto libre. Esta historia es de
verificación, no de código nuevo — si T024 o T025 fallan, es señal de que alguna tarea de US1/US2
rompió algo que debía quedar intacto.

**Checkpoint**: el tercer modo es indistinguible de los otros dos en cuanto a trazabilidad — mismo
contrato, sin excepciones.

---

## Phase 6: User Story 4 - Que los modos existentes sigan exactamente igual (Priority: P4)

**Goal**: demostrar —no afirmar— que `break` y `surface` no cambiaron de resultado.

**Independent Test**: recalcular los análisis del baseline de T001 con sus parámetros originales y
comparar tramo a tramo (spec.md, User Story 4).

### Tests for User Story 4

- [X] T026 [P] [US4] Comprobar en `coreplugins/road/tests/test_compute.py` que un análisis con
      `edge_mode` ausente (documento anterior a esta feature) sigue resolviéndose como `"break"`, sin
      tocar `store._upgrade_segments` ni el esquema de `006` —
      `test_a_params_dict_without_edge_mode_still_behaves_like_break`

### Implementation for User Story 4

- [X] T027 [US4] Comparar los análisis reales recalculados contra `specs/007-road-edge-segmentation/baseline/`
      (T001) y adjuntar la salida de la comparación al reporte — cero diferencias esperadas, igual
      criterio que `006/T032`.

      **Resultado**: en los 5 análisis reales, comparación campo a campo, **cero diferencias** en
      todo lo que `006`/`007` pueden afectar: `width`, `offset_left`, `offset_right`, `cross_slope`,
      `status`, `left_reason`, `right_reason`, `left_edge_source`, `right_edge_source`, `elevation`,
      `grade`. Sí aparecen diferencias en `width_min`/`width_max`/`width_sections`/
      `width_measured_sections` para 3 de los 5 análisis (`Noria`, `Colegio Trabunco`, `Task of
      2026-07-24…`): vacías en el baseline, con valor en el recálculo. Verificado que **no** es
      causado por esta feature — `git diff coreplugins/road/compute.py` no toca esas cuatro
      columnas en ningún punto. Son análisis persistidos **antes** del commit `0ae6050f`
      ("medir el ancho como estadística del tramo"), que ya estaba en `006-street-width` antes de
      empezar `/speckit-specify` para `007`: el baseline de T001 se leyó del documento persistido
      (`store.read_segments`), calculado por una versión de código anterior a esa columna, mientras
      que el recálculo usa el código actual, que siempre la rellena. Es una discrepancia heredada de
      `006`, no una regresión de `007` — recalcular esos mismos análisis con el código de `006` tal
      cual estaba antes de esta feature habría mostrado la misma diferencia.

**Checkpoint**: la no regresión está demostrada con datos reales, no solo con fixtures sintéticos.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T028 Ejecutar la suite completa con
      `docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests` y
      comprobar que el recuento de tests **sube** respecto de `006` — 310 tests, `OK` (frente a 285
      antes de esta feature)
- [X] T029 Verificar en worker un análisis real en modo `segmentation` sobre una tarea con ortofoto,
      incluida la primera descarga del modelo `roads`, y adjuntar el fragmento del log — Principio
      IV, no negociable, con el riesgo de red nuevo de `research.md` D31; si el entorno no tiene
      salida de red, adjuntar en su lugar la evidencia de que el fallo es identificable
      (`status: "failed"`) y no un análisis colgado, según
      [quickstart.md](./quickstart.md#escenario-6--verificación-del-worker-principio-iv-no-negociable--con-riesgo-de-red-nuevo)

      **Resultado**: lanzado un análisis real (fuera de `CELERY_TASK_ALWAYS_EAGER`, vía
      `run_function_async` real contra Celery/Redis) en modo `segmentation` sobre
      `Polideportivo María Puebla Vásquez` (proyecto `marcoleta`), reutilizando el eje ya trazado
      del análisis `surface` existente (66 m, 14 tramos). El worker tenía salida de red
      (`curl https://huggingface.co` → `200` desde el contenedor `worker`).

      **Primer intento: `status: "failed"`**, `error: "analyze() got an unexpected keyword
      argument 'orthophoto_path'"` — no un fallo de `geodeep` ni de red: el proceso Celery del
      worker tenía el módulo `coreplugins.road.compute` **cacheado en memoria** desde antes de mis
      últimos `docker compose cp` (el worker es un proceso persistente; copiar archivos a disco no
      recarga lo ya importado). `docker compose restart worker` lo resolvió. Queda anotado porque
      es un gotcha real de este flujo de despliegue, no cubierto hasta ahora en `docs/` ni en el
      quickstart de `006` — se añade una nota en T030/README.

      **Segundo intento, tras reiniciar**: `status: "completed"` en el primer sondeo (~10 s),
      `measured_count: 13`, `no_edge_count: 1` sobre 14 tramos, `duration: 8.66 s`. Log del worker
      sin `NameError` ni `ImportError`; sí aparece el aviso propio de `geodeep`
      (`.../orthophoto.tif is not tiled...`) sobre el recorte generado por
      `segmentation.run_segmentation`, confirmando que el pipeline completo —corredor, `gdalwarp`,
      carga o descarga del modelo, inferencia— corrió de verdad en el worker:

      ```text
      worker  | Starting worker using broker at redis://broker
      worker  | [2026-07-29 22:35:43,375: WARNING/ForkPoolWorker-1]
      worker  | /webodm/app/media/tmp/tmpiw7s5z8l_road_segmentation/orthophoto.tif is not tiled.
               I/O performance will be affected. Consider adding tiles.
      ```

      El análisis de prueba se borró después (`store.delete_segments`/`remove_analysis`); la tarea
      real del usuario quedó sin cambios — el análisis `surface` original sigue intacto.
- [X] T030 [P] Documentar los tres modos, cuándo usar cada uno y las limitaciones conocidas del
      modelo `roads` (resolución nativa, dominio de entrenamiento en Google Earth, ver `spec.md`
      Assumptions) en `coreplugins/road/README.md` — incluye el gotcha real de `docker compose cp`
      sin `restart worker` descubierto en T029
- [X] T031 [P] Registrar el resultado de los escenarios de [quickstart.md](./quickstart.md) en
      `specs/007-road-edge-segmentation/validacion-manual.md`, con honestidad sobre cuáles se
      validaron a mano y cuáles solo con tests y dobles
- [X] T032 [P] (Opcional, `research.md` D33) Si existe una tarea real con ortofoto adecuada, correr
      el modo `segmentation` sobre ella, comparar contra `surface` donde ambos midan, y anotar en
      [research.md](./research.md) si el modelo sirve sobre ortofotos de dron o si el límite
      documentado como hipótesis pasa a hecho medido — hecho: mide de forma consistente (13/14
      tramos) pero con sesgo de +1,80 m de media frente a `surface` en la misma calle real
      (`research.md` D33, resolución 2026-07-29)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: primero de todo, antes de tocar código.
- **Foundational (Phase 2)**: depende de Setup. Bloquea todas las historias.
- **US1 (Phase 3)**: depende de Foundational. Sin dependencias con otras historias — es el MVP.
- **US2 (Phase 4)**: depende de Foundational. Reutiliza `segmentation.py` y `detect_edges_segmentation`
  de US1 para sus tests, pero su implementación (T022) es solo dejar que el fallo se propague por el
  mecanismo ya existente — en la práctica conviene implementarla junto con US1, no antes.
- **US3 (Phase 5)**: depende de US1 (necesita bordes producidos por el modo para verificar su
  trazabilidad). Sin implementación propia, solo tests.
- **US4 (Phase 6)**: depende de Setup (el baseline) y de que US1/US2 estén completas, para poder
  afirmar que no las afectaron.
- **Polish (Phase 7)**: al final.

### Within Each User Story

- Los tests van primero y deben fallar antes de implementar.
- En `profile.py`: solo T010 en esta feature, sin dependencias con `detect_edges`/`detect_edges_surface`
  existentes más allá de reutilizar `_center_index`.
- En `segmentation.py`: corredor (T011) antes que el recorte y la llamada al modelo (T012).
- En `compute.py`: fase de segmentación (T013) → muestreo de la máscara (T014) → despacho de
  detección (T015). **Las tres tocan el mismo archivo y van en serie**, aunque T013/T014 pertenecen
  a la implementación de US1 y T023 (verificación) a US2.
- En `api.py`: comprobación de disponibilidad (T005, Foundational) antes que el paso de la ruta de
  la ortofoto a `run_analysis` (T016, US1) — mismo archivo, fases distintas, en serie.

### Parallel Opportunities

- T002, T003, T004 y T007 en paralelo: archivos distintos (`sources.py`, `profile.py`,
  `test_params.py`, `test_api_capabilities.py`).
- T008 y T009 en paralelo: dos archivos de test nuevos, distintos módulos bajo prueba.
- T019, T020 y T021 en paralelo: tres archivos de test distintos.
- T024 y T025 en paralelo.
- T030, T031 y T032 en paralelo.
- **Cuidado con `compute.py`**: concentra T013, T014, T015, T018, T020, T023, T025, T026 — ocho
  tareas de cinco fases distintas. Es, otra vez, el cuello de botella real del plugin y ninguna de
  sus tareas admite `[P]`.

---

## Parallel Example: User Story 1

```bash
# Los dos tests de US1, en dos archivos distintos:
Task: "detect_edges_segmentation sobre máscaras sintéticas en coreplugins/road/tests/test_segmentation_edges.py"
Task: "Corredor y geodeep.segment con doble en coreplugins/road/tests/test_segmentation.py"

# Después, en serie porque tocan compute.py:
Task: "Fase de segmentación en compute.analyze()"
Task: "Muestreo de la máscara en _read_block"
Task: "Despacho de detección en _section_result"
```

---

## Implementation Strategy

### MVP (solo US1)

1. Phase 1: capturar el baseline.
2. Phase 2: el tercer modo existe y se rechaza sin ortofoto.
3. Phase 3: el criterio de segmentación funciona sobre datos sintéticos.
4. **PARAR Y VALIDAR**: Escenario opcional de `quickstart.md` (D33) sobre una tarea real, si existe
   una con ortofoto adecuada a mano.

Con eso la feature ya demuestra su motivo de ser: un borde donde ningún otro modo lo encuentra. US2,
US3 y US4 son robustecer esa base, no construir algo nuevo sobre ella.

### Entrega incremental

1. Setup + Foundational → el modo existe y se rechaza con seguridad cuando falta ortofoto.
2. + US1 → el criterio detecta bordes sobre datos sintéticos. **MVP.**
3. + US2 → los fallos totales y parciales se distinguen y se reportan con claridad.
4. + US3 → verificado que la trazabilidad ya existente no necesitó ningún cambio.
5. + US4 → la no regresión queda demostrada con datos reales.

### Nota sobre el orden real

A diferencia de `006`, donde US2 y US3 formaban una sola entrega obligada, aquí **US1 y US2 son la
pareja inseparable**: publicar un modo que puede fallar (librería ausente, sin red) sin manejar ese
fallo con el mecanismo ya existente dejaría análisis colgados en `running`, que es peor que no tener
la feature. Si hay que parar a mitad, se para **antes** de US1, no entre US1 y US2.

---

## Notes

- `[P]` = archivos distintos, sin dependencias pendientes.
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida con el
  exit code, en el mismo reporte (Flujo de desarrollo de la constitución).
- Toda clase de test nueva se re-exporta desde `tests/__init__.py` o no se ejecuta.
- Los tests de esta feature **no requieren `geodeep` real ni red**, salvo T029 (verificación de
  worker), que es deliberadamente manual.
- No usar `run_tests_in_docker.sh` en esta instancia si hay tareas reales que no se quieren perder:
  su `docker compose down -v` las destruiría, y T001/T027/T029 las necesitan.
