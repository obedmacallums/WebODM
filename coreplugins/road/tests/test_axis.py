"""Obtención del eje desde `annotations` y degradación sin él
(`contracts/consumed-contracts.md` §1).

Lo que se prueba aquí no es tanto que el camino feliz funcione como que **ninguna forma de fallo
del plugin hermano tumbe a este**: ausente, deshabilitado, con un contrato que no sabemos leer o
reventando por dentro, el resultado debe ser la lista vacía y la vía del archivo intacta (FR-005).
"""

from unittest import mock

from django.test import SimpleTestCase
from rasterio.crs import CRS

from .. import axis
from .base import DEM_EPSG, axis_vertices

UTM = CRS.from_epsg(DEM_EPSG)


class FakeAnnotations:
    """Doble del plugin `annotations` con la superficie exacta de su contrato público."""

    def __init__(self, polylines, version=2):
        self._polylines = polylines
        self._version = version

    def contract_version(self):
        return self._version

    def get_polylines(self, task_id):
        return self._polylines


def polyline(pid, name, mode='flat', vertices=None):
    return {'id': pid, 'name': name, 'mode': mode,
            'vertices': vertices or [[-93.87, 45.0], [-93.86, 45.01]]}


class AxesFromAnnotationsTest(SimpleTestCase):
    def test_lists_only_flat_polylines(self):
        # Las `draped` no se ofrecen: su Z es del DEM que ellas eligieron, no del que elige este
        # análisis, y mezclarlos daría métricas de dos superficies distintas.
        plugin = FakeAnnotations([polyline('a', 'Camino norte'),
                                  polyline('b', 'Perfil 3D', mode='draped'),
                                  polyline('c', 'Camino sur')])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            axes = axis.axes_from_annotations('task-1')

        self.assertEqual([a['id'] for a in axes], ['a', 'c'])

    def test_returns_its_own_copy_of_the_geometry(self):
        # El análisis sobrevive al borrado del eje que lo originó (FR-006): si compartiera la
        # lista, una edición posterior de la anotación cambiaría un resultado ya calculado.
        original = polyline('a', 'Camino')
        plugin = FakeAnnotations([original])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            axes = axis.axes_from_annotations('task-1')

        axes[0]['vertices'][0][0] = 999.0
        self.assertNotEqual(original['vertices'][0][0], 999.0)

    def test_missing_plugin_degrades_to_an_empty_list(self):
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=None):
            self.assertEqual(axis.axes_from_annotations('task-1'), [])
            self.assertFalse(axis.annotations_available())

    def test_newer_contract_is_treated_as_absent(self):
        plugin = FakeAnnotations([polyline('a', 'Camino')], version=3)
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            self.assertEqual(axis.axes_from_annotations('task-1'), [])

    def test_older_contract_is_still_readable(self):
        plugin = FakeAnnotations([polyline('a', 'Camino')], version=1)
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            self.assertEqual(len(axis.axes_from_annotations('task-1')), 1)

    def test_plugin_raising_does_not_propagate(self):
        broken = mock.Mock()
        broken.contract_version.side_effect = RuntimeError('boom')
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=broken):
            self.assertEqual(axis.axes_from_annotations('task-1'), [])

    def test_plugin_without_the_contract_is_treated_as_absent(self):
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=object()):
            self.assertEqual(axis.axes_from_annotations('task-1'), [])


class AxisSourceTest(SimpleTestCase):
    def test_build_records_identity_geometry_and_plan_length(self):
        vertices = axis_vertices(row_start=40, row_end=440, vertices=2)
        source = axis.build_axis_source('annotation', 'a1b2', vertices, UTM)

        self.assertEqual(source['kind'], 'annotation')
        self.assertEqual(source['ref'], 'a1b2')
        self.assertEqual(len(source['vertices']), 2)
        self.assertAlmostEqual(source['plan_length'], 100.0, places=3)

    def test_build_copies_the_vertices(self):
        vertices = axis_vertices(vertices=2)
        source = axis.build_axis_source('annotation', 'a1b2', vertices, UTM)
        source['vertices'][0][0] = 999.0

        self.assertNotEqual(vertices[0][0], 999.0)

    def test_invalid_geometry_is_rejected(self):
        with self.assertRaises(axis.InvalidAxis):
            axis.build_axis_source('annotation', 'a1b2', [[0.0, 0.0]], UTM)

    def test_axis_source_from_annotation_finds_it_by_reference(self):
        vertices = axis_vertices(vertices=2)
        plugin = FakeAnnotations([polyline('a1b2', 'Camino norte', vertices=vertices)])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            source, name = axis.axis_source_from_annotation('task-1', 'a1b2', UTM)

        self.assertEqual(name, 'Camino norte')
        self.assertAlmostEqual(source['plan_length'], 100.0, places=3)

    def test_axis_source_from_annotation_returns_none_when_missing(self):
        plugin = FakeAnnotations([polyline('other', 'Otro')])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=plugin):
            self.assertEqual(axis.axis_source_from_annotation('task-1', 'a1b2', UTM), (None, None))
