# Contrato REST — plugin `road`

**Feature**: 005-road-metrics | **Modelo**: [data-model.md](../data-model.md)

Todas las rutas cuelgan de `/api/plugins/road/task/<task_id>/…` y se montan con `MountPoint`
anclando el final con `$`, siguiendo la convención que `annotations` dejó documentada: sin `$`,
Django resuelve por prefijo y una ruta genérica se traga a las específicas. Las rutas literales se
registran antes que las paramétricas cuando coinciden en forma.

Toda vista extiende `TaskView` y resuelve el acceso con `get_and_check_task(request, pk)`; las que
modifican estado añaden `check_project_perms(request, task.project, ('change_project',))`, igual que
`realign`.

## Errores

Formato uniforme `{"error": "<mensaje legible>", "code": "<slug>"}`. Códigos usados:

| HTTP | `code` | Cuándo |
|---|---|---|
| 400 | `invalid_parameter` | Parámetro fuera del rango de [data-model.md §4](../data-model.md). El mensaje indica el rango. |
| 400 | `invalid_axis` | Eje inválido: no es un `LineString`, menos de dos vértices distintos, CRS no admitido, fuera de la extensión del DEM. |
| 400 | `no_elevation_model` | La tarea no tiene DSM ni DTM. |
| 400 | `unavailable_variant` | Se pidió `realigned` en una tarea sin realineación aplicada. |
| 404 | `not_found` | El análisis no existe en esa tarea. |
| 409 | `analysis_running` | Ya hay un análisis en curso en la tarea (FR-036). Incluye `running_analysis_id`. |
| 409 | `confirmation_required` | La estimación supera el umbral de aviso, o se va a sustituir un análisis existente, y no se envió `confirm: true`. Incluye el motivo y la estimación. |
| 410 | `result_missing` | El índice tiene el análisis pero su archivo de tramos ha desaparecido. |

---

## `GET task/<pk>/capabilities`

Qué puede ofrecer el plugin sobre esta tarea, para que el panel se dibuje sin opciones muertas.

```json
{
  "models": ["dsm", "dtm"],
  "default_model": "dtm",
  "variants": {"dsm": ["original", "realigned"], "dtm": ["original"]},
  "resolution": 0.052,
  "vertical_unit": "metre",
  "annotations_available": true,
  "axes": [{"id": "a1b2", "name": "Camino norte", "vertices": 12, "plan_length": 812.4}],
  "defaults": {"segment_length": 5.0, "search_half_width": 10.0, "sample_step": 0.1,
               "break_threshold": 15.0, "min_consecutive_samples": 3,
               "color_thresholds": [8.0, 12.0]},
  "ranges": {"segment_length": [0.5, 100.0], "search_half_width": [1.0, 50.0],
             "sample_step": [0.052, 5.0], "break_threshold": [2.0, 200.0],
             "min_consecutive_samples": [1, 20]},
  "max_vertices": 500,
  "max_upload_bytes": 5242880
}
```

- `axes` lista solo las polilíneas 2D (`mode == "flat"`) que devuelve el contrato de `annotations`.
  Con el plugin ausente o deshabilitado, `annotations_available` es `false` y `axes` va vacío: la
  vía del archivo sigue disponible (FR-005).
- `resolution` y `sample_step` mínimo salen del DEM por defecto.

## `GET task/<pk>/analyses`

Índice de análisis de la tarea, **sin** los tramos.

```json
{
  "running": {"analysis_id": "…", "started_at": "…"},
  "analyses": [{
    "id": "…", "name": "Camino norte",
    "axis": {"kind": "annotation", "ref": "a1b2", "plan_length": 812.4},
    "model": "dtm", "variant": "original",
    "params": {"segment_length": 5.0, "…": "…"},
    "color_thresholds": [8.0, 12.0],
    "status": "completed", "progress": null, "error": null, "stale": false,
    "summary": {"segment_count": 163, "measured_count": 148, "…": "…"},
    "created_at": "…", "updated_at": "…", "created_by": 1
  }]
}
```

## `POST task/<pk>/analyses`

Lanza un análisis. `Content-Type: application/json` cuando el eje es una anotación, o
`multipart/form-data` cuando se sube un archivo (campo `file`, resto de campos como texto).

```json
{
  "axis": {"kind": "annotation", "ref": "a1b2"},
  "name": "Camino norte",
  "model": "dtm",
  "variant": "original",
  "params": {"segment_length": 5.0, "search_half_width": 10.0, "sample_step": 0.1,
             "break_threshold": 15.0, "min_consecutive_samples": 3},
  "confirm": false
}
```

- `params` puede omitirse entero o parcialmente: lo ausente toma el defecto.
- `model` y `variant` opcionales; por defecto DTM si existe, DSM si no, y `original`.
- Responde `202 Accepted` con `{"analysis_id": "…", "celery_task_id": "…", "estimate": {…}}`.
- `409 analysis_running` si ya hay uno corriendo en la tarea.
- `409 confirmation_required` si la estimación supera el umbral de aviso o si `(kind, ref)` ya tiene
  análisis; reenviar con `confirm: true` procede y, en el segundo caso, **sustituye** el anterior
  conservando su `id` y su `name` (FR-037).

## `POST task/<pk>/analyses/estimate`

Mismo cuerpo que el anterior, sin lanzar nada (D11). El eje puede venir por referencia o por
archivo.

```json
{"segments": 163, "cross_sections": 163, "samples": 41_252,
 "estimated_seconds": 22.4, "warn": false}
```

## `GET task/<pk>/analyses/<analysis_id>`

El análisis con sus tramos: el objeto del índice más
`"segments": [Segment, …]` tal como los define [data-model.md §6](../data-model.md).
`410 result_missing` si el archivo de tramos no está.

## `PATCH task/<pk>/analyses/<analysis_id>`

Solo dos campos son modificables; cualquier otro se rechaza con `400 invalid_parameter`.

```json
{"name": "Camino norte km 0-1", "color_thresholds": [6.0, 10.0]}
```

Cambiar `color_thresholds` **no** invalida ni recalcula el análisis (FR-030). Responde con el objeto
del índice actualizado.

## `POST task/<pk>/analyses/<analysis_id>/cancel`

Cancela el análisis si está `running`: aborta la tarea de Celery, deja `status: "canceled"`, limpia
el candado `running` y no conserva resultado parcial. Idempotente: sobre un análisis que ya terminó
responde `200` sin cambiar nada.

## `DELETE task/<pk>/analyses/<analysis_id>`

Elimina el análisis del índice y borra su archivo de tramos. Si estaba `running`, lo cancela primero.

## `GET task/<pk>/analyses/<analysis_id>/export?format=csv|geojson`

Descarga con `Content-Disposition: attachment`. Nombre del archivo:
`<tarea>-<análisis>-road.csv|geojson`, con ambas partes pasadas por `slugify`.

**CSV** — una fila por tramo, cabecera en la primera línea:

```text
index,station_start,station_end,length,elevation,grade_pct,grade_deg,width,
offset_left,offset_right,cross_slope_pct,status,left_reason,right_reason
```

Las celdas sin dato van **vacías**, nunca a cero (FR-022). Tras los tramos, un bloque de comentarios
`#` con el eje, el modelo, la variante y los parámetros de cálculo (FR-033).

**GeoJSON** — un `FeatureCollection` con tres familias de entidades, distinguibles por la propiedad
`kind`:

| `kind` | Geometría | Propiedades |
|---|---|---|
| `segment` | `LineString` en planta del tramo | todas las métricas del tramo y su estado |
| `cross_section` | `LineString` de dos puntos | `index` del tramo al que pertenece |
| `edge` | `Point` | `index` y `side` (`left` \| `right`) |

Los parámetros del análisis viajan en un miembro `properties` de la colección (extensión admitida
por RFC 7946 en el objeto raíz).
