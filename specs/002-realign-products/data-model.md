# Phase 1 — Data Model: plugin `realign`

El plugin no crea modelos Django ni migraciones. El estado se persiste como **un documento JSON
por tarea** en `PluginDatum.json_value` a través del `GlobalDataStore` del plugin (namespace
`realign`, key `task_<pk>`, `user=None`). Los productos corregidos se guardan como archivos en
`get_persistent_path("task_<pk>/")`. Esta sección define la forma lógica de esas entidades y sus
reglas de validación (derivadas de los FR de la spec).

## Entidad: ControlPointPair (par de puntos de control)

Correspondencia origen→destino marcada por el usuario.

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | string/int | identificador estable del par dentro de la tarea |
| `source` | `{lat, lng}` | punto sobre la ortofoto (posición actual) |
| `target` | `{lat, lng}` | punto sobre el mapa base (posición correcta) |
| `residual_m` | float \| null | residuo del par tras el último ajuste (metros); `null` si aún no hay ajuste |
| `enabled` | bool | si participa en el ajuste (permite excluir un punto sin borrarlo) |

**Reglas**:
- `source` y `target` con `lat ∈ [-90, 90]`, `lng ∈ [-180, 180]`.
- Al menos 1 par para producir transformación; 0 pares ⇒ sin transformación (estado original).
- Dos o más pares con `source` coincidentes (o todos en el mismo punto) ⇒ ajuste **degenerado**:
  se marca inválido y bloquea Aplicar (FR-015, Edge Cases).

## Entidad: SimilarityTransform (transformación de similitud)

Modelo ajustado a partir de los pares habilitados. Independiente del tipo de dato (FR-017).

| Campo | Tipo | Descripción |
|---|---|---|
| `crs` | string (p. ej. `EPSG:32617`) | CRS proyectado en el que se ajustó y se aplica la similitud |
| `scale` | float | factor de escala uniforme (1.0 = sin cambio) |
| `rotation_deg` | float | rotación en grados (0 = sin giro) |
| `translation` | `{x, y}` | traslación en unidades del CRS (metros) |
| `n_points` | int | nº de pares habilitados usados en el ajuste |
| `rmse_m` | float \| null | error cuadrático medio global (metros) |
| `degenerate` | bool | true si los puntos no permiten un ajuste válido |

**Reglas**:
- 1 par ⇒ `scale=1`, `rotation_deg=0`, solo `translation` (FR-005).
- 2+ pares ⇒ ajuste Umeyama por mínimos cuadrados (FR-005).
- `rmse_m` y `residual_m` de cada par se recalculan ante cualquier cambio de puntos (FR-006).
- Se recalcula de forma autoritativa en el backend al aplicar, a partir de los `source`/`target`
  persistidos (no se confía en el cálculo del cliente para el resultado final).

## Entidad: TaskRealignment (estado de realineación de la tarea)

Documento raíz persistido en `PluginDatum` (key `task_<pk>`). Representa todo el estado.

| Campo | Tipo | Descripción |
|---|---|---|
| `version` | int | versión del esquema del documento (migraciones futuras) |
| `state` | enum | `previewing` \| `applied` \| `reverted` |
| `points` | ControlPointPair[] | pares de puntos de control |
| `transform` | SimilarityTransform \| null | última transformación calculada |
| `products` | string[] | productos afectados presentes: subconjunto de `orthophoto`,`dsm`,`dtm` |
| `corrected_paths` | `{type: path}` | rutas de los COG corregidos en el dir. persistente (solo si `applied`) |
| `applied_at` | ISO8601 \| null | marca de tiempo de la última aplicación |
| `applied_by` | int \| null | id del usuario que aplicó |
| `updated_at` | ISO8601 | última modificación del documento |

**Transiciones de estado**:

```text
(sin documento) --marcar puntos--> previewing
previewing --Aplicar (change_project, puntos válidos)--> applied
applied --editar puntos--> previewing        (los corregidos previos se descartan/regeneran desde el original)
applied|previewing --Revertir (change_project)--> reverted   (se descartan corregidos; vista al original)
reverted --marcar/editar puntos--> previewing
```

**Reglas / invariantes**:
- `applied` requiere `transform` no degenerada y `n_points ≥ 1` (FR-015).
- `products` se determina por los assets 2D presentes en la tarea; si no hay ninguno, la
  herramienta no se activa (FR-016). Puede incluir un subconjunto (Edge Case: productos parciales).
- Cada aplicación regenera `corrected_paths` **desde los assets originales** de la tarea (FR-010).
- `reverted` deja de exponer/usar los corregidos; los originales de la tarea permanecen intactos
  en todo momento (FR-009).
- Solo un `TaskRealignment` por tarea (un estado activo).

## Artefactos en disco (no en BD)

| Ruta | Contenido |
|---|---|
| `get_persistent_path("task_<pk>/orthophoto.tif")` | ortofoto corregida (COG north-up) |
| `get_persistent_path("task_<pk>/dsm.tif")` | DSM corregido (si existe el original) |
| `get_persistent_path("task_<pk>/dtm.tif")` | DTM corregido (si existe el original) |

Volumen compartido webapp↔worker: el worker los escribe al aplicar; la webapp los lee para tiles
y descargas. Se eliminan/regeneran al revertir o reaplicar.
