# Phase 1 — API Contract: corrección de la nube de puntos (`realign`)

Extensión del contrato de 002 (`specs/002-realign-products/contracts/api.md`). Mismo prefijo
`/api/plugins/realign/` añadido por el framework (`app/plugins/views.py: api_view_handler`) y
mismas convenciones: lectura ⇒ permiso de vista (`get_and_check_task`); escritura ⇒
`change_project`.

**Rutas nuevas** (a añadir en `api_mount_points()`):

```text
task/(?P<pk>[^/.]+)/realign/pointcloud            [POST]   generar
task/(?P<pk>[^/.]+)/realign/pointcloud            [DELETE] descartar el resultado
task/(?P<pk>[^/.]+)/realign/pointcloud/download   [GET]    descargar el LAZ corregido
```

El sondeo de progreso **no necesita ruta nueva**: reutiliza el endpoint genérico del framework
`/api/workers/check/<celery_task_id>`, que es el que consume `Workers.waitForCompletion`
(D6). El estado persistente se lee por el `GET …/realign/state` ya existente, extendido.

---

## GET `…/realign/state` *(extendido)*

Se añade la clave `pointcloud` a la respuesta ya documentada en 002. El backend calcula
`stale` y `eligible` al vuelo; no son campos almacenados.

**200 OK** (fragmento nuevo)

```json
{
  "pointcloud": {
    "status": "ready",
    "stale": false,
    "available": true,
    "point_count": 61780499,
    "size_bytes": 280632581,
    "generated_at": "2026-07-23T21:02:00Z",
    "celery_task_id": null,
    "error": null,
    "eligible": true,
    "ineligible_reason": null
  }
}
```

| Campo | Tipo | Notas |
|---|---|---|
| `status` | `absent`\|`running`\|`ready`\|`error` | `absent` si nunca se generó |
| `stale` | bool | derivado: `ready` y huella ≠ transformación vigente (FR-012) |
| `available` | bool | `status == "ready" && !stale`; único caso con descarga (FR-010) |
| `celery_task_id` | string\|null | presente si `running`, para reanudar el sondeo tras recargar (FR-011) |
| `eligible` | bool | si se puede pedir una generación ahora (D9) |
| `ineligible_reason` | enum\|null | `no_pointcloud` \| `not_applied` \| `scale_enabled` \| `already_running` |

`ineligible_reason` es lo que permite a la UI dar el mensaje correcto por causa (US2, FR-004,
FR-017, SC-009) en lugar de deshabilitar un botón sin explicación.

## POST `…/realign/pointcloud`  *(requiere `change_project`)*

Lanza la generación asíncrona. Sin cuerpo: la transformación se toma del estado persistido, no
del cliente (FR-002 — es la misma que se aplicó a los rásteres).

**200 OK**

```json
{"celery_task_id": "b3f1…", "status": "running"}
```

**400 Bad Request** — el backend revalida las tres condiciones de elegibilidad sin confiar en la
UI (D9):

```json
{"error": "La tarea no tiene nube de puntos.", "reason": "no_pointcloud"}
```

| `reason` | Causa | Requisito |
|---|---|---|
| `no_pointcloud` | la tarea no tiene `georeferenced_model.laz` | FR-017 |
| `not_applied` | la realineación no está aplicada (solo previsualizada o revertida) | FR-005 |
| `scale_enabled` | la transformación vigente usa escala | FR-004 |
| `already_running` | ya hay una generación en curso para esta tarea | FR-015 |

**403 Forbidden** — sin permiso `change_project` (FR-016).

## GET `/api/workers/check/<celery_task_id>` *(endpoint del framework, sin cambios)*

Contrato ya existente (`app/api/workers.py: CheckTask`), consumido vía
`Workers.waitForCompletion`:

```json
{"ready": false, "status": "Transformando la nube de puntos", "progress": 42.5}
```

`status` y `progress` los emite el `progress_callback` inyectado por
`run_function_async(..., with_progress=True)`; `progress` se estima como
`tamaño(.tmp.laz) / tamaño(original)` (D6). Al terminar: `{"ready": true}` o
`{"ready": true, "error": "…"}`.

## DELETE `…/realign/pointcloud`  *(requiere `change_project`)*

Descarta el resultado y libera el espacio. Es la operación que invoca **Revertir** (FR-013) y la
que permite limpiar un resultado obsoleto o con error.

**200 OK**

```json
{"status": "absent"}
```

Si hay una generación en curso, la cancela (`Workers.cancel` sobre el `celery_task_id`, que hace
que `should_cancel()` devuelva `true`) y borra el temporal.

## GET `…/realign/pointcloud/download`

Descarga el LAZ corregido desde el directorio persistente, con el mismo mecanismo que
`RealignDownload` usa hoy para los GeoTIFF (`download_file_response`). **No** cuelga del
`celery_task_id` (D5), así que sobrevive a recargas y sirve a cualquier usuario con acceso a la
tarea (FR-011).

- **200 OK**: `Content-Type: application/octet-stream`, `Content-Disposition: attachment;
  filename="<tarea>_realigned.laz"`.
- **404 Not Found**: si `status != "ready"`, si está `stale`, o si el archivo no existe en disco
  (FR-012, FR-014).

Solo requiere permiso de lectura sobre la tarea: los usuarios con solo lectura pueden descargar
un resultado existente aunque no puedan generarlo (FR-016).

## Frontend (puntos de extensión, sin tocar el core)

Todo ocurre dentro del `RealignPanel.jsx` ya existente; no se añaden controles ni vistas nuevas
al core:

- una sección nueva en el panel con el estado de la nube (`absent`/`running`/`ready`/`stale`/
  `error`), el botón de generar y el enlace de descarga;
- el sondeo usa `Workers.waitForCompletion` (`app/static/app/js/classes/Workers.js`), ya
  disponible para plugins;
- cuando `eligible == false`, el panel muestra el texto correspondiente a `ineligible_reason` en
  lugar de un control deshabilitado sin explicación;
- un aviso permanente de que la corrección afecta solo al archivo descargable y no al visor 3D
  (FR-018).
