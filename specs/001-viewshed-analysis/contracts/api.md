# API Contract: plugin viewshed

**Feature**: 001-viewshed-analysis | **Date**: 2026-07-21

Endpoints montados por `api_mount_points()` bajo el prefijo del framework
`/api/plugins/viewshed/`. Autenticación y permisos: los de la API de WebODM (sesión/JWT
+ permisos por-objeto de la tarea vía `get_and_check_task`). Convención de errores de
dominio: HTTP 200 con cuerpo `{'error': <mensaje traducible>}` (patrón `contours`);
errores de permisos/no-encontrado usan los códigos estándar del framework.

## POST `/api/plugins/viewshed/task/{pk}/viewshed/generate`

Lanza el cálculo asíncrono de viewshed para la tarea `{pk}`.

**Request body** (JSON):

```json
{
  "lat": -33.4489,
  "lng": -70.6693,
  "observer_height": 1.6
}
```

| Campo | Tipo | Requerido | Default | Validación |
|---|---|---|---|---|
| `lat` | number | sí | — | [−90, 90]; punto dentro del extent del DEM, no nodata |
| `lng` | number | sí | — | [−180, 180]; ídem |
| `observer_height` | number | no | `1.6` | [0, 500] metros sobre el suelo |

**Responses**:

- `200 OK` — cálculo aceptado:

  ```json
  { "celery_task_id": "6f1c…" }
  ```

- `200 OK` — error de dominio (sin DEM, punto fuera de cobertura, parámetro inválido):

  ```json
  { "error": "La tarea no tiene modelo de elevación." }
  ```

- `403 / 404` — sin permiso sobre la tarea / tarea inexistente (framework).

## GET `/api/workers/check/{celery_task_id}` *(endpoint core existente — no lo monta el plugin)*

Polling de estado del job. Lo consume el frontend mediante la clase existente
`Workers.waitForCompletion`. Contrato core: `{ "ready": bool, "error": str? }`.

## GET `/api/plugins/viewshed/task/{pk}/viewshed/download/{celery_task_id}`

Descarga el resultado cuando el job terminó (`ready: true` sin `error`). La vista
extiende `GetTaskResult` del framework.

**Responses**:

- `200 OK` — `application/json`: FeatureCollection GeoJSON en EPSG:4326 con los
  polígonos de zonas visibles (ver [data-model.md](../data-model.md)). Si en la
  implementación se activa el plan B (D5 de research.md), el content-type pasa a
  `image/png` + metadatos de bounds — cualquier cambio se refleja aquí antes de
  implementarse.
- `200 OK` con `{'error': …}` — el job falló o el resultado expiró.

## Contrato de UI (punto de extensión del core)

- `public/main.js` se registra con `PluginsAPI.Map.willAddControls(...)` y agrega un
  control Leaflet cuando la vista 2D corresponde a una sola tarea (patrón
  `contours/public/main.js`).
- El control alterna un modo de captura de clic; el panel muestra: campo de altura
  (default visible `1.60 m`), estado de progreso, error si lo hay, y acciones
  generar/limpiar. Una sola capa de resultado activa (FR-007/008).
