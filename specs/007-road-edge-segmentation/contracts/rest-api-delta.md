# Contrato REST — delta de `007-road-edge-segmentation`

**Adiciones al contrato de
[`006-street-width/contracts/rest-api-delta.md`](../../006-street-width/contracts/rest-api-delta.md)**,
que a su vez es delta de
[`005-road-metrics/contracts/rest-api.md`](../../005-road-metrics/contracts/rest-api.md). Aquí solo
aparece lo que cambia. Rutas, autenticación, formato de error y todo lo no listado se conservan
idénticos.

**Ninguna ruta nueva.** El tercer modo viaja por el mismo campo `edge_mode` que ya existe. Un
cliente que no conozca `"segmentation"` sigue funcionando con `break` y `surface` exactamente igual
que hoy.

---

## `GET task/<pk>/capabilities` — un valor más en `edge_modes`

```jsonc
{
  // ... resto igual ...
  "edge_modes": ["break", "surface", "segmentation"]   // AMPLIADO
}
```

Sin campos nuevos en `defaults` ni en `ranges`: el modo segmentación no añade parámetros propios
(`007/FR-015`, `data-model.md §4`).

---

## `POST task/<pk>/analyses` — `edge_mode` admite un tercer valor, con una comprobación previa nueva

```jsonc
{
  "axis": { /* igual */ },
  "model": "dtm", "variant": "original",
  "params": {
    "edge_mode": "segmentation",   // AMPLIADO: admite "break" | "surface" | "segmentation"
    // el resto de params, sin cambios
  }
}
```

### Comprobación de disponibilidad, nueva

Cuando `params.edge_mode == "segmentation"`, la petición comprueba que la tarea tenga ortofoto
**antes** de aceptar el análisis, con el mismo patrón que ya usa `_resolve_model_and_variant` para
el DEM (`api.py:no_elevation_model()`). Si no la tiene, responde de inmediato sin lanzar el worker:

```json
{"error": "La tarea no tiene ortofoto.", "code": "no_orthophoto", "status": 400}
```

`no_orthophoto` es un código de error nuevo, del mismo estilo que los ya existentes
(`ERR_NO_ELEVATION_MODEL`, `api.py:31`). Solo se evalúa cuando el modo pedido es `segmentation`; los
otros dos modos no lo comprueban, igual que hoy no comprueban la ortofoto para nada.

Esta comprobación **no** cubre si la librería `geodeep` está instalada ni si el modelo se puede
descargar: eso no se puede saber sin intentarlo, y se resuelve como fallo del análisis ya en marcha
(ver más abajo), no como rechazo de la petición.

### Errores — un código nuevo

| Código | Cuándo | HTTP |
|---|---|---|
| `no_orthophoto` | `edge_mode == "segmentation"` y la tarea no tiene `orthophoto.tif` disponible | 400 |

`edge_mode` con un valor desconocido sigue usando `invalid_parameter`, ahora con los tres valores
en el mensaje:

```json
{"error": "edge_mode debe ser uno de: break, surface, segmentation", "code": "invalid_parameter"}
```

---

## `GET task/<pk>/analyses/<analysis_id>` — sin campos nuevos, dos cambios de contenido posibles

### Fallo global de la etapa de segmentación

Si la tarea sí tenía ortofoto (pasó la comprobación previa) pero la librería `geodeep` no está
disponible, o el modelo `roads` no se pudo descargar, el análisis completo usa el mecanismo de
fallo **ya existente**, sin forma nueva:

```jsonc
{
  "id": "…", "status": "failed", "progress": null,
  "error": "GeoDeep library is missing",   // o el mensaje concreto del fallo
  "summary": null
}
```

Ningún tramo se produce. Es el mismo esquema que hoy usa cualquier fallo del pipeline
(`compute.py:709-716`); no se introduce un código de error de análisis distinto de los que ya existen.

### Motivo nuevo en tramos con cobertura de ortofoto incompleta

```jsonc
{
  "index": 34,
  "status": "no_edge",
  "left_reason": "no_orthophoto",      // NUEVO valor, solo en edge_mode: "segmentation"
  "right_reason": null,
  "left_edge_source": null,
  "right_edge_source": "measured",
  "offset_left": null,
  "offset_right": 3.10
}
```

`left_reason` / `right_reason` amplían su dominio a `null | "no_break" | "no_data" |
"break_at_axis" | "no_orthophoto"` (`data-model.md §6`). Los clientes que ya distinguen los tres
motivos existentes y tratan cualquier motivo no reconocido como "sin borde, motivo desconocido"
siguen funcionando; los que quieran mostrar un mensaje específico para `no_orthophoto` necesitan
actualizarse, igual que ya se esperaba al añadir el estado `inferred` en `006`.

---

## `GET task/<pk>/analyses/<analysis_id>/export`

### CSV — sin columnas nuevas

Las columnas son las mismas de `006`. El valor de `left_reason` / `right_reason` puede ser ahora
`no_orthophoto`, como cualquier otra cadena de motivo — no requiere cambio de esquema.

### GeoJSON — sin propiedades nuevas

Igual razonamiento: `left_reason` / `right_reason` ya viajaban como texto libre dentro de
`properties`; el valor nuevo no rompe ningún lector que no valide el enum de forma estricta.

Los parámetros de la colección (`properties.params` en el `FeatureCollection`) siguen incluyendo
`edge_mode`, ahora con `"segmentation"` como valor posible.
