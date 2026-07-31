"""Canales derivados del DTM (`elevation.py`, D14, D15, D16).

El riesgo de este módulo es que **falla en silencio**. Un DTM desalineado medio píxel, un gradiente
calculado sin la resolución o una rugosidad normalizada con el techo de otra escala producen los
tres un canal de aspecto perfectamente razonable y sistemáticamente equivocado; el paquete se
genera, el entrenamiento corre y el modelo simplemente aprende peor.

Por eso el DTM sintético es un plano (`base.make_dtm`): sus dos canales tienen valor cerrado y aquí
se comprueban contra el número, no contra un rango.
"""

import numpy as np
import rasterio

from coreplugins.training import elevation, tiling

from .base import (DTM_BASE_M, DTM_GRADIENT, DTM_RES, ORTHO_ORIGIN, ORTHO_RES,
                   TrainingTestBase, expected_checkerboard_roughness_m, expected_slope_degrees,
                   expected_tri_m, make_dtm)

TILE_PX = 64
RESOLUTION_CM = 10.0
RESOLUTION_M = RESOLUTION_CM / 100.0


class ElevationTestBase(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.ortho = rasterio.open(self.task.get_asset_download_path('orthophoto.tif'))
        self.dem = rasterio.open(self.task.get_asset_download_path('dtm.tif'))
        self.addCleanup(self.ortho.close)
        self.addCleanup(self.dem.close)
        self.tiles = list(tiling.tile_grid(self.ortho, RESOLUTION_CM, TILE_PX, overlap_px=8))

    def first_tile(self):
        return self.tiles[0]


class AlignmentTest(ElevationTestBase):
    def test_the_aligned_dtm_lands_on_the_exact_output_grid(self):
        """D15: la comprobación que detectaría el desfase de medio píxel.

        El DTM de prueba se escribe con el origen corrido medio píxel en Y, igual que el DTM real
        de la mina respecto a su ortofoto. Sobre un plano `base + g*(x - x0)`, el valor remuestreado
        en el centro del píxel `c` de la tesela vale exactamente `base + g*(c+0.5)*res` menos el
        medio píxel nativo con que se escribió: `base + 0.05*c`.

        Leer con `read(window=...)` sin reproyectar daría los mismos valores desplazados, y ninguna
        otra comprobación de la suite lo notaría.
        """
        tile = self.first_tile()
        relative, valid, reference = elevation.read_aligned(self.dem, tile, TILE_PX, halo=0)
        absolute = relative.astype('float64') + reference

        self.assertEqual(relative.shape, (TILE_PX, TILE_PX))
        self.assertTrue(valid.all())

        columns = np.arange(TILE_PX)
        expected = DTM_BASE_M + DTM_GRADIENT * (columns * RESOLUTION_M)

        # Los bordes quedan fuera del núcleo bilineal completo, así que se comprueba el interior.
        interior = absolute[4:-4, 4:-4]
        np.testing.assert_allclose(interior, np.broadcast_to(expected[4:-4], interior.shape),
                                   atol=1e-4)

    def test_every_row_holds_the_same_value(self):
        """El plano solo varía en X: cualquier corrimiento en Y saldría como variación por filas.

        La tolerancia de 1e-6 m es la prueba de que el centrado funciona: sin él, el `float32` a
        4 100 m de cota dejaba 2 mm de ruido de fila a fila, un 5 % del TRI que hay que medir.
        """
        relative, _, _ = elevation.read_aligned(self.dem, self.first_tile(), TILE_PX, halo=0)
        interior = relative[4:-4, 4:-4]
        np.testing.assert_allclose(interior.std(axis=0), 0, atol=1e-6)

    def test_the_halo_extends_the_grid_without_shifting_it(self):
        halo = elevation.HALO_PX
        padded, _, padded_ref = elevation.read_aligned(self.dem, self.first_tile(), TILE_PX,
                                                       halo=halo)
        plain, _, plain_ref = elevation.read_aligned(self.dem, self.first_tile(), TILE_PX, halo=0)

        self.assertEqual(padded.shape, (TILE_PX + 2 * halo, TILE_PX + 2 * halo))
        # Las referencias difieren porque la ventana de origen no es la misma; lo que tiene que
        # coincidir es la cota absoluta.
        np.testing.assert_allclose(
            padded[halo:halo + TILE_PX, halo:halo + TILE_PX].astype('float64') + padded_ref,
            plain.astype('float64') + plain_ref, atol=1e-4)


class DerivedChannelTest(ElevationTestBase):
    def test_slope_uses_the_real_resolution(self):
        """Sin pasarle la resolución, `np.gradient` daría metros por píxel y la misma ladera
        tendría pendientes distintas según la resolución del dataset."""
        plane = np.tile(np.arange(32, dtype='float32') * DTM_GRADIENT * RESOLUTION_M, (32, 1))
        slope = elevation.slope_degrees(plane, RESOLUTION_M)

        np.testing.assert_allclose(slope[2:-2, 2:-2], expected_slope_degrees(DTM_GRADIENT),
                                   atol=1e-4)

    def test_the_same_terrain_at_another_resolution_gives_the_same_slope(self):
        coarse = np.tile(np.arange(32, dtype='float32') * DTM_GRADIENT * 0.5, (32, 1))
        fine = np.tile(np.arange(32, dtype='float32') * DTM_GRADIENT * 0.1, (32, 1))

        np.testing.assert_allclose(
            elevation.slope_degrees(coarse, 0.5)[2:-2, 2:-2],
            elevation.slope_degrees(fine, 0.1)[2:-2, 2:-2], atol=1e-4)

    def test_roughness_of_a_slope_is_zero(self):
        """La propiedad que separa este canal del de pendiente (D21).

        Una rampa perfectamente lisa no tiene rugosidad ninguna, por inclinada que esté. El TRI de
        Riley habría dado 0,0375 m sobre este mismo array —la pendiente otra vez— y con eso la
        quinta banda repetiría la cuarta.
        """
        plane = np.tile(np.arange(32, dtype='float64') * DTM_GRADIENT * RESOLUTION_M, (32, 1))
        rough = elevation.roughness(plane)

        np.testing.assert_allclose(rough[2:-2, 2:-2], 0.0, atol=1e-9)
        self.assertGreater(expected_tri_m(DTM_GRADIENT, RESOLUTION_M), 0.03,
                           'y que quede escrito cuánto habría contaminado el TRI')

    def test_roughness_of_flat_ground_is_zero(self):
        flat = np.full((16, 16), 4100.0, dtype='float64')
        np.testing.assert_allclose(elevation.roughness(flat), 0.0, atol=1e-9)

    def test_roughness_measures_departure_from_flatness(self):
        """Un damero de amplitud conocida: el único caso con forma cerrada y no trivial."""
        amplitude = 0.05
        rows, cols = np.indices((32, 32))
        board = amplitude * np.where((rows + cols) % 2 == 0, 1.0, -1.0)

        rough = elevation.roughness(board)
        np.testing.assert_allclose(rough[2:-2, 2:-2],
                                   expected_checkerboard_roughness_m(amplitude), atol=1e-9)

    def test_roughness_does_not_change_when_the_ground_is_tilted(self):
        """Inclinar el terreno no lo hace más rugoso, y es lo que el TRI no sabía distinguir."""
        amplitude = 0.05
        rows, cols = np.indices((32, 32))
        board = amplitude * np.where((rows + cols) % 2 == 0, 1.0, -1.0)
        tilted = board + cols * DTM_GRADIENT * RESOLUTION_M

        np.testing.assert_allclose(elevation.roughness(board)[2:-2, 2:-2],
                                   elevation.roughness(tilted)[2:-2, 2:-2], atol=1e-9)

    def test_no_channel_carries_absolute_elevation(self):
        """Un canal con la cota haría que el modelo aprendiera la altitud de su mina.

        El plano se construye en `float64` a propósito: en `float32` sumar 3 000 m ya destruye los
        incrementos de 5 cm del terreno, y el test estaría midiendo el redondeo en vez de la
        invariancia. Ese redondeo es real y es justo por lo que `read_aligned` centra la ventana.
        """
        low = np.tile(np.arange(32, dtype='float64') * DTM_GRADIENT * RESOLUTION_M, (32, 1))
        high = low + 3000.0

        np.testing.assert_allclose(elevation.slope_degrees(low, RESOLUTION_M),
                                   elevation.slope_degrees(high, RESOLUTION_M), atol=1e-4)
        np.testing.assert_allclose(elevation.roughness(low), elevation.roughness(high), atol=1e-5)

    def test_float32_at_mine_altitude_would_swamp_the_roughness_signal(self):
        """Por qué `read_aligned` centra la ventana antes de remuestrear.

        A 4 100 m de cota el paso de `float32` es 4100 x 2^-23 = 0,49 mm, y el TRI que hay que
        medir son 37 mm. Este test no comprueba código del plugin: fija la medida que justifica la
        decisión, para que nadie la quite por «simplificar».
        """
        step_m = float(np.spacing(np.float32(DTM_BASE_M)))
        self.assertAlmostEqual(step_m, 0.00049, places=5)
        # La rugosidad real medida en el DTM de la mina es de 0,013 m (p50): la cuantización se
        # come un 4 % de esa señal antes siquiera de remuestrear.
        self.assertGreater(step_m / 0.013, 0.03,
                           'la cuantización pasa del 3 % de la rugosidad real de la mina')


class NormalizationTest(ElevationTestBase):
    def test_slope_normalises_against_the_declared_ceiling(self):
        slope = np.array([[0.0, 22.5, 45.0, 90.0]], dtype='float32')
        normalized = elevation.normalize_slope(slope)
        np.testing.assert_allclose(normalized, [[0.0, 0.5, 1.0, 1.0]], atol=1e-6)

    def test_roughness_saturates_above_the_measured_ceiling(self):
        rough = np.array([[0.0, 0.05, 0.10, 0.50]], dtype='float32')
        np.testing.assert_allclose(elevation.normalize_roughness(rough, 0.10),
                                   [[0.0, 0.5, 1.0, 1.0]], atol=1e-6)

    def test_a_zero_ceiling_cannot_divide_by_zero(self):
        """Terreno perfectamente liso: el p98 vale 0 y la normalización tiene que sobrevivir."""
        rough = np.zeros((4, 4), dtype='float32')
        result = elevation.normalize_roughness(rough, 0.0)
        self.assertTrue(np.isfinite(result).all())
        self.assertEqual(float(result.max()), 0.0)

    def test_a_perfectly_smooth_terrain_falls_back_to_the_floor(self):
        """El DTM de prueba es un plano, así que su rugosidad es cero en todas partes.

        El techo no puede quedar en cero —la normalización dividiría por él— y aquí se comprueba
        que cae al suelo declarado en vez de a `inf` o a `nan`.
        """
        ceiling = elevation.estimate_roughness_ceiling(self.dem, self.tiles, TILE_PX)
        self.assertEqual(ceiling, elevation.MIN_ROUGHNESS_CEILING_M)

    def test_the_metadata_says_how_to_reproduce_the_normalisation(self):
        meta = elevation.normalization_metadata(0.0375)
        self.assertEqual([b['name'] for b in meta['bands']],
                         ['red', 'green', 'blue', 'slope', 'roughness'])
        self.assertEqual(meta['bands'][3]['ceiling_deg'], 45.0)
        self.assertEqual(meta['bands'][4]['ceiling_m'], 0.0375)
        self.assertEqual(meta['output_range'], [0.0, 1.0])


class NodataTest(ElevationTestBase):
    def test_missing_elevation_is_reported_as_invalid(self):
        path = self.task.get_asset_download_path('dtm.tif')
        make_dtm(path, nodata_corner=True)

        with rasterio.open(path) as dem:
            # Última tesela de la rejilla: cae en el cuadrante sin datos.
            _, _, valid = elevation.tile_channels(dem, self.tiles[-1], TILE_PX)
        self.assertFalse(valid.any(), 'un DTM sin datos no puede dar píxeles válidos')

    def test_nodata_does_not_poison_the_neighbouring_pixels(self):
        """El operador local se calcula sobre el hueco relleno, no sobre `nan`.

        Sin el relleno, un solo píxel sin dato propagaría `nan` a sus ocho vecinos y de ahí al
        canal entero de la tesela.
        """
        path = self.task.get_asset_download_path('dtm.tif')
        make_dtm(path, nodata_corner=True)

        with rasterio.open(path) as dem:
            for tile in self.tiles:
                slope, rough, valid = elevation.tile_channels(dem, tile, TILE_PX)
                self.assertTrue(np.isfinite(slope).all(), 'la pendiente nunca puede salir nan')
                self.assertTrue(np.isfinite(rough).all(), 'la rugosidad nunca puede salir nan')


class SourceResolutionTest(ElevationTestBase):
    def test_the_dtm_wins_when_both_exist(self):
        make_dtm(self.task.get_asset_download_path('dsm.tif'))
        _, source = elevation.resolve_source(str(self.task.id), 'dtm')
        self.assertEqual(source, 'dtm')

    def test_the_dsm_is_the_fallback(self):
        import os
        os.remove(self.task.get_asset_download_path('dtm.tif'))
        make_dtm(self.task.get_asset_download_path('dsm.tif'))

        _, source = elevation.resolve_source(str(self.task.id), 'dtm')
        self.assertEqual(source, 'dsm')

    def test_asking_for_the_dsm_never_falls_back_to_the_dtm(self):
        """Quien elige el DSM pide la superficie con lo que haya encima; servirle el terreno sería
        contestar otra pregunta, y en silencio."""
        with self.assertRaises(elevation.ElevationUnavailable):
            elevation.resolve_source(str(self.task.id), 'dsm')

    def test_no_elevation_raster_at_all_raises(self):
        import os
        os.remove(self.task.get_asset_download_path('dtm.tif'))
        with self.assertRaises(elevation.ElevationUnavailable):
            elevation.resolve_source(str(self.task.id), 'dtm')
