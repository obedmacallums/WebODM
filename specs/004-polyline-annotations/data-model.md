# Phase 1 — Modelo de datos: polilíneas anotadas

**Feature**: `004-polyline-annotations` | **Fecha**: 2026-07-26

Toda la persistencia vive en **un único documento JSON por tarea**, almacenado con el
`GlobalDataStore` del framework (`app/plugins/data_store.py`) en el espacio de nombres
`annotations`, bajo la clave `task_<pk>`. El valor acaba en `PluginDatum.json_value`, que es un
`JSONField` de `django.contrib.postgres` (`app/models/plugin_datum.py:13`), es decir `jsonb`. No hay
modelos Django ni migraciones nuevas (Principio I). Ver `research.md` D5 y D7.

## Documento `TaskPolylines`

Clave: `annotations::task_<pk>` con `user = NULL` (global, compartido por todos los usuarios con
acceso a la tarea, FR-025).

```json
{
  "version": 1,
  "polylines": [ /* Polyline */ ]
}
```

| Campo | Tipo | Reglas |
|---|---|---|
| `version` | entero | Versión del contrato de datos. Empieza en `1`. Un lector que encuentre una versión mayor que la suya no debe reescribir el documento. |
| `polylines` | lista de `Polyline` | Puede estar vacía. El orden es el de creación y no es significativo. |

La ausencia de documento equivale a "esta tarea no tiene polilíneas": los lectores deben tratar
`None` y `{"version": 1, "polylines": []}` de la misma forma.

## Entidad `Polyline`

```json
{
  "id": "0f3b1a6c-8d2e-4a77-9d61-2b7a5c0e4f18",
  "name": "Camino norte",
  "mode": "draped",
  "vertices": [[-70.58960, -33.46832], [-70.58901, -33.46790]],
  "plan_length": 188.39,
  "created_at": "2026-07-26T18:04:11Z",
  "created_by": "obed",
  "updated_at": "2026-07-26T18:09:52Z",
  "elevation": { /* ElevationSampling, solo si mode == "draped" */ }
}
```

| Campo | Tipo | Reglas de validación |
|---|---|---|
| `id` | UUID4 en texto | Generado por el servidor. Único dentro de la tarea. Inmutable. |
| `name` | texto | Se recorta a 255 caracteres. Si llega vacío, el servidor asigna `Polilínea N` con el menor `N` libre (FR-003). No se exige unicidad. |
| `mode` | `"flat"` \| `"draped"` | FR-007. `"draped"` solo es admisible si la tarea tiene DSM o DTM (FR-009). |
| `vertices` | lista de `[lng, lat]` | Mínimo 2 vértices y al menos dos posiciones distintas (FR-002). Orden `[lng, lat]` en EPSG:4326, el mismo que GeoJSON. Longitud máxima: 500 vértices (FR-023). |
| `plan_length` | número (metros) | Longitud en planta, calculada en un CRS proyectado (`research.md` D11). Recalculada en cada cambio de geometría. |
| `created_at` / `updated_at` | ISO-8601 UTC con sufijo `Z` | `updated_at` cambia con cualquier modificación, incluido el renombrado. |
| `created_by` | texto | `username` del creador. Informativo; los permisos se resuelven contra el proyecto (`research.md` D9), no contra este campo. |
| `elevation` | `ElevationSampling` \| ausente | MUST estar presente si `mode == "draped"` y MUST estar ausente si `mode == "flat"`. |

Las cotas **no se guardan dentro de `vertices`**: viven en `elevation.vertex_z`, con el mismo índice.
Así, convertir entre modos no toca la geometría en planta (FR-011) y el trazado es idéntico byte a
byte antes y después de elevar.

## Entidad `ElevationSampling`

```json
{
  "model": "dsm",
  "vertex_z": [601.90, 598.44],
  "step": 0.25,
  "surface_length": 297.36,
  "elevation_gain": 149.23,
  "sample_count": 755,
  "vertical_unit": "metre",
  "sampled_at": "2026-07-26T18:09:52Z",
  "source_mtime": 1785000000.0
}
```

| Campo | Tipo | Reglas de validación |
|---|---|---|
| `model` | `"dsm"` \| `"dtm"` | El modelo efectivamente usado (FR-016, FR-017). |
| `vertex_z` | lista de números | Misma longitud y orden que `vertices`. **Nunca contiene el valor `nodata` ni `null`**: si algún vértice o punto intermedio careciera de dato, el muestreo se rechaza entero y no se persiste nada (FR-021, FR-022). |
| `step` | número (metros) | Paso de densificación empleado. Por defecto `max(resolución_del_DEM, 0.25)`. Rango admitido: `[resolución_del_DEM, 10.0]`. Ver `research.md` D4. |
| `surface_length` | número (metros) | Longitud sobre el terreno, derivada de la densificada. **Solo comparable a igualdad de `step`.** |
| `elevation_gain` | número (metros) | Desnivel acumulado (suma de los incrementos absolutos de cota sobre la densificada). |
| `sample_count` | entero | Número de puntos de la densificada que produjo estas cifras. Tope duro: 20 000 (FR-023). |
| `vertical_unit` | texto | Unidad vertical declarada por el ráster, tal cual, sin conversión de datum (FR-018). |
| `sampled_at` | ISO-8601 UTC | Momento del muestreo (FR-017). |
| `source_mtime` | número | `st_mtime` del archivo del DEM en el momento del muestreo. Detecta cotas obsoletas (FR-020, `research.md` D12). |

La geometría densificada **no se persiste** (`research.md` D5): se recalcula bajo demanda, en
milisegundos, a partir de `vertices` y `step`.

## Estados y transiciones

`Polyline.mode` es el estado principal:

```
        elevar (POST .../elevate)
  flat ───────────────────────────►  draped
       ◄───────────────────────────
        aplanar (POST .../flatten)
```

- **`flat` → `draped`**: exige tarea con DEM y cobertura completa del trazado. Si falta dato en algún
  punto, la transición se rechaza con el tramo afectado y la polilínea permanece `flat` (FR-022,
  escenario 8 de la US4). Añade el bloque `elevation`.
- **`draped` → `flat`**: siempre posible. Elimina el bloque `elevation`; `vertices` y `plan_length`
  quedan intactos.
- **Edición de geometría en `draped`**: se vuelve a muestrear como parte de la misma operación
  (FR-019). Si el trazado nuevo pierde cobertura, se rechaza la edición completa y la polilínea
  conserva su estado anterior; no queda a medias.

Estado derivado, **no persistido**, que el contrato de lectura calcula al vuelo:

| Estado | Condición | Efecto |
|---|---|---|
| `fresh` | `elevation.source_mtime == os.stat(dem).st_mtime` | Normal. |
| `stale` | difieren | La respuesta marca el muestreo como obsoleto y la interfaz ofrece volver a muestrear (FR-020). Las cifras se siguen mostrando, señaladas como antiguas. |

## Reglas transversales

1. **Escritura atómica del documento**: toda modificación lee el documento completo, lo altera y lo
   reescribe (`set_json`). Es el patrón de `coreplugins/realign/store.py` y arrastra su misma
   limitación: dos ediciones simultáneas sobre la misma tarea pueden perder una de ellas. El spec lo
   acepta al dejar la fusión fuera de alcance.
2. **Borrado en cascada**: al recibir `task_removed` se elimina la clave entera (FR-027,
   `research.md` D8).
3. **Unidades**: todas las longitudes se almacenan **en metros**, siempre. La conversión al sistema
   de unidades del usuario ocurre solo en el frontend, con `webodm/classes/Units` (FR-006, FR-015).
4. **Sistema de coordenadas**: se persiste siempre EPSG:4326 en orden `[lng, lat]` (FR-026). Las
   proyecciones a un CRS métrico son intermedias y no se guardan.
5. **Límites**: 500 vértices por polilínea y 20 000 puntos densificados. Superarlos devuelve un error
   explicativo que propone reducir el trazado o aumentar el paso (FR-023).
