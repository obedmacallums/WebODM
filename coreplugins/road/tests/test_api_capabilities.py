"""`GET task/<pk>/capabilities` (`contracts/rest-api.md`).

El panel se dibuja entero con esta respuesta, así que lo que se comprueba aquí es que no queden
opciones muertas: los modelos que hay de verdad, las variantes por modelo, y unos rangos cuyo suelo
depende de la resolución del ráster y no de una constante duplicada en el frontend.
"""

from rest_framework import status

from .. import sources
from .base import RoadTestBase, DEM_RES, dem_extent, make_road_dem


class CapabilitiesTest(RoadTestBase):
    def test_reports_the_available_model_and_its_resolution(self):
        task = self._task_with_dem(asset='dtm.tif')
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['models'], ['dtm'])
        self.assertEqual(res.data['default_model'], 'dtm')
        self.assertAlmostEqual(res.data['resolution'], DEM_RES, places=6)

    def test_prefers_dtm_over_dsm(self):
        # El ancho se mide sobre el terreno: un DSM trae la vegetación del borde y los vehículos
        # aparcados, que son justo los quiebres falsos que la detección confundiría con calzada.
        task = self._task_with_dem(asset='dtm.tif',
                                   available_assets=['orthophoto.tif', 'dtm.tif', 'dsm.tif'],
                                   dsm_extent=dem_extent())
        make_road_dem(task.get_asset_download_path('dsm.tif'))
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertEqual(sorted(res.data['models']), ['dsm', 'dtm'])
        self.assertEqual(res.data['default_model'], 'dtm')
        self.assertEqual(sources.default_model(task), 'dtm')

    def test_defaults_and_ranges_follow_the_dem_resolution(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertAlmostEqual(res.data['defaults']['sample_step'], DEM_RES, places=6)
        self.assertAlmostEqual(res.data['ranges']['sample_step'][0], DEM_RES, places=6)
        self.assertEqual(res.data['defaults']['segment_length'], 5.0)
        self.assertEqual(res.data['defaults']['color_thresholds'], [8.0, 12.0])
        self.assertEqual(res.data['ranges']['segment_length'], [0.5, 100.0])

    def test_only_the_original_variant_without_realign(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertEqual(res.data['variants'], {'dtm': ['original']})

    def test_task_without_elevation_model_is_rejected(self):
        task = self._task(self._project())
        self._login()

        res = self.client.get(self._url(task, 'capabilities'))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'no_elevation_model')

    def test_requires_access_to_the_task(self):
        # 404 y no 403: `check_project_perms` del core levanta `NotFound` ante cualquier fallo de
        # permiso, deliberadamente, para no revelar que la tarea existe. Los tests de escritura de
        # este plugin esperan lo mismo por la misma razón.
        task = self._task_with_dem()

        anonymous = self.client.get(self._url(task, 'capabilities'))
        self.assertEqual(anonymous.status_code, status.HTTP_404_NOT_FOUND)

        self._login('testuser2')
        stranger = self.client.get(self._url(task, 'capabilities'))
        self.assertEqual(stranger.status_code, status.HTTP_404_NOT_FOUND)
