"""Ciclo de vida del análisis: umbrales, recálculo que pisa y borrado
(`contracts/rest-api.md`, FR-030, FR-037).

Lo que separa un umbral de color de un parámetro de cálculo es que el primero **no invalida el
resultado**. Aquí se comprueba literalmente: tras mover los umbrales, los tramos son bit a bit los
mismos y el `updated_at` del cálculo no se mueve. Si esa frontera se borrara, cada movimiento de un
deslizador dispararía un recálculo de minutos.
"""

from unittest import mock

from rest_framework import status

from .. import axis, sources, store
from .base import axis_vertices
from .test_api_analyses import AXIS_REF, AnalysesApiTestBase
from .test_axis import FakeAnnotations, polyline

SECOND_REF = 'c3d4'


class PreFeatureDocumentTest(AnalysesApiTestBase):
    """Un análisis guardado antes de `006-street-width` se lee sin migración (FR-024)."""

    OLD_DOC = {
        'version': store.SCHEMA_VERSION,
        'analysis_id': 'old-1',
        'segments': [
            {'index': 0, 'status': 'measured', 'offset_left': 4.0, 'offset_right': 4.0,
             'width': 8.0, 'left_reason': None, 'right_reason': None},
            {'index': 1, 'status': 'no_edge', 'offset_left': 4.0, 'offset_right': None,
             'width': None, 'left_reason': None, 'right_reason': 'no_break'},
        ],
    }

    def test_missing_edge_sources_are_completed_as_measured_on_read(self):
        task_id = 'compat-task'
        store.write_segments(task_id, 'old-1', self.OLD_DOC)
        self.addCleanup(store.delete_task_segments, task_id)

        document = store.read_segments(task_id, 'old-1')
        first, second = document['segments']

        self.assertEqual(first['left_edge_source'], 'measured')
        self.assertEqual(first['right_edge_source'], 'measured')
        self.assertEqual(second['left_edge_source'], 'measured')   # el lado que sí tiene borde
        self.assertIsNone(second['right_edge_source'])             # el que no, sin origen

    def test_the_completion_happens_in_memory_not_on_disk(self):
        # Sin migración de verdad: el archivo queda byte a byte como se escribió.
        task_id = 'compat-task-2'
        store.write_segments(task_id, 'old-1', self.OLD_DOC)
        self.addCleanup(store.delete_task_segments, task_id)
        with open(store.segments_path(task_id, 'old-1')) as f:
            before = f.read()

        store.read_segments(task_id, 'old-1')

        with open(store.segments_path(task_id, 'old-1')) as f:
            self.assertEqual(f.read(), before)
        self.assertNotIn('edge_source', before)

    def test_a_document_with_sources_is_left_untouched(self):
        # Uno nuevo, con `inferred`, no debe "corregirse" a measured al releerlo.
        task_id = 'compat-task-3'
        doc = {'version': store.SCHEMA_VERSION, 'analysis_id': 'new-1', 'segments': [
            {'index': 0, 'status': 'inferred', 'offset_left': 4.0, 'offset_right': 5.8,
             'width': 9.8, 'left_edge_source': 'measured', 'right_edge_source': 'inferred',
             'left_reason': None, 'right_reason': 'no_break'},
        ]}
        store.write_segments(task_id, 'new-1', doc)
        self.addCleanup(store.delete_task_segments, task_id)

        segment = store.read_segments(task_id, 'new-1')['segments'][0]

        self.assertEqual(segment['right_edge_source'], 'inferred')


class PatchTest(AnalysesApiTestBase):
    def _analysis(self, task):
        return self._create(task).data['analysis_id']

    def _create_second(self, task):
        """Un segundo camino en la misma tarea: otro eje, otro análisis."""
        two = FakeAnnotations([
            polyline(AXIS_REF, 'Camino norte', vertices=axis_vertices()),
            polyline(SECOND_REF, 'Camino sur',
                     vertices=axis_vertices(row_start=60, row_end=400)),
        ])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=two):
            return self.client.post(
                self._url(task, 'analyses'),
                {'axis': {'kind': 'annotation', 'ref': SECOND_REF}},
                format='json').data['analysis_id']

    def _two_analyses(self, task):
        """Dos caminos distintos de la misma tarea, sobre dos tramos del eje sintético."""
        return self._analysis(task), self._create_second(task)

    def test_changing_thresholds_touches_neither_segments_nor_updated_at(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        before = store.get_analysis(str(task.id), analysis_id)
        segments_before = store.read_segments(str(task.id), analysis_id)

        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'color_thresholds': [6.0, 10.0]}, format='json')

        after = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(store.get_thresholds(store.get_document(str(task.id)))['color'],
                         [6.0, 10.0])
        self.assertEqual(after['updated_at'], before['updated_at'])
        self.assertEqual(after['summary'], before['summary'])
        self.assertEqual(store.read_segments(str(task.id), analysis_id), segments_before)

    def test_thresholds_survive_a_reload(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)
        self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                          {'color_thresholds': [6.0, 10.0]}, format='json')

        listed = self.client.get(self._url(task, 'analyses')).data['analyses'][0]
        self.assertEqual(listed['color_thresholds'], [6.0, 10.0])

    def test_width_thresholds_arrive_derived_and_can_be_overridden(self):
        """Sin fijar, los umbrales de ancho llegan deducidos del ancho medio del propio análisis;
        en cuanto el usuario los mueve, mandan los suyos y dejan de deducirse."""
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        listed = self.client.get(self._url(task, 'analyses')).data['analyses'][0]
        mean = listed['summary']['mean_width']
        self.assertEqual(listed['width_thresholds'], sources.derive_width_thresholds(mean))
        # En el almacén no se sella nada: así un recálculo con otro ancho vuelve a deducirlos.
        self.assertIsNone(store.get_analysis(str(task.id), analysis_id).get('width_thresholds'))

        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'width_thresholds': [3.0, 4.5]}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['width_thresholds'], [3.0, 4.5])
        listed = self.client.get(self._url(task, 'analyses')).data['analyses'][0]
        self.assertEqual(listed['width_thresholds'], [3.0, 4.5])

    def test_colour_thresholds_are_shared_by_every_analysis_of_the_task(self):
        """El semáforo es una preferencia de lectura del usuario, no una propiedad de un camino:
        moverlo en un análisis lo mueve en todos los de la tarea."""
        task = self._task_with_dem()
        self._login()
        first, second = self._two_analyses(task)

        res = self.client.patch(self._url(task, 'analyses/{}'.format(first)),
                                {'color_thresholds': [4.0, 9.0]}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        listed = self.client.get(self._url(task, 'analyses')).data['analyses']
        self.assertEqual(len(listed), 2)
        for analysis in listed:
            self.assertEqual(analysis['color_thresholds'], [4.0, 9.0])
        # Y también al pedir el otro por separado, no solo en el índice.
        detail = self.client.get(self._url(task, 'analyses/{}'.format(second))).data
        self.assertEqual(detail['color_thresholds'], [4.0, 9.0])

    def test_width_thresholds_are_shared_and_derived_from_the_whole_task(self):
        task = self._task_with_dem()
        self._login()
        first, second = self._two_analyses(task)

        listed = self.client.get(self._url(task, 'analyses')).data['analyses']
        derived = [a['width_thresholds'] for a in listed]
        self.assertEqual(derived[0], derived[1], 'un solo par para toda la tarea')
        self.assertIsNotNone(derived[0])

        self.client.patch(self._url(task, 'analyses/{}'.format(second)),
                          {'width_thresholds': [3.0, 4.5]}, format='json')

        listed = self.client.get(self._url(task, 'analyses')).data['analyses']
        for analysis in listed:
            self.assertEqual(analysis['width_thresholds'], [3.0, 4.5])

    def test_a_new_analysis_inherits_the_thresholds_already_in_use(self):
        # Calcular un camino más no puede devolver el semáforo a los valores de fábrica.
        task = self._task_with_dem()
        self._login()
        first = self._analysis(task)
        self.client.patch(self._url(task, 'analyses/{}'.format(first)),
                          {'color_thresholds': [4.0, 9.0]}, format='json')

        second = self._create_second(task)

        detail = self.client.get(self._url(task, 'analyses/{}'.format(second))).data
        self.assertEqual(detail['color_thresholds'], [4.0, 9.0])

    def test_invalid_width_thresholds_are_rejected(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'width_thresholds': [8.0, 5.0]}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_parameter')

    def test_renaming_is_allowed(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'name': 'Camino norte km 0-1'}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(store.get_analysis(str(task.id), analysis_id)['name'],
                         'Camino norte km 0-1')

    def test_invalid_thresholds_are_rejected(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'color_thresholds': [12.0, 8.0]}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_parameter')

    def test_any_other_field_is_refused(self):
        # Cambiar `params` por PATCH dejaría un análisis cuyos parámetros no describen sus tramos.
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        for payload in ({'params': {'segment_length': 10.0}}, {'status': 'completed'},
                        {'model': 'dsm'}, {'summary': {}}):
            with self.subTest(payload=payload):
                res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                        payload, format='json')
                self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(res.data['code'], 'invalid_parameter')

    def test_patch_requires_change_project(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._analysis(task)

        self.client.logout()
        self._grant_read_only('testuser2', task.project)
        self._login('testuser2')
        res = self.client.patch(self._url(task, 'analyses/{}'.format(analysis_id)),
                                {'name': 'otro'}, format='json')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)


class RecalculateTest(AnalysesApiTestBase):
    def test_relaunching_the_same_axis_needs_confirmation(self):
        task = self._task_with_dem()
        self._login()
        self._create(task)

        res = self._create(task, params={'break_threshold': 25.0})

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], 'confirmation_required')
        self.assertEqual(res.data['reason'], 'replaces_existing')
        self.assertEqual(len(store.list_analyses(str(task.id))), 1)

    def test_confirmed_relaunch_replaces_keeping_id_and_name(self):
        task = self._task_with_dem()
        self._login()
        first = self._create(task).data['analysis_id']
        self.client.patch(self._url(task, 'analyses/{}'.format(first)),
                          {'name': 'Camino bautizado'}, format='json')

        second = self._create(task, params={'segment_length': 10.0},
                              confirm=True).data['analysis_id']

        analyses = store.list_analyses(str(task.id))
        self.assertEqual(len(analyses), 1, 'recalcular pisa, no acumula')
        self.assertEqual(second, first, 'conserva el id')
        self.assertEqual(analyses[0]['name'], 'Camino bautizado', 'conserva el nombre')
        self.assertEqual(analyses[0]['params']['segment_length'], 10.0)
        self.assertEqual(analyses[0]['summary']['segment_count'], 10)

    def test_replacement_discards_the_previous_segments_file(self):
        task = self._task_with_dem()
        self._login()
        first = self._create(task).data['analysis_id']
        self.assertEqual(len(store.read_segments(str(task.id), first)['segments']), 20)

        self._create(task, params={'segment_length': 10.0}, confirm=True)

        self.assertEqual(len(store.read_segments(str(task.id), first)['segments']), 10)

    def test_a_different_axis_creates_a_second_analysis(self):
        task = self._task_with_dem()
        self._login()
        self._create(task)

        from unittest import mock
        from .. import axis
        from .test_axis import FakeAnnotations, polyline
        other = FakeAnnotations([polyline('otro-eje', 'Camino sur', vertices=axis_vertices())])
        with mock.patch.object(axis, 'get_plugin_by_name', return_value=other):
            res = self._create(task, axis={'kind': 'annotation', 'ref': 'otro-eje'})

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(len(store.list_analyses(str(task.id))), 2)


class DeleteTest(AnalysesApiTestBase):
    def test_delete_removes_index_entry_and_segments_file(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']

        res = self.client.delete(self._url(task, 'analyses/{}'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNone(store.get_analysis(str(task.id), analysis_id))
        self.assertIsNone(store.read_segments(str(task.id), analysis_id))

    def test_deleting_a_running_analysis_cancels_it_first(self):
        task = self._task_with_dem()
        self._login()
        store.upsert_analysis(str(task.id), {
            'id': 'running-1', 'name': 'Camino', 'status': 'running', 'progress': 0.4,
            'model': 'dtm', 'variant': 'original', 'params': {}, 'celery_task_id': None,
            'axis': {'kind': 'annotation', 'ref': AXIS_REF, 'vertices': axis_vertices(),
                     'plan_length': 100.0},
        })
        store.acquire_running(str(task.id), 'running-1')

        res = self.client.delete(self._url(task, 'analyses/running-1'))

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIsNone(store.get_analysis(str(task.id), 'running-1'))
        self.assertIsNone(store.get_running(str(task.id)),
                          'el candado debe quedar libre o la tarea se inutiliza')

    def test_deleting_something_that_is_not_there(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.delete(self._url(task, 'analyses/nope'))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_requires_change_project(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']

        self.client.logout()
        self._grant_read_only('testuser2', task.project)
        self._login('testuser2')
        res = self.client.delete(self._url(task, 'analyses/{}'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIsNotNone(store.get_analysis(str(task.id), analysis_id))
