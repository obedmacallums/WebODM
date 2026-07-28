# Data Model — ancho de calle por criterio de superficie (`006-street-width`)

**Delta sobre [`005-road-metrics/data-model.md`](../005-road-metrics/data-model.md).** Aquí solo se
describe lo que cambia; todo lo que no aparece se conserva idéntico. Las secciones se numeran igual
que allí para poder cotejarlas.

El documento de tramos **no cambia de versión** (`"version": 1`): las adiciones son claves nuevas
con valor por defecto deducible, y los archivos escritos por la versión anterior se leen sin
conversión (§6b).

---

## 4. `AnalysisParameters` — tres campos nuevos

| Campo | Unidad | Defecto | Rango admitido |
|---|---|---|---|
| `edge_mode` | enum | `break` | `break` \| `surface` |
| `surface_tolerance` | m | `0.06` | `[0.02, 0.50]` |
| `coherence_window` | tramos | `0` | `[0, 5]` |

Reglas:

- `edge_mode` decide qué criterio busca el borde. `break` es el de `005/D3` y debe producir
  resultados idénticos a los de la versión anterior (FR-002).
- `surface_tolerance` **solo se usa en modo `surface`**. Se acepta y se persiste igualmente en modo
  `break`, para que cambiar de modo sobre un análisis existente no pierda el valor que el usuario ya
  había ajustado.
- `coherence_window` se aplica en **ambos** modos. El defecto `0` desactiva la pasada, que es lo que
  garantiza que ningún análisis existente cambie de resultado (FR-012).
- `min_consecutive_samples` se reutiliza tal cual en los dos modos: en `break` cuenta pendientes
  locales por encima del umbral, en `surface` cuenta residuos por encima de la tolerancia.
- Un valor fuera de rango, o un `edge_mode` desconocido, se rechaza con los valores admitidos en el
  mensaje y no inicia el cálculo (FR-004, FR-027).

Los defectos y rangos los sigue publicando `GET capabilities`, sin que el panel duplique constantes
(FR-026).

---

## 6. `Segment` — dos campos nuevos y un estado nuevo

### Campos añadidos

| Campo | Tipo | Reglas |
|---|---|---|
| `left_edge_source`, `right_edge_source` | enum \| null | `measured` si el borde se halló en el perfil de ese tramo; `inferred` si procede de la vecindad (D20); `null` si ese lado no tiene borde. |

### Campos cuyo dominio cambia

| Campo | Cambio |
|---|---|
| `status` | Se añade `inferred` al enum: `measured` \| `inferred` \| `no_edge` \| `no_coverage`. |
| `width`, `cross_slope` | Dejan de estar atados a `measured`: existen también cuando `status == "inferred"`. |
| `left_reason`, `right_reason` | **Sin cambios de dominio ni de significado**: siguen diciendo por qué no hay borde *medido* en ese lado. Lo que cambia es que ahora pueden convivir con un `offset_*` no nulo. |

### Estados

| `status` | Cuándo | `width` / `cross_slope` |
|---|---|---|
| `measured` | los dos bordes con origen `measured` | presentes |
| `inferred` | los dos bordes presentes y al menos uno con origen `inferred` | presentes |
| `no_edge` | falta al menos un borde tras la coherencia | `null` |
| `no_coverage` | sin rasante ajustable en el eje | `null` (y también `elevation`, `grade`, `grade_deg`) |

### Combinación de motivo y origen

Las cuatro combinaciones posibles por lado, y cómo se leen:

| `*_reason` | `*_edge_source` | `offset_*` | Lectura |
|---|---|---|---|
| `null` | `measured` | valor | Borde medido en este tramo. |
| `null` | `inferred` | valor | Había borde medido, pero se apartaba tanto de la vecindad que se sustituyó (FR-016). |
| `no_break` / `no_data` / `break_at_axis` | `inferred` | valor | No se pudo medir aquí, y el valor viene de los vecinos (FR-015). El motivo original se conserva. |
| `no_break` / `no_data` / `break_at_axis` | `null` | `null` | No hay borde, ni medido ni inferible. |

La tercera fila es la que justifica que existan dos campos en vez de uno: sin el motivo se perdería
**por qué** no se pudo medir, que es lo que le dice al usuario si el problema es su umbral, su vuelo
o su trazado (`005/FR-021`).

### Invariantes (reemplazan a los de `005/data-model §6`)

- `status == "measured"` ⟺ `width`, `offset_left`, `offset_right` y `cross_slope` no son `null`, y
  **ambos** `*_edge_source` valen `measured`.
- `status == "inferred"` ⟺ `width`, `offset_left`, `offset_right` y `cross_slope` no son `null`, y
  **al menos uno** de los `*_edge_source` vale `inferred`.
- **Existe `width` ⟺ `status ∈ {measured, inferred}`** ⟺ los dos `offset_*` no son `null`, con
  independencia de su origen (FR-022).
- `status == "no_edge"` ⟹ `width` y `cross_slope` son `null`, y al menos un `*_edge_source` es
  `null`. El lado que sí tiene borde conserva su `offset_*`, su `edge_*` y su origen.
- `*_edge_source == null` ⟺ `offset_* == null`.
- `*_edge_source == "inferred"` ⟹ existe al menos un tramo dentro de la ventana de coherencia con
  ese mismo lado en `measured` (D20: los inferidos no votan, así que ninguna inferencia puede nacer
  de otra inferencia).
- `coherence_window == 0` ⟹ ningún `*_edge_source` vale `inferred` (FR-012).
- Ningún campo se rellena por interpolación **dentro** de un tramo. La única información que cruza
  entre tramos es la que declara `*_edge_source` (`005/FR-022`, matizado por FR-019).
- Se conservan sin cambios el resto de invariantes de `005`: continuidad de progresivas, `no_coverage`
  fuera de las estadísticas del resumen, etc.

---

## 6b. Lectura de documentos escritos por la versión anterior

Un documento de tramos generado antes de esta feature no tiene los campos de origen. Al leerlo se
completan sin escribir nada en disco (FR-024):

```
left_edge_source  = "measured" si offset_left  no es null, si no null
right_edge_source = "measured" si offset_right no es null, si no null
status            = el que ya trae (nunca "inferred", porque no hubo coherencia)
```

Y en `AnalysisParameters`, un análisis antiguo se lee con `edge_mode = "break"`,
`surface_tolerance = 0.06` y `coherence_window = 0`, que es exactamente el comportamiento con el que
se calculó.

No hay migración, ni script de conversión, ni cambio de `version`: el documento antiguo sigue siendo
válido y el completado ocurre en el punto de lectura.

---

## 5. `AnalysisSummary` — sin campos nuevos, con un matiz

El recuento por estado del resumen incorpora `inferred` como categoría propia. Los tramos `inferred`
**sí** cuentan en las estadísticas de ancho, porque tienen ancho; el usuario distingue su origen
tramo a tramo, no en el agregado.

---

## 7. Relaciones

Sin cambios. La coherencia no crea entidades: opera sobre la secuencia de `Segment` de un mismo
análisis y modifica campos de esos mismos objetos antes de persistirlos.

La **referencia de calzada** (la recta ajustada de D18) es intermedia del cálculo de un tramo y
**no se persiste**: se puede reconstruir en cualquier momento desde el DEM y los parámetros, y
guardarla añadiría peso al documento de tramos sin que nadie la consulte.
