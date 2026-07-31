# Phase 1 — Modelo de datos

Feature: `009-training-dataset-labeling`. Fecha: 2026-07-30.

Ninguna entidad usa el ORM de Django: el plugin no añade migraciones. Los metadatos viven en
`GlobalDataStore` y las etiquetas en ficheros JSON, según [D2](./research.md#d2).

---

## Dataset

La unidad de trabajo. Vive por encima de las tareas y sobrevive al borrado de cualquiera de ellas.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | generado al crear; nunca cambia |
| `name` | texto | obligatorio, no vacío |
| `created_at` | ISO 8601 | fijado al crear |
| `resolution_cm_px` | decimal | > 0. Por defecto **10,0** (FR-005). No se puede cambiar tras etiquetar |
| `tile_size_px` | entero | > 0. Por defecto **512** (FR-024) |
| `classes` | lista de Clase | al menos 2; índices consecutivos desde 0 (FR-003) |
| `tasks` | lista de referencias a tarea | al menos 1 |
| `min_labeled_fraction` | decimal | 0–1. Por defecto **0,01** (FR-027) |
| `min_valid_fraction` | decimal | 0–1. Por defecto **0,50** (FR-027) |
| `schema_version` | entero | 1 |

**Clave en el store**: `dataset_<id>`, más una clave `datasets` con la lista de identificadores para
poder listar sin recorrer el disco.

**Por qué la resolución se congela tras etiquetar**: no por limitación técnica —las etiquetas son
vectoriales y se reexportan a cualquier escala— sino porque `simplify` ya se aplicó con la tolerancia
de la resolución original (FR-015). Bajar a una resolución más fina después no recuperaría los
vértices descartados, y presentarlo como si sí lo hiciera sería mentir sobre la precisión del
resultado.

## Clase

| Campo | Tipo | Reglas |
|---|---|---|
| `index` | entero | consecutivo desde 0; el 0 es el fondo (FR-004) |
| `name` | texto | obligatorio, único dentro del dataset |
| `color` | color | distinguible; fuera de la paleta verde/amarillo/rojo de `road` (FR-007) |

El `index` es el contrato con el modelo entrenado: es lo que acaba escrito en las máscaras y en los
metadatos del `.onnx`. El `name` es solo para el usuario.

**Restricción de borrado** (FR-006): borrar una clase con etiquetas asociadas exige confirmación
explícita indicando cuántas se perderán. Renombrarla es inocuo.

**Valor reservado**: 255 significa «sin etiquetar» y no puede ser el índice de ninguna clase. En la
práctica esto limita el dataset a 255 clases, lo cual sobra.

## Etiqueta

Lo que producen los cuatro métodos de etiquetado. Una sola forma para todos.

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | generado al crear |
| `class_index` | entero | debe existir en las clases del dataset |
| `kind` | `polygon` \| `stroke` | determina cómo se interpreta `geometry` |
| `geometry` | coordenadas geográficas | anillo cerrado si `polygon`; polilínea si `stroke` |
| `radius_m` | decimal | solo si `kind == stroke`; > 0; en **metros sobre el terreno** (FR-010) |
| `order` | entero | posición en la composición; monótono creciente |
| `source` | `manual` \| `import` \| `model` | procedencia; `import` y `model` llegan en entregas posteriores |

**Composición** (FR-012): al rasterizar se pintan en orden ascendente y **gana la última**. El orden
por defecto es el de creación.

**El borrador** (FR-014) es una etiqueta con `class_index = null`: al rasterizar devuelve esos
píxeles al valor «ignorar». No es lo mismo que pintar clase 0, y confundirlos arruinaría el
entrenamiento — ver FR-026.

**Simplificación al guardar** (FR-015): tolerancia igual a la resolución del dataset. Por debajo de
esa escala la etiqueta no contiene información que la exportación pueda representar.

**Almacenamiento**: un fichero JSON por par (dataset, tarea), en
`get_persistent_path('datasets', '<dataset_id>', '<task_id>.json')`. Separarlos por tarea es lo que
permite que el borrado de una tarea no arrastre el resto del dataset (FR de US3-4) y que abrir una
tarea no cargue las etiquetas de las demás.

## Tarea del dataset

Referencia a una tarea del core, más el estado que el plugin necesita recordar.

| Campo | Tipo | Reglas |
|---|---|---|
| `task_id` | UUID | referencia a `app.models.Task` |
| `project_id` | entero | necesario para construir las URL del core |
| `added_at` | ISO 8601 | |
| `available` | derivado | `false` si la tarea ya no existe o perdió la ortofoto |

`available` **no se persiste**: se calcula al leer. Persistirlo daría un valor obsoleto en cuanto el
usuario borrase la tarea por otra vía. Cuando es `false`, el dataset sigue abriéndose y la tarea se
excluye de la exportación en vez de fallar.

## Paquete de exportación

Artefacto derivado y desechable: siempre se puede regenerar desde el dataset. Su formato es el
contrato con la imagen de entrenamiento y está en
[`contracts/dataset-package.md`](./contracts/dataset-package.md).

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | UUID | |
| `dataset_id` | UUID | |
| `created_at` | ISO 8601 | |
| `status` | `running` \| `completed` \| `failed` \| `canceled` | |
| `progress` | 0–100 | |
| `celery_task_id` | texto | para poder cancelar |
| `tile_count` | entero | teselas que entraron tras aplicar los filtros de FR-027 |
| `size_bytes` | entero | |
| `error` | texto o nulo | |

---

## Invariantes que los tests deben proteger

1. Un píxel sin ninguna etiqueta encima sale como **255**, nunca como 0.
2. Con etiquetas solapadas, el valor final es el de la etiqueta de mayor `order`.
3. Un trazo de radio *r* rasterizado a resolución *R* cubre un área que coincide con la del polígono
   que produce su `buffer`, dentro del error de discretización. Medido: 118,14 m² frente a 118,25 m².
4. Cambiar la resolución del dataset y reexportar produce máscaras coherentes: las etiquetas no se
   tocan, solo el rasterizado.
5. Una tarea no disponible no rompe la lectura del dataset ni la exportación de las demás.
6. Dos exportaciones sin cambios intermedios producen el mismo conjunto de teselas y el mismo
   manifiesto salvo marcas de tiempo (FR-031).
