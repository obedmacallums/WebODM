# Contrato HTTP — selección asistida

Extiende la API del plugin `training` con dos rutas. El contrato existente
([`009/contracts/rest-api.md`](../../009-training-dataset-labeling/contracts/rest-api.md)) **no
cambia**: las etiquetas que produce esta feature se crean por el endpoint de etiquetas que ya existe.

Prefijo: `/api/plugins/training/`. Autenticación y permisos, los del plugin (el usuario necesita
acceso a la tarea).

Convención de rutas heredada de `plugin.py`: toda ruta ancla el final con `$`.

---

## `POST datasets/<dataset_id>/tasks/<task_id>/regions`

Devuelve la geometría de las regiones que corresponden a unos puntos del terreno. **No crea
etiquetas**: el cliente decide qué hacer con la geometría y la guarda, si quiere, por
`POST .../labels`.

Separar las dos cosas mantiene toda la validación de etiquetas en un solo sitio y permite que el
arrastre de US2 pida geometría en vivo y escriba una sola vez al soltar.

### Petición

```json
{
  "points": [{"lat": -33.4569, "lon": -70.6483}],
  "granularity": "medium",
  "tolerance": 0.0,
  "elevation_weight": 1.0
}
```

| Campo | Obligatorio | Notas |
|---|---|---|
| `points` | sí | uno o más puntos en EPSG:4326. Uno para un clic (US1); varios para un arrastre (US2) |
| `granularity` | no | `fine` / `medium` / `coarse`. Por defecto, el del dataset |
| `tolerance` | no | `0.0`–`1.0`. `0.0` = exactamente la región de cada punto. Por defecto, la del dataset |
| `elevation_weight` | no | `0.0`–`1.0`. `0.0` desactiva los canales de terreno. Por defecto, el del dataset |

Los tres ajustes se aceptan en la petición **y** viven en el dataset: el cliente puede
previsualizar con un valor sin haberlo guardado todavía.

### Respuesta `200`

```json
{
  "geometry": {"type": "MultiPolygon", "coordinates": [[[[-70.6483, -33.4569], "..."]]]},
  "region_count": 7,
  "elevation_source": "dtm",
  "band_count": 5,
  "truncated": false,
  "prepared_cells": 2
}
```

| Campo | Significado |
|---|---|
| `geometry` | unión de las regiones seleccionadas, EPSG:4326. `MultiPolygon` siempre, aunque salga una sola parte |
| `region_count` | cuántas regiones entraron |
| `elevation_source` | `dtm`, `dsm` o `none` — permite a la interfaz decir que se está trabajando sin terreno (FR-011) |
| `band_count` | 3 o 5 |
| `truncated` | `true` si el crecimiento por tolerancia chocó con el tope de FR-018. La interfaz **debe** avisarlo |
| `prepared_cells` | celdas que hubo que calcular en esta petición; `0` significa que todo estaba en caché |

### Respuesta `200` sin selección

Pinchar fuera de la huella del vuelo no es un error (FR-025):

```json
{
  "geometry": null,
  "region_count": 0,
  "reason": "no_data",
  "message": "Ese punto está fuera de la zona cubierta por el vuelo."
}
```

### Errores

| Código | `error_code` | Cuándo |
|---|---|---|
| `400` | `bad_points` | `points` vacío, mal formado o fuera de rango de coordenadas |
| `400` | `bad_settings` | granularidad desconocida, o tolerancia/peso fuera de `[0, 1]` |
| `404` | `not_found` | el dataset no existe, o la tarea no pertenece al dataset |
| `409` | `no_orthophoto` | la tarea no tiene ortofoto |
| `403` | — | el usuario no tiene acceso a la tarea |

Todos los mensajes van traducidos con `_()` y son accionables (FR-025).

---

## `GET datasets/<dataset_id>/tasks/<task_id>/regions/status`

Dice si una zona ya está preparada, para que la interfaz pueda anunciar la espera **antes** de que
ocurra en vez de dejar el cursor colgado (FR-024).

### Parámetros

| Parámetro | Notas |
|---|---|
| `bounds` | `minLon,minLat,maxLon,maxLat` — normalmente el encuadre visible |
| `granularity`, `elevation_weight` | opcionales; por defecto los del dataset |

### Respuesta `200`

```json
{
  "cells_total": 12,
  "cells_ready": 9,
  "estimated_seconds": 2.9,
  "elevation_source": "dtm"
}
```

`estimated_seconds` sale de multiplicar las celdas pendientes por el coste medido por celda. Es una
estimación declarada, no una promesa.

---

## Lo que NO cambia

- **El contrato del paquete exportado**
  ([`009/contracts/dataset-package.md`](../../009-training-dataset-labeling/contracts/dataset-package.md))
  no se toca. Es el contrato más caro de cambiar del plugin, lo consume a ciegas otra máquina, y esta
  feature no le da ningún motivo para cambiar: produce etiquetas `polygon`, que ya existían.
- **`POST .../labels`** acepta un valor más en `source` (`assisted`). El campo ya estaba en el
  modelo; no hay campo nuevo ni forma nueva.
- **Ningún endpoint existente cambia de forma ni de semántica.**

## Invariantes que el contrato debe respetar

1. **Determinismo** (FR-007): dos peticiones con el mismo punto y los mismos ajustes devuelven
   geometrías idénticas, sean de la misma sesión o no, esté la caché fría o caliente.
2. **Independencia del encuadre** (FR-008): la respuesta no depende de `bounds`, del zoom ni de nada
   que describa la vista. `bounds` solo aparece en `status`, que es informativo.
3. **Regiones completas** (FR-005): nunca se devuelve una fracción de región, aunque el punto caiga
   junto a su borde.
4. **Sin juntas** (FR-009): una región que cruza el borde de una celda se devuelve entera y sin
   partir. Garantizado por el halo de `8S` (research.md D2).
