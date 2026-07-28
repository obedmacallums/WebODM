"""Ciclo de vida del análisis: umbrales, recálculo que pisa y borrado
(`contracts/rest-api.md`, FR-030, FR-037).

Lo que separa un umbral de color de un parámetro de cálculo es que el primero **no invalida el
resultado**. Aquí se comprueba literalmente: tras mover los umbrales, los tramos son bit a bit los
mismos y el `updated_at` del cálculo no se mueve. Si esa frontera se borrara, cada movimiento de un
deslizador dispararía un recálculo de minutos.
"""

from rest_framework import status

from .. import store
from .base import axis_vertices
from .test_api_analyses import AXIS_REF, AnalysesApiTestBase


class PatchTest(AnalysesApiTestBase):
    def _analysis(self, task):
        return self._create(task).data['analysis_id']

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
        self.assertEqual(after['color_thresholds'], [6.0, 10.0])
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
