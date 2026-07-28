# Data Model: características geométricas de caminos (`road`)

**Feature**: 005-road-metrics | **Spec**: [spec.md](./spec.md) | **Decisiones**: [research.md](./research.md)

Dos almacenes, según [research.md D8](./research.md):

| Almacén | Qué guarda | Dónde |
|---|---|---|
| Índice | metadatos de cada análisis y el candado de ejecución | `GlobalDataStore('road')`, clave `task_<pk>` |
| Tramos | la colección de tramos de un análisis terminado | `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json` |

Todas las coordenadas viajan en EPSG:4326, orden `[lng, lat]`. Todas las distancias y cotas en
metros; las pendientes en porcentaje, salvo `grade_deg`, que va en grados.

---

## 1. Documento de índice — `TaskRoadAnalyses`

```json
{
  "version": 1,
  "analyses": [ RoadAnalysis, ... ],
  "running": { "analysis_id": "...", "celery_task_id": "...", "started_at": "..." }
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `version` | int | Versión del esquema. Hoy `1`. |
| `analyses` | lista | Puede estar vacía. Sin límite formal de longitud. |
| `running` | objeto \| ausente | Candado de ejecución (D10). Se crea y se comprueba dentro del `document_lock`; se considera obsoleto si su `AsyncResult` ya está `ready()`. |

La ausencia del documento equivale a `{"version": 1, "analyses": []}`.

---

## 2. `RoadAnalysis` (entrada del índice)

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | str | UUID4 generado al crear. Inmutable. |
| `name` | str | 1–255 caracteres. Se prellena con el nombre de la anotación o del archivo. |
| `axis` | `AxisSource` | Origen y geometría del eje. Copia propia: el análisis sobrevive al borrado del origen (FR-006). |
| `model` | `"dsm"` \| `"dtm"` | Debe estar entre los disponibles de la tarea. |
| `variant` | `"original"` \| `"realigned"` | `"realigned"` solo si `realign` la ofrece para esa tarea (D1). |
| `params` | `AnalysisParameters` | Parámetros de cálculo. Cambiarlos exige recalcular. |
| `color_thresholds` | `[float, float]` | Umbrales del semáforo. No intervienen en el cálculo (FR-030). |
| `status` | enum | `running` \| `completed` \| `canceled` \| `failed`. |
| `progress` | float \| null | 0.0–1.0 mientras `running`; `null` en el resto. |
| `error` | str \| null | Mensaje cuando `status == "failed"`; `null` en el resto. |
| `celery_task_id` | str \| null | Presente mientras `running`, para poder cancelar desde cualquier sesión. |
| `source_mtime` | float \| null | `st_mtime` del DEM usado, para derivar `stale` (D12). |
| `summary` | `AnalysisSummary` \| null | Agregados del resultado. `null` mientras no haya terminado. |
| `created_at`, `updated_at` | str | ISO-8601 UTC con sufijo `Z`. |
| `created_by` | int \| null | `user.id` de quien lo lanzó. |

**Estado derivado, no persistido**: `stale` — `true` si el `mtime` actual del DEM difiere de
`source_mtime`, o si el archivo ya no se puede leer.

### Transiciones

```text
        POST /analyses            worker termina
   (nada) ──────────► running ──────────────────► completed
                        │                              │
                        │ POST /cancel                 │ POST /analyses sobre el mismo eje
                        ▼                              │   (recalcular: pisa la entrada)
                     canceled ◄───────────────────── running
                        │
                        │ excepción en el worker
                        ▼
                      failed
```

- `canceled` y `failed` no dejan archivo de tramos; `running` tampoco (FR-034: sin resultados
  parciales).
- Recalcular reutiliza el `id` y el `name` del análisis existente de ese eje y sustituye todo lo
  demás (FR-037).
- Borrar elimina la entrada del índice y su archivo de tramos.

---

## 3. `AxisSource`

| Campo | Tipo | Reglas |
|---|---|---|
| `kind` | `"annotation"` \| `"upload"` | Vía de entrada. |
| `ref` | str | Identidad del eje (D3 de las clarificaciones): `polyline_id` si `kind == "annotation"`, nombre del archivo si `kind == "upload"`. Es la clave con la que "recalcular pisa". |
| `vertices` | `[[lng, lat], ...]` | Copia propia de la geometría. 2 ≤ n ≤ 500 vértices, al menos dos distintos. |
| `plan_length` | float | Longitud en planta, en metros, calculada en el CRS del DEM. |

**Unicidad**: `(kind, ref)` identifica al análisis dentro de la tarea. Crear un análisis con un
`(kind, ref)` ya presente sustituye al anterior previa confirmación.

---

## 4. `AnalysisParameters`

| Campo | Unidad | Defecto | Rango admitido |
|---|---|---|---|
| `segment_length` | m | `5.0` | `[0.5, 100.0]` |
| `search_half_width` | m | `10.0` | `[1.0, 50.0]` |
| `sample_step` | m | `max(resolución del DEM, 0.1)` | `[resolución del DEM, 5.0]` |
| `break_threshold` | % | `15.0` | `[2.0, 200.0]` |
| `min_consecutive_samples` | muestras | `3` | `[1, 20]` |

Reglas transversales:

- `sample_step` nunca por debajo de la resolución del DEM: muestrear más fino que el píxel inventa
  detalle que no existe.
- `segment_length` debe ser ≥ `sample_step`; si no, un tramo puede quedarse sin muestras.
- Un valor fuera de rango se rechaza con el rango admitido en el mensaje y no inicia el cálculo
  (FR-042).

`color_thresholds` = `[warn, alert]`, en %, defecto `[8.0, 12.0]`, con `0 < warn < alert ≤ 100`.
Verde: `|pendiente| ≤ warn`. Amarillo: `warn < |pendiente| ≤ alert`. Rojo: `|pendiente| > alert`.

---

## 5. `AnalysisSummary`

| Campo | Tipo | Descripción |
|---|---|---|
| `segment_count` | int | Tramos generados. |
| `measured_count` | int | Tramos con ancho medido en ambos lados. |
| `no_edge_count` | int | Tramos sin ancho por falta de quiebre. |
| `no_data_count` | int | Tramos con algún lado sin datos de elevación. |
| `no_coverage_count` | int | Tramos cuyo eje no tiene cobertura del DEM. |
| `length` | float | Longitud total analizada, en metros. |
| `min_grade`, `max_grade`, `mean_grade` | float | Pendiente longitudinal, en %. |
| `min_width`, `max_width`, `mean_width` | float \| null | Ancho, en metros, sobre los tramos medidos. `null` si no hay ninguno. |
| `samples` | int | Muestras del DEM efectivamente leídas. |
| `duration` | float | Segundos que tardó el cálculo. |

---

## 6. Documento de tramos (archivo por análisis)

```json
{
  "version": 1,
  "analysis_id": "...",
  "generated_at": "...",
  "segments": [ Segment, ... ]
}
```

Escritura atómica: archivo temporal en el mismo directorio y `os.replace`, para que un worker
cancelado a media escritura no deje un JSON truncado.

### `Segment`

| Campo | Tipo | Reglas |
|---|---|---|
| `index` | int | 0-based, en orden de progresiva. |
| `station_start`, `station_end` | float | Progresiva en metros desde el inicio del eje. |
| `length` | float | Longitud real del tramo; el último puede ser menor que `segment_length`. |
| `geometry` | `[[lng, lat], ...]` | Geometría en planta del tramo, con sus vértices originales. |
| `midpoint` | `[lng, lat]` | Punto medio por progresiva; origen de la transversal. |
| `elevation` | float \| null | Cota del ajuste en el punto medio. `null` sin cobertura. |
| `grade` | float \| null | Pendiente longitudinal en %, con signo según el sentido del eje. |
| `grade_deg` | float \| null | La misma pendiente en grados. |
| `width` | float \| null | Ancho entre bordes. `null` si falta cualquiera de los dos. |
| `offset_left`, `offset_right` | float \| null | Distancia del eje a cada borde. `null` en el lado sin borde. |
| `cross_slope` | float \| null | Pendiente transversal entre bordes, en %. `null` sin ambos bordes. |
| `status` | enum | `measured` \| `no_edge` \| `no_coverage`. |
| `left_reason`, `right_reason` | enum \| null | `null` si ese lado tiene borde; si no, `no_break`, `no_data` o `break_at_axis` (FR-021). |

**Motivos de "sin borde"**:

| Motivo | Qué ocurrió | Qué suele significar |
|---|---|---|
| `no_break` | se recorrió todo el semiancho sin encontrar quiebre | el camino se funde con el terreno circundante |
| `no_data` | el DEM se quedó sin dato antes de completar el recorrido | el vuelo no cubre esa franja |
| `break_at_axis` | la racha de quiebre arranca sobre el propio eje | el eje no pasa por la calzada en ese tramo |

`break_at_axis` se añadió tras verlo sobre un DSM real: sin él, el borde caía a distancia cero, el
tramo salía con `width: 0.0` marcado como `measured`, y su `cross_slope` quedaba vacío por falta de
muestras entre bordes — rompiendo el primer invariante de esta sección. Un ancho de 0 m no es una
medición: es la señal de que ahí no hay calzada que medir.
| `edge_left`, `edge_right` | `[lng, lat]` \| null | Punto de borde detectado, para las geometrías auxiliares de la exportación. |
| `cross_section` | `[[lng, lat], [lng, lat]]` | Extremos de la transversal recorrida, para la exportación. |

**Coherencia obligatoria** (invariantes verificables en test):

- `status == "measured"` ⟺ `width`, `offset_left`, `offset_right` y `cross_slope` no son `null`, y
  ambos `*_reason` son `null`.
- `status == "no_edge"` ⟹ `width` y `cross_slope` son `null`, y al menos un `*_reason` no es `null`.
  El lado que sí detectó borde conserva su `offset_*` y su `edge_*`.
- `status == "no_coverage"` ⟹ `elevation`, `grade` y `grade_deg` son `null`; el tramo no aporta a
  las estadísticas de pendiente del resumen.
- Ningún campo se rellena por interpolación entre tramos (FR-022).
- `station_end` de un tramo es exactamente el `station_start` del siguiente; el primero empieza en
  `0.0` y el último termina en `plan_length`.

---

## 7. Relaciones

```text
Task (core, no se modifica)
 └─1:N─ RoadAnalysis (índice en el DataStore)
          ├─1:1─ AxisSource       (copia de la geometría del eje)
          ├─1:1─ AnalysisParameters
          ├─1:1─ AnalysisSummary  (cuando status == completed)
          └─1:N─ Segment          (archivo JSON aparte)
                   └─1:1─ transversal, con 0..2 puntos de borde
```

**Borrado en cascada**: al eliminarse la tarea, el receptor de `task_removed` —mismo patrón que
`annotations.signals`— borra el documento del DataStore y el directorio de tramos de esa tarea.
