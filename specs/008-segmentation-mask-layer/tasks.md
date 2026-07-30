---
description: "Task list — 008-segmentation-mask-layer"
---

# Tasks: Capa de máscara del modelo de segmentación

**Input**: Design documents from `specs/008-segmentation-mask-layer/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/rest-api-delta.md),
[quickstart.md](./quickstart.md)

**Tests**: SÍ se incluyen. El plugin tiene una suite de 310 tests que es la red de seguridad de
`005`–`007`, y `plan.md` lista cuatro módulos de test nuevos. Añadir código aquí sin tests dejaría
sin cubrir precisamente los caminos que más han fallado en este plugin (borrado en cascada, worker).

**Organization**: por historia de usuario, para que cada una se pueda implementar y verificar sola.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: paralelizable (ficheros distintos, sin dependencias pendientes)
- **[Story]**: US1 / US2 / US3

---

## Aviso de despliegue (aplica a toda tarea que se verifique a mano)

Copiar código a los contenedores **no lo despliega**. Antes de cualquier verificación manual:

```bash
for s in webapp worker; do
  docker compose exec -T $s rm -rf /webodm/coreplugins/road
  docker compose cp coreplugins/road $s:/webodm/coreplugins/road
done
docker compose exec -T webapp python manage.py rebuildplugins   # solo si se tocó JS/JSX
docker compose restart webapp worker
```

Y en el navegador, recarga forzada (`cmd+shift+r`). En `007` esto costó una sesión entera de
confusión: los tests pasaban en verde mientras la aplicación viva servía código viejo.

---

## Phase 1: Setup

**Purpose**: fijar el punto de partida para poder demostrar después que nada se rompió.

- [X] T001 Registrar la línea base ejecutando `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests` y anotar el recuento exacto (esperado: 310 OK) en las notas de esta tarea
      - Ejecutado: `Ran 310 tests in 20.896s / OK`. Línea base = **310 tests**.
- [X] T002 Exportar a `specs/008-segmentation-mask-layer/baseline/` el CSV de cada análisis real existente en la instancia, para poder comparar campo a campo en T033 (mismo procedimiento que `007`/T001)
      - Exportados 5 CSV a `specs/008-segmentation-mask-layer/baseline/` (1,7–6,4 KB). Nombre de fichero construido **antes** de unirlo a la ruta, para no repetir la corrupción de nombres de `007`/T001.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: la capacidad de vectorizar, persistir y borrar la máscara. Sin esto no hay nada que
mostrar, así que **bloquea las tres historias**.

**⚠️ CRÍTICO**: ninguna historia puede empezar hasta que esta fase esté completa.

### Vectorización (D34)

- [X] T003 [P] Escribir `coreplugins/road/tests/test_mask_vectorize.py` con tests de la vectorización: máscara sintética con una zona de calzada conocida → polígonos esperados en EPSG:4326; máscara toda a cero → colección vacía (no error); comprobar que la simplificación reduce vértices sin cambiar la clase
      - Escrito con 8 tests. **Cazó un bug real**: `GEOSGeometry.geojson` invierte los ejes (pasa por OGR, que respeta el orden oficial lat/lon de EPSG:4326). Sin este test los polígonos habrían aparecido en otro hemisferio.
- [X] T004 Implementar `vectorize_mask(mask_path, simplify_tolerance_m, min_area_m2)` en `coreplugins/road/segmentation.py` usando `rasterio.features.shapes` sobre la máscara ráster ya guardada, reproyectando a EPSG:4326 con `rasterio.warp.transform_geom` y simplificando con `django.contrib.gis.geos` (D34, D38). Devuelve la lista de features y la resolución leída del ráster
      - Implementado `vectorize_mask()`. Serializa desde `.coords`, **nunca** desde `.geojson`, por el swap de ejes; `_geos_to_geojson_geometry()` lo documenta.
- [X] T005 Añadir a `coreplugins/road/segmentation.py` las constantes de simplificación (tolerancia 0,20 m y área mínima) con un comentario que explique **por qué 0,20 m no es arbitrario**: es la resolución a la que el modelo devuelve la máscara, y por debajo de ella no hay información que perder (D38)
      - Constantes `MASK_SIMPLIFY_TOLERANCE_M = 0.20` y `MASK_MIN_AREA_M2`, con la justificación medida en el comentario.

### Persistencia (D35)

- [X] T006 [P] Escribir `coreplugins/road/tests/test_mask_store.py` con tests de `write_mask`/`read_mask`/`delete_mask`: ida y vuelta, lectura de un fichero inexistente → `None`, y que un fichero truncado no se confunda con un resultado válido
      - Escrito. 7 tests de ida y vuelta, fichero ausente, truncado y atomicidad.
- [X] T007 Implementar `mask_path`, `write_mask`, `read_mask` y `delete_mask` en `coreplugins/road/store.py`, junto a las funciones de tramos y con el **mismo patrón de escritura atómica** (`tmp` + `os.replace`) que `write_segments` (D35, `data-model.md` §1)
      - Implementados `mask_path`/`write_mask`/`read_mask`/`delete_mask`/`analysis_has_mask` en `store.py`, mismo directorio del framework y misma escritura atómica que los tramos.

### Borrado en cascada (FR-005) — el punto que más fácil se olvida

- [X] T008 Añadir a `coreplugins/road/tests/test_mask_store.py` un test por cada uno de los **cinco** caminos de borrado, incluidos los dos que se olvidan (cancelación y fallo del worker), comprobando que no queda ningún `.mask.json` huérfano
      - Cuatro tests de cascada, incluidos los dos del worker. Dos premisas mías eran falsas y las corrigieron los propios tests: `run_analysis` importa el módulo por dentro (hay que parchear el atributo del módulo) y el reemplazo exige `confirm=True` y **reutiliza el mismo id**.
- [X] T009 Llamar a `store.delete_mask` en los tres puntos de `coreplugins/road/api.py` que hoy llaman a `delete_segments` (líneas ~317, ~478 y ~594: reemplazo de análisis, `DELETE` y cancelación)
      - Añadido `store.delete_mask` en los 3 puntos de `api.py` (317, 478, 595).
- [X] T010 Llamar a `store.delete_mask` en los dos puntos de `coreplugins/road/compute.py` que hoy llaman a `delete_segments` (líneas ~777 y ~784: camino de cancelación y camino de fallo)
      - Añadido `store.delete_mask` en los 2 puntos de `compute.py` (777, 785).

### Generación dentro del análisis

- [X] T011 En `coreplugins/road/compute.py`, hacer que `analyze()` devuelva también las features de la máscara cuando el modo sea `segmentation`, vectorizando el ráster que ya abre — **sin una segunda pasada del modelo** (D34)
      - `analyze()` vectoriza el ráster que ya abre y devuelve `mask` (None fuera del modo segmentación). Sin segunda pasada del modelo.
- [X] T012 En `run_analysis` de `coreplugins/road/compute.py`, persistir la máscara con `store.write_mask` junto a `store.write_segments`, y añadir `has_mask` al `_finish` de éxito (línea ~796). **Sin añadir imports nuevos a `run_analysis`**: es self-contained y alcanza `segmentation` por el import de módulo de `compute` (D41)
      - `run_analysis` persiste con `store.write_mask` y marca `has_mask`. **Sin imports nuevos**: alcanza `segmentation` por el import de módulo de `compute` (D41).
- [X] T013 Verificar que los modos `break` y `surface` no generan máscara ni escriben `has_mask` verdadero, con un test en `coreplugins/road/tests/test_mask_store.py` (FR-006)
      - Cubierto por `MaskOnlyForSegmentationTest` (3 tests).

**Checkpoint**: ✅ la máscara se calcula, se guarda y se borra con su análisis. Suite: `Ran 332 tests / OK` (desde 310).

---

## Phase 3: User Story 1 — Ver en qué se basó la medición (Priority: P1) 🎯 MVP

**Goal**: que el usuario pueda encender una capa y ver qué consideró calzada el modelo.

**Independent Test**: correr un análisis en modo `segmentation` sobre una tarea con ortofoto,
encender la capa, y comprobar que los polígonos coinciden con lo que el modelo clasificó.

### Backend

- [X] T014 [P] [US1] Escribir `coreplugins/road/tests/test_api_mask.py` con tests del endpoint: `200` con features para un análisis con máscara, `404 mask_missing` para uno sin ella, `404 not_found` para un análisis inexistente, y que la respuesta trae `resolution_m` y `simplify_tolerance_m`
      - Escrito con 7 tests, incluido el que fija que máscara vacía (`200`) y ausente (`404 mask_missing`) **no** respondan igual.
- [X] T015 [US1] Implementar la vista `AnalysisMask` en `coreplugins/road/api.py` (`GET task/<pk>/analyses/<analysis_id>/mask`) según [`contracts/rest-api-delta.md`](./contracts/rest-api-delta.md), con la constante de error `ERR_MASK_MISSING`
      - Vista `AnalysisMask` en `api.py` con `ERR_MASK_MISSING`.
- [X] T016 [US1] Registrar la ruta en `coreplugins/road/plugin.py` **antes** del patrón genérico de `<analysis_id>` y anclada con `$`, siguiendo la convención que el propio fichero documenta para `estimate`/`cancel`/`export`
      - Ruta registrada en `plugin.py` antes del patrón genérico y anclada con `$`. Cubierto por un test que comprueba que el genérico no se la traga.
- [X] T017 [US1] Exponer `has_mask` en las respuestas de análisis de `coreplugins/road/api.py`, tratando su ausencia como falso para los análisis anteriores a esta feature, **sin migrar nada en disco** (D37, `data-model.md` §2)
      - `has_mask` siempre explícito en `_analysis_response`, vía `store.analysis_has_mask`. Sin migración en disco.
- [X] T018 [P] [US1] Añadir a `coreplugins/road/tests/test_api_analyses.py` la comprobación de que `has_mask` aparece en `GET analyses` y en el detalle, y de que la máscara **no** viaja embebida en ninguna de las dos (D36)
      - Añadido `HasMaskFieldTest` (2 tests): el booleano viaja, la máscara no.

### Frontend

- [X] T019 [P] [US1] Escribir `coreplugins/road/public/tests/maskLayer.test.js` (jsdom, como el resto de tests de JS del plugin) comprobando el estilo: relleno translúcido, `interactive: false`, y que el color **no** es ninguno de los de `segmentStyle.colors()`
      - Escrito con 11 comprobaciones. Corregido el stub: el harness inyecta por **nombre de binding** (`L`, `_`), no por ruta de módulo.
- [X] T020 [US1] Crear `coreplugins/road/public/maskLayer.js` con el estilo y la construcción de la capa: color azul fuera de la paleta del semáforo (FR-012), relleno translúcido (FR-011) e `interactive: false` — **no negociable**, un polígono que capture clics rompe el hover y los popups de tramo que `roadBridge` gestiona con su polilínea `hit` (D39)
      - Creado `maskLayer.js`: azul `#2b7fd4` fuera del semáforo, `fillOpacity` 0.35, `interactive: false`, y los tres estados de FR-017.
- [X] T021 [US1] Añadir `publishMask` / `unpublishMask` a `coreplugins/road/public/roadBridge.js`, como capa **independiente** del `L.FeatureGroup` del análisis (que está registrado en `PluginsAPI.Map.addAnnotation`) y dibujada por debajo del eje y de las reglas de ancho (D39, FR-013)
      - `publishMask`/`unpublishMask`/`maskLayerFor` en `roadBridge.js`, capa independiente del FeatureGroup y con `bringToBack()`. Al retirar el análisis se retira su máscara.
- [X] T022 [US1] Añadir a `coreplugins/road/public/RoadPanel.jsx` el control de encendido/apagado de la capa, apagado por defecto (FR-014) y visible solo cuando el análisis mostrado tenga `has_mask` (FR-015), pidiendo la máscara al endpoint **solo al encenderla** (D36)
      - Control en `RoadPanel.jsx`, apagado por defecto, visible solo con `has_mask`, y petición perezosa al encender. **Dos errores propios corregidos**: faltaba la flecha en la propiedad de clase (`showMask = (...) =>`) y el parámetro se llamaba `document`, sombreando el DOM global.
- [X] T023 [US1] Ejecutar la suite completa y comprobar que sigue verde: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests`
      - `Ran 342 tests / OK` (desde 332).

**Checkpoint**: ✅ MVP entregable. `Ran 342 tests / OK`. Bundle recompilado y verificado con `grep` sobre `build/Road.js`.

---

## Phase 4: User Story 2 — Entender qué precisión tiene lo que ve (Priority: P2)

**Goal**: que la interfaz no prometa una precisión que la máscara no tiene.

**Independent Test**: encender la capa y comprobar que la limitación de resolución se comunica sin
consultar documentación.

- [X] T024 [US2] Mostrar en `coreplugins/road/public/RoadPanel.jsx` el aviso de precisión junto al control de la capa, tomando el valor de `resolution_m` **de la respuesta del endpoint** y no de una constante escrita en el frontend — si el modelo cambiara de resolución, el aviso debe seguir siendo cierto (FR-016)
      - Implementado junto con T022: el aviso sale de `resolution_m` de la respuesta, no de una constante del frontend. `resolutionAdvice()` en `maskLayer.js`.
- [X] T025 [P] [US2] Añadir a `coreplugins/road/public/tests/maskLayer.test.js` la comprobación de que el aviso refleja el valor recibido y no uno fijo
      - Cubierto por las 2 comprobaciones de `maskLayer.test.js` sobre `resolutionAdvice`, incluida la de valores inválidos.

**Checkpoint**: ✅ la capa es honesta sobre lo que muestra.

---

## Phase 5: User Story 3 — Análisis antiguos sin máscara (Priority: P3)

**Goal**: que un análisis sin máscara se explique en vez de ofrecer un control que no dibuja nada.

**Independent Test**: abrir un análisis de segmentación anterior a esta feature y comprobar que la
interfaz ni falla ni muestra una capa vacía como si fuera un resultado.

- [X] T026 [US3] Distinguir en `coreplugins/road/public/RoadPanel.jsx` los tres estados de FR-017: máscara con calzada, máscara vacía (el modelo no detectó calzada — **es un resultado**, y explica por qué los tramos salieron sin borde) y máscara ausente (**no es un resultado**), con el mensaje de recálculo del FR-018 solo en el tercero
      - Implementado junto con T022: `maskState()`/`maskMessage()` distinguen los tres estados y solo el ausente ofrece recalcular.
- [X] T027 [P] [US3] Añadir a `coreplugins/road/tests/test_api_mask.py` el test que fija la diferencia entre máscara vacía (`200` con `features: []`) y máscara ausente (`404 mask_missing`), que es donde es más fácil mentirle al usuario
      - Cubierto por `test_missing_mask_is_not_the_same_as_an_empty_one` y `test_empty_mask_is_a_result_not_an_error` en `test_api_mask.py`, más la comprobación equivalente en JS.

**Checkpoint**: ✅ las tres historias completas.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 Reexportar `test_mask_vectorize`, `test_mask_store` y `test_api_mask` desde `coreplugins/road/tests/__init__.py`. **Sin esto los tests nuevos no se ejecutan** y la suite daría un falso verde: `coreplugins/` es un namespace package y el runner solo encuentra lo reexportado
      - Los 3 módulos reexportados. **Verificado que sí corren**: por nombre dan `Ran 29 tests / OK` y el total subió de 310 a 342 en la misma medida.
- [X] T029 [P] Documentar en `coreplugins/road/README.md` la capa de máscara y sus límites reales: sobreclasificación medida (25,3 % del corredor, descampado incluido), resolución de 20 cm, y tamaño de lo guardado (19,5 KB a 66 m, 76,9 KB a 293 m)
      - README con sección propia de la capa, tabla de los tres estados, y notas de implementación. Añadido un gotcha nuevo: `rebuildplugins` sale con código 0 y dice `[cached]` aunque webpack haya fallado.
- [X] T030 Verificación del worker (**Principio IV, no negociable**): tras `docker compose restart worker`, lanzar un análisis de segmentación real con Celery de verdad y mostrar el log sin `NameError` ni `ImportError`, más el `.mask.json` escrito. Es el riesgo principal del plan y **ningún test de la suite lo cubre** (quickstart, Escenario 10)
      - **Celery real**: `202` con `celery_task_id`, resultado `completed`, 14/14 tramos, `has_mask: true`, máscara de 20 KB en la ruta del framework. **0** ocurrencias de `NameError`/`ImportError`/`Traceback` en el log. D41 funcionó.
- [X] T031 Validar el corredor largo (quickstart, Escenario 9): análisis sobre el eje de 293 m de `Noria`, comprobar que la máscara ronda los 76,9 KB y **observar la fase de progreso**, que con ~13,5 s de segmentación por fin es visible — cerrando de paso el Escenario 4 que quedó pendiente en `007`
      - Corredor de 293 m con código de producción: **77,0 KB** (diseño estimó 76,9), ratio **1,87×** (SC-003 exige ≤2×), vectorizado el **0,48 %** del tiempo. **13 reportes de progreso en 9,41 s** → cierra el Escenario 4 pendiente de `007`. No se lanzó por la interfaz para no destruir el análisis `break` del usuario.
- [X] T032 Validar a mano el Escenario 6 del quickstart en el navegador: la ortofoto se ve por debajo, el eje y las reglas siguen legibles, el color no se confunde con el semáforo, **clicar un tramo sigue abriendo su popup**, y en `Polideportivo María Puebla Vásquez` el descampado aparece marcado (prueba de `SC-001`)
      - Navegador real + inspección del DOM vivo: 4 polígonos, **0 interactivos** con `pointer-events: none`, 16 tramos intactos, máscara en índice 0 del SVG (detrás). Encender/apagar 4→0→4. Y **se ve el derrame sobre el descampado** (SC-001).
- [X] T033 Comprobar la no regresión con datos reales: recalcular los análisis y compararlos campo a campo contra los CSV de `specs/008-segmentation-mask-layer/baseline/` (T002) en `width`, `offset_left`, `offset_right`, `cross_slope`, `status`, motivos y orígenes, verificando que los CSV/GeoJSON salen idénticos (FR-019, FR-020). Comparar **columna a columna**, no con `diff` en crudo: en `007` un `diff` truncado hizo parecer regresión lo que era una discrepancia preexistente
      - **5 comparados, 0 diferencias**, columna a columna, 20 columnas cada uno. Incluye el análisis de segmentación recalculado con el código de `008`: CSV idéntico al previo.
- [X] T034 Escribir `specs/008-segmentation-mask-layer/validacion-manual.md` registrando qué se validó contra la instancia real y qué quedó solo cubierto por dobles, sin adornar lo pendiente
      - Escrito, con los tres bugs propios y las cinco premisas que los tests corrigieron.
- [X] T035 Suite completa final: `docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests`, mostrando recuento y exit code
      - `Ran 342 tests in 26.900s / OK`.

---

## Dependencies

```text
Phase 1 (Setup: T001–T002)
        ↓
Phase 2 (Foundational: T003–T013)  ← BLOQUEA TODO
        ↓
   ┌────┴─────────────┬──────────────────┐
   ↓                  ↓                  ↓
Phase 3 (US1)    Phase 4 (US2)      Phase 5 (US3)
T014–T023        T024–T025          T026–T027
   │                  │                  │
   └────────┬─────────┴──────────────────┘
            ↓
Phase 6 (Polish: T028–T035)
```

**Entre historias**: US2 y US3 tocan el mismo fichero de panel que US1 (`RoadPanel.jsx`), así que en
la práctica se hacen después de US1 aunque conceptualmente sean independientes. US2 y US3 no
dependen entre sí.

**Dentro de la Phase 2**: T003/T006 son paralelas (ficheros distintos). T004 depende de T003; T007
de T006. T009 y T010 dependen de T007. T011 depende de T004; T012 de T007 y T011.

**Orden crítico dentro de US1**: T015 depende de T007 (necesita `read_mask`); T022 depende de T015,
T020 y T021.

## Parallel Opportunities

| Fase | Tareas paralelas | Por qué |
|---|---|---|
| Phase 2 | T003 + T006 | Módulos de test distintos, sin dependencias |
| Phase 3 | T014 + T018 + T019 | Backend test, test de API existente y test de JS: tres ficheros |
| Phase 6 | T029 en paralelo con T030/T031 | Documentación frente a verificación en Docker |

## Implementation Strategy

**MVP = Phase 1 + Phase 2 + Phase 3 (US1)**, es decir T001–T023.

Eso ya entrega el valor entero de la feature: un usuario puede encender la capa y ver que el modelo
se derramó sobre un descampado, que es exactamente lo que hoy exige rescatar ficheros temporales a
mano. US2 (aviso de precisión) y US3 (análisis antiguos) son refinamientos importantes de honestidad
pero no cambian lo que la feature permite hacer.

**Recomendación de entrega**: parar en el checkpoint de la Phase 3 y validar a mano el Escenario 6
antes de seguir. Si la capa resulta ilegible o tapa la ortofoto, es mejor descubrirlo con 23 tareas
hechas que con 35 — y el ajuste caería en `maskLayer.js`, que ya estaría escrito.

## Notas de riesgo heredadas del plan

1. **El worker es el riesgo principal** (T030). `run_analysis` se recompila en un espacio de nombres
   vacío; un import mal colocado da un `NameError` que la suite no ve. Ya pasó en `007`.
2. **Cinco caminos de borrado** (T008–T010), y los dos del worker son los que se olvidan.
3. **`tests/__init__.py`** (T028): olvidarlo produce un verde falso, no un fallo.
4. **El bundle JS no se recompila solo**: ver el aviso de despliegue al principio de este documento.
