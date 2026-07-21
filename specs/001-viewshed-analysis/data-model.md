# Data Model: Análisis de visibilidad (viewshed)

**Feature**: 001-viewshed-analysis | **Date**: 2026-07-21

Sin persistencia propia: no hay modelos Django nuevos ni migraciones. Las entidades
viven en el ciclo request → job Celery → archivo temporal → capa en el mapa.

## Entidades

### ViewshedRequest (payload del POST, efímero)

| Campo | Tipo | Validación | Fuente FR |
|---|---|---|---|
| `lat` | float | requerido; −90 ≤ lat ≤ 90; el punto transformado debe caer dentro del extent del DEM y no sobre nodata | FR-002, FR-010 |
| `lng` | float | requerido; −180 ≤ lng ≤ 180; ídem anterior | FR-002, FR-010 |
| `observer_height` | float | opcional; default **1.60**; 0 ≤ h ≤ 500 (metros sobre el suelo) | FR-004, FR-005 |

Contexto implícito: `task` (por URL, validada con `get_and_check_task` → FR-012).

### ViewshedJob (job Celery, efímero)

| Atributo | Valor |
|---|---|
| Identidad | `celery_task_id` (devuelto por `run_function_async`) |
| Estados | `PENDING` → `STARTED` → `SUCCESS` \| `FAILURE` (semántica estándar de Celery, consultada vía `CheckTask`) |
| Resultado en `SUCCESS` | `{'file': <ruta GeoJSON en MEDIA_TMP>}` o `{'error': <mensaje>}` |
| Transiciones visibles al usuario | en curso (progreso, FR-009) → resultado en mapa \| mensaje de error (FR-010) |

### ViewshedResult (archivo GeoJSON, efímero)

- `FeatureCollection` en EPSG:4326; cada feature es un polígono de zona **visible**
  (las zonas no visibles son la ausencia de polígono — la simbología del panel las
  distingue, FR-006).
- Properties mínimas por feature: ninguna requerida en v1 (la semántica es "visible");
  el panel agrega estilo y leyenda en el cliente.
- Ciclo de vida: creado en `settings.MEDIA_TMP` por el worker; descargado una vez por el
  frontend; sin retención garantizada (resultado efímero según Assumptions del spec).

### Capa de resultado en el mapa (estado del frontend)

- A lo sumo **una** por sesión de visualización (FR-008): referencia a la `L.geoJSON`
  layer activa + parámetros con que se generó (punto, altura) para contexto del usuario.
- Operaciones: agregar (reemplaza la anterior si existe), quitar (FR-007).

## Fuentes de datos existentes (solo lectura)

| Dato | Acceso | Uso |
|---|---|---|
| DSM de la tarea | `task.dsm_extent` (disponibilidad) + `task.get_asset_download_path("dsm.tif")` | fuente topográfica preferida (D3) |
| DTM de la tarea | `task.dtm_extent` + `get_asset_download_path("dtm.tif")` | respaldo si no hay DSM |
| Permisos de la tarea | `TaskView.get_and_check_task(request, pk)` | FR-012 |

## Reglas de validación (server-side, orden de evaluación)

1. Permisos de la tarea (`get_and_check_task`) → 404/403 estándar del framework.
2. Disponibilidad de DEM: sin DSM ni DTM → `{'error': 'La tarea no tiene modelo de elevación…'}` (FR-001/FR-010).
3. Tipos y rangos de `lat`/`lng`/`observer_height` → `{'error': <motivo>}` (FR-005).
4. Punto dentro del extent del DEM y con dato (no nodata) → `{'error': 'El punto está fuera del área con datos…'}` (FR-010).
5. Solo si todo pasa: `run_function_async` → `{'celery_task_id': …}`.
