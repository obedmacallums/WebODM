# Contrato REST — plugin `annotations`

**Feature**: `004-polyline-annotations` | **Fecha**: 2026-07-26

Todas las rutas cuelgan de `/api/plugins/annotations/` y se declaran con `MountPoint` en
`api_mount_points()`, igual que `coreplugins/viewshed/plugin.py`. Todas las vistas heredan de
`app.plugins.views.TaskView` y resuelven la tarea con `get_and_check_task(request, pk)`.

**Permisos** (`research.md` D9): lectura exige `view_project` —lo aplica `get_and_check_task`—; toda
escritura añade `check_project_perms(request, task.project, ('change_project',))`. Un usuario sin
permiso de edición recibe `404`, que es lo que hace `check_project_perms` en el core (no `403`, para
no revelar la existencia del recurso).

**Errores**: `{"error": "<mensaje traducible>"}` con el código HTTP correspondiente, siguiendo el
patrón de `coreplugins/realign/api.py`. Los mensajes pasan por `gettext_lazy`.

---

## `GET task/<pk>/elevation`

Capacidades de elevación de la tarea. La interfaz la usa para decidir si ofrece el modo sobre el
terreno y con qué valores por defecto (FR-009, FR-010, FR-016).

```json
{
  "available": ["dsm", "dtm"],
  "default_model": "dsm",
  "resolution": 0.0222,
  "default_step": 0.25,
  "step_range": [0.0222, 10.0],
  "max_vertices": 500,
  "max_samples": 20000,
  "vertical_unit": "metre"
}
```

`available` sale de `task.dsm_extent` / `task.dtm_extent`, sin tocar el disco. Con la lista vacía, el
resto de campos relativos al DEM van a `null` y el cliente deshabilita el modo sobre el terreno
explicando por qué (FR-009).

## `GET task/<pk>/polylines`

Todas las polilíneas de la tarea (FR-024).

```json
{
  "version": 1,
  "polylines": [
    {
      "id": "0f3b1a6c-…",
      "name": "Camino norte",
      "mode": "draped",
      "vertices": [[-70.58960, -33.46832], [-70.58901, -33.46790]],
      "plan_length": 188.39,
      "created_at": "2026-07-26T18:04:11Z",
      "created_by": "obed",
      "updated_at": "2026-07-26T18:09:52Z",
      "elevation": {
        "model": "dsm",
        "vertex_z": [601.90, 598.44],
        "step": 0.25,
        "surface_length": 297.36,
        "elevation_gain": 149.23,
        "sample_count": 755,
        "vertical_unit": "metre",
        "sampled_at": "2026-07-26T18:09:52Z",
        "stale": false
      }
    }
  ]
}
```

`elevation.stale` es el estado derivado de `data-model.md` (comparación de `source_mtime`); el campo
`source_mtime` en sí no se expone. Si la tarea no tiene documento, devuelve `polylines: []`.

## `POST task/<pk>/polylines`

Crea una polilínea (FR-001, FR-003, FR-007).

```json
{
  "name": "Camino norte",
  "mode": "draped",
  "vertices": [[-70.58960, -33.46832], [-70.58901, -33.46790]],
  "model": "dsm",
  "step": 0.25
}
```

- `mode` por defecto: `"draped"` si la tarea tiene DEM, `"flat"` si no (FR-010).
- `model` y `step` solo se leen con `mode == "draped"`; si se omiten se aplican los valores por
  defecto de `GET .../elevation`.
- **`201`** con la polilínea creada, en el mismo formato del `GET`.
- **`400`** con menos de 2 vértices distintos (FR-002), con más de `max_vertices`, con un `step`
  fuera de rango, o si el modo pedido es `"draped"` y la tarea no tiene DEM.
- **`422`** si falta cobertura de elevación; el cuerpo detalla el tramo afectado (ver más abajo).

### Respuesta de cobertura incompleta

Se emplea en toda operación que intente muestrear (`POST`, `PATCH` con geometría, `elevate`). Es la
materialización de FR-022:

```json
{
  "error": "Parte del recorrido no tiene datos de elevación.",
  "reason": "incomplete_coverage",
  "missing_ranges": [[0.42, 0.57]],
  "missing_samples": 217,
  "total_samples": 755
}
```

`missing_ranges` son intervalos normalizados `[0, 1]` sobre la longitud del trazado, para que el
cliente pueda resaltar en el mapa exactamente qué tramo falta. **Nunca se devuelven cotas parciales
ni rellenadas**, y no se persiste nada.

## `PATCH task/<pk>/polylines/<id>`

Modifica nombre y/o geometría (FR-004, FR-005, FR-019).

```json
{ "name": "Camino norte revisado", "vertices": [[…], […], […]] }
```

- Enviar solo `name` es un renombrado puro: no vuelve a muestrear.
- Enviar `vertices` sobre una polilínea `draped` **rehace el muestreo con el mismo `model` y `step`**.
  Si el trazado nuevo pierde cobertura, responde `422` y la polilínea **queda intacta** — la
  operación es todo o nada (`data-model.md`, transiciones).
- **`200`** con la polilínea actualizada. **`404`** si el `id` no existe en esa tarea.

## `DELETE task/<pk>/polylines/<id>`

Elimina la polilínea (FR-005). **`204`** sin cuerpo; **`404`** si no existe.

## Conversión entre tipos: no existe (desde v2)

El tipo se fija al crear la polilínea (2D → `mode: "flat"`, 3D → `mode: "draped"`) y es inmutable.
Las rutas `POST …/elevate` y `POST …/flatten` de la v1 fueron **eliminadas** y responden `404`. Un
`PATCH` que envíe un `mode` distinto del actual responde **`400`**; reenviar el mismo `mode` junto a
otros campos es válido y se ignora.

## `GET task/<pk>/polylines/<id>/densified[?step=<m>]`

Geometría densificada calculada al vuelo (FR-038, `research.md` D5). Solo para polilíneas `draped`.

```json
{
  "step": 0.25,
  "model": "dsm",
  "sample_count": 755,
  "coordinates": [[-70.58960, -33.46832, 601.90], "…"]
}
```

`step` permite recalcular a otra escala sin alterar lo persistido; si se omite se usa el de la
polilínea. **`400`** sobre una polilínea plana o con un `step` que superaría `max_samples`.

## `GET task/<pk>/polylines/<id>/export[?geometry=vertices|densified]`

Descarga GeoJSON de **una sola** polilínea (FR-032 a FR-034): es lo que usa el botón *Exportar* del
panel sobre la polilínea seleccionada. Mismo cuerpo y cabeceras que la exportación de la tarea, con
una única feature, y el tipo en el nombre del archivo:
`<slug-de-la-tarea>-<slug-de-la-polilínea>-2d|3d.geojson`. **`404`** si el `id` no existe en esa
tarea; **`400`** con un `geometry` inválido.

## `GET task/<pk>/polylines/export[?geometry=vertices|densified]`

Descarga GeoJSON de toda la tarea (FR-032, FR-033, FR-034). `geometry` por defecto `vertices`; con
`densified` solo se densifican las polilíneas `draped` (las planas salen igual en ambos casos).
Mezcla ambos tipos, así que su nombre **no** lleva sufijo. El panel ya no la usa; se conserva
porque el botón de descarga del grupo de anotaciones lo dibuja el core, no el plugin.

Responde `application/geo+json` con `Content-Disposition: attachment` y nombre
`<slug-de-la-tarea>-polylines.geojson`. Una `FeatureCollection` cuyas features son `LineString` —con
tres ordenadas en las polilíneas elevadas, dos en las planas— y estas propiedades (FR-033):

```json
{
  "type": "Feature",
  "geometry": { "type": "LineString", "coordinates": [[-70.58960, -33.46832, 601.90], "…"] },
  "properties": {
    "id": "0f3b1a6c-…",
    "name": "Camino norte",
    "mode": "draped",
    "plan_length_m": 188.39,
    "surface_length_m": 297.36,
    "elevation_gain_m": 149.23,
    "elevation_model": "dsm",
    "densify_step_m": 0.25,
    "vertical_unit": "metre",
    "sampled_at": "2026-07-26T18:09:52Z"
  }
}
```

En las polilíneas planas, las propiedades derivadas de la elevación se omiten en lugar de ir a
`null`, para que QGIS no cree columnas vacías. El GeoJSON se emite sin CRS explícito, que en GeoJSON
significa EPSG:4326 (FR-035).
