---

description: "Tareas de implementación — etiquetado asistido por regiones"
---

# Tasks: Etiquetado asistido por regiones en el plugin `training`

**Input**: documentos de diseño en `specs/010-superpixel-labeling/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/rest-api.md](./contracts/rest-api.md),
[quickstart.md](./quickstart.md)

**Tests**: incluidos. El Flujo de desarrollo de la constitución exige ejecutar el comando que
verifica cada tarea y mostrar su salida; sin tests eso no es posible.

**Organización**: por historia de usuario, para que cada una se pueda implementar y validar sola.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (ficheros distintos, sin dependencias pendientes)
- **[Story]**: a qué historia pertenece (US1–US4)

## Path Conventions

Todo vive en `coreplugins/training/`. Backend en la raíz del plugin, frontend en `public/`, tests
en `tests/` (Python) y `public/tests/` (JavaScript).

**Orden de ejecución de la suite**:

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.training.tests
```

⚠️ **Nunca `./run_tests_in_docker.sh`**: hace `docker compose down -v` y borraría las tareas reales.

⚠️ **Todo módulo de test nuevo debe reexportarse en `tests/__init__.py`.** Si no, no se ejecuta y la
suite sigue en verde — el fallo silencioso que ya ocurrió en `008`.

---

## Phase 1: Setup — el gate de dependencias

**Purpose**: dejar `scikit-image` disponible sin romper `rasterio`. Va primero porque, si esto falla,
todo lo demás da resultados engañosos.

- [X] T001 Crear `coreplugins/training/requirements.txt` con `scikit-image==0.24.0`, `numpy==1.26.2`
      y `scipy==1.11.3`. Los pines de numpy y scipy **no son opcionales**: el instalador del
      framework (`app/plugins/plugin_base.py:44`) usa `pip install -U --target` sin `--no-deps` y
      `python_imports()` antepone el directorio del plugin a `sys.path`; sin ellos entra numpy 2.0.2
      y `rasterio` revienta con `numpy.dtype size changed` (research.md D1)
- [X] T002 Crear `coreplugins/training/tests/test_requirements.py`: afirmar que la versión de numpy y
      de scipy instalada en `get_python_packages_path()` **coincide** con la del intérprete del
      sistema, y que `import rasterio` y `from skimage.segmentation import slic` funcionan con ese
      directorio al frente de `sys.path`. Es el gate que convierte en fallo ruidoso la rotura
      silenciosa que traería un merge de upstream que suba numpy
- [X] T003 Reexportar `test_requirements` en `coreplugins/training/tests/__init__.py`
- [X] T004 Verificación de workers (Principio IV paso 3, **no negociable**): mostrar la salida de
      `docker compose exec worker python -c "from coreplugins.training import superpixels"` y de
      `docker compose logs --tail=50 worker` demostrando que el worker importa el módulo nuevo sin
      errores. Se repite al final de la feature, cuando `superpixels.py` ya tenga contenido

**Checkpoint**: `scikit-image` disponible y `rasterio` intacto, con evidencia.

---

## Phase 2: Foundational — la partición determinista

**Purpose**: la maquinaria que todas las historias comparten: rejilla anclada, partición, caché y
vectorización.

**⚠️ CRÍTICO**: ninguna historia puede empezar hasta que esta fase esté completa.

- [X] T005 [P] Crear `coreplugins/training/superpixels.py` con la geometría de la rejilla de trabajo:
      `CELL = 512`, paso `S` de 8/16/32 px según granularidad, halo `8·S`, anclaje a la esquina
      superior izquierda de la ortofoto (mismo criterio que `tiling.py`). Funciones para resolver la
      celda de un punto del terreno y la ventana de cálculo de una celda. Imponer las invariantes:
      `S` divide a `CELL` y el origen de cada ventana es múltiplo de `S` en coordenadas globales
- [X] T006 [P] En `coreplugins/training/models.py`: añadir `SOURCE_ASSISTED = 'assisted'` y la
      validación del bloque `assist` del dataset (`granularity` en `fine`/`medium`/`coarse`,
      `tolerance` y `elevation_weight` en `[0, 1]`), y rellenarlo en `with_defaults()` para los
      datasets creados antes de esta feature (data-model.md)
- [X] T007 [P] Crear `coreplugins/training/tests/test_superpixels.py` con los tests de la rejilla:
      la celda de un punto no depende del encuadre ni del zoom; el origen de la ventana es siempre
      múltiplo de `S`; `S` que no divide a `CELL` es un error explícito
- [X] T008 [P] Ampliar `coreplugins/training/tests/test_api_datasets.py` con los ajustes `assist`:
      valores por defecto, rechazo de granularidad desconocida y de tolerancia/peso fuera de rango
- [X] T009 En `superpixels.py`, construir el stack de bandas de una ventana: RGB de la ortofoto leído
      al tamaño de salida, más `slope` y `roughness` de `elevation.tile_channels()` escalados por
      `elevation_weight`. Con peso 0 o sin ráster de elevación, 3 bandas. **`elevation.py` no se
      toca**: se consume tal cual, incluida su corrección del desalineo de 0,6 px entre ortofoto y
      DTM
- [X] T010 En `superpixels.py`, la partición: `slic` con `n_segments = (W/S)·(H/S)` para que el paso
      efectivo sea exactamente `S`, sobre la ventana con halo, recortando al núcleo. Devolver el mapa
      de etiquetas, el vector medio por región y los pares de adyacencia (research.md D2)
- [X] T011 Añadir a `tests/test_superpixels.py` **el test que define la feature**: la partición del
      núcleo de una celda calculada con halo `8·S` es **idéntica** a la calculada con un halo mayor
      (0,000 % de desacuerdo medido), y una ventana con origen no múltiplo de `S` diverge. Sin este
      test, FR-007 y FR-009 pueden romperse en cualquier refactor sin que nadie se entere
- [X] T012 Crear `coreplugins/training/regions.py`: caché de mapas de regiones bajo
      `get_persistent_path()`, con clave `(task_id, resolución, S, elevation_weight, versión del
      algoritmo)`. Incluir la versión del algoritmo es lo que impide que un cambio futuro en la
      partición conviva con mapas viejos y rompa el determinismo en silencio (research.md D5)
- [X] T013 En `regions.py`, presupuesto de caché por dataset y expulsión por antigüedad de acceso.
      Perder un mapa no pierde nada: se reconstruye en ~0,95 s
- [X] T014 [P] Crear `coreplugins/training/tests/test_regions_cache.py`: un mapa cacheado devuelve
      exactamente lo mismo que el recién calculado; cambiar granularidad o peso genera clave nueva;
      la expulsión respeta el presupuesto
- [X] T015 En `superpixels.py`, vectorizar una selección: máscara booleana de las regiones elegidas →
      `rasterio.features.shapes` → `MultiPolygon` en EPSG:4326. Reproyectar con
      `rasterio.warp.transform`, **nunca** con `GEOSGeometry.transform`, que invierte el orden de
      ejes al pasar a 4326 y produce geometrías corruptas en silencio (research.md D6)
- [X] T016 Añadir a `tests/test_superpixels.py` los tests de vectorización: el polígono resultante es
      válido y cerrado; una región que cruza el borde de una celda sale entera y sin junta; las
      coordenadas caen donde deben (no invertidas)
- [X] T017 Reexportar `test_superpixels` y `test_regions_cache` en `tests/__init__.py`

**Checkpoint**: partición determinista, cacheada y vectorizable. Las historias pueden empezar.

---

## Phase 3: User Story 1 — Seleccionar una región de un clic (P1) 🎯 MVP

**Goal**: activar el modo, pinchar sobre la calzada y que aparezca una etiqueta de la clase activa
con el contorno del borde real.

**Independent Test**: activar el modo, pinchar sobre una calzada, comprobar que aparece la etiqueta
con su contorno; recargar la página y comprobar que sigue ahí.

### Tests for User Story 1

- [X] T018 [P] [US1] Crear `coreplugins/training/tests/test_api_regions.py` con el contrato de
      `POST datasets/<id>/tasks/<task>/regions` para un punto: forma de la respuesta
      (`geometry`, `region_count`, `elevation_source`, `band_count`, `truncated`, `prepared_cells`)
      según [contracts/rest-api.md](./contracts/rest-api.md)
- [X] T019 [P] [US1] En `test_api_regions.py`, el test de determinismo de FR-007: tres peticiones con
      el mismo punto devuelven geometrías idénticas, y también con la caché fría
- [X] T020 [P] [US1] En `test_api_regions.py`, los casos de error del contrato: `bad_points` (400),
      `bad_settings` (400), `not_found` (404), `no_orthophoto` (409), sin acceso (403), y el
      **`200` con `geometry: null` y `reason: "no_data"`** al pinchar fuera de la huella del vuelo,
      que no es un error (FR-025)
- [X] T021 [P] [US1] Crear `coreplugins/training/public/tests/assistMode.test.js`: activar
      `MODE_ASSIST` no rompe los modos existentes y `Shift` sigue haciendo selección múltiple y
      marcado de vértices (FR-002)

### Implementation for User Story 1

- [X] T022 [US1] Implementar `RegionSelect` en `coreplugins/training/api.py` para el caso de un
      punto: resolver la celda, preparar o leer de caché, devolver la geometría de la región. Los
      ajustes se aceptan en la petición y, si faltan, se toman del dataset
- [X] T023 [US1] Registrar `datasets/(?P<dataset_id>[^/.]+)/tasks/(?P<pk>[^/.]+)/regions$` en
      `api_mount_points()` de `coreplugins/training/plugin.py`, con `$` final y respetando el orden
      frente a los patrones genéricos, según la convención documentada en ese fichero
- [X] T024 [US1] Añadir `MODE_ASSIST` a `coreplugins/training/public/LabelEditor.js`, junto a los
      seis modos existentes, con su comportamiento en `setMode()`, `isBrush()`/`isRing()` y el
      manejo del clic. **Sin usar `Shift`** (FR-002)
- [X] T025 [US1] Crear `coreplugins/training/public/assistLayer.js`: pide la región del punto bajo el
      cursor y la dibuja como previsualización antes de confirmarla
- [X] T026 [US1] Añadir el botón del modo a la barra de herramientas en
      `coreplugins/training/public/TrainingPanel.jsx`, junto a polígono, pincel y borrador (FR-001)
- [X] T027 [US1] Al confirmar el clic, crear la etiqueta por el endpoint de etiquetas que ya existe,
      con `kind: 'polygon'` y `source: 'assisted'`. **No se crea un endpoint de escritura nuevo**:
      toda la validación de etiquetas sigue en un solo sitio
- [X] T028 [US1] Indicador de preparación en el panel: mientras se calcula una celda nueva el usuario
      debe saber que está ocurriendo, y cuándo está listo (FR-024)
- [X] T029 [US1] Mensajes de usuario del camino de US1 con `_()`, claros y accionables: fuera de la
      huella del vuelo, tarea sin ortofoto, sin permiso (FR-025)
- [X] T030 [US1] Reexportar `test_api_regions` en `tests/__init__.py`
- [X] T031 [US1] Ejecutar la suite y mostrar su salida con exit code; validar a mano los escenarios
      1–6 de la tabla de [quickstart.md](./quickstart.md) §3 más §2.1 (determinismo), §2.2
      (independencia del encuadre) y §2.3 (sin juntas visibles)

**Checkpoint**: US1 funciona sola. Es el MVP: ya se ahorra el trazado de bordes.

---

## Phase 4: User Story 2 — Pintar varias regiones arrastrando (P2)

**Goal**: arrastrar el cursor a lo largo de una pista y que todas las regiones tocadas queden
etiquetadas.

**Independent Test**: arrastrar sobre una pista y comprobar que las regiones tocadas quedan con la
clase activa y el contorno sigue el borde de la calzada.

### Tests for User Story 2

- [X] T032 [P] [US2] En `tests/test_api_regions.py`, el contrato con varios puntos: la unión de
      regiones sale como un `MultiPolygon` y `region_count` refleja cuántas entraron
- [X] T033 [P] [US2] En `tests/test_api_regions.py`, FR-005: un punto que cae junto al borde de una
      región devuelve la región **entera**, nunca una fracción
- [X] T034 [P] [US2] En `public/tests/assistMode.test.js`, el arrastre acumula regiones y al soltar
      escribe una sola vez

### Implementation for User Story 2

- [X] T035 [US2] Ampliar `RegionSelect` en `api.py` para aceptar varios puntos en `points` y devolver
      la unión, preparando las celdas que hagan falta
- [X] T036 [US2] Manejo del arrastre en `LabelEditor.js` y `assistLayer.js`: acumular las regiones
      tocadas durante el gesto y previsualizar la unión en vivo
- [X] T037 [US2] Escribir la etiqueta **al soltar**, no por cada región tocada: un arrastre produce
      una etiqueta, no treinta
- [X] T038 [US2] Ejecutar la suite y mostrar su salida; validar a mano los escenarios 7 y 8 de
      quickstart.md §3

**Checkpoint**: US1 y US2 funcionan de forma independiente.

---

## Phase 5: User Story 3 — Extender la selección a lo parecido (P3)

**Goal**: un clic con tolerancia selecciona el área uniforme contigua y se detiene en el borde.

**Independent Test**: pinchar con tolerancia mínima (una región) y subirla progresivamente,
comprobando que la selección crece de forma continua y se detiene en un borde marcado.

### Tests for User Story 3

- [X] T039 [P] [US3] En `tests/test_superpixels.py`, la monotonía de FR-017: con tolerancias A < B
      sobre el mismo punto, la selección de A está **contenida** en la de B
- [X] T040 [P] [US3] En `tests/test_superpixels.py`, el tope de FR-018: el crecimiento se detiene en
      el límite de regiones y lo señala, en vez de expandirse sin freno
- [X] T041 [P] [US3] En `tests/test_api_regions.py`, `truncated: true` viaja en la respuesta cuando
      se alcanza el tope

### Implementation for User Story 3

- [X] T042 [US3] En `superpixels.py`, el crecimiento por tolerancia: recorrido en anchura sobre los
      pares de adyacencia, admitiendo una vecina si la distancia entre vectores medios está bajo la
      tolerancia. El tope se evalúa **antes** de expandir (research.md D7)
- [X] T043 [US3] Permitir que el crecimiento cruce a celdas vecinas, preparándolas al vuelo. La
      coincidencia exacta en el solape (T011) garantiza que la región resultante no tenga junta
- [X] T044 [US3] Exponer `tolerance` en `RegionSelect` y propagar `truncated` a la respuesta
- [X] T045 [US3] Control de tolerancia en `TrainingPanel.jsx` y aviso visible cuando la respuesta
      llega con `truncated: true` (FR-018)
- [X] T046 [US3] Ejecutar la suite y mostrar su salida; validar a mano los escenarios 9–12 de
      quickstart.md §3

**Checkpoint**: las tres historias funcionan de forma independiente.

---

## Phase 6: User Story 4 — Ajustar la asistencia al terreno (P4)

**Goal**: trabajar sobre terreno donde el relieve no aporta, o sobre una tarea sin modelo de terreno,
sin cambiar de herramienta.

**Independent Test**: etiquetar una zona con el peso por defecto, anularlo, repetir en la misma zona
y comprobar que la herramienta sigue produciendo regiones utilizables.

### Tests for User Story 4

- [X] T047 [P] [US4] En `tests/test_superpixels.py`, la caída sin elevación: sin ráster de terreno,
      o con `elevation_weight = 0`, la partición usa 3 bandas y **no falla** (FR-011)
- [X] T048 [P] [US4] En `tests/test_api_regions.py`, `elevation_source` y `band_count` reflejan lo
      que realmente se usó (`dtm`, `dsm` o `none`)
- [X] T049 [P] [US4] En `tests/test_api_datasets.py`, FR-023: cambiar granularidad, tolerancia o peso
      **no altera ninguna etiqueta ya guardada**

### Implementation for User Story 4

- [X] T050 [US4] Capturar `ElevationUnavailable` de `elevation.resolve_source()` y caer a 3 bandas
      declarándolo en la respuesta, en vez de tratarlo como error (FR-011)
- [X] T051 [US4] Persistir los ajustes de asistencia en el documento del dataset con
      `store.update_dataset`, bajo el advisory lock que el plugin ya usa (FR-022)
- [X] T052 [US4] Controles de granularidad y peso de elevación en `TrainingPanel.jsx`, con el peso
      llegando hasta cero (FR-012, FR-013)
- [X] T053 [US4] Mensaje en la interfaz cuando se está trabajando sin canales de terreno, con el
      motivo (la tarea no los tiene, o el usuario los anuló)
- [X] T054 [US4] Ejecutar la suite y mostrar su salida; validar a mano los escenarios 13–16 de
      quickstart.md §3

**Checkpoint**: las cuatro historias completas.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T055 [P] Implementar `GET datasets/<id>/tasks/<task>/regions/status` según el contrato: cuántas
      celdas del encuadre están listas y una estimación de segundos para las pendientes, para poder
      anunciar la espera **antes** de que ocurra (FR-024)
- [X] T056 [P] Test de `regions/status` en `tests/test_api_regions.py`, incluido que la respuesta de
      `POST regions` **no** dependa de `bounds` (FR-008: solo `status` es sensible a la vista)
- [X] T057 [P] Test de extremo a extremo del formato: exportar un dataset con etiquetas asistidas y
      manuales mezcladas y comprobar que el `.zip` no tiene **ninguna** diferencia de formato
      (FR-020, SC-008). Es el contrato más caro de romper del plugin
- [X] T058 [P] Comprobar que el plugin se puede desactivar y reactivar sin romper el etiquetado
      manual (FR-026, Principio III)
- [X] T059 [P] Revisar todos los textos `_(...)` nuevos de `api.py`, `TrainingPanel.jsx` y
      `assistLayer.js`: claros, accionables y traducibles
- [X] T060 [P] Actualizar `coreplugins/training/README.md`: el modo nuevo, la rejilla de trabajo y su
      anclaje, y **por qué el `requirements.txt` pinea numpy y scipy** — sin esa explicación, el
      siguiente que lo lea los quitará por parecer redundantes y romperá `rasterio`
- [X] T061 [P] Añadir `scikit-image` a la tabla de `docs/entorno-plugins.md`, moviéndola de «no
      disponible» a dependencia declarada por plugin, con la nota del conflicto de ABI
- [X] T062 Repetir la verificación de workers de T004 con `superpixels.py` ya implementado y mostrar
      la salida (Principio IV paso 3)
- [ ] T063 Ejecutar el recorrido funcional completo de quickstart.md §3 (los 19 escenarios) contra el
      stack en Docker y registrar el resultado de cada uno, distinguiendo lo validado a mano de lo
      cubierto solo por la suite

      **Parcial.** Los 12 escenarios que pasan por la API se validaron por la ruta HTTP real contra
      el stack vivo (ver research.md §Mediciones de la implementación): 4, 6, 7, 8, 9, 10, 11, 12,
      13, 14, 15, 16 y 19. Quedan los 7 que solo se ven en el navegador: **1** (botón y cursor),
      **2** (etiqueta creada de un clic), **3** (persistencia tras recargar), **5** (retoque con el
      borrador), **17** (`Shift` sin interferencia, cubierto por `assistMode.test.js` pero no a
      mano) y **18** (desactivar y reactivar el plugin, cubierto por `AssistIsolationTest` pero no a
      mano). Requieren una sesión de navegador sobre la instancia del usuario.
- [ ] T064 Medir SC-001 y SC-005 sobre una pista de tierra de ~100 m: tiempo con el pincel de píxeles
      contra tiempo con la selección asistida (debe bajar a menos de la mitad) y fracción de regiones
      que necesitaron retoque (< 20 %). Registrar ambas cifras en research.md

      **No hecho.** Las dos son medidas sobre un operador humano etiquetando dos veces la misma
      pista con un cronómetro. No hay forma de producirlas sin esa sesión, y estimarlas sería
      inventarlas.
- [X] T065 Confirmar SC-002, SC-003, SC-004, SC-006, SC-007 y SC-008 con evidencia (salidas de
      comandos, `docker stats`, capturas), según la tabla de quickstart.md §4

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: sin dependencias. **Bloquea todo**: sin el gate de ABI resuelto, cualquier
  medición posterior es engañosa
- **Phase 2 (Foundational)**: depende de Phase 1. **Bloquea todas las historias**
- **Phases 3–6 (historias)**: dependen de Phase 2. En orden de prioridad, o en paralelo si hay manos
- **Phase 7 (Polish)**: depende de las historias que se quieran entregar

### User Story Dependencies

- **US1 (P1)**: solo depende de Phase 2. Es el MVP
- **US2 (P2)**: solo depende de Phase 2. Reutiliza el endpoint de US1 ampliándolo, pero se valida sola
- **US3 (P3)**: solo depende de Phase 2. Necesita los pares de adyacencia de T010
- **US4 (P4)**: solo depende de Phase 2. Es transversal, pero su valor (funcionar sin terreno) se
  comprueba sin las otras historias

### Dentro de cada historia

Tests → backend → rutas → frontend → validación manual. Los tests se escriben antes y deben **fallar**
antes de implementar.

### Parallel Opportunities

- T005–T008 en paralelo (rejilla, modelo y sus tests, ficheros distintos)
- T018–T021 en paralelo (todos los tests de US1)
- T032–T034, T039–T041, T047–T049 en paralelo dentro de sus historias
- T055–T061 en paralelo en Polish
- Con varias manos: US1, US2, US3 y US4 en paralelo una vez cerrada la Phase 2

## Parallel Example: User Story 1

```text
# Los cuatro tests de US1, a la vez:
T018 Contrato de POST regions en tests/test_api_regions.py
T019 Determinismo (FR-007) en tests/test_api_regions.py
T020 Casos de error y no_data en tests/test_api_regions.py
T021 MODE_ASSIST y no colisión con Shift en public/tests/assistMode.test.js
```

---

## Implementation Strategy

### MVP primero (solo US1)

1. Phase 1 completa — **con evidencia**, o nada de lo que venga después es fiable
2. Phase 2 completa, con T011 en verde: es el test que sostiene FR-007 y FR-009
3. Phase 3 completa
4. **PARAR Y VALIDAR**: §2.1, §2.2 y §2.3 de quickstart.md
5. Ya hay producto: se ahorra el trazado de bordes

### Entrega incremental

Cada historia añade valor sin romper la anterior: US2 hace el gesto más rápido, US3 cubre las áreas
grandes, US4 asegura que nada de esto depende de que el terreno coopere.

---

## Notes

- **T011 es la tarea que no se puede saltar.** El halo de `8·S` sobre ventanas alineadas es lo único
  que hace compatibles FR-009 y FR-015, y es invisible en revisión de código: sin ese test, un
  refactor que cambie `n_segments` o el tamaño de ventana rompe el determinismo sin síntoma
- Reexportar cada módulo de test nuevo en `tests/__init__.py`, o no se ejecuta y la suite sigue verde
- `elevation.py`, `rasterize.py` y `export.py` **no se tocan**. Si una tarea parece necesitarlo,
  probablemente esté saliéndose del alcance
- Ningún fichero del core (`app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/`) se modifica
- Ninguna tarea se marca completa sin ejecutar el comando que la verifica y mostrar su salida con
  exit code
- Al validar a mano, usar un dataset de prueba propio e identificable: un polígono ajeno borrado por
  descuido no se recupera
