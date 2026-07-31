"""Reparto train/val por zonas (`split.py`, D19).

Lo que se protege aquí es una sola propiedad, y es la que da sentido a la métrica de validación:
**ningún píxel de val aparece en train**. Con teselas solapadas es fácil violarla sin que nada
falle: el entrenamiento corre, la métrica sube y la subida no significa nada.
"""

from django.test import SimpleTestCase

from coreplugins.training import split, tiling


def grid(rows, cols, task='t'):
    return [(task, r, c) for r in range(rows) for c in range(cols)]


class BlockAssignmentTest(SimpleTestCase):
    def test_whole_blocks_go_to_the_same_side(self):
        assignments = split.assign_tiles(grid(8, 8), block_tiles=4, val_fraction=0.5, seed='s',
                                         reach=0)
        blocks = {}
        for (task, row, col), side in assignments.items():
            blocks.setdefault((row // 4, col // 4), set()).add(side)

        for block, sides in blocks.items():
            self.assertEqual(len(sides), 1,
                             'el bloque {} quedó partido entre train y val'.format(block))

    def test_the_requested_fraction_is_respected(self):
        # 16x16 teselas en bloques de 4 son 16 bloques, así que el 25 % son 4 bloques exactos. Con
        # una rejilla que no divida, el reparto solo puede acercarse: se reparten bloques enteros.
        assignments = split.assign_tiles(grid(16, 16), block_tiles=4, val_fraction=0.25, seed='s',
                                         reach=0)
        self.assertEqual(split.summarize(assignments)['val_fraction'], 0.25)

    def test_an_indivisible_grid_gets_the_closest_whole_block(self):
        # 25 bloques al 25 % son 6,25: se reparten 6, o sea el 24 %.
        assignments = split.assign_tiles(grid(20, 20), block_tiles=4, val_fraction=0.25, seed='s',
                                         reach=0)
        self.assertEqual(split.summarize(assignments)['val_fraction'], 0.24)

    def test_the_same_seed_gives_the_same_split(self):
        first = split.assign_tiles(grid(8, 8), seed='dataset-a')
        second = split.assign_tiles(grid(8, 8), seed='dataset-a')
        self.assertEqual(first, second)

    def test_different_seeds_give_different_splits(self):
        # 64 bloques, no 4: con pocos bloques dos semillas distintas caen en el mismo reparto con
        # probabilidad alta y el test fallaría de vez en cuando sin que nada estuviera roto.
        first = split.assign_tiles(grid(16, 16), block_tiles=2, seed='dataset-a')
        second = split.assign_tiles(grid(16, 16), block_tiles=2, seed='dataset-b')
        self.assertNotEqual(first, second)

    def test_neither_side_is_ever_left_empty(self):
        """Un split con un lado vacío no es un split, y descubrirlo tras entrenar cuesta caro."""
        for fraction in (0.01, 0.05, 0.95, 0.99):
            summary = split.summarize(
                split.assign_tiles(grid(4, 4), block_tiles=2, val_fraction=fraction, seed='s',
                                   reach=0))
            self.assertGreater(summary['val'], 0, 'val vacío con fracción {}'.format(fraction))
            self.assertGreater(summary['train'], 0, 'train vacío con fracción {}'.format(fraction))

    def test_a_single_block_stays_in_train(self):
        assignments = split.assign_tiles(grid(2, 2), block_tiles=4, val_fraction=0.2, seed='s')
        self.assertEqual(set(assignments.values()), {split.TRAIN})

    def test_tasks_do_not_share_blocks(self):
        """Dos ortofotos no comparten rejilla: mezclar sus índices juntaría sitios a kilómetros."""
        assignments = split.assign_tiles(grid(4, 4, 'a') + grid(4, 4, 'b'), block_tiles=4,
                                         val_fraction=0.5, seed='s', reach=0)
        sides_a = {side for (task, _, _), side in assignments.items() if task == 'a'}
        sides_b = {side for (task, _, _), side in assignments.items() if task == 'b'}
        self.assertEqual(len(sides_a), 1)
        self.assertEqual(len(sides_b), 1)
        self.assertNotEqual(sides_a, sides_b)


class GutterTest(SimpleTestCase):
    def test_no_train_tile_touches_a_val_block(self):
        """La garantía completa: con `reach=1`, ninguna tesela de train es vecina de una de val."""
        assignments = split.assign_tiles(grid(12, 12), block_tiles=4, val_fraction=0.25, seed='s',
                                         reach=1)
        val = {key for key, side in assignments.items() if side == split.VAL}

        for (task, row, col), side in assignments.items():
            if side != split.TRAIN:
                continue
            for delta_row in (-1, 0, 1):
                for delta_col in (-1, 0, 1):
                    self.assertNotIn((task, row + delta_row, col + delta_col), val,
                                     'la tesela de train ({},{}) toca una de val'.format(row, col))

    def test_the_gutter_costs_tiles_and_says_how_many(self):
        assignments = split.assign_tiles(grid(12, 12), block_tiles=4, val_fraction=0.25, seed='s',
                                         reach=1)
        summary = split.summarize(assignments)
        self.assertGreater(summary['dropped_by_gutter'], 0)
        self.assertEqual(summary['train'] + summary['val'] + summary['dropped_by_gutter'], 144)

    def test_without_overlap_there_is_no_gutter(self):
        """Sin solape las teselas no comparten píxeles y no hay nada que separar."""
        assignments = split.assign_tiles(grid(12, 12), block_tiles=4, val_fraction=0.25, seed='s',
                                         reach=0)
        self.assertEqual(split.summarize(assignments)['dropped_by_gutter'], 0)


class ReachTest(SimpleTestCase):
    def test_the_reach_comes_from_the_stride(self):
        # Sin solape: el paso iguala al tamaño y las teselas no se tocan.
        self.assertEqual(split.neighbour_reach(512, 512), 0)
        # El caso de la especificación: 512 con 64 de solape -> paso 448, alcanza a la vecina.
        self.assertEqual(split.neighbour_reach(512, 448), 1)
        # Solape mayor que la mitad: la tesela alcanza a dos vecinas a cada lado.
        self.assertEqual(split.neighbour_reach(512, 200), 2)

    def test_the_reach_matches_the_real_grid(self):
        """El alcance tiene que coincidir con qué teselas se solapan de verdad."""
        for tile_size, overlap in ((512, 64), (512, 256), (512, 400), (64, 8)):
            stride = tiling.stride(tile_size, overlap)
            reach = split.neighbour_reach(tile_size, stride)

            # La tesela `reach` sí solapa con la 0; la `reach + 1` ya no.
            self.assertLess(reach * stride, tile_size,
                            'reach {} debería solapar con {}/{}'.format(reach, tile_size, overlap))
            self.assertGreaterEqual((reach + 1) * stride, tile_size,
                                    'reach {} se queda corto con {}/{}'.format(
                                        reach, tile_size, overlap))
