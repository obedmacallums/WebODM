"""API de selección asistida (`010/contracts/rest-api.md`).

La ortofoto sintética de `base.py` mide 30 m, o sea que cabe entera en la celda (0,0) de la rejilla
de trabajo. Eso no debilita estos tests: lo que se prueba aquí es el contrato —qué campos vuelven,
qué códigos de error, qué es un error y qué no—, mientras que la partición, la costura de juntas y
la tolerancia se prueban sobre una ortofoto de dos celdas en `test_superpixels.py`.
"""

import json
from unittest import mock

from coreplugins.training import models, regions, store, superpixels

from .base import TrainingTestBase, offset_to_lnglat


def point(dx, dy):
    """Punto a `dx` m al este y `dy` m al sur de la esquina superior izquierda de la ortofoto."""
    lng, lat = offset_to_lnglat(dx, dy)
    return {'lon': lng, 'lat': lat}


class RegionApiTest(TrainingTestBase):
    """Contrato de `POST regions` para un punto (US1)."""

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()
        self.addCleanup(regions.clear, str(self.task.id))

    def _url(self, *extra):
        return self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'regions', *extra)

    def _post(self, **payload):
        payload.setdefault('points', [point(8, 8)])
        return self.client.post(self._url(), payload, format='json')

    # --- Forma de la respuesta (T018) ----------------------------------------------------

    def test_a_click_returns_the_geometry_of_a_region(self):
        res = self._post()
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['geometry']['type'], 'MultiPolygon')
        self.assertGreaterEqual(res.data['region_count'], 1)
        self.assertIn(res.data['elevation_source'], ('dtm', 'dsm', 'none'))
        self.assertIn(res.data['band_count'], (3, 5))
        self.assertFalse(res.data['truncated'])
        self.assertGreaterEqual(res.data['prepared_cells'], 1)

    def test_no_labels_are_created(self):
        """El endpoint devuelve geometría y nada más: quien crea etiquetas es el de etiquetas."""
        self._post()
        self.assertEqual(store.list_labels(self.dataset['id'], str(self.task.id)), [])

    def test_the_second_call_reuses_the_prepared_cell(self):
        self.assertGreaterEqual(self._post().data['prepared_cells'], 1)
        self.assertEqual(self._post().data['prepared_cells'], 0)

    def test_the_geometry_lands_on_the_orthophoto(self):
        """Contra el intercambio de ejes: una geometría en `(lat, lon)` cae en el océano Índico."""
        res = self._post()
        expected = point(8, 8)
        for polygon in res.data['geometry']['coordinates']:
            for ring in polygon:
                for lng, lat in ring:
                    self.assertAlmostEqual(lng, expected['lon'], places=2)
                    self.assertAlmostEqual(lat, expected['lat'], places=2)

    # --- Determinismo (T019, FR-007) -----------------------------------------------------

    def test_three_identical_requests_return_identical_geometries(self):
        payloads = [json.dumps(self._post().data['geometry'], sort_keys=True) for _ in range(3)]
        self.assertEqual(len(set(payloads)), 1)

    def test_the_result_survives_a_cold_cache(self):
        """El caso que de verdad rompe el determinismo: la caché no puede cambiar la respuesta."""
        warm = json.dumps(self._post().data['geometry'], sort_keys=True)
        regions.clear(str(self.task.id))
        cold = self._post()
        self.assertGreaterEqual(cold.data['prepared_cells'], 1, 'La caché no se llegó a vaciar.')
        self.assertEqual(json.dumps(cold.data['geometry'], sort_keys=True), warm)

    def test_the_result_does_not_depend_on_the_viewport(self):
        """FR-008. `POST regions` no acepta `bounds` y no debe reaccionar a nada parecido."""
        first = self._post()
        second = self._post(bounds='-71,-34,-70,-33', zoom=18)
        self.assertEqual(json.dumps(first.data['geometry'], sort_keys=True),
                         json.dumps(second.data['geometry'], sort_keys=True))

    # --- Casos de error (T020) -----------------------------------------------------------

    def test_no_points_is_a_bad_request(self):
        res = self.client.post(self._url(), {'points': []}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_points')

    def test_a_malformed_point_is_a_bad_request(self):
        res = self.client.post(self._url(), {'points': [{'lon': 'aquí'}]}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_points')

    def test_coordinates_out_of_range_are_a_bad_request(self):
        res = self.client.post(self._url(), {'points': [{'lon': 999, 'lat': 0}]}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_points')

    def test_an_unknown_granularity_is_a_bad_request(self):
        res = self._post(granularity='enorme')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_settings')

    def test_a_tolerance_out_of_range_is_a_bad_request(self):
        res = self._post(tolerance=1.5)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_settings')

    def test_an_elevation_weight_out_of_range_is_a_bad_request(self):
        res = self._post(elevation_weight=-0.2)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_settings')

    def test_an_unknown_dataset_is_not_found(self):
        url = self._api('datasets', 'no-existe', 'tasks', self.task.id, 'regions')
        self.assertEqual(self.client.post(url, {'points': [point(8, 8)]}, format='json')
                         .status_code, 404)

    def test_a_task_outside_the_dataset_is_not_found(self):
        other = self._task_with_orthophoto(project=self.task.project)
        url = self._api('datasets', self.dataset['id'], 'tasks', other.id, 'regions')
        res = self.client.post(url, {'points': [point(8, 8)]}, format='json')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data['code'], 'task_not_in_dataset')

    def test_a_task_without_orthophoto_is_a_conflict(self):
        task = self._task()   # referencia en la base de datos, sin fichero en disco
        dataset = self._create_dataset(task)
        url = self._api('datasets', dataset['id'], 'tasks', task.id, 'regions')
        res = self.client.post(url, {'points': [point(8, 8)]}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['code'], 'no_orthophoto')

    def test_a_user_without_access_cannot_select(self):
        """Como en el resto del plugin, la falta de permiso sale como 404 y no como 403.

        Es lo que hace `check_project_perms` del core, deliberadamente, para no confirmar que el
        recurso existe. El contrato de `010` decía 403; se sigue la convención del plugin, que es la
        que un cliente ya tiene implementada.
        """
        self.client.logout()
        self.client.login(username='testuser2', password='test1234')
        res = self.client.post(self._url(), {'points': [point(8, 8)]}, format='json')
        self.assertEqual(res.status_code, 404)

    def test_clicking_outside_the_flight_is_not_an_error(self):
        """FR-025. Es lo que el usuario hace cada dos por tres sin equivocarse en nada."""
        res = self.client.post(self._url(), {'points': [point(1000, 1000)]}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIsNone(res.data['geometry'])
        self.assertEqual(res.data['region_count'], 0)
        self.assertEqual(res.data['reason'], 'no_data')
        self.assertTrue(res.data['message'])

    def test_clicking_on_a_pixel_without_flight_data_is_not_an_error(self):
        """Dentro de la ortofoto pero sobre el cuadrante con alfa 0."""
        res = self.client.post(self._url(), {'points': [point(25, 25)]}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertIsNone(res.data['geometry'])
        self.assertEqual(res.data['reason'], 'no_data')


class RegionDragTest(TrainingTestBase):
    """Varios puntos: el arrastre de US2 (T032, T033)."""

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()
        self.addCleanup(regions.clear, str(self.task.id))

    def _url(self):
        return self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'regions')

    def test_several_points_return_the_union(self):
        res = self.client.post(self._url(), {
            'points': [point(4, 4), point(8, 8), point(12, 12)]}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['geometry']['type'], 'MultiPolygon')
        self.assertGreaterEqual(res.data['region_count'], 3)

    def test_repeated_points_do_not_duplicate_regions(self):
        one = self.client.post(self._url(), {'points': [point(8, 8)]}, format='json')
        again = self.client.post(self._url(), {'points': [point(8, 8), point(8, 8)]},
                                 format='json')
        self.assertEqual(again.data['region_count'], one.data['region_count'])

    def test_a_point_next_to_a_border_returns_the_whole_region(self):
        """FR-005: nunca una fracción de región, aunque el punto caiga pegado a su borde.

        Se comprueba comparando el área que devuelve un punto cualquiera con la de un punto vecino
        de la misma región: si el resultado dependiera de dónde se pinchó dentro de la región,
        serían distintas.
        """
        with regions.CellProvider(str(self.task.id), self.dataset['resolution_cm_px'],
                                  elevation_weight=0.0) as provider:
            centre = provider.region_at(*offset_to_lnglat(8, 8))
            self.assertIsNotNone(centre)
            partition = provider.get(centre[0], centre[1])
            pixels = (partition.labels == centre[2])
            rows, cols = pixels.nonzero()

            grid = provider.grid
            from rasterio.warp import transform as warp_transform
            edge_row, edge_col = int(rows[0]), int(cols[0])
            x = grid.left + (edge_col + 0.5) * grid.resolution_m
            y = grid.top - (edge_row + 0.5) * grid.resolution_m
            lngs, lats = warp_transform(grid.crs, 'EPSG:4326', [x], [y])

        first = self.client.post(self._url(), {'points': [point(8, 8)], 'elevation_weight': 0},
                                 format='json')
        edge = self.client.post(self._url(),
                                {'points': [{'lon': lngs[0], 'lat': lats[0]}],
                                 'elevation_weight': 0}, format='json')
        self.assertEqual(json.dumps(first.data['geometry'], sort_keys=True),
                         json.dumps(edge.data['geometry'], sort_keys=True),
                         'Pinchar en el borde de una región devolvió algo distinto que pinchar en '
                         'su centro: se está devolviendo una fracción.')


class RegionToleranceTest(TrainingTestBase):
    """Crecimiento por tolerancia a través de la API (T041)."""

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()
        self.addCleanup(regions.clear, str(self.task.id))

    def _post(self, **payload):
        payload.setdefault('points', [point(8, 8)])
        return self.client.post(
            self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'regions'),
            payload, format='json')

    def test_zero_tolerance_selects_one_region(self):
        self.assertEqual(self._post(tolerance=0).data['region_count'], 1)

    def test_more_tolerance_selects_more(self):
        small = self._post(tolerance=0.0).data['region_count']
        large = self._post(tolerance=0.5).data['region_count']
        self.assertGreater(large, small)

    def test_hitting_the_cap_is_reported(self):
        """FR-018: `truncated` viaja en la respuesta para que la interfaz pueda avisarlo."""
        with mock.patch.object(superpixels, 'MAX_GROWTH_REGIONS', 5):
            res = self._post(tolerance=1.0)
        self.assertTrue(res.data['truncated'])
        self.assertLessEqual(res.data['region_count'], 5)


class RegionElevationTest(TrainingTestBase):
    """Lo que se usó de verdad viaja en la respuesta (T048, FR-011)."""

    def setUp(self):
        super().setUp()
        self._login()

    def _select(self, task, dataset, **payload):
        payload.setdefault('points', [point(8, 8)])
        self.addCleanup(regions.clear, str(task.id))
        return self.client.post(
            self._api('datasets', dataset['id'], 'tasks', task.id, 'regions'),
            payload, format='json')

    def test_with_a_dtm_the_stack_has_five_bands(self):
        task = self._task_with_orthophoto(with_dtm=True)
        res = self._select(task, self._create_dataset(task))
        self.assertEqual(res.data['elevation_source'], 'dtm')
        self.assertEqual(res.data['band_count'], 5)

    def test_without_a_dem_it_falls_back_to_three_bands(self):
        """No es un error: una tarea sin terreno se etiqueta igual, solo que con color."""
        task = self._task_with_orthophoto(with_dtm=False)
        res = self._select(task, self._create_dataset(task))
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['elevation_source'], 'none')
        self.assertEqual(res.data['band_count'], 3)
        self.assertIsNotNone(res.data['geometry'])

    def test_zero_weight_disables_the_terrain_channels(self):
        task = self._task_with_orthophoto(with_dtm=True)
        res = self._select(task, self._create_dataset(task), elevation_weight=0)
        self.assertEqual(res.data['band_count'], 3)
        self.assertEqual(res.data['elevation_source'], 'none')


class RegionStatusTest(TrainingTestBase):
    """`GET regions/status` (T055, T056)."""

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()
        self.addCleanup(regions.clear, str(self.task.id))

    def _status_url(self):
        return self._api('datasets', self.dataset['id'], 'tasks', self.task.id,
                         'regions', 'status')

    def _bounds(self):
        (lng0, lat0), (lng1, lat1) = offset_to_lnglat(2, 2), offset_to_lnglat(28, 28)
        return '{},{},{},{}'.format(min(lng0, lng1), min(lat0, lat1),
                                    max(lng0, lng1), max(lat0, lat1))

    def test_status_reports_pending_cells_before_anything_is_prepared(self):
        res = self.client.get(self._status_url(), {'bounds': self._bounds()})
        self.assertEqual(res.status_code, 200, res.data)
        self.assertGreaterEqual(res.data['cells_total'], 1)
        self.assertEqual(res.data['cells_ready'], 0)
        self.assertGreater(res.data['estimated_seconds'], 0)

    def test_status_reflects_a_prepared_cell(self):
        self.client.post(
            self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'regions'),
            {'points': [point(8, 8)]}, format='json')
        res = self.client.get(self._status_url(), {'bounds': self._bounds()})
        self.assertEqual(res.data['cells_ready'], res.data['cells_total'])
        self.assertEqual(res.data['estimated_seconds'], 0)

    def test_missing_bounds_is_a_bad_request(self):
        res = self.client.get(self._status_url())
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_bounds')

    def test_malformed_bounds_is_a_bad_request(self):
        res = self.client.get(self._status_url(), {'bounds': 'a,b,c,d'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_bounds')

    def test_status_route_is_not_swallowed_by_the_regions_route(self):
        """Las dos rutas comparten prefijo: sin el `$` final, `regions` se tragaría `status`."""
        res = self.client.get(self._status_url(), {'bounds': self._bounds()})
        self.assertIn('cells_total', res.data)
        self.assertNotIn('geometry', res.data)


class AssistedLabelTest(TrainingTestBase):
    """La etiqueta que produce la selección asistida (T027, FR-020)."""

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()
        self.addCleanup(regions.clear, str(self.task.id))

    def _labels_url(self):
        return self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'labels')

    def _ring_from_a_click(self):
        res = self.client.post(
            self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'regions'),
            {'points': [point(8, 8)]}, format='json')
        return res.data['geometry']['coordinates'][0][0]

    def test_an_assisted_label_is_an_ordinary_polygon(self):
        """Es lo que hace que FR-020 se cumpla sin trabajo: `rasterize` y `export` ni se enteran."""
        res = self.client.post(self._labels_url(), {
            'kind': 'polygon', 'class_index': 1, 'source': 'assisted',
            'geometry': self._ring_from_a_click()}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['kind'], models.KIND_POLYGON)
        self.assertEqual(res.data['source'], models.SOURCE_ASSISTED)

    def test_the_default_source_is_still_manual(self):
        res = self.client.post(self._labels_url(), {
            'kind': 'polygon', 'class_index': 1,
            'geometry': self._ring_from_a_click()}, format='json')
        self.assertEqual(res.data['source'], models.SOURCE_MANUAL)

    def test_a_client_cannot_claim_a_label_came_from_a_model(self):
        """La procedencia solo vale para algo si no se puede falsear."""
        res = self.client.post(self._labels_url(), {
            'kind': 'polygon', 'class_index': 1, 'source': 'model',
            'geometry': self._ring_from_a_click()}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_source')
