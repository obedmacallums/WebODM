# Annotations

Plugin para trazar polilíneas anotadas sobre el mapa 2D de una tarea — **2D** (planas) o **3D**
(sobre el terreno, con cotas muestreadas del DSM/DTM) —, editarlas, exportarlas a GeoJSON y
reutilizarlas desde otros plugins del fork. Documentación completa de diseño en
[`specs/004-polyline-annotations/`](../../specs/004-polyline-annotations/):
[`spec.md`](../../specs/004-polyline-annotations/spec.md),
[`data-model.md`](../../specs/004-polyline-annotations/data-model.md),
[`contracts/rest-api.md`](../../specs/004-polyline-annotations/contracts/rest-api.md) y
[`contracts/plugin-contract.md`](../../specs/004-polyline-annotations/contracts/plugin-contract.md).

## Qué hace

- **Trazar y conservar**: se elige el tipo antes de dibujar, con los botones *Polilínea 2D* y
  *Polilínea 3D*; la línea se nombra y se persiste, aparece en el panel de capas nativo de WebODM
  y sobrevive a recargas.
- **El tipo es inmutable**: queda fijado al crear la polilínea y no se convierte después. Para
  cambiar de tipo se traza una nueva. En la lista cada una lleva su distintivo 2D/3D.
- **Elevación (solo 3D)**: cotas del DSM o el DTM, con longitud sobre el terreno, desnivel
  acumulado y el paso de densificación empleado.
- **Editar**: mover/insertar/borrar vértices y renombrar, con recálculo automático de métricas.
  En modo edición: arrastrar un nodo lo mueve, click izquierdo sobre la línea inserta un nodo en
  ese punto del tramo y click derecho sobre un nodo lo elimina (nunca por debajo de 2 vértices).
- **Exportar**: se selecciona una polilínea de la lista y se descarga en GeoJSON (`LineString`,
  con Z en las 3D). El archivo lleva el tipo en el nombre: `<tarea>-<polilínea>-2d|3d.geojson`.
  El botón de descarga del panel de capas del core sigue bajando el grupo entero en un archivo.
- **Reutilizar**: contrato Python versionado para que otro plugin lea la geometría o la variante
  densificada (ver más abajo).

## API REST

Todas las rutas cuelgan de `/api/plugins/annotations/task/<task_id>/…`. Esquema completo,
incluidos los códigos de error, en
[`contracts/rest-api.md`](../../specs/004-polyline-annotations/contracts/rest-api.md).

## Contrato para otros plugins

`CONTRACT_VERSION = 2`. Un consumidor **no importa este paquete directamente**: lo obtiene por
el framework de plugins, que es lo que permite degradar con elegancia si `annotations` está
ausente o deshabilitado.

```python
from app.plugins.functions import get_plugin_by_name

plugin = get_plugin_by_name("annotations")
if plugin is None:
    ...  # el plugin no está instalado o está deshabilitado

if plugin.contract_version() > 2:
    ...  # esta versión del consumidor no sabe interpretar contratos mayores (FR-040)

lines = plugin.get_polylines(task_id)                 # list[dict], mismo esquema que el GET REST
elevated = [l for l in lines if l["mode"] == "draped"]  # las 3D; "flat" son las 2D
densified = plugin.get_densified(task_id, elevated[0]["id"])
print(densified["sample_count"], densified["coordinates"][0])  # [lng, lat, z]
```

Métodos públicos de la clase `Plugin` (delegan en `contract.py`; ningún otro atributo forma
parte del contrato): `contract_version()`, `get_polylines(task_id)`,
`get_polyline(task_id, polyline_id)` y `get_densified(task_id, polyline_id, step=None)`.
Ninguno comprueba permisos: el consumidor ya resolvió el acceso a la tarea. Excepciones
públicas, importables desde este mismo módulo
(`from coreplugins.annotations.plugin import IncompleteCoverage, LimitExceeded`):
`IncompleteCoverage` (con `missing_ranges`, `missing_samples`, `total_samples`) y
`LimitExceeded`.

**Cambios de v1 a v2**: el tipo de una polilínea dejó de ser convertible, así que desaparecen
`plugin.elevate()` y las rutas REST `…/elevate` y `…/flatten`, y un `PATCH` que intente cambiar
`mode` se rechaza con `400`. El campo `mode` conserva sus valores `"flat"`/`"draped"`: 2D y 3D
son las etiquetas de la interfaz, no valores nuevos. Se añadió
`GET …/polylines/<id>/export` para descargar una sola polilínea.

Detalle completo de compromisos de compatibilidad y del contrato con el sistema de anotaciones
del core (bus de `PluginsAPI.Map`) en
[`contracts/plugin-contract.md`](../../specs/004-polyline-annotations/contracts/plugin-contract.md).

## Desarrollo

Sin dependencias nuevas: usa `rasterio`, ya presente en la imagen. Guía de despliegue en
Docker, cobertura de tests y validación manual en
[`quickstart.md`](../../specs/004-polyline-annotations/quickstart.md).

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.annotations.tests
```
