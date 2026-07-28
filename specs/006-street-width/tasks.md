---

description: "Task list for 006-street-width"
---

# Tasks: ancho de calle por criterio de superficie (`road`)

**Input**: Design documents from `/specs/006-street-width/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: **SÍ se incluyen.** La constitución del fork exige que ninguna tarea se marque completa
sin ejecutar el comando que la verifica, y esta feature toca justo la pieza que puede equivocarse en
silencio: un borde mal detectado produce un número plausible, no un error. Los dos módulos centrales
son funciones puras, así que se prueban de forma exacta contra perfiles sintéticos.

**Organization**: agrupadas por historia de usuario, en orden de prioridad.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: puede correr en paralelo (archivos distintos, sin dependencias pendientes)
- **[Story]**: historia a la que pertenece (US1–US4)
- Cada tarea indica su archivo exacto

## Path Conventions

Todo cuelga de `coreplugins/road/`, sobre la estructura que dejó `005-road-metrics`: backend en la
raíz del paquete, frontend en `public/`, tests de Python en `tests/` y de JS en `public/tests/`.
Ningún archivo fuera del plugin.

**Recordatorio que muerde**: `coreplugins/` es un paquete de espacio de nombres, así que una clase de
test nueva que no se re-exporte desde `tests/__init__.py` **no se ejecuta y no falla** — pasa
desapercibida. Cada tarea que crea un archivo de test incluye su re-export.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: capturar el "antes" mientras todavía existe.

- [X] T001 Exportar a CSV los análisis actuales de las tareas `Noria` y `ruta de zona 1` con sus parámetros originales y versionarlos en `specs/006-street-width/baseline/` como referencia de no regresión

**Checkpoint**: existe una referencia contra la que comparar. **Sin esto, SC-004 no se puede
demostrar después**, porque el código que produjo esos números ya no estará.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: que los tres parámetros nuevos existan, se validen y viajen, sin cambiar todavía ningún
comportamiento.

**⚠️ CRITICAL**: ninguna historia puede empezar hasta que esta fase esté completa.

- [X] T002 [P] Añadir `edge_mode`, `surface_tolerance` y `coherence_window` a `DEFAULTS`, `RANGES` y la validación de `validate_params` en `coreplugins/road/sources.py`, con el enum de modos como dominio propio
- [X] T003 [P] Cubrir rangos, defectos y el rechazo de un `edge_mode` desconocido en `coreplugins/road/tests/test_params.py`
- [X] T004 Servir `edge_modes` y los nuevos `defaults`/`ranges` desde la vista de capacidades en `coreplugins/road/api.py`, según [contracts/rest-api-delta.md](./contracts/rest-api-delta.md)
- [X] T005 [P] Comprobar que capacidades publica los tres parámetros y el enum en `coreplugins/road/tests/test_api_capabilities.py`
- [X] T006 Aceptar y propagar los tres parámetros hasta `analyze()` sin usarlos aún en `coreplugins/road/compute.py`, verificando que con los defectos el resultado no cambia

**Checkpoint**: los parámetros existen de punta a punta y el comportamiento sigue siendo el de hoy.

---

## Phase 3: User Story 1 - Medir el ancho de una calle con bordillo (Priority: P1) 🎯 MVP

**Goal**: que el modo `surface` detecte bordes donde el criterio de quiebre no puede.

**Independent Test**: lanzar un análisis en modo `surface` sobre la calle de referencia y comprobar
que los tramos contiguos con bordillo a ambos lados dan anchos con desviación típica ≤ 0,25 m
(SC-001). No necesita coherencia ni campos de origen.

### Tests for User Story 1

> Escribir primero y comprobar que fallan antes de implementar.

- [X] T007 [US1] Crear `coreplugins/road/tests/test_surface.py` con los cuatro casos que justifican el modo —bordillo difuminado en 1 m, peralte del 8 % con bordillo de 12 cm, ruido de picos aislados de ±5 cm, eje descentrado con bordes a +1,0 y −5,5 m— y re-exportar su clase desde `coreplugins/road/tests/__init__.py`
- [X] T008 [US1] Añadir a `coreplugins/road/tests/test_surface.py` los casos de contrato: `no_data`, `no_break` sin bordillo, `break_at_axis` con el eje sobre la acera, y tolerancia mayor que el escalón

### Implementation for User Story 1

- [X] T009 [US1] Implementar `detect_edges_surface()` en `coreplugins/road/profile.py`: ajuste semilla a ±0,5 m, recorrido por residuo sostenido y reajuste entre bordes provisionales, dos iteraciones (D17, D18)
- [X] T010 [US1] Derivar la pendiente transversal de la referencia ajustada en modo `surface`, dejando intacto el cálculo actual del modo `break`, en `coreplugins/road/profile.py` (D19)
- [X] T011 [US1] Despachar por `edge_mode` en `_segment_metrics()` de `coreplugins/road/compute.py`
- [X] T012 [P] [US1] Añadir el selector de modo y el control de tolerancia al bloque de parámetros en `coreplugins/road/public/RoadPanel.jsx`, leyendo dominio y rangos de capacidades
- [X] T013 [US1] Cubrir el modo `surface` de extremo a extremo sobre un DEM sintético de calle en `coreplugins/road/tests/test_compute.py`

**Checkpoint**: el modo `surface` funciona y se puede elegir desde el panel. Es el MVP: entrega valor
sin nada de lo que viene después.

---

## Phase 4: User Story 2 - No recibir anchos inventados donde no hay borde (Priority: P2)

**Goal**: que la coherencia corrija atípicos y huecos cortos **sin** inventar calle donde no la hay.

**Independent Test**: sobre la calle de referencia con `coherence_window = 2`, comprobar que los diez
o más tramos consecutivos sin bordillo este no reciben ningún borde inferido (SC-006) y que no se
reporta ancho donde el lado es descampado (SC-002).

### Tests for User Story 2

> Las tres primeras son garantías de que **no** inventa. Escribirlas primero.

- [X] T014 [US2] Crear `coreplugins/road/tests/test_coherence.py` con las garantías de seguridad —un hueco de diez tramos no se rellena, los inferidos no votan (sin cascada), ventana 0 es la identidad— y re-exportar su clase desde `coreplugins/road/tests/__init__.py`
- [X] T015 [US2] Añadir a `coreplugins/road/tests/test_coherence.py` los casos de precisión: un atípico aislado se sustituye, un hueco corto se rellena, una variación legítima que se abre de 1,0 a 2,0 m no se aplana, y una vecindad con menos de dos bordes medidos se deja intacta

### Implementation for User Story 2

- [X] T016 [US2] Crear `coreplugins/road/coherence.py` con `repair_edges()`: mediana de la vecindad, umbral por MAD con suelo de 0,30 m, y solo los bordes medidos como evidencia (D20)
- [X] T017 [US2] Retener el vector de cotas de cada transversal cuando `coherence_window > 0`, y solo entonces, en el bucle por bloques de `coreplugins/road/compute.py` (D22)
- [X] T018 [US2] Invocar la coherencia tras el bucle y antes de la reproyección final en `coreplugins/road/compute.py`, recalculando ancho, estado y pendiente transversal de los tramos reparados
- [X] T019 [US2] Resuelto en `analyze()`: `coherence` entra por el import de módulo de `compute`, que `run_analysis()` ya importa absoluto y dentro del cuerpo — mismo alcance de seguridad frente a `eval_async`, verificado en worker en T034. Tarea original: importar dentro de `run_analysis()` en `coreplugins/road/compute.py` (D23: la función se reejecuta por código fuente en un namespace vacío)
- [X] T020 [US2] Añadir el control de ventana de coherencia a `coreplugins/road/public/RoadPanel.jsx`, con la propuesta de 2 al elegir el modo `surface` como conveniencia de interfaz

**Checkpoint**: la coherencia repara lo reparable y se niega a rellenar lo demás.

---

## Phase 5: User Story 3 - Saber de dónde sale cada número (Priority: P3)

**Goal**: que el origen de cada borde llegue al usuario, en el mapa y en el archivo.

**Independent Test**: consultar un tramo con borde inferido y comprobar que la consulta, el CSV y el
GeoJSON distinguen medido de inferido por lado (SC-005).

**⚠️ Depende de US2**: sin la pasada de coherencia no existe ningún borde inferido que mostrar. Es la
única dependencia entre historias de esta feature.

### Tests for User Story 3

- [X] T021 [P] [US3] Cubrir las dos columnas nuevas del CSV, las propiedades del GeoJSON y el `source` de los puntos de borde en `coreplugins/road/tests/test_export.py`
- [X] T022 [P] [US3] Comprobar que el estado `inferred` tiene estilo propio y distinguible de `measured` y de `no_edge` en `coreplugins/road/public/tests/segmentStyle.test.js`
- [X] T023 [P] [US3] Comprobar que el popup marca el origen por lado en `coreplugins/road/public/tests/roadBridge.test.js`
- [X] T024 [P] [US3] Comprobar los invariantes de [data-model.md](./data-model.md) —origen nulo si y solo si no hay offset, `inferred` implica ancho, motivo y origen conviven— en `coreplugins/road/tests/test_compute.py`

### Implementation for User Story 3

- [X] T025 [US3] Emitir `left_edge_source` / `right_edge_source` y el estado `inferred` en el tramo, conservando el motivo original por lado, en `coreplugins/road/compute.py`
- [X] T026 [P] [US3] Añadir las dos columnas al final del CSV, las propiedades al GeoJSON, el `source` a los puntos de borde y los tres parámetros al pie en `coreplugins/road/export.py`
- [X] T027 [P] [US3] Dar trazo propio al estado `inferred` en `coreplugins/road/public/segmentStyle.js`
- [X] T028 [P] [US3] Marcar el origen por lado en el popup de tramo en `coreplugins/road/public/roadBridge.js`

**Checkpoint**: ninguna cifra inferida se puede confundir con una medida.

---

## Phase 6: User Story 4 - Que los análisis rurales sigan exactamente igual (Priority: P4)

**Goal**: demostrar —no afirmar— que nada de lo anterior cambió el comportamiento existente.

**Independent Test**: recalcular los dos análisis rurales con sus parámetros originales y comparar
tramo a tramo contra el baseline de T001 (SC-004).

### Tests for User Story 4

- [X] T029 [P] [US4] Comprobar que un documento de tramos sin los campos de origen se lee completándolos como `measured`, sin escribir en disco, en `coreplugins/road/tests/test_lifecycle.py`
- [X] T030 [P] [US4] Comprobar que el modo `break` con ventana 0 produce valores idénticos a los fixtures existentes en `coreplugins/road/tests/test_compute.py`

### Implementation for User Story 4

- [X] T031 [US4] Completar los campos de origen y los tres parámetros al leer análisis anteriores a esta feature, en el punto de lectura de `coreplugins/road/store.py`, sin migración de datos (FR-024)
- [X] T032 [US4] Comparar los dos análisis rurales reales contra `specs/006-street-width/baseline/` y adjuntar la salida de la comparación al reporte

**Checkpoint**: la no regresión está demostrada con datos reales, no con un test sintético.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T033 Ejecutar la suite completa con `docker compose exec -T webapp /webodm/webodm.sh test backend coreplugins.road.tests` y comprobar que el recuento de tests **sube** respecto de la feature anterior
- [X] T034 Verificar en worker un análisis real en modo `surface` con `coherence_window = 2` y adjuntar el fragmento del log, según [quickstart.md](./quickstart.md#verificación-del-worker-principio-iv-no-negociable) — Principio IV, no negociable
- [X] T035 Medir SC-001, SC-002 y SC-003 sobre la calle de referencia y adjuntar las cifras
- [X] T036 Medir SC-007 cronometrando el mismo análisis en los dos modos, y el consumo de memoria con la coherencia activada
- [X] T037 [P] Documentar los dos modos, cuándo usar cada uno y el límite conocido del criterio de superficie en `coreplugins/road/README.md`
- [X] T038 [P] Registrar el resultado de los escenarios de [quickstart.md](./quickstart.md) en `specs/006-street-width/validacion-manual.md`, diciendo con honestidad cuáles se validaron a mano y cuáles solo con tests
- [X] T039 [P] (Opcional, D24) Correr el criterio de superficie sobre `Noria` y `ruta de zona 1`, comparar contra el de quiebre y anotar en [research.md](./research.md) si la deuda de los dos modos se puede saldar

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: primero de todo, y **antes de tocar una sola línea de código**.
- **Foundational (Phase 2)**: depende de Setup. Bloquea todas las historias.
- **US1 (Phase 3)**: depende de Foundational. Sin dependencias con otras historias.
- **US2 (Phase 4)**: depende de Foundational. Independiente de US1 en el código, aunque su valor solo
  se aprecia sobre un análisis en modo `surface`.
- **US3 (Phase 5)**: depende de Foundational **y de US2** — sin coherencia no hay bordes inferidos
  que declarar.
- **US4 (Phase 6)**: depende de Setup (el baseline) y de que las historias que se vayan a entregar
  estén completas.
- **Polish (Phase 7)**: al final.

### Within Each User Story

- Los tests van primero y deben fallar antes de implementar.
- En `profile.py`: primero el criterio (T009), después la pendiente transversal (T010).
- En `compute.py`: despacho (T011) → retención de perfiles (T017) → llamada a la coherencia (T018) →
  import en el worker (T019) → campos de origen (T025). **Todas tocan el mismo archivo y van en
  serie**, aunque pertenezcan a fases distintas.
- En `RoadPanel.jsx`: modo y tolerancia (T012) antes que la ventana de coherencia (T020).

### Parallel Opportunities

- T002, T003 y T005 en paralelo: `sources.py`, `test_params.py` y `test_api_capabilities.py` son
  archivos distintos.
- Dentro de US3, los cuatro tests (T021–T024) en paralelo entre sí, y después T026, T027 y T028
  también entre sí: cuatro archivos distintos.
- T029 y T030 en paralelo.
- T037, T038 y T039 en paralelo.
- **Cuidado con `compute.py`**: concentra seis tareas de cuatro fases. Es el cuello de botella real de
  esta feature y ninguna de sus tareas admite `[P]`.

---

## Parallel Example: User Story 3

```bash
# Los cuatro tests de US3, en cuatro archivos distintos:
Task: "Export CSV/GeoJSON en coreplugins/road/tests/test_export.py"
Task: "Estilo de inferred en coreplugins/road/public/tests/segmentStyle.test.js"
Task: "Popup con origen por lado en coreplugins/road/public/tests/roadBridge.test.js"
Task: "Invariantes del modelo en coreplugins/road/tests/test_compute.py"

# Y después, tres de las cuatro implementaciones:
Task: "Columnas y propiedades en coreplugins/road/export.py"
Task: "Trazo de inferred en coreplugins/road/public/segmentStyle.js"
Task: "Origen en el popup en coreplugins/road/public/roadBridge.js"
```

---

## Implementation Strategy

### MVP (solo US1)

1. Phase 1: capturar el baseline.
2. Phase 2: los parámetros de punta a punta.
3. Phase 3: el criterio de superficie.
4. **PARAR Y VALIDAR**: medir SC-001 sobre la calle de referencia.

Con eso la herramienta ya sirve en entorno urbano, con `coherence_window = 0` y sin ningún campo
nuevo en el modelo de datos. Es una entrega defendible por sí sola.

### Entrega incremental

1. Setup + Foundational → los parámetros existen y nada cambia.
2. + US1 → se puede medir una calle. **MVP.**
3. + US2 → la dispersión entre tramos vecinos se corrige sin inventar.
4. + US3 → cada cifra dice de dónde sale. Cierra el compromiso que hizo aceptable la inferencia.
5. + US4 → la no regresión queda demostrada con datos reales.

### Nota sobre el orden real

US2 y US3 son, en la práctica, una sola entrega: publicar bordes inferidos **sin** declararlos
rompería `005/FR-022`, que es el principio que hace fiable al plugin. Si hay que parar a mitad, se
para **antes** de US2, no entre US2 y US3.

---

## Notes

- `[P]` = archivos distintos, sin dependencias pendientes.
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida con el
  exit code, en el mismo reporte (Flujo de desarrollo de la constitución).
- Toda clase de test nueva se re-exporta desde `tests/__init__.py` o no se ejecuta.
- El bundle `Road.js` se cachea con fuerza: si el mapa no refleja un cambio de frontend, `Cmd+Shift+R`
  antes de sospechar del código.
- No usar `run_tests_in_docker.sh` en esta instancia: su `docker compose down -v` destruiría las
  tareas reales que necesitan T001, T032 y T034.
