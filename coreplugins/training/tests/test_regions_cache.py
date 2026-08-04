"""Caché de mapas de regiones y `CellProvider` (`010` T012–T014).

Lo que se prueba aquí no es que la caché sea rápida —eso ya se midió— sino que **no cambia el
resultado**. Una caché que devuelve algo distinto de lo recién calculado rompe FR-007 sin lanzar
ningún error: los dos valores son plausibles, solo que no son el mismo. De ahí que el primer test
compare píxel a píxel.
"""

import os
import shutil
import tempfile

import numpy as np

from django.test import SimpleTestCase, override_settings

from coreplugins.training import regions, superpixels
from coreplugins.training.tests.test_superpixels import (RESOLUTION_CM_PX,
                                                         make_textured_orthophoto)


class _CacheCase(SimpleTestCase):
    """Aísla la caché en un `MEDIA_ROOT` propio: los tests no tocan la del entorno."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = tempfile.mkdtemp(prefix='training-regions-')
        cls.orthophoto = make_textured_orthophoto(os.path.join(cls.directory, 'ortho.tif'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix='training-media-')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.task_id = 'zz-prueba-010'
        patcher = override_settings(MEDIA_ROOT=self.media)
        patcher.enable()
        self.addCleanup(patcher.disable)

    def provider(self, granularity='medium', elevation_weight=0.0):
        return regions.CellProvider(
            self.task_id, RESOLUTION_CM_PX, granularity=granularity,
            elevation_weight=elevation_weight, orthophoto_path=self.orthophoto)


class CacheRoundTripTest(_CacheCase):

    def test_the_cached_partition_is_identical_to_the_computed_one(self):
        """FR-007. Si esto falla, dos clics sobre el mismo punto dan regiones distintas."""
        with self.provider() as provider:
            fresh = provider.get(0, 0)
            self.assertEqual(provider.prepared_cells, 1)

        with self.provider() as provider:
            cached = provider.get(0, 0)
            self.assertEqual(provider.prepared_cells, 0,
                             'La segunda apertura recalculó la celda en vez de leerla de disco.')

        np.testing.assert_array_equal(fresh.labels, cached.labels)
        np.testing.assert_allclose(fresh.means, cached.means, rtol=0, atol=0)
        np.testing.assert_array_equal(fresh.valid, cached.valid)
        self.assertEqual(fresh.adjacency, cached.adjacency)
        self.assertEqual(fresh.band_count, cached.band_count)
        for side in ('top', 'bottom', 'left', 'right'):
            np.testing.assert_array_equal(fresh.continues[side], cached.continues[side])

    def test_a_second_call_within_a_provider_does_not_recompute(self):
        with self.provider() as provider:
            first = provider.get(0, 0)
            second = provider.get(0, 0)
            self.assertIs(first, second)
            self.assertEqual(provider.prepared_cells, 1)

    def test_a_cell_outside_the_raster_is_not_an_error(self):
        with self.provider() as provider:
            self.assertIsNone(provider.get(99, 99))
            self.assertEqual(provider.prepared_cells, 0)


class CacheKeyTest(_CacheCase):

    def test_the_key_separates_configurations(self):
        """Cambiar granularidad o peso genera clave nueva, así que no hay que invalidar nada."""
        keys = {
            regions.cache_key(10.0, 'medium', 1.0),
            regions.cache_key(10.0, 'fine', 1.0),
            regions.cache_key(10.0, 'coarse', 1.0),
            regions.cache_key(10.0, 'medium', 0.0),
            regions.cache_key(5.0, 'medium', 1.0),
        }
        self.assertEqual(len(keys), 5)

    def test_the_key_carries_the_algorithm_version(self):
        """Sin la versión, un cambio en la partición convive con mapas viejos y rompe FR-007."""
        self.assertIn('v{}'.format(superpixels.ALGORITHM_VERSION),
                      regions.cache_key(10.0, 'medium', 1.0))

    def test_changing_the_granularity_recomputes(self):
        with self.provider('medium') as provider:
            provider.get(0, 0)
        with self.provider('coarse') as provider:
            provider.get(0, 0)
            self.assertEqual(provider.prepared_cells, 1,
                             'Una granularidad distinta reutilizó el mapa de la anterior.')


class CacheBudgetTest(_CacheCase):

    def _write_fake_cells(self, count):
        directory = regions.cache_dir(self.task_id)
        os.makedirs(directory, exist_ok=True)
        paths = []
        for i in range(count):
            path = os.path.join(directory, 'k-{}_{}.npz'.format(i, i))
            with open(path, 'wb') as f:
                f.write(b'x')
            # Marcas de uso separadas para que la expulsión tenga un orden que respetar.
            os.utime(path, (1000 + i, 1000 + i))
            paths.append(path)
        return paths

    def test_the_budget_evicts_the_least_recently_used(self):
        paths = self._write_fake_cells(10)
        evicted = regions.enforce_budget(self.task_id, limit=4)

        self.assertEqual(evicted, 6)
        self.assertFalse(any(os.path.exists(p) for p in paths[:6]))
        self.assertTrue(all(os.path.exists(p) for p in paths[6:]))

    def test_nothing_is_evicted_below_the_budget(self):
        paths = self._write_fake_cells(3)
        self.assertEqual(regions.enforce_budget(self.task_id, limit=4), 0)
        self.assertTrue(all(os.path.exists(p) for p in paths))

    def test_losing_the_cache_loses_nothing(self):
        """Es una caché, no un almacén: borrarla entera solo cuesta un segundo de recálculo."""
        with self.provider() as provider:
            before = provider.get(0, 0)

        regions.clear(self.task_id)

        with self.provider() as provider:
            after = provider.get(0, 0)
            self.assertEqual(provider.prepared_cells, 1)
        np.testing.assert_array_equal(before.labels, after.labels)


class CorruptCacheTest(_CacheCase):

    def test_a_truncated_file_is_treated_as_absent(self):
        """Una escritura interrumpida no puede convertirse en un error en cada clic."""
        with self.provider() as provider:
            provider.get(0, 0)

        path = regions.cell_path(self.task_id, regions.cache_key(RESOLUTION_CM_PX, 'medium', 0.0),
                                 0, 0)
        self.assertTrue(os.path.isfile(path))
        with open(path, 'r+b') as f:
            f.truncate(64)

        self.assertIsNone(regions.load_cell(
            self.task_id, regions.cache_key(RESOLUTION_CM_PX, 'medium', 0.0), 0, 0))
        self.assertFalse(os.path.exists(path), 'El fichero corrupto debería haberse borrado.')


class ProviderSelectionTest(_CacheCase):

    def lnglat_of(self, provider, px, py):
        """Punto geográfico del centro de un píxel global de salida."""
        from rasterio.warp import transform as warp_transform

        grid = provider.grid
        x = grid.left + (px + 0.5) * grid.resolution_m
        y = grid.top - (py + 0.5) * grid.resolution_m
        lngs, lats = warp_transform(grid.crs, 'EPSG:4326', [x], [y])
        return lngs[0], lats[0]

    def test_region_at_a_point_is_stable(self):
        with self.provider() as provider:
            point = self.lnglat_of(provider, 256, 128)
            first = provider.region_at(*point)
            second = provider.region_at(*point)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first[:2], (0, 0))

    def test_a_point_outside_the_raster_selects_nothing(self):
        with self.provider() as provider:
            grid = provider.grid
            from rasterio.warp import transform as warp_transform
            lngs, lats = warp_transform(grid.crs, 'EPSG:4326', [grid.left - 100.0], [grid.top])
            self.assertIsNone(provider.region_at(lngs[0], lats[0]))

    def test_a_point_without_flight_data_selects_nothing(self):
        """FR-025: pinchar fuera de la huella del vuelo no es un error, es que ahí no hay nada."""
        with self.provider() as provider:
            # Esquina inferior derecha, donde la ortofoto sintética tiene alfa 0.
            point = self.lnglat_of(provider, 1000, 1000)
            self.assertIsNone(provider.region_at(*point))

    def test_a_drag_over_several_points_selects_them_all(self):
        with self.provider() as provider:
            points = [self.lnglat_of(provider, 256, y) for y in (64, 160, 256)]
            selection = provider.select(points, tolerance=0.0)
        self.assertGreaterEqual(len(selection.regions), 3)
        self.assertFalse(selection.truncated)

    def test_the_geometry_of_a_selection_is_a_multipolygon(self):
        with self.provider() as provider:
            selection = provider.select([self.lnglat_of(provider, 256, 128)])
            geometry = provider.geometry(selection.regions)
        self.assertEqual(geometry['type'], 'MultiPolygon')
