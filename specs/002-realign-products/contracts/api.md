# Phase 1 — API Contract: plugin `realign`

Endpoints REST del plugin, montados por `api_mount_points()` bajo `/api/plugins/realign/`
(el prefijo lo añade el framework; ver `app/plugins/views.py: api_view_handler`). Todos operan
sobre una tarea identificada por `pk`. Lectura ⇒ permiso de vista (`get_and_check_task`);
escritura ⇒ `change_project` (D7). Formato: JSON salvo tiles (PNG) y descarga (GeoTIFF).

Convención de rutas (patrón `MountPoint`, estilo `coreplugins/viewshed/plugin.py`):

```text
task/(?P<pk>[^/.]+)/realign/state                     [GET, PUT, DELETE]
task/(?P<pk>[^/.]+)/realign/apply                     [POST]
task/(?P<pk>[^/.]+)/realign/revert                    [POST]
task/(?P<pk>[^/.]+)/realign/status/(?P<celery_task_id>.+)   [GET]
task/(?P<pk>[^/.]+)/realign/tiles/(?P<type>orthophoto|dsm|dtm)/(?P<z>\d+)/(?P<x>\d+)/(?P<y>\d+)(?P<ext>\.png)?   [GET]
task/(?P<pk>[^/.]+)/realign/tilejson/(?P<type>orthophoto|dsm|dtm)   [GET]
task/(?P<pk>[^/.]+)/realign/download/(?P<type>orthophoto|dsm|dtm)   [GET]
```

---

## GET `…/realign/state`

Devuelve el estado de realineación persistido de la tarea (o el estado vacío inicial), más los
productos 2D disponibles para realinear.

**200 OK**
```json
{
  "state": "previewing",
  "points": [
    {"id": 1, "source": {"lat": 0.0, "lng": 0.0}, "target": {"lat": 0.0, "lng": 0.0},
     "residual_m": 0.12, "enabled": true}
  ],
  "transform": {"crs": "EPSG:32617", "use_scale": true, "scale": 1.0002, "rotation_deg": 0.35,
                 "translation": {"x": 1.8, "y": -0.9}, "n_points": 3, "rmse_m": 0.14,
                 "degenerate": false},
  "products": ["orthophoto", "dsm", "dtm"],
  "corrected_available": false,
  "updated_at": "2026-07-22T12:00:00Z"
}
```
**409/available=false**: si la tarea no tiene productos ráster 2D, `products` es `[]` y el
frontend no activa la herramienta (FR-016).

## PUT `…/realign/state`  *(requiere `change_project`)*

Guarda los pares de puntos editados (crear/mover/eliminar) y devuelve la transformación y los
residuos recalculados de forma autoritativa en el backend.

**Body**
```json
{ "points": [ {"id": 1, "source": {"lat": .., "lng": ..}, "target": {"lat": .., "lng": ..}, "enabled": true} ],
  "use_scale": true }
```
`use_scale` es opcional; si se omite, se conserva el último valor persistido (o `true` si no hay
ninguno todavía). Al cambiarlo, la respuesta refleja el ajuste recalculado en el nuevo modo
(FR-018 a FR-020).

**200 OK**: mismo shape que `GET state`, con `transform` y `residual_m`/`rmse_m` recalculados.
**400**: puntos fuera de rango o ajuste degenerado (`transform.degenerate=true`); no impide
guardar, pero marca el estado como no aplicable.

> Nota: la previsualización en vivo y los residuos que ve el usuario se calculan en el **cliente**
> (`similarity.js`) para respuesta < 1 s (SC-002); este endpoint persiste y da el cálculo
> autoritativo. El guardado puede hacerse al vuelo (cada cambio) o al aplicar.

## DELETE `…/realign/state`  *(requiere `change_project`)*

Elimina el estado de realineación de la tarea (equivale a un revert + limpieza). Borra los
corregidos del directorio persistente. **200 OK** `{ "ok": true }`.

## POST `…/realign/apply`  *(requiere `change_project`)*

Lanza el pipeline asíncrono que genera los COG corregidos desde los **originales** (FR-010) para
todos los productos disponibles y marca el estado `applied` al terminar.

**Body** (opcional) `{ "points": [...], "use_scale": true }` para aplicar con los puntos y el modo
de escala actuales; si se omite `use_scale`, usa el último persistido.
**200 OK** `{ "celery_task_id": "<id>" }` (patrón `run_function_async`, como viewshed).
**400**: sin puntos suficientes o ajuste degenerado (FR-015) → no lanza el pipeline.
**403**: sin permiso `change_project` (FR-014).

## GET `…/realign/status/<celery_task_id>`

Sondea el progreso del pipeline (reutiliza `GetTaskResult`/`CheckTask` del framework, como
`TaskViewshedDownload`).

**200 OK** `{ "ready": true, "output": { "state": "applied", "corrected": ["orthophoto","dsm","dtm"] } }`
o `{ "ready": false }` mientras procesa. En error: `{ "ready": true, "error": "…" }`.

## POST `…/realign/revert`  *(requiere `change_project`)*

Marca el estado `reverted`, deja de exponer los corregidos y descarta sus archivos; los originales
de la tarea permanecen intactos (FR-009, FR-011). **200 OK** `{ "state": "reverted" }`.
**403**: sin permiso.

## GET `…/realign/tiles/<type>/<z>/<x>/<y>.png`

Sirve un tile PNG del producto corregido `<type>` leyendo el COG del directorio persistente con
rio-tiler `COGReader` (mismo `rescale` por defecto que el core: `orthophoto`→`0,255`,
`dsm|dtm`→`0,1000`). **200 image/png**. **404** si no hay corregido (estado ≠ applied) o el tile
cae fuera de bounds. Consumido por el `TileLayer` del frontend en estado aplicado (D5).

## GET `…/realign/tilejson/<type>`

TileJSON del producto corregido (bounds/center leídos del COG corregido; `tiles` apunta al
endpoint anterior). **200 OK** TileJSON. **404** si no hay corregido.

## GET `…/realign/download/<type>`

Descarga el GeoTIFF corregido `<type>` desde el directorio persistente
(`download_file_response`, patrón del core). **200 image/tiff**. **404** si no aplicado.

---

## Frontend (puntos de extensión, sin tocar el core)

- `PluginsAPI.Map.willAddControls([...], cb)` con `args.map` y `args.tiles` (verificado en
  `coreplugins/viewshed/public/main.js`): monta el control `Realign` cuando hay exactamente una
  tarea en la vista.
- El control abre `RealignPanel`, que: captura pares de puntos (2 clics/par sobre `args.map`),
  calcula similitud/residuos en vivo (`similarity.js`), aplica la matriz CSS de previsualización a
  las capas de `args.tiles`, muestra la tabla de residuos + RMSE, y expone Aplicar/Revertir con
  polling de `status`. En estado aplicado, intercambia la capa por un `TileLayer` que apunta a
  `…/realign/tilejson/<type>`; en revertido, restaura la capa del core.
