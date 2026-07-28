# Road

Plugin para extraer características geométricas de un camino a partir de su eje y de un modelo de
elevación de la tarea: divide el eje en tramos configurables y reporta por tramo la cota, la
pendiente longitudinal, el ancho medido entre bordes detectados y la pendiente transversal,
pintándolos sobre el mapa 2D con un semáforo verde/amarillo/rojo y exportándolos a CSV y GeoJSON.
Documentación completa de diseño en [`specs/005-road-metrics/`](../../specs/005-road-metrics/):
[`spec.md`](../../specs/005-road-metrics/spec.md),
[`plan.md`](../../specs/005-road-metrics/plan.md),
[`data-model.md`](../../specs/005-road-metrics/data-model.md),
[`contracts/rest-api.md`](../../specs/005-road-metrics/contracts/rest-api.md) y
[`contracts/consumed-contracts.md`](../../specs/005-road-metrics/contracts/consumed-contracts.md).

## Qué hace

- **El eje entra por dos vías**: una polilínea 2D del plugin `annotations` de la misma tarea, o un
  GeoJSON con un `LineString` subido desde el panel. Sin `annotations` la vía del archivo sigue
  funcionando.
- **Tramificación por progresiva**: el eje se corta cada `segment_length` metros (5 m por defecto);
  el último tramo conserva su longitud real.
- **Bordes por quiebre de pendiente**: en el punto medio de cada tramo se recorre una transversal
  perpendicular hacia cada lado hasta `search_half_width`, y el borde es el arranque de la primera
  racha sostenida de pendiente por encima de `break_threshold`. Cuando no hay borde se dice por qué,
  por lado: `no_break` (se recorrió todo sin quiebre) o `no_data` (el DEM se quedó sin dato).
- **Pendientes por mínimos cuadrados**, no por diferencia de extremos: la longitudinal sobre todas
  las muestras del eje del tramo, la transversal sobre las muestras entre bordes.
- **Nada se rellena**: una métrica que no se pudo medir viaja vacía, nunca interpolada ni a cero.
- **Semáforo en el cliente**: el color sale de la pendiente y de dos umbrales que el usuario mueve
  con recoloreado inmediato; los umbrales se persisten sin invalidar el cálculo.
- **Exportación**: CSV (una fila por tramo) y GeoJSON (tramos, transversales y puntos de borde).

## Parámetros de cálculo

| Parámetro | Unidad | Defecto | Rango | Qué controla |
|---|---|---|---|---|
| `segment_length` | m | 5,0 | 0,5 – 100 | cada cuánto se corta el eje |
| `search_half_width` | m | 10,0 | 1 – 50 | hasta dónde se busca el borde a cada lado |
| `sample_step` | m | `max(resolución, 0,1)` | resolución – 5 | separación entre muestras |
| `break_threshold` | % | 15,0 | 2 – 200 | pendiente local que cuenta como quiebre |
| `min_consecutive_samples` | muestras | 3 | 1 – 20 | longitud mínima de la racha de quiebre |

El suelo de `sample_step` es la **resolución del ráster**, no una constante: muestrear más fino que
el píxel inventa detalle que no existe. Y `segment_length` nunca puede ser menor que `sample_step`,
o un tramo puede quedarse sin muestras que ajustar. Los valores y rangos vigentes los sirve
`GET capabilities`, para que el panel no duplique constantes.

`color_thresholds` = `[aviso, alerta]` en %, por defecto `[8, 12]`, con `0 < aviso < alerta ≤ 100`.
**No interviene en el cálculo**: cambiarlo recolorea en el cliente y se persiste sin invalidar nada.

## Rutas

Todas cuelgan de `/api/plugins/road/task/<task_id>/…`. Esquema completo, incluidos los códigos de
error, en [`contracts/rest-api.md`](../../specs/005-road-metrics/contracts/rest-api.md).

| Método y ruta | Qué hace |
|---|---|
| `GET capabilities` | modelos, variantes, ejes, defectos y rangos |
| `GET analyses` | índice de la tarea, sin tramos, más el candado de ejecución |
| `POST analyses` | lanza un análisis (JSON o `multipart/form-data` con `file`) |
| `POST analyses/estimate` | coste previo sin lanzar nada |
| `GET analyses/<id>` | el análisis con sus tramos |
| `PATCH analyses/<id>` | solo `name` y `color_thresholds` |
| `DELETE analyses/<id>` | borra índice y archivo de tramos |
| `POST analyses/<id>/cancel` | cancela; idempotente |
| `GET analyses/<id>/export?format=csv\|geojson` | descarga |

`?format=` en la exportación necesita desactivar la negociación de contenido de DRF en esa vista:
`format` es un nombre reservado (`URL_FORMAT_OVERRIDE`) y DRF responde `404` ante un valor que no
corresponde a ningún renderer, antes de ejecutar la vista.

## Motivos de "sin borde"

| Motivo | Qué ocurrió | Qué suele significar |
|---|---|---|
| `no_break` | se recorrió todo el semiancho sin quiebre | el camino se funde con el terreno |
| `no_data` | el DEM se quedó sin dato | el recorrido llegó al borde del vuelo |
| `break_at_axis` | el quiebre arranca sobre el propio eje | el eje no pasa por la calzada ahí |

## Almacenamiento

Dos niveles, para no meter megabytes en una fila de texto que se reescribe en cada actualización de
progreso:

| Almacén | Qué guarda | Dónde |
|---|---|---|
| Índice | metadatos de cada análisis y el candado de ejecución | `GlobalDataStore('road')`, clave `task_<pk>` |
| Tramos | la colección de tramos de un análisis terminado | `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json` |

Ninguna tabla ni migración propia. Al eliminarse la tarea, el receptor de `task_removed` borra
ambos.

## Plugins hermanos

`road` es **consumidor**: no expone contrato Python a otros plugins.

- `annotations` (`CONTRACT_VERSION = 2`): de él salen los ejes disponibles, solo los `mode == "flat"`.
- `realign` (`CONTRACT_VERSION = 1`): de él sale la variante realineada del DEM, vía
  `corrected_rasters(task_id)`.

Ambos se obtienen con `get_plugin_by_name` y se degradan en silencio si están ausentes,
deshabilitados o exponen un contrato mayor del que este plugin sabe leer.

## Rendimiento

El eje se recorre **por bloques de tramos**: por cada bloque se lee una única ventana del ráster a
un array de numpy y todas sus muestras —eje y transversales— se resuelven por indexación
vectorizada. `ds.sample()` haría una lectura por punto, que es el cuello de botella directo con
decenas de miles de muestras. El borde del bloque es además donde se reporta progreso y se
comprueba la cancelación.

Medido sobre un DTM de 2,2 cm: 1 km de eje con los valores por defecto son 200 tramos y 50.400
muestras en **0,37 s**, con 14 reportes de progreso.

## Desarrollo

Sin dependencias nuevas: usa `rasterio` y `numpy`, ya presentes en la imagen.

`coreplugins/` va horneado en la imagen, así que un plugin nuevo no aparece por el bind mount. Y
`docker compose cp origen destino` copia **dentro** del destino cuando este ya existe (deja un
`road/road/` anidado y el código viejo intacto), así que hay que borrarlo antes:

```bash
for s in webapp worker; do
  docker compose exec -T $s rm -rf /webodm/coreplugins/road
  docker compose cp coreplugins/road $s:/webodm/coreplugins/road
done
docker compose restart webapp worker
```

El worker necesita su copia porque el cálculo corre allí.

## Tests

```bash
docker compose exec webapp /webodm/webodm.sh test backend coreplugins.road.tests
```

A diferencia de `annotations` y `realign`, que usan un `tests.py` plano, aquí los tests viven en un
paquete `tests/`. Eso obliga a **reexportar las clases desde `tests/__init__.py`**: el runner de
Django prueba primero `loadTestsFromName` y solo si eso devuelve 0 tests intenta `discover()`, que
aquí revienta porque `coreplugins/` no tiene `__init__.py` (es un namespace package). Un módulo de
test nuevo que no se importe en `__init__.py` sencillamente no se ejecuta.

Guía de despliegue, cobertura y validación manual en
[`quickstart.md`](../../specs/005-road-metrics/quickstart.md).
