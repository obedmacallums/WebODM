# Contratos consumidos y ampliados

**Feature**: 005-road-metrics | **Decisiones**: [research.md D1](../research.md)

`road` no expone contrato Python a otros plugins: es consumidor. Este documento fija cómo habla con
los dos plugins hermanos y qué hace cuando no están.

---

## 1. `annotations` — consumido sin cambios

Contrato existente, `CONTRACT_VERSION = 2`, documentado en
[`specs/004-polyline-annotations/contracts/plugin-contract.md`](../../004-polyline-annotations/contracts/plugin-contract.md).

```python
from app.plugins.functions import get_plugin_by_name

plugin = get_plugin_by_name("annotations")
if plugin is None:
    ...  # ausente o deshabilitado: `capabilities` responde annotations_available: false
elif plugin.contract_version() > 2:
    ...  # contrato mayor del que sabemos leer: se trata como ausente y se registra en el log
else:
    axes = [p for p in plugin.get_polylines(task_id) if p["mode"] == "flat"]
```

De cada polilínea se usan `id`, `name` y `vertices`. **No** se usa `get_densified()`: `road` hace su
propio muestreo, denso y en dos dimensiones (D2), y densificar por el contrato de `annotations`
duplicaría la lectura del ráster.

Solo se ofrecen las polilíneas `flat` (2D). Las `draped` no se listan, por la razón registrada en
las asunciones de la spec: su Z es del DEM que ellas eligieron, no del que elige este análisis.

**Degradación**: cualquier fallo al hablar con `annotations` deja `annotations_available: false` y
la lista de ejes vacía. La vía del archivo funciona igual (FR-005). `road` nunca importa
`coreplugins.annotations` directamente.

---

## 2. `realign` — se le añade un contrato de lectura

Hoy `realign` no expone métodos públicos. Esta feature le añade los mínimos para que `road` pueda
usar sus productos corregidos sin conocer su almacenamiento interno.

```python
class Plugin(PluginBase):
    def contract_version(self):
        """Versión del contrato de consumo de este plugin. Hoy 1."""

    def corrected_rasters(self, task_id):
        """{'orthophoto': '/ruta.tif', 'dsm': ..., 'dtm': ...} con solo los productos
        corregidos que existen en disco ahora mismo. Diccionario vacío si la tarea no tiene
        realineación aplicada, si se revirtió, o si los archivos ya no están.
        No comprueba permisos: el consumidor ya resolvió el acceso a la tarea."""
```

Implementación: delega en un módulo `contract.py` nuevo dentro de `realign`, que reutiliza los
helpers de rutas ya existentes en su `api.py` y comprueba `state == 'applied'` más la presencia real
del archivo — el mismo criterio que `corrected_available` usa hoy para responder al panel.

**Uso desde `road`**:

```python
plugin = get_plugin_by_name("realign")
corrected = {}
if plugin is not None and getattr(plugin, "contract_version", None) and plugin.contract_version() <= 1:
    corrected = plugin.corrected_rasters(task_id)
variants = ["original"] + (["realigned"] if model in corrected else [])
```

**Degradación**: sin `realign`, sin contrato o sin corregidos, la única variante ofrecida es
`original` y el panel no muestra opciones muertas (FR-008).

**Compatibilidad**: es una adición pura a `realign`. No cambia ninguna ruta, respuesta ni
comportamiento existente, así que no afecta a su propia feature ni a sus tests.

---

## 3. Bus de anotaciones del core — `PluginsAPI.Map`

`road` es el **segundo** productor del bus (el primero es `annotations`), lo que hace crítica la
regla que aquel dejó documentada: el bus se detiene en el primer manejador que devuelve un valor
*truthy*, así que **todo manejador debe devolver `false` sobre layers que no le pertenecen**.

| Evento | Comportamiento de `road` |
|---|---|
| `addAnnotation(layer, name, task, stored)` | Publica un `L.FeatureGroup` por análisis: una polilínea por tramo. |
| `onToggleAnnotation(layer, visible)` | Muestra u oculta el grupo. `false` si el layer no está en su registro. |
| `onDeleteAnnotation(layer)` | `DELETE` del análisis; al confirmar, retira el grupo y avisa con `annotationDeleted`. `false` si el layer es ajeno. |
| `onDownloadAnnotations(format)` | `false` siempre: la exportación de `road` es CSV y GeoJSON con su propio esquema, y se pide desde su panel, no desde el botón genérico del panel de capas. |

Convivencia verificada en test: con ambos plugins activos, una acción sobre una anotación de
`annotations` no debe pasar por los manejadores de `road`, y viceversa.

---

## 4. Núcleo de WebODM — solo interfaces públicas

| Interfaz | Uso |
|---|---|
| `app.plugins.PluginBase`, `MountPoint` | Estructura del plugin y rutas. |
| `app.plugins.views.TaskView`, `GetTaskResult` | Vistas y sondeo de la tarea asíncrona. |
| `app.plugins.worker.run_function_async` | Ejecución en el worker con progreso y cancelación. |
| `app.plugins.data_store.GlobalDataStore` | Índice de análisis compartido por tarea. |
| `app.plugins.functions.get_plugins_persistent_path`, `get_plugin_by_name` | Almacenamiento de tramos y acceso a plugins hermanos. |
| `app.api.common.check_project_perms` | Permisos de escritura sobre el proyecto. |
| `app.geoutils.get_rasterio_to_meters_factor` | Conversión de unidades del ráster a metros. |
| `Task.get_asset_download_path`, `Task.dsm_extent`, `Task.dtm_extent` | Rásteres originales y su extensión. |
| Señal `task_removed` | Borrado en cascada. |

Ninguna de estas se modifica. No hay cambios en `app/`, `webodm/`, `worker/`, `nodeodm/`, `nginx/`
ni en los scripts raíz.
