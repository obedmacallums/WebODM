# Contrato — Interfaz HTTP del plugin `training`

Feature: `009-training-dataset-labeling`. Fecha: 2026-07-30.

Solo se documentan las rutas de **esta entrega** (US1 + US2). Las de importación de GeoJSON (US4) y
resumen de calidad (US5) llegarán con sus entregas.

**Convención heredada de `annotations` y `road`**: un `MountPoint` sin `$` final resuelve por
prefijo, así que toda ruta ancla el final con `$`, y las rutas literales se registran **antes** que
los patrones genéricos con identificador. Saltarse esto hace que `datasets` se trague
`datasets/export`.

## Página global (`app_mount_points`)

Precedente: `coreplugins/task-manager/plugin.py`.

| Ruta | Qué hace |
|---|---|
| `GET $` | Página de gestión de datasets. Entra también en el menú principal vía `main_menu()` |

## API (`api_mount_points`)

Prefijo real: `/api/plugins/training/`.

### Datasets

| Método y ruta | Qué hace |
|---|---|
| `GET datasets$` | Lista los datasets visibles para el usuario |
| `POST datasets$` | Crea uno. Cuerpo: `name`, `classes`, `resolution_cm_px`, `tile_size_px`, `tasks` |
| `GET datasets/(?P<dataset_id>[^/.]+)$` | Detalle, incluido el estado `available` de cada tarea |
| `PATCH datasets/(?P<dataset_id>[^/.]+)$` | Renombrar y editar clases |
| `DELETE datasets/(?P<dataset_id>[^/.]+)$` | Borra el dataset y sus etiquetas |

**Errores con motivo, no genéricos** (FR-020 fija el principio para la importación; se aplica a
todo):

| Situación | Código | `code` |
|---|---|---|
| La tarea indicada no tiene ortofoto | 400 | `no_orthophoto` |
| Menos de dos clases | 400 | `too_few_classes` |
| Índices de clase no consecutivos desde 0 | 400 | `bad_class_indexes` |
| Resolución ≤ 0 | 400 | `bad_resolution` |
| Borrar una clase con etiquetas sin `confirm=true` | 409 | `class_in_use` (incluye `label_count`) |
| Cambiar la resolución de un dataset ya etiquetado | 409 | `dataset_has_labels` |

### Etiquetas

Siempre en el contexto de un par (dataset, tarea): es la unidad de bloqueo y de fichero.

| Método y ruta | Qué hace |
|---|---|
| `GET datasets/(?P<dataset_id>[^/.]+)/tasks/(?P<pk>[^/.]+)/labels$` | Todas las etiquetas de esa tarea |
| `POST datasets/(?P<dataset_id>[^/.]+)/tasks/(?P<pk>[^/.]+)/labels$` | Crea una. Cuerpo: `class_index`, `kind`, `geometry`, `radius_m` |
| `PATCH …/labels/(?P<label_id>[^/.]+)$` | Modifica geometría o clase |
| `DELETE …/labels/(?P<label_id>[^/.]+)$` | Borra una |

Toda escritura toma el bloqueo por documento ([D3](../research.md#d3)) y devuelve el `order`
asignado, que el frontend necesita para dibujar en el orden correcto sin volver a pedir la lista.

| Situación | Código | `code` |
|---|---|---|
| `class_index` que no existe en el dataset | 400 | `unknown_class` |
| `kind: stroke` sin `radius_m`, o con `radius_m` ≤ 0 | 400 | `bad_radius` |
| Geometría con menos vértices de los que su tipo exige | 400 | `bad_geometry` |
| La tarea no pertenece al dataset | 404 | `task_not_in_dataset` |

### Exportación

| Método y ruta | Qué hace |
|---|---|
| `POST datasets/(?P<dataset_id>[^/.]+)/exports$` | Lanza la exportación. `202` con `export_id` y `celery_task_id` |
| `GET datasets/(?P<dataset_id>[^/.]+)/exports$` | Lista exportaciones con su estado y progreso |
| `GET datasets/(?P<dataset_id>[^/.]+)/exports/(?P<export_id>[^/.]+)/download$` | Descarga el paquete |
| `DELETE datasets/(?P<dataset_id>[^/.]+)/exports/(?P<export_id>[^/.]+)$` | Cancela si corre; borra el paquete si terminó |

La descarga sale como respuesta con `Content-Disposition`, igual que la exportación de `road`
(`road/api.py:598-602`), sobre un fichero ya construido en disco — nunca generado en memoria durante
la petición (FR-030).

| Situación | Código | `code` |
|---|---|---|
| El dataset no tiene ninguna etiqueta | 400 | `nothing_to_export` |
| Ninguna tarea del dataset está disponible | 400 | `no_available_tasks` |
| Descargar una exportación que no ha terminado | 409 | `export_not_ready` |
| Todas las teselas quedaron descartadas por los filtros | 400 | `all_tiles_filtered` (incluye el recuento) |

El último merece existir por separado: «no hay nada que exportar» y «lo etiquetado no supera los
umbrales» son problemas distintos con soluciones distintas, y responder lo mismo a ambos dejaría al
usuario sin saber si le falta etiquetar o si debe bajar el umbral.

## Permisos

Toda ruta exige usuario autenticado. Las que tocan una tarea comprueban además que el usuario tenga
acceso a su proyecto, con el mismo mecanismo que usan `road` y `annotations`. Un dataset solo lista
las tareas que su dueño puede ver.
