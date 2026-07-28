# Realign

Plugin para realinear los productos ráster 2D de una tarea (ortofoto, DSM, DTM) a partir de pares
de puntos, aplicando una similitud y regenerando los corregidos sin tocar los originales; incluye
la generación de la nube de puntos corregida. Documentación de diseño en
[`specs/002-realign-products/`](../../specs/002-realign-products/) y
[`specs/003-realign-pointcloud/`](../../specs/003-realign-pointcloud/).

## Contrato para otros plugins

`CONTRACT_VERSION = 1`. Un consumidor **no importa este paquete directamente**: lo obtiene por el
framework de plugins, que es lo que permite degradar con elegancia si `realign` está ausente o
deshabilitado.

```python
from app.plugins.functions import get_plugin_by_name

plugin = get_plugin_by_name("realign")
corrected = {}
if plugin is not None and getattr(plugin, "contract_version", None) and plugin.contract_version() <= 1:
    corrected = plugin.corrected_rasters(task_id)

# {'orthophoto': '/ruta.tif', 'dsm': ..., 'dtm': ...} con solo los que existen ahora mismo
```

Métodos públicos de la clase `Plugin` (delegan en `contract.py`; ningún otro atributo forma parte
del contrato):

| Método | Devuelve |
|---|---|
| `contract_version()` | `1` |
| `corrected_rasters(task_id)` | Rutas de los productos corregidos **que existen en disco**. Diccionario vacío si la tarea no tiene realineación aplicada, si se revirtió, o si los archivos ya no están. |

Se comprueban las dos cosas —estado `applied` **y** presencia real del archivo— porque son
independientes: un borrado manual del directorio de plugins deja el estado intacto, y un consumidor
que se fiara solo del estado abriría una ruta inexistente dentro del worker, lejos de donde se
podría explicar. Ninguno comprueba permisos: el consumidor ya resolvió el acceso a la tarea.

Lo consume [`road`](../road/README.md) para ofrecer la variante realineada del modelo de elevación.
Detalle en
[`005-road-metrics/contracts/consumed-contracts.md`](../../specs/005-road-metrics/contracts/consumed-contracts.md).

## Tests

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.realign.tests
```
