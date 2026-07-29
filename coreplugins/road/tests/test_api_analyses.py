"""Ciclo de vida de un análisis por REST (`contracts/rest-api.md`).

Los tests corren con `CELERY_TASK_ALWAYS_EAGER`, así que un `POST` termina el cálculo antes de
responder. Los estados intermedios —análisis en curso, candado tomado— se montan a mano sobre el
almacén, que es la única forma de comprobarlos de manera determinista.

El eje llega de un doble de `annotations`: probar contra el plugin real acoplaría esta suite al
esquema interno de otro plugin, que es justo lo que el contrato existe para evitar.
"""

from unittest import mock

from rest_framework import status

from .. import axis, store
from .base import RoadTestBase, axis_vertices
from .test_axis import FakeAnnotations, polyline

AXIS_REF = 'a1b2'


def fake_annotations(vertices=None):
    return FakeAnnotations([polyline(AXIS_REF, 'Camino norte',
                                     vertices=vertices or axis_vertices())])


class AnalysesApiTestBase(RoadTestBase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(axis, 'get_plugin_by_name', return_value=fake_annotations())
        patcher.start()
        self.addCleanup(patcher.stop)

    def _create(self, task, **payload):
        body = {'axis': {'kind': 'annotation', 'ref': AXIS_REF}}
        body.update(payload)
        return self.client.post(self._url(task, 'analyses'), body, format='json')


class CreateAnalysisTest(AnalysesApiTestBase):
    def test_post_accepts_and_returns_the_analysis_id(self):
        task = self._task_with_dem()
        self._login()

        res = self._create(task)

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertIn('analysis_id', res.data)
        self.assertIn('estimate', res.data)

    def test_defaults_are_applied_when_params_are_omitted(self):
        task = self._task_with_dem()
        self._login()

        analysis_id = self._create(task).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)

        self.assertEqual(analysis['params']['segment_length'], 5.0)
        self.assertEqual(analysis['params']['break_threshold'], 15.0)
        self.assertEqual(analysis['model'], 'dtm')
        self.assertEqual(analysis['variant'], 'original')
        # Los umbrales de color no viven en el análisis sino en la tarea: son una preferencia de
        # lectura compartida por todos sus caminos.
        self.assertNotIn('color_thresholds', analysis)
        listed = self.client.get(self._url(task, 'analyses')).data['analyses'][0]
        self.assertEqual(listed['color_thresholds'], [8.0, 12.0])

    def test_the_analysis_keeps_its_own_copy_of_the_axis(self):
        task = self._task_with_dem()
        self._login()

        analysis_id = self._create(task).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)

        self.assertEqual(analysis['axis']['kind'], 'annotation')
        self.assertEqual(analysis['axis']['ref'], AXIS_REF)
        self.assertEqual(len(analysis['axis']['vertices']), 2)
        self.assertAlmostEqual(analysis['axis']['plan_length'], 100.0, places=3)

    def test_name_defaults_to_the_annotation_name(self):
        task = self._task_with_dem()
        self._login()

        analysis_id = self._create(task).data['analysis_id']
        self.assertEqual(store.get_analysis(str(task.id), analysis_id)['name'], 'Camino norte')

    def test_eager_run_completes_and_stores_segments(self):
        task = self._task_with_dem()
        self._login()

        analysis_id = self._create(task).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)

        self.assertEqual(analysis['status'], 'completed')
        self.assertEqual(analysis['summary']['segment_count'], 20)
        self.assertIsNotNone(store.read_segments(str(task.id), analysis_id))

    def test_unknown_axis_reference_is_rejected(self):
        task = self._task_with_dem()
        self._login()

        res = self._create(task, axis={'kind': 'annotation', 'ref': 'nope'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_axis')

    def test_task_without_elevation_model_is_rejected(self):
        task = self._task(self._project())
        self._login()

        res = self._create(task)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'no_elevation_model')

    def test_second_analysis_while_one_runs_is_refused(self):
        task = self._task_with_dem()
        self._login()
        store.acquire_running(str(task.id), 'already-running')

        res = self._create(task)

        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(res.data['code'], 'analysis_running')
        self.assertEqual(res.data['running_analysis_id'], 'already-running')

    def test_writing_requires_change_project(self):
        # 404 y no 403: `check_project_perms` del core oculta la existencia de la tarea.
        task = self._task_with_dem()
        self._grant_read_only('testuser2', task.project)
        self._login('testuser2')

        res = self._create(task)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(store.list_analyses(str(task.id)), [])


class ListAndDetailTest(AnalysesApiTestBase):
    def test_index_lists_analyses_without_their_segments(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']

        res = self.client.get(self._url(task, 'analyses'))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['analyses']), 1)
        self.assertEqual(res.data['analyses'][0]['id'], analysis_id)
        self.assertNotIn('segments', res.data['analyses'][0])
        self.assertIn('stale', res.data['analyses'][0])
        self.assertIsNone(res.data['running'])

    def test_detail_returns_the_segments(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']

        res = self.client.get(self._url(task, 'analyses/{}'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['segments']), 20)
        self.assertEqual(res.data['id'], analysis_id)

    def test_unknown_analysis_is_not_found(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.get(self._url(task, 'analyses/nope'))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['code'], 'not_found')

    def test_missing_segments_file_reports_result_missing(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']
        store.delete_segments(str(task.id), analysis_id)

        res = self.client.get(self._url(task, 'analyses/{}'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_410_GONE)
        self.assertEqual(res.data['code'], 'result_missing')

    def test_index_reports_the_running_lock(self):
        task = self._task_with_dem()
        self._login()
        store.acquire_running(str(task.id), 'running-1')

        res = self.client.get(self._url(task, 'analyses'))

        self.assertEqual(res.data['running']['analysis_id'], 'running-1')


class CancelTest(AnalysesApiTestBase):
    def _running_analysis(self, task, analysis_id='running-1'):
        store.upsert_analysis(str(task.id), {
            'id': analysis_id, 'name': 'Camino', 'status': 'running', 'progress': 0.4,
            'model': 'dtm', 'variant': 'original', 'params': {},
            'axis': {'kind': 'annotation', 'ref': AXIS_REF, 'vertices': axis_vertices(),
                     'plan_length': 100.0},
            'celery_task_id': None, 'summary': None, 'error': None,
        })
        store.acquire_running(str(task.id), analysis_id)
        return analysis_id

    def test_cancel_marks_it_canceled_and_frees_the_lock(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._running_analysis(task)

        res = self.client.post(self._url(task, 'analyses/{}/cancel'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        analysis = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(analysis['status'], 'canceled')
        self.assertIsNone(analysis['progress'])
        self.assertIsNone(store.get_running(str(task.id)))

    def test_cancel_leaves_no_partial_result(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._running_analysis(task)

        self.client.post(self._url(task, 'analyses/{}/cancel'.format(analysis_id)))

        self.assertIsNone(store.read_segments(str(task.id), analysis_id))

    def test_cancel_is_idempotent_on_a_finished_analysis(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']

        res = self.client.post(self._url(task, 'analyses/{}/cancel'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(store.get_analysis(str(task.id), analysis_id)['status'], 'completed')

    def test_sc008_cancel_returns_control_in_under_five_seconds(self):
        # SC-008. La cancelación es síncrona: aborta la tarea de Celery, limpia el estado y
        # responde. El worker consulta `should_cancel` una vez por bloque —14 veces en un análisis
        # de 1 km—, así que lo que el usuario percibe es esta respuesta, no el fin del cálculo.
        import time

        task = self._task_with_dem()
        self._login()
        analysis_id = self._running_analysis(task)

        started = time.time()
        res = self.client.post(self._url(task, 'analyses/{}/cancel'.format(analysis_id)))
        elapsed = time.time() - started

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertLess(elapsed, 5.0, 'la cancelación tardó {:.2f} s'.format(elapsed))
        self.assertEqual(store.get_analysis(str(task.id), analysis_id)['status'], 'canceled')

    def test_cancel_requires_change_project(self):
        task = self._task_with_dem()
        analysis_id = self._running_analysis(task)
        self._grant_read_only('testuser2', task.project)
        self._login('testuser2')

        res = self.client.post(self._url(task, 'analyses/{}/cancel'.format(analysis_id)))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(store.get_analysis(str(task.id), analysis_id)['status'], 'running')
