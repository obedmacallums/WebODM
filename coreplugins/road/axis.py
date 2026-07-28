"""De dónde sale el eje del camino (`contracts/consumed-contracts.md` §1, `research.md` D13).

Dos vías: una polilínea 2D de `annotations` o un GeoJSON subido. Ambas terminan en el mismo
`AxisSource` de `data-model.md` §3, que es lo que hace que el resto del plugin no tenga que saber
por dónde entró el eje.

Regla que gobierna todo el módulo: **cualquier fallo hablando con `annotations` degrada a la lista
vacía**, nunca propaga. El plugin hermano puede estar ausente, deshabilitado, exponiendo un
contrato que no sabemos leer o sencillamente roto, y la vía del archivo tiene que seguir
funcionando (FR-005). Por eso se le habla siempre por `get_plugin_by_name` y jamás importando
`coreplugins.annotations`.
"""

import copy
import logging

from django.utils.translation import gettext_lazy as _

from app.plugins.functions import get_plugin_by_name

from . import geometry

logger = logging.getLogger('app.logger')

# Versión máxima del contrato de `annotations` que este plugin sabe interpretar.
ANNOTATIONS_CONTRACT_MAX = 2

KIND_ANNOTATION = 'annotation'
KIND_UPLOAD = 'upload'


class InvalidAxis(Exception):
    """Eje inválido (`400 invalid_axis`). El mensaje identifica la causa concreta (FR-003)."""
    pass


def _annotations_plugin():
    """El plugin `annotations` si está disponible y su contrato es legible; si no, `None`."""
    try:
        plugin = get_plugin_by_name('annotations')
        if plugin is None:
            return None
        version = getattr(plugin, 'contract_version', None)
        if version is None:
            return None
        if version() > ANNOTATIONS_CONTRACT_MAX:
            logger.warning(
                'road: annotations expone el contrato v%s y este plugin lee hasta v%s; '
                'se tratará como ausente', version(), ANNOTATIONS_CONTRACT_MAX)
            return None
        return plugin
    except Exception as e:
        logger.warning('road: no se pudo hablar con annotations (%s); se degrada sin ejes', e)
        return None


def annotations_available():
    return _annotations_plugin() is not None


def axes_from_annotations(task_id):
    """Polilíneas 2D de la tarea, como candidatas a eje.

    Solo las `flat`: la Z de una `draped` es del DEM que ella eligió, no del que elige este
    análisis, y ofrecerlas mezclaría métricas de dos superficies distintas.

    Se devuelve una **copia** de la geometría: el análisis sobrevive al borrado del eje que lo
    originó (FR-006), así que no puede compartir la lista con quien sí la va a editar.
    """
    plugin = _annotations_plugin()
    if plugin is None:
        return []
    try:
        polylines = plugin.get_polylines(task_id) or []
    except Exception as e:
        logger.warning('road: annotations.get_polylines falló (%s); se degrada sin ejes', e)
        return []

    axes = []
    for p in polylines:
        if p.get('mode') != 'flat':
            continue
        axes.append({
            'id': p.get('id'),
            'name': p.get('name') or '',
            'vertices': copy.deepcopy(p.get('vertices') or []),
        })
    return axes


def build_axis_source(kind, ref, vertices, crs, unit_factor=1.0):
    """Construye el `AxisSource` de `data-model.md` §3, validando la geometría.

    `plan_length` se calcula en el CRS del DEM para que la longitud del eje y las progresivas de
    los tramos vivan en el mismo sistema que el ráster que se va a muestrear.
    """
    ok, err = geometry.validate_vertices(vertices)
    if not ok:
        raise InvalidAxis(err)
    return {
        'kind': kind,
        'ref': ref,
        'vertices': copy.deepcopy([[float(v[0]), float(v[1])] for v in vertices]),
        'plan_length': geometry.plan_length(vertices, crs, unit_factor),
    }


def axis_source_from_annotation(task_id, ref, crs, unit_factor=1.0):
    """`(AxisSource, nombre)` de la polilínea `ref`, o `(None, None)` si no está disponible."""
    for candidate in axes_from_annotations(task_id):
        if candidate['id'] == ref:
            return (build_axis_source(KIND_ANNOTATION, ref, candidate['vertices'], crs,
                                      unit_factor),
                    candidate['name'])
    return None, None


def _extract_geometry(payload):
    """Localiza la geometría dentro del GeoJSON, admitiendo las tres formas de RFC 7946.

    Se acepta un `Feature`, un `FeatureCollection` de un solo elemento o una geometría suelta, que
    es lo que producen QGIS, una exportación de topografía y un `curl` a mano respectivamente. Más
    de una línea se rechaza a propósito: el análisis es de **un** eje, y elegir la primera en
    silencio dejaría al usuario mirando el resultado del camino equivocado.
    """
    kind = payload.get('type')

    if kind == 'FeatureCollection':
        features = payload.get('features') or []
        if len(features) == 0:
            raise InvalidAxis(_('El archivo no contiene ninguna entidad.'))
        if len(features) > 1:
            raise InvalidAxis(
                _('El archivo contiene %(n)s entidades y el análisis necesita una sola línea. '
                  'Deja solo el eje que quieres analizar.') % {'n': len(features)})
        return _extract_geometry(features[0])

    if kind == 'Feature':
        geometry = payload.get('geometry')
        if not isinstance(geometry, dict):
            raise InvalidAxis(_('La entidad del archivo no tiene geometría.'))
        return geometry

    if isinstance(kind, str):
        return payload

    raise InvalidAxis(_('El archivo no parece un GeoJSON: falta el miembro "type".'))


def axis_from_geojson(content, filename, task, model):
    """`AxisSource` a partir de un GeoJSON subido, validado en cascada (`research.md` D13).

    Cada paso falla con **su** mensaje. FR-003 exige identificar la causa concreta, y un "archivo
    inválido" genérico deja al usuario probando variantes a ciegas: no es lo mismo haber exportado
    un polígono que haber trazado la línea fuera de la zona del vuelo.

    Devuelve `(vertices, aviso)`: `aviso` es `None` salvo que se haya descartado la Z.
    """
    import json

    if isinstance(content, bytes):
        try:
            content = content.decode('utf-8')
        except UnicodeDecodeError:
            raise InvalidAxis(_('El archivo no está en UTF-8.'))

    try:
        payload = json.loads(content)
    except ValueError as e:
        raise InvalidAxis(_('El archivo no es JSON válido: %(err)s') % {'err': e})
    if not isinstance(payload, dict):
        raise InvalidAxis(_('El archivo no es un objeto GeoJSON.'))

    # RFC 7946 fija CRS84 y elimina el miembro `crs`; si viene y declara otra cosa, las
    # coordenadas no significan lo que este plugin asume y el resultado saldría desplazado.
    crs_member = payload.get('crs')
    if crs_member:
        name = str(((crs_member or {}).get('properties') or {}).get('name', ''))
        if not any(token in name.upper() for token in ('CRS84', '4326')):
            raise InvalidAxis(
                _('El archivo declara el CRS "%(crs)s". Solo se admite EPSG:4326 (CRS84), '
                  'que es lo que fija GeoJSON.') % {'crs': name or crs_member})

    # `geom` y no `geometry`: este módulo importa `geometry` y una local con ese nombre lo taparía
    # justo antes de llamar a `geometry.validate_vertices`.
    geom = _extract_geometry(payload)
    geom_type = geom.get('type')
    if geom_type != 'LineString':
        raise InvalidAxis(
            _('La geometría es de tipo %(got)s y el eje debe ser un LineString.') % {
                'got': geom_type or _('desconocido')})

    coordinates = geom.get('coordinates')
    if not isinstance(coordinates, list):
        raise InvalidAxis(_('La línea no tiene coordenadas.'))

    warning = None
    vertices = []
    for position in coordinates:
        if not isinstance(position, (list, tuple)) or len(position) < 2:
            raise InvalidAxis(_('Cada posición de la línea debe tener al menos longitud y latitud.'))
        if len(position) > 2 and warning is None:
            # La Z de la línea es del modelo que la produjo, no del que elige este análisis: se
            # descarta, pero se dice, porque el usuario que la incluyó esperaba que contara.
            warning = _('Se descartó la tercera coordenada: las cotas salen del modelo de '
                        'elevación elegido, no del archivo.')
        vertices.append([position[0], position[1]])

    ok, err = geometry.validate_vertices(vertices)
    if not ok:
        raise InvalidAxis(err)

    _check_within_extent(vertices, task, model)
    return vertices, warning


def _check_within_extent(vertices, task, model):
    """La línea tiene que tocar la extensión del modelo elegido.

    Se comprueba contra la columna de la base de datos y no abriendo el ráster: rechazar un archivo
    no debería costar una lectura de disco, y la extensión ya está indexada.
    """
    from django.contrib.gis.geos import LineString as GEOSLineString

    extent = task.dsm_extent if model == 'dsm' else task.dtm_extent
    if extent is None:
        return
    line = GEOSLineString([(float(v[0]), float(v[1])) for v in vertices], srid=4326)
    if not line.intersects(extent):
        raise InvalidAxis(
            _('La línea queda fuera de la zona cubierta por el %(model)s de esta tarea.') % {
                'model': model.upper()})


def describe_axes(task_id, crs, unit_factor=1.0):
    """Ejes disponibles tal como los lista `capabilities`: sin geometría, con su longitud.

    Un eje cuya geometría no valide se omite en vez de romper la respuesta: el panel debe poder
    dibujarse aunque una anotación concreta esté corrupta.
    """
    described = []
    for candidate in axes_from_annotations(task_id):
        try:
            length = geometry.plan_length(candidate['vertices'], crs, unit_factor)
        except Exception:
            continue
        described.append({
            'id': candidate['id'],
            'name': candidate['name'],
            'vertices': len(candidate['vertices']),
            'plan_length': length,
        })
    return described
