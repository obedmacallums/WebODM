"""Superficie pública versionada: exportación GeoJSON (`contracts/rest-api.md`) y contrato de
consumo para otros plugins (`contracts/plugin-contract.md` §1)."""

from django.utils.text import slugify

from app.models import Task

from . import store, elevation
from .elevation import IncompleteCoverage, LimitExceeded  # noqa: F401 - reexport del contrato

# v2: el tipo de una polilínea (2D/3D, `mode` "flat"/"draped") queda fijado al crearla y ya no se
# puede convertir. Desaparecen `elevate()` y el `flatten` REST; la exportación pasa a ser por
# polilínea. `mode` sigue siendo "flat"/"draped" en el esquema: 2D y 3D son las etiquetas de la
# interfaz, no valores nuevos, para no invalidar lo ya almacenado.
CONTRACT_VERSION = 2

# Etiqueta de interfaz por cada `mode` del esquema. Se usa en el nombre del archivo exportado.
MODE_SUFFIX = {'flat': '2d', 'draped': '3d'}


def serialize_polyline(polyline, task=None):
    """Polilínea persistida -> esquema público de `contracts/rest-api.md` (sin `source_mtime`,
    que es un detalle interno de `data-model.md` usado solo para calcular `elevation.stale`).
    Único punto de serialización: lo usan tanto el REST (`api.py`) como el contrato Python
    ofrecido a otros plugins (`get_polylines`/`get_polyline`), que exige "el mismo esquema"
    (`contracts/plugin-contract.md` §1.1)."""
    out = {
        'id': polyline['id'],
        'name': polyline['name'],
        'mode': polyline['mode'],
        'vertices': polyline['vertices'],
        'plan_length': polyline['plan_length'],
        'created_at': polyline['created_at'],
        'created_by': polyline.get('created_by'),
        'updated_at': polyline['updated_at'],
    }
    elevation_block = polyline.get('elevation')
    if elevation_block:
        elevation_block = dict(elevation_block)
        elevation_block.pop('source_mtime', None)
        elevation_block['stale'] = task is not None and elevation.is_stale(task, polyline['elevation'])
        out['elevation'] = elevation_block
    return out


def get_polylines(task_id):
    """Todas las polilíneas de la tarea, mismo esquema que el `GET` REST. Lista vacía si no hay
    ninguna. No comprueba permisos: el consumidor ya resolvió el acceso a la tarea
    (`contracts/plugin-contract.md` §1.1)."""
    task = Task.objects.get(pk=task_id)
    return [serialize_polyline(p, task) for p in store.list_polylines(task_id)]


def get_polyline(task_id, polyline_id):
    """Una polilínea de la tarea, o `None` si `polyline_id` no existe en ella."""
    task = Task.objects.get(pk=task_id)
    polyline = store.get_polyline(task_id, polyline_id)
    return serialize_polyline(polyline, task) if polyline is not None else None


def get_densified(task_id, polyline_id, step=None):
    """Geometría densificada calculada al vuelo (FR-038), sin persistirla (`research.md` D5).

    Devuelve `{'step', 'model', 'sample_count', 'coordinates'}`, o `None` si `polyline_id` no
    existe en la tarea. Lanza `ValueError` sobre una polilínea plana (`'flat_polyline'`) o con
    un `step` fuera del rango admitido por el DEM (`'step_out_of_range'`, `'invalid_step'`),
    `LimitExceeded` si el `step` pedido superaría `elevation.MAX_SAMPLES`, e `IncompleteCoverage`
    si el DEM ya no cubre el trazado.
    """
    task = Task.objects.get(pk=task_id)
    polyline = store.get_polyline(task_id, polyline_id)
    if polyline is None:
        return None
    if polyline['mode'] != 'draped':
        raise ValueError('flat_polyline')

    resolved_step = step if step is not None else polyline['elevation']['step']
    coordinates = elevation.densified_coordinates_for_polyline(task, polyline, step)
    return {
        'step': resolved_step,
        'model': polyline['elevation']['model'],
        'sample_count': len(coordinates),
        'coordinates': coordinates,
    }


def _vertices_coordinates(polyline):
    vertices = polyline['vertices']
    elevation_block = polyline.get('elevation') or {}
    vertex_z = elevation_block.get('vertex_z') or []
    if len(vertex_z) == len(vertices):
        return [[v[0], v[1], z] for v, z in zip(vertices, vertex_z)]
    # `zip` se detiene en la lista más corta: un desajuste entre vértices y cotas exportaba una
    # línea recortada sin avisar. Perder las cotas es recuperable; perder vértices, no.
    return [[v[0], v[1]] for v in vertices]


def _feature(task, polyline, geometry_mode):
    elevation_block = polyline.get('elevation')

    coords = None
    if geometry_mode == 'densified' and elevation_block:
        try:
            coords = elevation.densified_coordinates_for_polyline(task, polyline)
        except (IncompleteCoverage, LimitExceeded, ValueError, OSError):
            # DEM cambió desde el muestreo: degrada a los vértices persistidos. `ValueError`
            # cubre el caso en que el reproceso cambió la resolución y el `step` guardado ya
            # no es válido para el DEM actual; la exportación no debe fallar por eso.
            coords = None
    if coords is None:
        coords = _vertices_coordinates(polyline)

    properties = {
        'id': polyline['id'],
        'name': polyline['name'],
        'mode': polyline['mode'],
        'plan_length_m': polyline['plan_length'],
    }
    if elevation_block:
        properties.update({
            'surface_length_m': elevation_block['surface_length'],
            'elevation_gain_m': elevation_block['elevation_gain'],
            'elevation_model': elevation_block['model'],
            'densify_step_m': elevation_block['step'],
            'vertical_unit': elevation_block['vertical_unit'],
            'sampled_at': elevation_block['sampled_at'],
        })

    return {
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': coords},
        'properties': properties,
    }


def export_feature_collection(task, geometry_mode='vertices'):
    """`FeatureCollection` de todas las polilíneas de la tarea (FR-032 a FR-035). Lo usa el botón
    de descarga del panel de capas del core, que exporta el grupo entero."""
    polylines = store.list_polylines(task.id)
    return {
        'type': 'FeatureCollection',
        'features': [_feature(task, p, geometry_mode) for p in polylines],
    }


def export_polyline_feature_collection(task, polyline, geometry_mode='vertices'):
    """`FeatureCollection` con una sola polilínea (FR-032). Sigue siendo una colección, y no un
    `Feature` suelto, para que el consumidor no tenga que distinguir el caso de una o varias."""
    return {
        'type': 'FeatureCollection',
        'features': [_feature(task, polyline, geometry_mode)],
    }


def export_filename(task, polyline=None):
    """Nombre del archivo descargado. Con `polyline`, `<tarea>-<polilínea>-2d|3d.geojson`: el
    sufijo hace explícito el tipo, que desde v2 queda fijado al crearla. Sin `polyline`, el
    nombre histórico de la exportación completa, que mezcla ambos tipos y por eso no lo lleva."""
    task_part = slugify(task.name) or str(task.id)
    if polyline is None:
        return '{}-polylines.geojson'.format(task_part)
    name_part = slugify(polyline['name']) or polyline['id']
    return '{}-{}-{}.geojson'.format(task_part, name_part, MODE_SUFFIX[polyline['mode']])
