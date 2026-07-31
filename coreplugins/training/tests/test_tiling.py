"""Rejilla de teselas (`tiling.py`, D5, D6, D11).

La rejilla tiene que ser **determinista**: dos exportaciones sin cambios intermedios deben producir
el mismo conjunto de teselas (FR-031). Por eso se ancla a la esquina superior izquierda de la
ortofoto y no a nada que dependa del momento en que se calcula.
"""

import rasterio

from coreplugins.training import tiling

from .base import ORTHO_RES, ORTHO_SIZE, TrainingTestBase, make_orthophoto


class TileGridTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.path = make_orthophoto(self.scratch_path('ortho.tif'))

    def scratch_path(self, name):
        import os
        import tempfile
        directory = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, directory, ignore_errors=True)
        return os.path.join(directory, name)

    def test_grid_covers_the_orthophoto_at_the_dataset_resolution(self):
        """30 m de lado a 10 cm/px son 300 px; con teselas de 64 px salen 5 columnas (ceil)."""
        with rasterio.open(self.path) as raster:
            tiles = list(tiling.tile_grid(raster, resolution_cm_px=10.0, tile_size_px=64))

        self.assertEqual(len(tiles), 25)
        self.assertEqual(max(t.row for t in tiles), 4)
        self.assertEqual(max(t.col for t in tiles), 4)

    def test_tile_covers_the_expected_ground_size(self):
        with rasterio.open(self.path) as raster:
            tile = next(iter(tiling.tile_grid(raster, resolution_cm_px=10.0, tile_size_px=64)))
        left, bottom, right, top = tile.bounds
        self.assertAlmostEqual(right - left, 6.4, places=6)   # 64 px * 0,10 m
        self.assertAlmostEqual(top - bottom, 6.4, places=6)

    def test_native_window_is_wider_than_the_output_when_upsampling(self):
        """D6: la ventana nativa se lee directamente al tamaño de salida, sin warp intermedio.

        La ortofoto es de 5 cm/px y el dataset de 10, así que una tesela de 64 px de salida debe
        leer 128 px nativos. Si la ventana midiera lo mismo que la salida, se estaría exportando
        media tesela con la escala equivocada.
        """
        with rasterio.open(self.path) as raster:
            tile = next(iter(tiling.tile_grid(raster, resolution_cm_px=10.0, tile_size_px=64)))
        self.assertAlmostEqual(tile.window.width, 64 * (0.10 / ORTHO_RES), places=6)
        self.assertAlmostEqual(tile.window.height, 64 * (0.10 / ORTHO_RES), places=6)

    def test_grid_is_deterministic(self):
        """FR-031: sin cambios, la misma rejilla."""
        with rasterio.open(self.path) as raster:
            first = [(t.row, t.col, tuple(t.bounds))
                     for t in tiling.tile_grid(raster, 10.0, 64)]
            second = [(t.row, t.col, tuple(t.bounds))
                      for t in tiling.tile_grid(raster, 10.0, 64)]
        self.assertEqual(first, second)

    def test_coarser_resolution_yields_fewer_tiles(self):
        """D11: a 21 cm/px salían 227 teselas frente a 912 a 10 cm/px, y de ahí la elección."""
        with rasterio.open(self.path) as raster:
            fine = len(list(tiling.tile_grid(raster, resolution_cm_px=10.0, tile_size_px=64)))
            coarse = len(list(tiling.tile_grid(raster, resolution_cm_px=21.0, tile_size_px=64)))
        self.assertLess(coarse, fine)

    def test_transform_places_the_tile_at_its_bounds(self):
        with rasterio.open(self.path) as raster:
            tiles = {(t.row, t.col): t for t in tiling.tile_grid(raster, 10.0, 64)}

        tile = tiles[(2, 3)]
        # El transform de salida debe situar el píxel (0,0) en la esquina superior izquierda de la
        # tesela: es lo que después alinea la máscara rasterizada con la imagen leída.
        self.assertAlmostEqual(tile.transform.c, tile.bounds[0], places=6)
        self.assertAlmostEqual(tile.transform.f, tile.bounds[3], places=6)
        self.assertAlmostEqual(tile.transform.a, 0.10, places=6)
        self.assertAlmostEqual(tile.transform.e, -0.10, places=6)

    def test_tiles_do_not_overlap_and_leave_no_gap(self):
        with rasterio.open(self.path) as raster:
            tiles = sorted(tiling.tile_grid(raster, 10.0, 64), key=lambda t: (t.row, t.col))

        first_row = [t for t in tiles if t.row == 0]
        for left, right in zip(first_row, first_row[1:]):
            self.assertAlmostEqual(left.bounds[2], right.bounds[0], places=6)

    def test_grid_ignores_a_task_resolution_finer_than_the_dataset(self):
        """Todas las tareas del dataset comparten escala aunque su GSD nativo difiera (FR-023).

        En las cinco ortofotos reales del usuario el GSD va de 2,22 a 6,35 cm/px; si la rejilla
        dependiera del nativo, cada tarea aportaría teselas de un tamaño de terreno distinto.
        """
        coarse_path = make_orthophoto(self.scratch_path('coarse.tif'), res=0.10,
                                      size=ORTHO_SIZE // 2)
        with rasterio.open(self.path) as fine_raster, rasterio.open(coarse_path) as coarse_raster:
            fine = next(iter(tiling.tile_grid(fine_raster, 10.0, 64)))
            coarse = next(iter(tiling.tile_grid(coarse_raster, 10.0, 64)))

        self.assertAlmostEqual(fine.bounds[2] - fine.bounds[0],
                               coarse.bounds[2] - coarse.bounds[0], places=6)
