# Contrato REST — delta de `006-street-width`

**Adiciones al contrato de [`005-road-metrics/contracts/rest-api.md`](../../005-road-metrics/contracts/rest-api.md).**
Aquí solo aparece lo que cambia. Rutas, autenticación, formato de error y todo lo no listado se
conservan idénticos.

**Ninguna ruta nueva.** Los parámetros nuevos viajan por el canal que ya existe y los campos nuevos
aparecen dentro de las representaciones que ya se servían. Un cliente antiguo que ignore las claves
nuevas sigue funcionando.

---

## `GET task/<pk>/capabilities` — tres entradas más en `defaults` y `ranges`

```jsonc
{
  // ... resto igual ...
  "defaults": {
    "segment_length": 5.0, "search_half_width": 10.0, "sample_step": 0.1,
    "break_threshold": 15.0, "min_consecutive_samples": 3,
    "edge_mode": "break",              // NUEVO
    "surface_tolerance": 0.06,         // NUEVO
    "coherence_window": 0,             // NUEVO
    "color_thresholds": [8.0, 12.0]
  },
  "ranges": {
    "segment_length": [0.5, 100.0], "search_half_width": [1.0, 50.0],
    "sample_step": [0.052, 5.0], "break_threshold": [2.0, 200.0],
    "min_consecutive_samples": [1, 20],
    "surface_tolerance": [0.02, 0.50], // NUEVO
    "coherence_window": [0, 5]         // NUEVO
  },
  "edge_modes": ["break", "surface"]   // NUEVO: dominio de edge_mode, que no es un rango numérico
}
```

`edge_modes` va aparte de `ranges` porque es un enum, no un intervalo, y el panel lo consume de forma
distinta: dibuja un selector, no un deslizador. Sigue valiendo la regla de `005`: el panel no
codifica ninguno de estos valores, los lee de aquí.

---

## `POST task/<pk>/analyses` — tres parámetros más

Se admiten dentro del mismo objeto `params` que el resto:

```jsonc
{
  "axis": { /* igual */ },
  "model": "dtm", "variant": "original",
  "params": {
    "segment_length": 5.0,
    "search_half_width": 5.0,
    "sample_step": 0.05,
    "break_threshold": 15.0,
    "min_consecutive_samples": 3,
    "edge_mode": "surface",       // NUEVO, defecto "break"
    "surface_tolerance": 0.06,    // NUEVO
    "coherence_window": 2         // NUEVO, defecto 0
  },
  "color_thresholds": [8.0, 12.0]
}
```

Los tres son opcionales; omitirlos deja el comportamiento anterior exactamente igual.

### Errores

Sin códigos nuevos. `edge_mode` con un valor desconocido usa el `invalid_parameter` que ya existe,
con los valores admitidos en el mensaje (FR-004):

```json
{"error": "edge_mode debe ser uno de: break, surface", "code": "invalid_parameter"}
```

---

## `POST task/<pk>/analyses/estimate` — sin cambios de forma

La estimación de muestras no cambia: el número de transversales y de muestras por transversal es el
mismo en los dos modos. El modo afecta al coste **por muestra**, no a cuántas hay, y ese sobrecoste
está acotado por SC-007 (≤ 25 %).

---

## `GET task/<pk>/analyses/<analysis_id>` — campos nuevos en cada tramo

```jsonc
{
  "index": 17,
  "station_start": 85.0, "station_end": 90.0, "length": 5.0,
  "elevation": 142.31, "grade": -2.4, "grade_deg": -1.37,
  "width": 6.75,
  "offset_left": 0.95, "offset_right": 5.80,
  "cross_slope": -1.9,
  "status": "inferred",              // AMPLIADO: measured | inferred | no_edge | no_coverage
  "left_reason": null,
  "right_reason": "no_break",        // el motivo original se conserva
  "left_edge_source": "measured",    // NUEVO
  "right_edge_source": "inferred"    // NUEVO
}
```

Y en la representación del análisis, `params` incluye los tres campos nuevos, de modo que siempre se
sabe con qué criterio se calculó (FR-003).

Reglas del contrato, con detalle en [data-model.md](../data-model.md#6-segment--dos-campos-nuevos-y-un-estado-nuevo):

- `*_edge_source` es `null` exactamente cuando `offset_*` es `null`.
- `status: "inferred"` implica ancho presente y al menos un `*_edge_source` en `inferred`.
- Un tramo puede llevar `*_reason` no nulo **y** `offset_*` no nulo a la vez; no es una
  contradicción, es la combinación "no se pudo medir aquí, el valor viene de los vecinos".

---

## `GET task/<pk>/analyses/<analysis_id>/export`

### CSV — dos columnas más, al final

```text
index,station_start,station_end,length,elevation,grade_pct,grade_deg,width,
offset_left,offset_right,cross_slope_pct,status,left_reason,right_reason,
left_edge_source,right_edge_source
```

Se añaden **al final** para no romper a quien lea el CSV por posición de columna. Las celdas sin dato
siguen yendo vacías, nunca a cero.

El bloque de comentarios `#` del pie incorpora `edge_mode`, `surface_tolerance` y
`coherence_window` junto al resto de parámetros (FR-033).

### GeoJSON — dos propiedades más en las entidades `segment`

Las entidades de `kind: "segment"` incorporan `left_edge_source` y `right_edge_source`. Las de
`kind: "cross_section"` y `kind: "edge"` no cambian.

Un punto de borde (`kind: "edge"`) **sí se emite** para un borde inferido, con su posición deducida,
y la propiedad `source` del propio punto dice de dónde sale:

| Propiedad | Valores |
|---|---|
| `side` | `left` \| `right` |
| `source` | `measured` \| `inferred` |

Sin esa propiedad, quien abra el GeoJSON en QGIS vería puntos de borde indistinguibles y daría por
medido lo que no lo está.

Los parámetros de la colección incluyen también los tres campos nuevos.
