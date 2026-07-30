"""Persistencia de la máscara y su borrado en cascada (`008` Phase 2, FR-004/FR-005/FR-006).

El borrado es la parte que más fácil se rompe: hay **cinco** caminos que borran el documento de
tramos, y los dos del worker (cancelación y fallo) son los que se olvidan. Un `.mask.json` que
sobrevive a su análisis es exactamente el fichero huérfano que FR-005 prohíbe.
"""

import json
import os

from unittest import mock

from rest_framework import status

from .base import RoadTestBase
from .test_api_analyses import AnalysesApiTestBase

from coreplugins.road import store


MASK_PAYLOAD = {
    'version': 1,
    'analysis_id': 'a-1',
    'generated_at': '2026-07-29T00:00:00Z',
    'resolution_m': 0.2,
    'simplify_tolerance_m': 0.2,
    'features': [{
        'type': 'Feature',
        'properties': {'class': 'road'},
        'geometry': {'type': 'Polygon',
                     'coordinates': [[[-93.0, 45.0], [-92.9, 45.0], [-92.9, 45.1], [-93.0, 45.0]]]},
    }],
}


class MaskStoreTest(RoadTestBase):
    """Ida y vuelta, y qué pasa cuando el fichero no está o está roto."""

    TASK_ID = '11111111-2222-3333-4444-555555555555'

    def tearDown(self):
        store.delete_mask(self.TASK_ID, 'a-1')
        super().tearDown()

    def test_round_trip(self):
        store.write_mask(self.TASK_ID, 'a-1', MASK_PAYLOAD)
        self.assertEqual(store.read_mask(self.TASK_ID, 'a-1'), MASK_PAYLOAD)

    def test_lives_next_to_the_segments_document(self):
        """Mismo directorio del framework que los tramos (`FR-004`, constitución).

        La constitución prohíbe rutas ad-hoc del contenedor. Antes de `008` la máscara solo existía
        en un temporal de `MEDIA_TMP` que nadie limpiaba ni servía.
        """
        store.write_mask(self.TASK_ID, 'a-1', MASK_PAYLOAD)
        mask = store.mask_path(self.TASK_ID, 'a-1')
        segments = store.segments_path(self.TASK_ID, 'a-1')
        self.assertEqual(os.path.dirname(mask), os.path.dirname(segments))
        self.assertTrue(os.path.exists(mask))

    def test_missing_file_reads_as_none(self):
        """Ausencia de máscara: un estado esperado, no una anomalía (`FR-017`, caso c)."""
        self.assertIsNone(store.read_mask(self.TASK_ID, 'no-existe'))

    def test_truncated_file_reads_as_none(self):
        """Un JSON truncado no debe confundirse con un resultado válido."""
        store.write_mask(self.TASK_ID, 'a-1', MASK_PAYLOAD)
        with open(store.mask_path(self.TASK_ID, 'a-1'), 'w') as f:
            f.write('{"features": [')
        self.assertIsNone(store.read_mask(self.TASK_ID, 'a-1'))

    def test_write_is_atomic(self):
        """No debe quedar el `.tmp` por medio (mismo patrón que `write_segments`)."""
        store.write_mask(self.TASK_ID, 'a-1', MASK_PAYLOAD)
        self.assertFalse(os.path.exists(store.mask_path(self.TASK_ID, 'a-1') + '.tmp'))

    def test_delete_removes_file_and_tolerates_absence(self):
        store.write_mask(self.TASK_ID, 'a-1', MASK_PAYLOAD)
        store.delete_mask(self.TASK_ID, 'a-1')
        self.assertFalse(os.path.exists(store.mask_path(self.TASK_ID, 'a-1')))
        store.delete_mask(self.TASK_ID, 'a-1')   # idempotente, no debe reventar

    def test_empty_features_survive_the_round_trip(self):
        """Máscara vacía = el modelo no vio calzada. Es un resultado y debe persistirse como tal,
        distinguible de «no hay fichero» (`FR-017`)."""
        payload = dict(MASK_PAYLOAD, features=[])
        store.write_mask(self.TASK_ID, 'a-1', payload)
        read = store.read_mask(self.TASK_ID, 'a-1')
        self.assertIsNotNone(read)
        self.assertEqual(read['features'], [])


class MaskCascadeDeleteTest(AnalysesApiTestBase):
    """Los cinco caminos que borran tramos deben borrar también la máscara (`FR-005`).

    Tres viven en la capa de API y dos en el worker. Los del worker —cancelación y fallo— son los
    que se olvidan, porque solo se recorren cuando algo va mal.
    """

    def _seed_mask(self, task, analysis_id):
        store.write_mask(str(task.id), analysis_id, MASK_PAYLOAD)
        self.assertTrue(os.path.exists(store.mask_path(str(task.id), analysis_id)))

    def _assert_gone(self, task, analysis_id):
        self.assertFalse(os.path.exists(store.mask_path(str(task.id), analysis_id)),
                         'quedó un .mask.json huérfano')

    def test_delete_endpoint_removes_the_mask(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']
        self._seed_mask(task, analysis_id)

        self.client.delete(self._url(task, 'analyses/{}'.format(analysis_id)))

        self._assert_gone(task, analysis_id)

    def test_replacing_an_analysis_removes_the_previous_mask(self):
        """Al recalcular sobre el mismo eje, la máscara vieja no debe sobrevivir."""
        task = self._task_with_dem()
        self._login()
        first = self._create(task).data['analysis_id']
        self._seed_mask(task, first)

        res = self._create(task, confirm=True)

        # El reemplazo **reutiliza el mismo id** (`api.py`: `existing['id']`), así que la máscara
        # que se borra es la de este mismo análisis. Si el POST no se aceptase, el test no estaría
        # probando el camino de reemplazo y sería un falso verde.
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED, res.data)
        self.assertEqual(res.data['analysis_id'], first)
        self._assert_gone(task, first)

    def test_worker_cancel_path_removes_the_mask(self):
        """Camino de cancelación en el worker: uno de los dos que se olvidan."""
        from coreplugins.road import compute

        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)
        self._seed_mask(task, analysis_id)

        with mock.patch.object(compute, 'analyze', side_effect=compute.Canceled):
            compute.run_analysis(str(task.id), analysis_id, self._dem_path(task),
                                 analysis['axis']['vertices'], dict(analysis['params']))

        self._assert_gone(task, analysis_id)

    def test_worker_failure_path_removes_the_mask(self):
        """Camino de fallo en el worker: el otro que se olvida."""
        from coreplugins.road import compute

        task = self._task_with_dem()
        self._login()
        analysis_id = self._create(task).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)
        self._seed_mask(task, analysis_id)

        with mock.patch.object(compute, 'analyze', side_effect=RuntimeError('boom')):
            compute.run_analysis(str(task.id), analysis_id, self._dem_path(task),
                                 analysis['axis']['vertices'], dict(analysis['params']))

        self._assert_gone(task, analysis_id)

    def _dem_path(self, task):
        return os.path.abspath(task.get_asset_download_path('dtm.tif'))


class MaskOnlyForSegmentationTest(RoadTestBase):
    """`break` y `surface` no producen máscara y no deben marcar `has_mask` (`FR-006`)."""

    def test_non_segmentation_modes_report_no_mask(self):
        for mode in ('break', 'surface'):
            with self.subTest(mode=mode):
                self.assertFalse(store.analysis_has_mask({'params': {'edge_mode': mode}}))

    def test_absent_flag_is_treated_as_no_mask(self):
        """Análisis anteriores a `008`: sin campo, sin migración en disco (`data-model.md` §2)."""
        self.assertFalse(store.analysis_has_mask({'params': {'edge_mode': 'segmentation'}}))

    def test_flag_present_and_true(self):
        self.assertTrue(store.analysis_has_mask(
            {'params': {'edge_mode': 'segmentation'}, 'has_mask': True}))
