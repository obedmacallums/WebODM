# Contrato de consumo para otros plugins + contrato con el core

**Feature**: `004-polyline-annotations` | **Fecha**: 2026-07-26

Dos contratos distintos: el que este plugin **ofrece** a otros plugins del fork (FR-036 a FR-040), y
el que **debe cumplir** frente al sistema de anotaciones del core (FR-028, FR-029, FR-032).

---

# 1. Contrato ofrecido a otros plugins

`CONTRACT_VERSION = 2`. Se expone en toda respuesta y en el módulo Python. Un consumidor debe
comprobarlo y negarse a interpretar versiones mayores que la suya (FR-040).

**v1 → v2**: el tipo de una polilínea pasó a ser inmutable (se elige al crearla con los botones
*Polilínea 2D* / *Polilínea 3D*). Se retiró `elevate()` del contrato Python y las rutas REST
`…/elevate` y `…/flatten`; un `PATCH` que intente cambiar `mode` responde `400`. Se añadió
`GET …/polylines/<id>/export`. `mode` mantiene sus valores `"flat"`/`"draped"`: 2D y 3D son
etiquetas de la interfaz, no valores nuevos, así que lo ya almacenado sigue siendo válido.

## 1.1 Desde el backend (Python)

El consumidor **no importa el paquete del plugin directamente**: lo obtiene por el framework, que es
lo que permite detectar que el plugin está ausente o deshabilitado.

```python
from app.plugins.functions import get_plugin_by_name

plugin = get_plugin_by_name("annotations")   # None si no está instalado o está deshabilitado
if plugin is None:
    ...  # degradar con elegancia: el consumidor no puede exigir su presencia
```

Métodos públicos de la clase `Plugin` (delegan en `contract.py`; ningún otro atributo forma parte
del contrato):

| Método | Devuelve | Notas |
|---|---|---|
| `contract_version()` | `int` | `2` en esta feature. |
| `get_polylines(task_id)` | `list[dict]` | Todas las polilíneas de la tarea, con el mismo esquema del `GET` REST. Lista vacía si no hay ninguna. **No comprueba permisos**: el consumidor ya resolvió el acceso a la tarea. |
| `get_polyline(task_id, polyline_id)` | `dict \| None` | |
| `get_densified(task_id, polyline_id, step=None)` | `dict` | Calcula la densificada al vuelo (FR-038). Lanza `ValueError` sobre una polilínea 2D. |

Excepciones públicas, importables desde el módulo del plugin: `IncompleteCoverage` (con
`missing_ranges`, `missing_samples`, `total_samples`) y `LimitExceeded`.

**Caso de uso previsto** (un plugin de perfil longitudinal): pedir `get_polylines`, filtrar por
`mode == "draped"` y pedir su densificada — sin dibujar nada ni abrir un solo ráster. Las 2D no
llevan cota y el contrato ya no las eleva: si el consumidor necesita un perfil, el usuario debe
trazar una 3D.

## 1.2 Desde el frontend (JavaScript)

No hay bus del core para esto, así que el contrato es el REST de `rest-api.md`, consumido con
`$.ajax` como hace el resto del fork:

```js
$.getJSON(`/api/plugins/annotations/task/${taskId}/polylines`, res => {
  if (res.version !== 1) return;          // versión del documento almacenado, no del contrato
  const usable = res.polylines.filter(p => p.mode === "draped");  // las 3D
});
```

El `version` de esa respuesta identifica el **esquema del documento persistido**, que sigue en `1`
porque v2 no cambió nada de lo almacenado. El contrato Python es el que va por `contract_version()`.

Ese endpoint sí aplica permisos, porque la petición llega con la sesión del usuario.

## 1.3 Compromisos de compatibilidad

Dentro de una versión: **se pueden añadir** campos nuevos a las respuestas y parámetros
opcionales; **no se pueden** eliminar ni renombrar campos ni métodos, cambiar tipos o unidades, ni
alterar la semántica de `mode`. Cualquiera de esas cosas exige subir `CONTRACT_VERSION` — es
exactamente lo que obligó al salto a `2` al retirar `elevate`. Las longitudes van siempre en metros
y las coordenadas siempre en EPSG:4326 con orden `[lng, lat]`.

---

# 2. Contrato con el sistema de anotaciones del core

El core define este contrato en `app/static/app/js/classes/plugins/Map.js:24-32` y **no lo implementa
nadie**: este plugin es el primer productor (`research.md` D2). Reglas de obligado cumplimiento:

## 2.1 Publicar

Por cada polilínea guardada, una vez creado su `L.Polyline`:

```js
PluginsAPI.Map.addAnnotation(layer, name, task, stored);
```

`stored` en `true` cuando la línea viene de la persistencia y no de un trazado recién hecho: el core
lo usa para decidir la visibilidad inicial en mapas multi-tarea (`Map.jsx:1052-1060`). El core
escribe `layer[Symbol.for("meta")]` y encaja la línea en el grupo de la tarea (FR-030).

## 2.2 Responder

El plugin **debe** registrar estos manejadores; sin ellos los botones del panel de capas no hacen
nada (FR-029):

| Manejador | Qué debe hacer |
|---|---|
| `onToggleAnnotation(layer, visible)` | Añadir o quitar el layer del mapa. |
| `onDeleteAnnotation(layer)` | Borrar en el servidor y, al confirmarse, emitir `PluginsAPI.Map.annotationDeleted(layer)` para que el core lo saque de su estado. |
| `onDownloadAnnotations(format)` | Con `format === "geojson"`, disparar la descarga y devolver `true`. Es lo que rellena el `// TODO?` de `LayersControlAnnotations.jsx:127`. |

El renombrado se propaga en sentido contrario: tras guardar el nombre nuevo, el plugin emite
`PluginsAPI.Map.updateAnnotation(layer, name)` y el core refresca la etiqueta
(`LayersControlAnnotations.jsx:28-40`).

## 2.3 Regla crítica: no acaparar el bus

Las `functions` de `PluginsAPI` recorren los callbacks y **se detienen en el primero que devuelve un
valor *truthy*** (`ApiFactory.js:95-102`). Todos los manejadores de este plugin deben comprobar que
el layer es suyo y **devolver `false` cuando no lo sea**, o romperán a cualquier otro plugin que en
el futuro produzca anotaciones. Se marcan los layers propios con una propiedad privada en el momento
de crearlos.

## 2.4 Activación del control

`main.js` se engancha a `PluginsAPI.Map.willAddControls`, que recibe `args.tiles` con la tarea de
cada capa (patrón de `coreplugins/viewshed/public/main.js`). De ahí sale la comprobación de FR-031:
**el control de trazado solo se añade cuando hay exactamente una tarea**; con varias, las polilíneas
guardadas se siguen cargando y mostrando, pero sin herramientas de creación ni de edición de
geometría.
