"""Eje subido como GeoJSON (`research.md` D13, FR-003).

Lo que se prueba aquí no es que un archivo válido funcione —eso es media prueba— sino que **cada
archivo inválido lo sea por un motivo distinto y lo diga**. Un "archivo inválido" genérico deja al
usuario probando variantes a ciegas: no es lo mismo haber exportado un polígono que haber trazado
la línea fuera de la zona del vuelo, y la corrección es distinta en cada caso.
"""

import json
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status

from .. import axis, store
from .base import RoadTestBase, axis_vertices


def geojson_file(payload, name='eje.geojson'):
    content = json.dumps(payload).encode('utf-8')
    return SimpleUploadedFile(name, content, content_type='application/geo+json')


def linestring(vertices=None):
    return {'type': 'Feature', 'properties': {},
            'geometry': {'type': 'LineString',
                         'coordinates': vertices or axis_vertices()}}


class UploadTestBase(RoadTestBase):
    def _post(self, task, payload, name='eje.geojson', **extra):
        data = {'file': geojson_file(payload, name)}
        data.update(extra)
        return self.client.post(self._url(task, 'analyses'), data, format='multipart')

    def _reject(self, task, payload, name='eje.geojson'):
        res = self._post(task, payload, name)
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST,
                         'se esperaba rechazo, llegó {}'.format(res.status_code))
        self.assertEqual(res.data['code'], 'invalid_axis')
        return res.data['error']


class UploadHappyPathTest(UploadTestBase):
    def test_a_valid_linestring_produces_an_analysis(self):
        task = self._task_with_dem()
        self._login()

        res = self._post(task, linestring())

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        analysis = store.get_analysis(str(task.id), res.data['analysis_id'])
        self.assertEqual(analysis['status'], 'completed')
        self.assertEqual(analysis['summary']['segment_count'], 20)

    def test_the_axis_is_recorded_as_an_upload_named_after_the_file(self):
        task = self._task_with_dem()
        self._login()

        res = self._post(task, linestring(), name='camino-norte.geojson')
        analysis = store.get_analysis(str(task.id), res.data['analysis_id'])

        self.assertEqual(analysis['axis']['kind'], 'upload')
        self.assertEqual(analysis['axis']['ref'], 'camino-norte.geojson')
        self.assertEqual(analysis['name'], 'camino-norte.geojson')

    def test_the_three_geojson_shapes_are_accepted(self):
        # Un `Feature`, un `FeatureCollection` de uno y una geometría suelta: es lo que producen
        # QGIS, una exportación de topografía y un `curl` a mano.
        task = self._task_with_dem()
        self._login()
        vertices = axis_vertices()

        shapes = [
            linestring(vertices),
            {'type': 'FeatureCollection', 'features': [linestring(vertices)]},
            {'type': 'LineString', 'coordinates': vertices},
        ]
        for i, shape in enumerate(shapes):
            with self.subTest(shape=shape['type']):
                res = self._post(task, shape, name='eje-{}.geojson'.format(i))
                self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

    def test_a_third_coordinate_is_dropped_with_a_warning(self):
        task = self._task_with_dem()
        self._login()
        vertices = [v + [123.4] for v in axis_vertices()]

        res = self._post(task, linestring(vertices))
        analysis = store.get_analysis(str(task.id), res.data['analysis_id'])

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(analysis['axis']['vertices'][0]), 2)
        self.assertIn('tercera coordenada', analysis['axis']['warning'])

    def test_upload_works_without_the_annotations_plugin(self):
        # FR-005: la vía del archivo es independiente del plugin hermano.
        task = self._task_with_dem()
        self._login()

        with mock.patch.object(axis, 'get_plugin_by_name', return_value=None):
            res = self._post(task, linestring())

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

    def test_estimate_also_accepts_a_file(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.post(self._url(task, 'analyses/estimate'),
                               {'file': geojson_file(linestring())}, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['segments'], 20)


class UploadRejectionTest(UploadTestBase):
    def test_every_rejection_has_its_own_message(self):
        task = self._task_with_dem()
        self._login()
        vertices = axis_vertices()

        messages = {}
        cases = {
            'polygon': {'type': 'Feature', 'properties': {}, 'geometry': {
                'type': 'Polygon', 'coordinates': [vertices + [vertices[0]]]}},
            'two_lines': {'type': 'FeatureCollection',
                          'features': [linestring(vertices), linestring(vertices)]},
            'single_vertex': linestring([vertices[0], list(vertices[0])]),
            'foreign_crs': dict(linestring(vertices),
                                crs={'type': 'name', 'properties': {'name': 'EPSG:32615'}}),
            'outside_extent': linestring([[0.0, 0.0], [0.001, 0.0]]),
        }

        for label, payload in cases.items():
            with self.subTest(case=label):
                messages[label] = self._reject(task, payload)

        self.assertEqual(len(set(messages.values())), len(cases),
                         'hay mensajes repetidos: {}'.format(messages))

    def test_each_message_names_its_cause(self):
        task = self._task_with_dem()
        self._login()
        vertices = axis_vertices()

        self.assertIn('Polygon', self._reject(task, {
            'type': 'Feature', 'properties': {},
            'geometry': {'type': 'Polygon', 'coordinates': [vertices + [vertices[0]]]}}))

        self.assertIn('2', self._reject(task, {
            'type': 'FeatureCollection',
            'features': [linestring(vertices), linestring(vertices)]}))

        self.assertIn('EPSG:32615', self._reject(task, dict(
            linestring(vertices), crs={'type': 'name', 'properties': {'name': 'EPSG:32615'}})))

        self.assertIn('DTM', self._reject(task, linestring([[0.0, 0.0], [0.001, 0.0]])))

    def test_crs84_is_accepted_because_rfc_7946_fixes_it(self):
        task = self._task_with_dem()
        self._login()
        payload = dict(linestring(), crs={
            'type': 'name', 'properties': {'name': 'urn:ogc:def:crs:OGC:1.3:CRS84'}})

        res = self._post(task, payload)

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)

    def test_malformed_json_is_rejected_as_such(self):
        task = self._task_with_dem()
        self._login()
        broken = SimpleUploadedFile('eje.geojson', b'{"type": "Feature",',
                                    content_type='application/geo+json')

        res = self.client.post(self._url(task, 'analyses'), {'file': broken}, format='multipart')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_axis')
        self.assertIn('JSON', res.data['error'])

    def test_an_empty_collection_is_rejected(self):
        task = self._task_with_dem()
        self._login()
        self._reject(task, {'type': 'FeatureCollection', 'features': []})

    def test_a_file_over_the_limit_is_refused(self):
        task = self._task_with_dem()
        self._login()
        oversized = SimpleUploadedFile(
            'grande.geojson', b'x' * 100, content_type='application/geo+json')

        from .. import sources
        original = sources.MAX_UPLOAD_BYTES
        sources.MAX_UPLOAD_BYTES = 10
        try:
            res = self.client.post(self._url(task, 'analyses'), {'file': oversized},
                                   format='multipart')
        finally:
            sources.MAX_UPLOAD_BYTES = original

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_axis')

    def test_a_rejected_upload_starts_nothing(self):
        task = self._task_with_dem()
        self._login()
        self._reject(task, linestring([[0.0, 0.0], [0.001, 0.0]]))

        self.assertEqual(store.list_analyses(str(task.id)), [])
        self.assertIsNone(store.get_running(str(task.id)))

    def test_upload_requires_change_project(self):
        task = self._task_with_dem()
        self._grant_read_only('testuser2', task.project)
        self._login('testuser2')

        res = self._post(task, linestring())

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
