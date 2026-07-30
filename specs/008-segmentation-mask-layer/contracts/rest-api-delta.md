# Contrato REST — delta de `008-segmentation-mask-layer`

**Adiciones al contrato de
[`007-road-edge-segmentation/contracts/rest-api-delta.md`](../../007-road-edge-segmentation/contracts/rest-api-delta.md)**,
que a su vez es delta de `006` y `005`. Aquí solo aparece lo que cambia. Rutas, autenticación,
formato de error y todo lo no listado se conservan idénticos.

**Una ruta nueva** (para la máscara) y **un campo nuevo** en las respuestas de análisis. Un cliente
que ignore ambos sigue funcionando exactamente igual que hoy.

---

## `GET task/<pk>/analyses` y `GET task/<pk>/analyses/<analysis_id>` — un campo más por análisis

```jsonc
{
  "id": "…",
  "status": "completed",
  "params": { "edge_mode": "segmentation", /* … */ },
  "summary": { /* … igual … */ },
  "has_mask": true          // NUEVO
}
```

`has_mask` indica si este análisis tiene máscara guardada y, por tanto, si el cliente debe ofrecer
el control de la capa (`FR-015`).

- `true` solo en análisis de modo `segmentation` calculados a partir de esta feature.
- `false` (o **ausente**, en análisis anteriores) en todo lo demás.

Los clientes DEBEN tratar la ausencia del campo como `false`. No hay migración de datos: los
análisis antiguos siguen en disco tal cual y su falta de campo se interpreta en memoria
(`data-model.md §2`).

**La máscara NO viaja en estas respuestas.** Solo el booleano. Los polígonos se piden aparte y solo
cuando hacen falta (D36) — de lo contrario cada apertura del panel arrastraría decenas de KB para
una capa que por defecto está apagada (`FR-014`).

---

## `GET task/<pk>/analyses/<analysis_id>/mask` — ruta nueva

Devuelve los polígonos que el modelo clasificó como calzada en el corredor de ese análisis.

Se registra **antes** del patrón genérico de `<analysis_id>`, como el resto de rutas literales
(`plugin.py` advierte que un `MountPoint` sin `$` final resuelve por prefijo y se tragaría las rutas
hermanas).

### `200 OK` — hay máscara

```jsonc
{
  "version": 1,
  "analysis_id": "…",
  "generated_at": "2026-07-29T23:27:33Z",
  "resolution_m": 0.2,              // resolución real de la máscara; sostiene el aviso de FR-016
  "simplify_tolerance_m": 0.2,      // qué se simplificó (D38)
  "features": [
    {
      "type": "Feature",
      "properties": {"class": "road"},
      "geometry": {"type": "Polygon", "coordinates": [[[-70.713…, -33.355…], /* … */]]}
    }
    // …
  ]
}
```

Coordenadas en **EPSG:4326**, listas para dibujar sin reproyectar.

`features` **puede venir vacío**: significa que el modelo corrió y no reconoció calzada en el
corredor. Es un resultado con valor informativo —explica por qué los tramos salieron sin borde— y
el cliente NO DEBE presentarlo como un error ni como «no hay máscara» (`FR-017`).

### `404 Not Found` — no hay máscara guardada

```jsonc
{"code": "mask_missing", "detail": "…"}
```

Se da cuando el análisis es anterior a esta feature, o es de modo `break`/`surface`. Es **distinto**
de una máscara vacía: aquí no se llegó a guardar nada. El cliente debe explicarlo y ofrecer
recalcular (`FR-018`), no mostrar una capa vacía como si fuera un resultado.

### Otros códigos

| Código | Cuándo | Nota |
|---|---|---|
| `404` `not_found` | El análisis no existe en la tarea | Igual que el resto de rutas de análisis |
| `404` `mask_missing` | El análisis existe pero no tiene máscara | Ver arriba |

No hay `410 result_missing` propio: a diferencia del documento de tramos, la ausencia del fichero de
máscara no es una anomalía sino un estado esperado, y ya lo cubre `mask_missing`.

---

## Lo que NO cambia

- `GET task/<pk>/capabilities` — sin campos nuevos.
- `POST task/<pk>/analyses` — mismo cuerpo, mismos parámetros, mismas validaciones. La máscara se
  genera como efecto del modo `segmentation`, sin que el cliente pida nada.
- `POST task/<pk>/analyses/estimate` — igual.
- `GET …/export?format=csv|geojson` — **mismo esquema y mismas columnas** (`FR-020`). La máscara no
  aparece en las descargas.
- `DELETE task/<pk>/analyses/<analysis_id>` — misma respuesta. Internamente borra también la
  máscara, pero eso no cambia el contrato.
- `POST …/cancel` — igual.
