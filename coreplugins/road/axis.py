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
