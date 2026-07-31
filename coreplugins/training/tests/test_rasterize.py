"""Máscaras (`rasterize.py`) — las invariantes 1 a 3 de `data-model.md`.

Estas son las comprobaciones que sostienen SC-003 («las máscaras coinciden con lo dibujado») y
FR-026 (lo no etiquetado sale como 255 y nunca como clase 0). El fallo que evitan es silencioso:
una máscara mal compuesta no rompe nada, entrena un modelo peor y nadie se entera hasta después de
gastar horas de GPU.
"""

import numpy as np
import rasterio

from coreplugins.training import models, rasterize, tiling

from .base import TrainingTestBase, make_orthophoto, offset_to_lnglat


def square(dx, dy, side):
    """Cuadrado de `side` m con la esquina superior izquierda a (dx, dy) m del origen."""
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]


def label(class_index, geometry, order, kind='polygon', radius_m=None):
    return {'id': 'l{}'.format(order), 'class_index': class_index, 'kind': kind,
            'geometry': geometry, 'radius_m': radius_m, 'order': order, 'source': 'manual'}


class RasterizeTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        import os
        import shutil
        import tempfile
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        self.path = make_orthophoto(os.path.join(directory, 'ortho.tif'))
        self.raster = rasterio.open(self.path)
        self.addCleanup(self.raster.close)
        # Una sola tesela de 30 m de lado a 10 cm/px: 300 px, toda la ortofoto.
        self.tile = next(iter(tiling.tile_grid(self.raster, resolution_cm_px=10.0,
                                               tile_size_px=300)))
        self.crs = self.raster.crs

    def render(self, labels):
        return rasterize.rasterize_tile(labels, self.tile, self.crs, tile_size_px=300)

    # --- Invariante 1: lo no etiquetado es 255 -------------------------------------------

    def test_an_empty_tile_is_all_ignore(self):
        mask = self.render([])
        self.assertEqual(mask.dtype, np.uint8)
        self.assertEqual(mask.shape, (300, 300))
        self.assertTrue((mask == models.IGNORE_INDEX).all(),
                        'sin etiquetas, todo debe ser «ignorar» y nunca clase 0')

    def test_pixels_outside_every_label_stay_ignore(self):
        """FR-026: si lo no etiquetado saliera como clase 0, cada camino que el usuario olvidara
        marcar le enseñaría al modelo que los caminos no son caminos."""
        mask = self.render([label(1, square(0, 0, 5), 0)])
        self.assertEqual(mask[0, 0], 1)                       # dentro del cuadrado
        self.assertEqual(mask[-1, -1], models.IGNORE_INDEX)   # fuera

    # --- Invariante 2: gana la de mayor `order` -----------------------------------------

    def test_the_last_label_wins_on_overlap(self):
        mask = self.render([
            label(0, square(0, 0, 20), 0),   # fondo grande
            label(1, square(5, 5, 5), 1),    # camino encima
        ])
        self.assertEqual(mask[75, 75], 1, 'en la zona solapada gana la última dibujada')
        self.assertEqual(mask[10, 10], 0, 'fuera del solape sigue el fondo')
        # 5 x 5 m a 10 cm/px son 50 x 50 px: el camino tapa exactamente su superficie, ni un
        # píxel más. Comprobar el área y no solo un punto es lo que distingue «gana el último»
        # de «se pintó algo por ahí».
        self.assertEqual(int((mask == 1).sum()), 2500)

    def test_order_decides_regardless_of_list_position(self):
        """La lista puede llegar desordenada; lo que manda es `order`, no el índice del array."""
        out_of_order = [
            label(1, square(5, 5, 5), 1),
            label(0, square(0, 0, 20), 0),
        ]
        mask = self.render(out_of_order)
        self.assertEqual(mask[75, 75], 1)

    def test_a_lower_order_label_does_not_erase_a_higher_one(self):
        mask = self.render([
            label(1, square(5, 5, 5), 5),
            label(0, square(0, 0, 20), 2),
        ])
        self.assertEqual(mask[75, 75], 1)

    # --- El borrador ---------------------------------------------------------------------

    def test_the_eraser_returns_pixels_to_ignore_not_to_background(self):
        """FR-014: la diferencia no se ve en el mapa, se ve aquí."""
        mask = self.render([
            label(0, square(0, 0, 20), 0),
            label(None, square(5, 5, 5), 1),
        ])
        self.assertEqual(mask[75, 75], models.IGNORE_INDEX)
        self.assertEqual(mask[10, 10], 0)

    def test_painting_over_an_erasure_works_again(self):
        mask = self.render([
            label(1, square(0, 0, 20), 0),
            label(None, square(0, 0, 20), 1),
            label(1, square(5, 5, 5), 2),
        ])
        self.assertEqual(mask[75, 75], 1)
        self.assertEqual(mask[10, 10], models.IGNORE_INDEX)

    # --- Invariante 3: el trazo cubre el área de su buffer -------------------------------

    def test_a_stroke_covers_the_area_of_its_buffer(self):
        """D8, medido: una polilínea de 20 m con radio 2,5 m da 118,14 m² de polígono, y su
        rasterizado a 10 cm/px 11 825 px = 118,25 m². Aquí se rehace la misma comprobación.

        La tolerancia es del 2 %: la diferencia entre ambos números es de discretización, no de
        error, y apretarla más solo haría el test frágil frente al número de segmentos con que
        GEOS aproxima los extremos redondeados.
        """
        stroke = [list(offset_to_lnglat(5, 15)), list(offset_to_lnglat(25, 15))]
        mask = self.render([label(1, stroke, 0, kind='stroke', radius_m=2.5)])

        pixels = int((mask == 1).sum())
        area_m2 = pixels * 0.10 * 0.10          # cada píxel son 10 cm x 10 cm
        expected = 20 * 2 * 2.5 + 3.14159 * 2.5 ** 2   # rectángulo + los dos semicírculos
        self.assertAlmostEqual(area_m2, expected, delta=expected * 0.02)

    def test_stroke_width_follows_the_radius_in_meters(self):
        """El radio está en metros de terreno (FR-010, FR-012b).

        Si se interpretara sobre coordenadas angulares, el trazo saldría cinco órdenes de magnitud
        mayor y cubriría la tesela entera: por eso se compara el ancho medido, no solo que haya
        píxeles pintados.
        """
        stroke = [list(offset_to_lnglat(5, 15)), list(offset_to_lnglat(25, 15))]
        mask = self.render([label(1, stroke, 0, kind='stroke', radius_m=2.5)])

        column = mask[:, 150]                    # corte vertical por el centro del trazo
        painted_px = int((column == 1).sum())
        self.assertAlmostEqual(painted_px * 0.10, 5.0, delta=0.3)   # diámetro = 2 x 2,5 m

    def test_doubling_the_radius_doubles_the_width(self):
        stroke = [list(offset_to_lnglat(5, 15)), list(offset_to_lnglat(25, 15))]
        thin = self.render([label(1, stroke, 0, kind='stroke', radius_m=1.0)])
        thick = self.render([label(1, stroke, 0, kind='stroke', radius_m=2.0)])

        thin_width = int((thin[:, 150] == 1).sum())
        thick_width = int((thick[:, 150] == 1).sum())
        self.assertAlmostEqual(thick_width / thin_width, 2.0, delta=0.1)

    # --- Alcance y determinismo ---------------------------------------------------------

    def test_labels_outside_the_tile_do_not_bleed_in(self):
        far = square(1000, 1000, 10)   # a un kilómetro de la ortofoto
        mask = self.render([label(1, far, 0)])
        self.assertTrue((mask == models.IGNORE_INDEX).all())

    def test_rasterizing_twice_gives_the_same_mask(self):
        """FR-031: dos exportaciones sin cambios producen las mismas máscaras."""
        labels = [label(0, square(0, 0, 20), 0), label(1, square(5, 5, 5), 1)]
        self.assertTrue(np.array_equal(self.render(labels), self.render(labels)))

    def test_class_pixel_counts_exclude_the_ignore_value(self):
        """`class_pixels` del manifiesto no incluye el 255: se deduce restando del total."""
        mask = self.render([label(1, square(0, 0, 10), 0)])
        counts = rasterize.class_pixel_counts(mask)
        self.assertNotIn(models.IGNORE_INDEX, counts)
        self.assertEqual(counts[1], int((mask == 1).sum()))

    def test_labeled_fraction_measures_what_is_not_ignored(self):
        mask = self.render([label(1, square(0, 0, 15), 0)])   # 15x15 m de 30x30 m = 25 %
        self.assertAlmostEqual(rasterize.labeled_fraction(mask), 0.25, delta=0.01)
