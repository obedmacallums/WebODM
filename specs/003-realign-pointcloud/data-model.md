# Phase 1 — Modelo de datos: corrección de la nube de puntos

**Feature**: `003-realign-pointcloud` | **Fecha**: 2026-07-23

Esta feature **no crea entidades nuevas de primer nivel**: extiende el documento
`TaskRealignment` de 002 (`specs/002-realign-products/data-model.md`) con una clave nueva,
`pointcloud`. Las entidades `ControlPointPair` y `SimilarityTransform` se reutilizan sin cambios.

## Extensión de TaskRealignment

Se agrega un único campo al documento raíz persistido en `PluginDatum` (key `task_<pk>`):

| Campo | Tipo | Descripción |
|---|---|---|
| `pointcloud` | PointCloudCorrection \| null | estado de la nube corregida; ausente/`null` si nunca se pidió |

El resto del documento (`version`, `state`, `points`, `transform`, `products`,
`corrected_paths`, `applied_at`, `applied_by`, `updated_at`) no cambia. Los documentos
persistidos **antes** de esta feature no tienen la clave; se interpretan como `pointcloud = null`
(estado `absent`), lo que preserva el comportamiento existente.

## Entidad: PointCloudCorrection (estado de la nube corregida)

| Campo | Tipo | Descripción |
|---|---|---|
| `status` | enum | `running` \| `ready` \| `error` — ver máquina de estados |
| `path` | string \| null | ruta absoluta del LAZ corregido en el directorio persistente (solo si `ready`) |
| `fingerprint` | TransformFingerprint \| null | huella del ajuste con el que se generó (D8) |
| `celery_task_id` | string \| null | id de la ejecución asíncrona en curso (solo si `running`) |
| `point_count` | int \| null | puntos del resultado, para verificación y para mostrar al usuario |
| `size_bytes` | int \| null | tamaño del resultado |
| `source_size_bytes` | int \| null | tamaño del original; denominador del progreso estimado (D6) |
| `error` | string \| null | causa del fallo (solo si `error`) |
| `generated_at` | ISO8601 \| null | fin de la última generación exitosa |
| `generated_by` | int \| null | id del usuario que la generó |
| `updated_at` | ISO8601 | última modificación de este subdocumento |

**Nota**: `stale` no se almacena. Es un estado **derivado** que se calcula al leer, comparando
`fingerprint` con la transformación vigente (ver más abajo). Guardarlo obligaría a reescribir el
documento cada vez que el usuario mueve un punto, y quedaría desincronizado si esa escritura
falla.

## Entidad: TransformFingerprint (huella del ajuste)

Identifica de forma estable el ajuste con el que se generó un resultado (D8).

| Campo | Tipo | Descripción |
|---|---|---|
| `cos` | float | componente de rotación, redondeada a la tolerancia fija |
| `sin` | float | componente de rotación, redondeada a la tolerancia fija |
| `tx` | float | traslación X (forma afín respecto al origen), redondeada |
| `ty` | float | traslación Y (forma afín respecto al origen), redondeada |
| `use_scale` | bool | modo del ajuste; siempre `false` en los resultados válidos (FR-004) |
| `n_points` | int | número de pares **habilitados** usados en el ajuste |

**Regla de comparación**: dos huellas son iguales si todos sus campos coinciden tras redondear
`cos`/`sin`/`tx`/`ty` a la misma tolerancia. La tolerancia debe ser holgadamente menor que el paso
de cuantización del LAZ (0,001 m) para que un cambio irrelevante no marque el resultado como
obsoleto, y menor que cualquier cambio perceptible en el mapa.

## Máquina de estados de la nube corregida

```text
(sin clave / null) ──pedir generación (change_project, elegible)──> running
running ──pipeline termina bien──────────────────────────────────> ready
running ──pipeline falla / cancelado / sin espacio───────────────> error
error   ──pedir generación de nuevo──────────────────────────────> running
ready   ──cambia la transformación vigente───────────────────────> ready + stale (derivado)
ready|stale|error ──Revertir la realineación─────────────────────> (borrado: vuelve a null)
```

`stale` se evalúa en cada lectura: `ready` **y** `fingerprint ≠ huella(transform vigente)`.

## Reglas / invariantes

- **Elegibilidad para generar** (D9, las tres se validan en el backend):
  1. la tarea tiene `georeferenced_model.laz` entre sus assets disponibles (FR-017);
  2. `TaskRealignment.state == 'applied'` (FR-005);
  3. `TaskRealignment.transform.use_scale == false` (FR-004).
- **Una sola generación por tarea**: no se admite pasar a `running` si ya está `running`
  (FR-015). El `celery_task_id` almacenado permite reanudar el sondeo tras una recarga (FR-011).
- **La descarga solo se ofrece con `status == 'ready'` y sin `stale`** (FR-010, FR-012). En
  `running`, `error` o `stale` no hay descarga.
- **`path` solo existe si el pipeline terminó con éxito**: el worker escribe en `<final>.tmp.laz`
  y renombra atómicamente (D4), así que la ruta registrada nunca apunta a un archivo parcial
  (FR-014).
- **Cada generación parte del asset original** de la tarea, nunca de una nube corregida previa
  (FR-007). El original no se toca jamás (FR-006).
- **Z inalterada**: la matriz aplicada tiene la fila Z en identidad y hereda `offset_z`/`scale_z`,
  por lo que `max|ΔZ| = 0` de forma estructural (D2, D3 — FR-003).
- **Revertir borra el archivo y la clave** (FR-013), liberando el espacio.
- Solo un `PointCloudCorrection` por tarea.

## Artefactos en disco (no en BD)

| Ruta | Contenido |
|---|---|
| `get_persistent_path("task_<pk>/pointcloud.laz")` | nube corregida (LAZ, mismo formato y precisión que el original) |
| `get_persistent_path("task_<pk>/pointcloud.tmp.laz")` | temporal en curso; nunca se sirve; se renombra o se borra |

Mismo volumen compartido webapp↔worker que los rásteres corregidos de 002: el worker lo escribe,
la webapp lo sirve. El temporal conserva la extensión `.laz` a propósito, porque las herramientas
de verificación infieren el driver por la extensión (D4).
