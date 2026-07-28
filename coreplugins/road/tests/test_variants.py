"""Variante realineada del DEM (`research.md` D1, `contracts/consumed-contracts.md` §2).

`road` habla con `realign` por el framework de plugins, nunca importando su paquete. Aquí se
comprueban las dos mitades de esa relación: que la variante se ofrezca y se use cuando existe, y
que **ninguna forma de ausencia del plugin hermano rompa nada** — sin él, deshabilitado, o
exponiendo un contrato mayor del que sabemos leer, la única variante es `original`.
"""

import os
import shutil
import tempfile
from unittest import mock

from rest_framework import status

from .. import sources, store
from .base import RoadTestBase, make_road_dem
from .test_api_analyses import AnalysesApiTestBase


class FakeRealign:
    """Doble de `realign` con la superficie exacta de su contrato público."""

    def __init__(self, corrected, version=1):
        self._corrected = corrected
        self._version = version

    def contract_version(self):
        return self._version

    def corrected_rasters(self, task_id):
        return dict(self._corrected)


class VariantsTestBase(RoadTestBase):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _corrected_dem(self, **dem_kwargs):
        """DEM corregido de mentira, con una geometría distinta de la del original para poder
        distinguir cuál de los dos se muestreó de verdad."""
        path = os.path.join(self.tmp, 'dsm.tif')
        make_road_dem(path, **dem_kwargs)
        return path

    def _patch_realign(self, plugin):
        patcher = mock.patch('app.plugins.functions.get_plugin_by_name',
                             side_effect=lambda name: plugin if name == 'realign' else None)
        patcher.start()
        self.addCleanup(patcher.stop)


class AvailableVariantsTest(VariantsTestBase):
    def test_only_original_without_realign(self):
        task = self._task_with_dem()
        self._patch_realign(None)

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_only_original_when_realign_has_nothing_applied(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({}))

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_realigned_appears_when_the_corrected_file_exists(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({'dtm': self._corrected_dem()}))

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original', 'realigned'])

    def test_a_newer_contract_is_treated_as_absent(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({'dtm': self._corrected_dem()}, version=2))

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_a_plugin_without_the_contract_is_treated_as_absent(self):
        task = self._task_with_dem()
        self._patch_realign(object())

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_a_realign_that_raises_does_not_propagate(self):
        # Un fallo hablando con otro plugin no puede tumbar el análisis.
        task = self._task_with_dem()
        broken = mock.Mock()
        broken.contract_version.side_effect = RuntimeError('boom')
        self._patch_realign(broken)

        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_the_variant_is_per_model(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({'orthophoto': self._corrected_dem()}))

        # Hay un corregido, pero no del modelo que se va a muestrear.
        self.assertEqual(sources.available_variants(task, 'dtm'), ['original'])

    def test_dem_path_resolves_to_the_corrected_file(self):
        task = self._task_with_dem()
        corrected = self._corrected_dem()
        self._patch_realign(FakeRealign({'dtm': corrected}))

        self.assertEqual(sources.dem_path(task, 'dtm', 'realigned'), corrected)
        self.assertNotEqual(sources.dem_path(task, 'dtm', 'original'), corrected)

    def test_asking_for_an_unavailable_variant_raises(self):
        task = self._task_with_dem()
        self._patch_realign(None)

        with self.assertRaises(sources.UnavailableVariant):
            sources.dem_path(task, 'dtm', 'realigned')


class VariantsApiTest(AnalysesApiTestBase, VariantsTestBase):
    def test_capabilities_offers_both_variants(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({'dtm': self._corrected_dem()}))
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertEqual(res.data['variants']['dtm'], ['original', 'realigned'])

    def test_requesting_realigned_without_a_realignment_is_refused(self):
        task = self._task_with_dem()
        self._patch_realign(None)
        self._login()

        res = self._create(task, variant='realigned')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'unavailable_variant')
        self.assertEqual(store.list_analyses(str(task.id)), [])

    def test_the_analysis_uses_the_corrected_file_and_records_the_variant(self):
        # El corregido lleva una calzada de 6 m frente a los 8 del original: si el resultado da 6,
        # se muestreó el archivo correcto y no el de la tarea.
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({
            'dtm': self._corrected_dem(half_width_left=3.0, half_width_right=3.0)}))
        self._login()

        res = self._create(task, variant='realigned')
        analysis = store.get_analysis(str(task.id), res.data['analysis_id'])

        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(analysis['variant'], 'realigned')
        self.assertAlmostEqual(analysis['summary']['mean_width'], 6.0, places=6)

    def test_the_original_variant_still_measures_the_original(self):
        task = self._task_with_dem()
        self._patch_realign(FakeRealign({
            'dtm': self._corrected_dem(half_width_left=3.0, half_width_right=3.0)}))
        self._login()

        res = self._create(task)
        analysis = store.get_analysis(str(task.id), res.data['analysis_id'])

        self.assertEqual(analysis['variant'], 'original')
        self.assertAlmostEqual(analysis['summary']['mean_width'], 8.0, places=6)

    def test_the_variant_travels_to_the_export(self):
        import json

        task = self._task_with_dem()
        self._patch_realign(FakeRealign({'dtm': self._corrected_dem()}))
        self._login()
        analysis_id = self._create(task, variant='realigned').data['analysis_id']

        csv_res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                                  {'format': 'csv'})
        geojson_res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                                      {'format': 'geojson'})

        self.assertIn('realigned', csv_res.content.decode())
        self.assertEqual(json.loads(geojson_res.content.decode())['properties']['variant'],
                         'realigned')
