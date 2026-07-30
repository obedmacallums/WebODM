# Data Model — borde por segmentación semántica de la ortofoto (`007-road-edge-segmentation`)

**Delta sobre [`006-street-width/data-model.md`](../006-street-width/data-model.md)**, que a su vez
es delta sobre [`005-road-metrics/data-model.md`](../005-road-metrics/data-model.md). Aquí solo se
describe lo que cambia; todo lo que no aparece se conserva idéntico. Las secciones se numeran igual
que en los dos documentos anteriores para poder cotejarlas.

El documento de tramos **no cambia de versión** (`"version": 1`, sin cambios desde `005`): la
adición es un valor nuevo dentro de un dominio ya existente (el motivo), no una clave nueva. Un
documento escrito por `006` se lee sin conversión.

---

## 4. `AnalysisParameters` — sin campos nuevos, un valor nuevo en un enum existente

| Campo | Cambio |
|---|---|
| `edge_mode` | El enum pasa de `break` \| `surface` a `break` \| `surface` \| `segmentation`. Sigue siendo un único campo (`007/FR-001`). |

Reglas nuevas o modificadas:

- `edge_mode == 'segmentation'` no habilita ni exige ningún parámetro propio (`007/FR-015`): no hay
  equivalente a `break_threshold` o `surface_tolerance` para este modo. El margen del corredor de
  recorte (`research.md` D26) es una constante interna, no un parámetro, con el mismo estatus que
  `SURFACE_SEED_HALF_WIDTH` de `006` (`007/FR-028`-equivalente, aunque no está numerado como tal en
  `spec.md` por no haberse tocado esa sección).
- `min_consecutive_samples` se reutiliza tal cual en los tres modos, ahora contando rachas de
  clasificación "no-calzada" sostenida en vez de pendientes o residuos por encima de un umbral
  (`007/FR-006`, `research.md` D30).
- `coherence_window` se aplica en los **tres** modos sin distinción (`007/FR-011`); su semántica no
  cambia.
- `smooth_window` se sigue publicando y aceptando en modo segmentación (`007/FR-015b`), pero **no
  interviene** en la detección de ese modo: la máscara de calzada/no-calzada no es una señal
  continua sobre la que tenga sentido una mediana móvil de la misma forma que sobre elevación. Sigue
  aplicando, sin cambios, al perfil de elevación usado para `cross_slope` (`007/FR-010`). Se acepta y
  persiste en los tres modos por el mismo motivo que `surface_tolerance` se acepta en `break`
  (`006/data-model.md §4`): cambiar de modo sobre un análisis existente no debe perder el valor ya
  ajustado.
- Un `edge_mode` desconocido se sigue rechazando con los tres valores admitidos en el mensaje
  (`007/FR-004`), sin cambios en el mecanismo de `sources.validate_params`.

Los defectos y rangos los sigue publicando `GET capabilities` (`sources.EDGE_MODES` ampliado a tres
valores), sin que el panel duplique constantes (`007/FR-014`).

### Restricción de disponibilidad, nueva en este documento

A diferencia de `break` y `surface`, que solo requieren DSM o DTM, `edge_mode == 'segmentation'`
requiere que la tarea tenga una ortofoto (`orthophoto.tif` entre los assets disponibles). Esta
restricción se comprueba **antes** de aceptar la petición de análisis, con el mismo patrón que ya
usa `_resolve_model_and_variant` para el DEM (`api.py:96-122`, `no_elevation_model()`): ver
[contracts/rest-api-delta.md](./contracts/rest-api-delta.md).

---

## 6. `Segment` — un valor nuevo en el dominio del motivo, sin campos nuevos

### Campo cuyo dominio cambia

| Campo | Cambio |
|---|---|
| `left_reason`, `right_reason` | El dominio pasa de `null` \| `no_break` \| `no_data` \| `break_at_axis` a esos cuatro más `no_orthophoto` (`research.md` D29). El significado de los tres ya existentes no cambia; `no_orthophoto` es exclusivo del modo segmentación y solo aparece cuando la etapa de segmentación se completó pero la ortofoto no cubre la zona de **ese** tramo (`research.md` D28, caso 2). |

Ningún otro campo de `Segment` cambia de dominio ni de significado. `left_edge_source` /
`right_edge_source` (`006`) se reutilizan sin cambios: un borde hallado por el modo segmentación
cuenta como `measured`, exactamente igual que uno hallado por `break` o `surface`
(`007/FR-012`) — el origen del borde no distingue de qué criterio salió, solo si se midió en el
propio tramo o se dedujo de la vecindad.

### Combinación de motivo y origen — una fila nueva

Añade una fila a la tabla de `006/data-model.md §6`, con el resto de combinaciones sin cambios:

| `*_reason` | `*_edge_source` | `offset_*` | Lectura |
|---|---|---|---|
| `no_orthophoto` | `null` | `null` | El tramo cae en modo segmentación, la ortofoto no cubre este lado del tramo, y la coherencia no tenía evidencia con la que rellenarlo. |
| `no_orthophoto` | `inferred` | valor | Igual que la fila anterior, pero la pasada de coherencia sí tenía vecinos medidos y rellenó el valor (`007/FR-011`, reutiliza `006/FR-015` sin cambios). |

### Invariantes — sin cambios de fondo

Todos los invariantes de `006/data-model.md §6` siguen aplicando sin modificación: existe `width` si
y solo si el tramo tiene los dos bordes con independencia del origen; `*_edge_source == null` si y
solo si `offset_* == null`; un borde inferido nunca vota para inferir otro; etc. Ninguno depende de
qué modo produjo el borde, así que ampliar a un tercer modo no les afecta.

---

## 6c. Fallo global de la etapa de segmentación — no es un estado de `Segment`

Cuando la etapa de segmentación falla por completo (sin ortofoto en absoluto — cubierto ya por la
restricción de disponibilidad de arriba —, sin librería `geodeep`, o sin poder descargar el modelo;
`research.md` D28 caso 1), **no se produce ningún `Segment`**. El análisis entero adopta el estado ya
existente `status: 'failed'` con `error: <mensaje>` (`compute.py:709-716`, sin cambios de esquema:
es el mismo mecanismo que ya usa cualquier excepción no prevista del pipeline). No se introduce
ningún campo nuevo en el documento de índice de análisis para este caso.

---

## 5. `AnalysisSummary` — sin campos nuevos

`no_data_count` sigue contando solo `profile.NO_DATA`, sin ampliarse a `no_orthophoto`: son motivos
distintos con causas distintas (`research.md` D29) y fundirlos en el mismo contador ocultaría cuál de
las dos fuentes —DEM u ortofoto— está fallando. No se añade un `no_orthophoto_count` dedicado: no
hay ningún requisito de `spec.md` que lo pida, y los tramos con ese motivo ya se cuentan dentro de
`no_edge_count` como cualquier otro tramo sin borde. Si en el futuro se necesitara desglosar, es una
adición aislada y compatible, no algo que esta feature deba anticipar.

---

## 7. Relaciones — la máscara de segmentación no se persiste

Igual que la **referencia de calzada** de `006` (la recta ajustada de D18), la **máscara de
segmentación** (`research.md` D25, D30) es interna al cálculo de un análisis: se reconstruye desde
la ortofoto y el corredor del eje cada vez que se recalcula, y no se guarda en el documento de
tramos ni en el índice. Guardarla no aportaría nada que el usuario consulte directamente —no es una
de las tres familias que exporta `export.to_geojson` (tramo, transversal, punto de borde)— y añadiría
peso sin uso.
