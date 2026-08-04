"""Rejilla de trabajo, partición, costura de juntas, tolerancia y vectorización (`010`).

La ortofoto sintética de `base.py` mide 30 m: no llega ni a una celda de trabajo, así que aquí se
construye una propia de 102,4 m con textura de verdad. Sin textura SLIC devuelve una rejilla de
cuadrados y todos los tests pasarían sin ejercitar lo único que importa, que es si las regiones
siguen los bordes.
"""

import os
import shutil
import tempfile

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.windows import Window

from django.test import SimpleTestCase

from coreplugins.training import models, superpixels, tiling

EPSG = 32719
ORIGIN = (400000.0, 6000000.0)
NATIVE_RES = 0.05
RESOLUTION_CM_PX = 10.0
# 2048 px nativos a 5 cm son 102,4 m, o sea 1024 px de salida a 10 cm: exactamente 2 x 2 celdas.
NATIVE_SIZE = 2048

# Columna de salida por la que corre la «pista» vertical, y su ancho. Cae dentro de la columna de
# celdas 0 y cruza la junta horizontal entre las celdas (0,0) y (1,0), que es lo que hay que probar.
ROAD_COL_PX = 256
ROAD_HALF_WIDTH_PX = 20


def make_textured_orthophoto(path, size=NATIVE_SIZE, res=NATIVE_RES, origin=ORIGIN, epsg=EPSG):
    """Ortofoto sintética con una pista clara sobre terreno texturado.

    Todo es determinista (`RandomState` con semilla fija): un test que dependiera de ruido sin
    semilla fallaría de vez en cuando y nadie sabría por qué.

    - **Pista vertical clara** en la columna de salida `ROAD_COL_PX`, que cruza la junta entre las
      celdas (0,0) y (1,0). Es la región que la costura tiene que devolver entera.
    - **Dos zonas de fondo** de tono distinto, para que la tolerancia tenga un borde donde pararse.
    - **Textura** de grano fino, sin la cual SLIC devuelve una rejilla y los tests no probarían nada.
    - **Un cuadrado con alfa 0**, que es el perímetro sin datos de vuelo de una ortofoto real.
    """
    rng = np.random.RandomState(20260802)
    factor = int(round((RESOLUTION_CM_PX / 100.0) / res))   # px nativos por px de salida

    yy, xx = np.mgrid[0:size, 0:size]
    base = np.where(xx < size // 2, 70, 95).astype('float32')
    base += 18.0 * np.sin(xx / 23.0) * np.cos(yy / 31.0)
    base += rng.normal(0.0, 6.0, (size, size))

    road = np.abs(xx - ROAD_COL_PX * factor) < ROAD_HALF_WIDTH_PX * factor
    image = np.where(road, 205.0 + rng.normal(0.0, 4.0, (size, size)), base)
    image = np.clip(image, 0, 255)

    red = image.astype('uint8')
    green = np.clip(image * 0.95, 0, 255).astype('uint8')
    blue = np.clip(image * 0.80, 0, 255).astype('uint8')
    alpha = np.full((size, size), 255, dtype='uint8')
    # Sin datos de vuelo: esquina inferior derecha de la celda (1,1).
    alpha[size - 200:, size - 200:] = 0

    os.makedirs(os.path.dirname(path), exist_ok=True)
    profile = {
        'driver': 'GTiff', 'width': size, 'height': size, 'count': 4, 'dtype': 'uint8',
        'crs': CRS.from_epsg(epsg), 'transform': from_origin(origin[0], origin[1], res, res),
        'tiled': True, 'blockxsize': 256, 'blockysize': 256,
    }
    with rasterio.open(path, 'w', **profile) as dst:
        dst.write(red, 1)
        dst.write(green, 2)
        dst.write(blue, 3)
        dst.write(alpha, 4)
    return path


class _SyntheticRasterCase(SimpleTestCase):
    """Base con la ortofoto texturada creada una sola vez: escribirla cuesta ~1 s."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.directory = tempfile.mkdtemp(prefix='training-superpixels-')
        cls.orthophoto = make_textured_orthophoto(os.path.join(cls.directory, 'ortho.tif'))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.ortho = rasterio.open(self.orthophoto)
        self.addCleanup(self.ortho.close)
        self.grid = superpixels.WorkGrid(self.ortho, RESOLUTION_CM_PX, 'medium')

    def cell(self, row, col, elevation_weight=0.0):
        return superpixels.partition_cell(self.ortho, None, self.grid, row, col,
                                          elevation_weight=elevation_weight)

    def window_partition(self, px0, py0, width, height):
        """Partición cruda de una ventana arbitraria en píxeles globales de salida.

        Sirve para construir la referencia del test de junta y para el control desalineado.
        """
        resolution_m = self.grid.resolution_m
        x0 = self.grid.left + px0 * resolution_m
        y1 = self.grid.top - py0 * resolution_m
        tile = tiling.Tile(
            row=0, col=0,
            window=Window((x0 - self.grid.left) / self.grid.native_x,
                          (self.grid.top - y1) / self.grid.native_y,
                          width * resolution_m / self.grid.native_x,
                          height * resolution_m / self.grid.native_y),
            transform=from_origin(x0, y1, resolution_m, resolution_m),
            bounds=None, bounds_wgs84=None)

        rgb = self.ortho.read((1, 2, 3), window=tile.window, out_shape=(3, height, width),
                              boundless=True, fill_value=0)
        bands = np.stack([rgb[i].astype('float32') / 255.0 for i in range(3)], axis=-1)
        return superpixels.partition_window(bands, self.grid.spacing)


# --- Rejilla de trabajo (T007) -----------------------------------------------------------

class WorkGridTest(_SyntheticRasterCase):

    def test_granularities_match_models(self):
        """Los nombres viven en `models` y los píxeles en `superpixels`; no pueden separarse."""
        self.assertEqual(set(models.GRANULARITIES), set(superpixels.GRANULARITIES))
        self.assertEqual(models.DEFAULT_GRANULARITY, superpixels.DEFAULT_GRANULARITY)

    def test_unknown_granularity_is_an_explicit_error(self):
        with self.assertRaises(ValueError):
            superpixels.spacing_px('enorme')

    def test_spacing_divides_the_cell(self):
        """Invariante de la que depende que las ventanas queden alineadas."""
        for granularity in superpixels.GRANULARITIES:
            spacing = superpixels.spacing_px(granularity)
            self.assertEqual(superpixels.CELL_PX % spacing, 0,
                             'S={} no divide a CELL={}'.format(spacing, superpixels.CELL_PX))

    def test_window_origin_is_a_multiple_of_spacing(self):
        """Lo que hace que dos celdas vecinas reciban la misma rejilla de semillas."""
        for granularity in superpixels.GRANULARITIES:
            grid = superpixels.WorkGrid(self.ortho, RESOLUTION_CM_PX, granularity)
            for row in range(grid.rows):
                for col in range(grid.cols):
                    px, py = grid.window_origin_px(row, col)
                    self.assertEqual(px % grid.spacing, 0)
                    self.assertEqual(py % grid.spacing, 0)
                    self.assertEqual(grid.window_size % grid.spacing, 0)

    def test_cell_of_a_point_does_not_depend_on_the_framing(self):
        """FR-008. La celda es función del terreno, y de nada más.

        Se construyen dos rejillas por separado y se les pregunta por el mismo punto: no hay ningún
        estado compartido que pueda hacerlas coincidir por casualidad.
        """
        x = ORIGIN[0] + 60.0
        y = ORIGIN[1] - 70.0
        first = superpixels.WorkGrid(self.ortho, RESOLUTION_CM_PX, 'medium').cell_of_xy(x, y)
        second = superpixels.WorkGrid(self.ortho, RESOLUTION_CM_PX, 'medium').cell_of_xy(x, y)
        self.assertEqual(first, second)
        self.assertEqual(first, (1, 1))   # 70 m y 60 m a 51,2 m por celda

    def test_a_point_outside_the_raster_is_rejected(self):
        with self.assertRaises(superpixels.OutsideRaster):
            self.grid.cell_of_xy(ORIGIN[0] - 10.0, ORIGIN[1])

    def test_a_window_that_is_not_a_multiple_of_the_spacing_is_refused(self):
        """Una ventana desalineada desanclaría las semillas: mejor un error que una junta."""
        bands = np.zeros((100, 100, 3), dtype='float32')
        with self.assertRaises(ValueError):
            superpixels.partition_window(bands, 16)


# --- La junta (T011) ---------------------------------------------------------------------

def iou(a, b):
    union = np.logical_or(a, b).sum()
    return float(np.logical_and(a, b).sum()) / float(union) if union else 0.0


def disagreement(a, b):
    """% de pares de píxeles vecinos que discrepan sobre si están en la misma región.

    Compara particiones sin depender de cómo estén numeradas, que es lo que hace falta: dos
    particiones idénticas calculadas por separado no tienen por qué usar los mismos índices.
    """
    bad = total = 0
    for first, second in ((np.s_[:-1, :], np.s_[1:, :]), (np.s_[:, :-1], np.s_[:, 1:])):
        same_a = a[first] == a[second]
        same_b = b[first] == b[second]
        bad += int((same_a != same_b).sum())
        total += same_a.size
    return 100.0 * bad / total


class SeamTest(_SyntheticRasterCase):
    """**El test que no se puede saltar.**

    Sostiene FR-007 y FR-009, que son invisibles en revisión de código: romperlos no lanza ningún
    error, solo hace que de vez en cuando una región termine en una línea recta perfecta justo donde
    cae el borde de una celda. Quien cambie `COMPACTNESS`, `HALO_FACTOR`, `CELL_PX` o el
    `n_segments` de `partition_window` verá aquí lo que ha roto.

    Lo que se afirma **no** es que las dos celdas produzcan particiones idénticas: con la
    `compactness` que hace que las regiones sigan los bordes, eso es falso y está medido
    (research.md D2, corrección). Lo que se afirma es lo que el usuario percibe — que la región
    cruza la junta entera — y que la costura es lo que lo consigue.
    """

    def setUp(self):
        super().setUp()
        self.top = self.cell(0, 0)
        self.bottom = self.cell(1, 0)
        self.partitions = {(0, 0): self.top, (1, 0): self.bottom}

    def _road_seed(self):
        """Una región de la pista pegada al borde inferior del núcleo de la celda (0,0)."""
        edge = self.top.labels[-1, :]
        return int(edge[ROAD_COL_PX])

    def test_the_road_region_continues_across_the_seam(self):
        region = self._road_seed()
        self.assertTrue(self.top.continues['bottom'][ROAD_COL_PX],
                        'La región de la pista toca la junta pero se declara terminada en ella: '
                        'la costura no tendría nada por donde cruzar.')

        fragments, _ = superpixels.cross_cell_links(
            self.top, region, (0, 0), lambda r, c: self.partitions.get((r, c)))
        self.assertTrue(fragments, 'La región no encontró ningún fragmento en la celda de abajo.')
        self.assertTrue(all(cell[:2] == (1, 0) for cell in fragments))

    def test_the_selection_crosses_the_seam(self):
        """FR-009 tal y como se ve: la selección no termina en el borde de la celda."""
        seed = (0, 0, self._road_seed())
        selection = superpixels.grow([seed], 0.0, lambda r, c: self.partitions.get((r, c)))

        cells = {(row, col) for row, col, _ in selection.regions}
        self.assertIn((1, 0), cells,
                      'La selección se quedó dentro de la celda del clic: eso es exactamente el '
                      'corte recto en la junta que FR-009 prohíbe.')
        self.assertFalse(selection.truncated)

    def test_stitching_recovers_the_region_that_a_single_cell_truncates(self):
        """El número que justifica la costura y el halo `8·S`.

        Se compara contra una partición de referencia calculada sobre una ventana que abarca las
        **dos** celdas con halo grande — o sea, la partición que no tiene ninguna junta que coser.
        """
        halo = 24 * self.grid.spacing
        reference = self.window_partition(
            -halo, -halo, superpixels.CELL_PX + 2 * halo, 2 * superpixels.CELL_PX + 2 * halo)
        reference = reference[halo:halo + 2 * superpixels.CELL_PX, halo:halo + superpixels.CELL_PX]

        seed_row = superpixels.CELL_PX - 1
        truth = reference == reference[seed_row, ROAD_COL_PX]
        self.assertTrue(truth[superpixels.CELL_PX:, :].any(),
                        'La región de referencia no cruza la junta: el montaje del test no prueba '
                        'lo que dice probar.')

        region = self._road_seed()
        without = np.zeros_like(truth)
        without[:superpixels.CELL_PX, :] = self.top.labels == region

        selection = superpixels.grow([(0, 0, region)], 0.0,
                                     lambda r, c: self.partitions.get((r, c)))
        with_stitching = np.zeros_like(truth)
        for row, col, index in selection.regions:
            block = self.partitions[(row, col)].labels == index
            with_stitching[row * superpixels.CELL_PX:(row + 1) * superpixels.CELL_PX, :] |= block

        stitched_iou = iou(truth, with_stitching)
        truncated_iou = iou(truth, without)
        self.assertGreater(
            stitched_iou, truncated_iou,
            'Coser no mejoró nada ({:.3f} vs {:.3f}): o la costura no funciona, o el montaje del '
            'test dejó de tener una región que cruce.'.format(stitched_iou, truncated_iou))
        self.assertGreater(
            stitched_iou, 0.85,
            'La región cosida solo recupera el {:.1%} de la región sin junta. Medido sobre datos '
            'reales daba 0,981 con halo 8·S; por debajo de 0,85 algo movió el halo, la '
            'compactness o la alineación de las ventanas.'.format(stitched_iou))

    def test_alignment_is_what_makes_the_partitions_comparable(self):
        """Desalinear la ventana un número de píxeles que no sea múltiplo de `S` la descuadra.

        Es la invariante de `window_origin_px`. Medido sobre la ortofoto real: 0,960 % alineada
        frente a 11,343 % desalineada 7 px.
        """
        spacing = self.grid.spacing
        halo = superpixels.HALO_FACTOR * spacing
        size = superpixels.CELL_PX + 2 * halo
        core = np.s_[halo:halo + superpixels.CELL_PX, halo:halo + superpixels.CELL_PX]

        reference = self.window_partition(-halo, -halo, size, size)[core]
        aligned = self.window_partition(-halo + spacing, -halo + spacing, size, size)
        aligned = aligned[halo - spacing:halo - spacing + superpixels.CELL_PX,
                          halo - spacing:halo - spacing + superpixels.CELL_PX]
        offset = 7
        misaligned = self.window_partition(-halo + offset, -halo + offset, size, size)
        misaligned = misaligned[halo - offset:halo - offset + superpixels.CELL_PX,
                                halo - offset:halo - offset + superpixels.CELL_PX]

        self.assertLess(
            disagreement(aligned, reference), disagreement(misaligned, reference),
            'Una ventana desplazada un múltiplo de S={} debe coincidir mucho mejor con la '
            'referencia que una desplazada {} px. Si no, el anclaje de las semillas dejó de '
            'funcionar y las juntas volverán.'.format(spacing, offset))


# --- Vectorización (T016) ----------------------------------------------------------------

class VectorizeTest(_SyntheticRasterCase):

    def test_geometry_is_a_closed_multipolygon(self):
        partition = self.cell(0, 0)
        region = int(partition.labels[100, ROAD_COL_PX])
        geometry = superpixels.selection_geometry(self.grid, {(0, 0, region)}, {(0, 0): partition})

        self.assertIsNotNone(geometry)
        self.assertEqual(geometry['type'], 'MultiPolygon')
        self.assertTrue(geometry['coordinates'])
        for polygon in geometry['coordinates']:
            for ring in polygon:
                self.assertGreaterEqual(len(ring), 4)
                self.assertEqual(ring[0], ring[-1], 'Los anillos deben venir cerrados.')

    def test_coordinates_are_lon_lat_and_land_where_they_should(self):
        """Contra el fallo de `GEOSGeometry.transform`, que invierte los ejes sin protestar.

        Un `(lat, lon)` en vez de `(lon, lat)` no lanza nada: la etiqueta se guarda y aparece en
        mitad del océano Índico. Se comprueba contra la esquina conocida de la ortofoto.
        """
        from rasterio.warp import transform as warp_transform

        partition = self.cell(0, 0)
        region = int(partition.labels[100, ROAD_COL_PX])
        geometry = superpixels.selection_geometry(self.grid, {(0, 0, region)}, {(0, 0): partition})

        lngs, lats = warp_transform(self.grid.crs, 'EPSG:4326', [ORIGIN[0]], [ORIGIN[1]])
        expected_lng, expected_lat = lngs[0], lats[0]

        for polygon in geometry['coordinates']:
            for ring in polygon:
                for lng, lat in ring:
                    self.assertAlmostEqual(lng, expected_lng, places=2)
                    self.assertAlmostEqual(lat, expected_lat, places=2)

    def test_an_empty_selection_has_no_geometry(self):
        self.assertIsNone(superpixels.selection_geometry(self.grid, set(), {}))


# --- Tolerancia (T039, T040) -------------------------------------------------------------

class ToleranceTest(_SyntheticRasterCase):

    def setUp(self):
        super().setUp()
        self.partition = self.cell(0, 0)
        self.load = lambda row, col: self.partition if (row, col) == (0, 0) else None
        self.seed = (0, 0, int(self.partition.labels[256, ROAD_COL_PX]))

    def test_zero_tolerance_selects_exactly_one_region(self):
        selection = superpixels.grow([self.seed], 0.0, self.load)
        self.assertEqual(len(selection.regions), 1)
        self.assertFalse(selection.truncated)

    def test_growth_is_monotone(self):
        """FR-017: la selección con tolerancia menor está **contenida** en la de tolerancia mayor.

        Es lo que hace que el control de tolerancia se sienta como un control y no como una
        ruleta: subirlo solo puede añadir terreno, nunca cambiar el que ya estaba.
        """
        previous = None
        for tolerance in (0.0, 0.02, 0.05, 0.1, 0.2):
            current = superpixels.grow([self.seed], tolerance, self.load).regions
            if previous is not None:
                self.assertTrue(
                    previous <= current,
                    'Con tolerancia {} se perdieron regiones que la tolerancia anterior sí '
                    'seleccionaba.'.format(tolerance))
            previous = current

    def test_growth_stops_at_the_cap_and_says_so(self):
        """FR-018: el tope se declara, no se disimula."""
        selection = superpixels.grow([self.seed], 1.0, self.load, max_regions=12)
        self.assertTrue(selection.truncated)
        self.assertLessEqual(len(selection.regions), 12)

    def test_growth_that_fits_is_not_reported_as_truncated(self):
        selection = superpixels.grow([self.seed], 0.0, self.load, max_regions=12)
        self.assertFalse(selection.truncated)


# --- Sin elevación (T047) ----------------------------------------------------------------

class WithoutElevationTest(_SyntheticRasterCase):

    def test_three_bands_without_a_dem(self):
        """FR-011: trabajar sin terreno es un modo de uso, no un error."""
        partition = superpixels.partition_cell(self.ortho, None, self.grid, 0, 0,
                                               elevation_weight=1.0)
        self.assertEqual(partition.band_count, 3)
        self.assertEqual(partition.means.shape[1], 3)
        self.assertGreater(partition.means.shape[0], 100)

    def test_the_partition_is_usable_without_terrain(self):
        """No basta con que no falle: tiene que seguir dando regiones que sirvan para etiquetar."""
        partition = superpixels.partition_cell(self.ortho, None, self.grid, 0, 0,
                                               elevation_weight=0.0)
        sizes = np.bincount(partition.labels.ravel())
        sizes = sizes[sizes > 0]
        self.assertGreater(sizes.size, 500)
        self.assertLess(np.median(sizes), 4 * self.grid.spacing ** 2)

    def test_the_no_data_corner_is_marked_invalid(self):
        """El alfa a 0 llega hasta `valid`: es lo que convierte un clic ahí en `no_data`."""
        partition = superpixels.partition_cell(self.ortho, None, self.grid, 1, 1,
                                               elevation_weight=0.0)
        self.assertFalse(partition.valid[-1, -1])
        self.assertTrue(partition.valid[0, 0])
