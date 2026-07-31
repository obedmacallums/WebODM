"""Paquete exportado (`export.py`, `contracts/dataset-package.md`).

Este es el contrato más caro de cambiar de la feature: lo consume a ciegas la imagen de
entrenamiento, desde otra máquina y sin acceso a WebODM. Lo que se comprueba aquí es que el
paquete se baste a sí mismo (FR-029) y que sus filtros, sus canales y su determinismo se comporten
como promete el contrato.

Las teselas son GeoTIFF y no PNG, así que se abren con `rasterio` sobre un `MemoryFile`: leerlas
como imágenes sueltas habría dejado sin comprobar justo lo que el formato aporta, que es que cada
tesela sepa dónde está.
"""

import json
import zipfile

import numpy as np
import rasterio

from coreplugins.training import elevation, export, models, split, store

from .base import (DTM_GRADIENT, TrainingTestBase, expected_slope_degrees, offset_to_lnglat)


def square(dx, dy, side):
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]


def read_raster(archive, name):
    """`(array, dataset abierto)` de una tesela del zip."""
    with rasterio.io.MemoryFile(archive.read(name)) as memfile:
        with memfile.open() as src:
            return src.read(), src.profile, src.transform, src.crs, src.descriptions


class ExportTestBase(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task, tile_size_px=64)

    def run_export(self, dataset=None, **kwargs):
        dataset = dataset or store.get_dataset(self.dataset['id'])
        result = export.build_package(dataset, **kwargs)
        self.addCleanup(export.delete_package, dataset['id'], result['export_id'])
        return result

    def open_package(self, result):
        archive = zipfile.ZipFile(result['path'])
        self.addCleanup(archive.close)
        return archive, json.loads(archive.read('dataset.json'))


class PackageStructureTest(ExportTestBase):
    def setUp(self):
        super().setUp()
        # Ortofoto entera revisada y un camino encima: la composición mínima que produce teselas
        # con fondo real (0) y clase (1).
        self._review_all(self.dataset, self.task)
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 6))

    def test_package_pairs_every_image_with_its_mask(self):
        archive, meta = self.open_package(self.run_export())

        images = [n for n in archive.namelist() if n.startswith('images/')]
        masks = [n for n in archive.namelist() if n.startswith('masks/')]
        self.assertTrue(images, 'el paquete debe traer teselas')
        self.assertEqual(len(images), len(masks))
        self.assertEqual(len(images), len(meta['tiles']))

        for name in images:
            self.assertIn(name.replace('images/', 'masks/'), masks,
                          'cada imagen necesita su máscara con el mismo nombre')

    def test_metadata_declares_everything_the_trainer_needs(self):
        """FR-028 y FR-029: `dataset.json` se basta solo, sin acceso a WebODM ni a la spec."""
        _, meta = self.open_package(self.run_export())

        self.assertEqual(meta['schema_version'], 2)
        self.assertEqual(meta['ignore_index'], 255)
        self.assertEqual(meta['background_index'], 0)
        self.assertEqual(meta['resolution_cm_px'], 10.0)
        self.assertEqual(meta['tile_size_px'], 64)
        self.assertEqual(meta['tile_overlap_px'], 8)
        self.assertEqual(meta['stride_px'], 56)
        self.assertEqual(meta['bands'], ['red', 'green', 'blue', 'slope', 'roughness'])
        self.assertEqual(meta['elevation_source'], 'dtm')
        self.assertEqual([(c['index'], c['name']) for c in meta['classes']],
                         [(0, 'background'), (1, 'road')])

        self.assertEqual(meta['dataset']['id'], self.dataset['id'])
        self.assertIn('exported_at', meta['dataset'])

        source = meta['source_tasks'][0]
        self.assertEqual(source['task_id'], str(self.task.id))
        self.assertEqual(source['crs'], 'EPSG:32719')
        self.assertAlmostEqual(source['native_resolution_cm_px'], 5.0, places=3)
        self.assertEqual(source['elevation_source'], 'dtm')

    def test_normalization_is_reproducible_from_the_metadata_alone(self):
        """La inferencia tiene que aplicar exactamente esta normalización (FR-045).

        Por eso el bloque lleva la fórmula escrita y los techos numéricos: con solo «se normaliza a
        [0,1]» habría que adivinar entre dividir por 45 o por el máximo observado, y las dos
        opciones dan un modelo que funciona en entrenamiento y falla en producción.
        """
        _, meta = self.open_package(self.run_export())
        bands = meta['normalization']['bands']

        self.assertEqual([b['name'] for b in bands],
                         ['red', 'green', 'blue', 'slope', 'roughness'])
        self.assertEqual(bands[0]['formula'], 'value / 255')
        self.assertEqual(bands[3]['ceiling_deg'], 45.0)
        self.assertIn('ceiling_m', bands[4])
        self.assertGreater(bands[4]['ceiling_m'], 0)
        self.assertEqual(bands[4]['percentile'], 98.0)
        self.assertEqual(bands[4]['window_px'], 3)

    def test_each_tile_entry_locates_itself(self):
        _, meta = self.open_package(self.run_export())
        tile = meta['tiles'][0]

        for field in ('tile_id', 'image', 'mask', 'task_id', 'row', 'column', 'split', 'block',
                      'origin', 'bounds', 'bounds_wgs84', 'reviewed_fraction', 'valid_fraction',
                      'positive_fraction', 'hard_negative', 'class_pixels'):
            self.assertIn(field, tile)

        west, south, east, north = tile['bounds_wgs84']
        self.assertLess(west, east)
        self.assertLess(south, north)
        self.assertTrue(-180 <= west <= 180 and -90 <= south <= 90,
                        'bounds_wgs84 va en coordenadas geográficas')

        # `origin` es la esquina superior izquierda en el CRS métrico, que es lo que permite
        # reconstruir el mosaico sin volver a abrir la ortofoto.
        self.assertAlmostEqual(tile['origin'][0], tile['bounds'][0], places=4)
        self.assertAlmostEqual(tile['origin'][1], tile['bounds'][3], places=4)

    def test_images_are_five_band_georeferenced_geotiffs(self):
        archive, meta = self.open_package(self.run_export())
        data, profile, transform, crs, descriptions = read_raster(
            archive, meta['tiles'][0]['image'])

        self.assertEqual(data.shape, (5, 64, 64))
        self.assertEqual(profile['dtype'], 'float32')
        self.assertEqual(str(crs), 'EPSG:32719')
        self.assertEqual(list(descriptions),
                         ['red', 'green', 'blue', 'slope', 'roughness'])
        self.assertAlmostEqual(abs(transform.a), 0.10, places=6,
                               msg='la tesela va a la resolución del dataset')

    def test_every_channel_is_normalised_to_the_unit_range(self):
        archive, meta = self.open_package(self.run_export())
        for entry in meta['tiles']:
            data, _, _, _, _ = read_raster(archive, entry['image'])
            self.assertGreaterEqual(float(data.min()), 0.0)
            self.assertLessEqual(float(data.max()), 1.0)

    def test_the_slope_channel_matches_the_synthetic_terrain(self):
        """El DTM de prueba es un plano de pendiente conocida (`base.make_dtm`).

        Es la comprobación que descubriría un DTM mal alineado o un gradiente calculado sin la
        resolución: los dos darían un canal plausible y equivocado.
        """
        archive, meta = self.open_package(self.run_export())
        data, _, _, _, _ = read_raster(archive, meta['tiles'][0]['image'])

        expected = expected_slope_degrees(DTM_GRADIENT) / elevation.SLOPE_CEILING_DEG
        interior = data[3][4:-4, 4:-4]
        self.assertAlmostEqual(float(interior.mean()), expected, places=3)
        self.assertLess(float(interior.std()), 1e-3,
                        'un plano debe dar pendiente constante en toda la tesela')

    def test_the_roughness_channel_is_flat_over_a_planar_terrain(self):
        """El DTM de prueba es un plano inclinado: rugosidad cero, pendiente constante.

        Es la separación entre las dos bandas puesta a prueba de punta a punta (D21). Con el TRI de
        Riley esta misma tesela habría dado una rugosidad proporcional a la pendiente, y las bandas
        4 y 5 del paquete serían la misma información dos veces.
        """
        archive, meta = self.open_package(self.run_export())
        data, _, _, _, _ = read_raster(archive, meta['tiles'][0]['image'])
        ceiling_m = meta['normalization']['bands'][4]['ceiling_m']

        # La comprobación va en **metros**, no en el valor normalizado. Sobre un plano perfecto la
        # rugosidad real es cero, así que el p98 cae al suelo de 1 mm y cualquier residuo numérico
        # del remuestreo se ve enorme una vez dividido por él. Lo que importa es el tamaño físico:
        # una décima de milímetro no es rugosidad de nada.
        peak_m = float(data[4].max()) * ceiling_m
        self.assertLess(peak_m, 1e-3,
                        'una rampa lisa no tiene rugosidad, por inclinada que esté: '
                        'salieron {:.2e} m'.format(peak_m))
        self.assertGreater(float(data[3].mean()), 0.5,
                           'y sin embargo su pendiente es alta: las bandas dicen cosas distintas')

    def test_masks_are_single_band_uint8_with_ignore_as_nodata(self):
        archive, meta = self.open_package(self.run_export())
        data, profile, _, crs, _ = read_raster(archive, meta['tiles'][0]['mask'])

        self.assertEqual(data.shape, (1, 64, 64))
        self.assertEqual(profile['dtype'], 'uint8')
        self.assertEqual(profile['nodata'], 255)
        self.assertEqual(str(crs), 'EPSG:32719')

    def test_mask_values_are_class_indexes_or_ignore(self):
        archive, meta = self.open_package(self.run_export())
        values = set()
        for tile in meta['tiles']:
            data, _, _, _, _ = read_raster(archive, tile['mask'])
            values |= set(np.unique(data).tolist())

        self.assertTrue(values <= {0, 1, 255},
                        'valores inesperados en las máscaras: {}'.format(sorted(values)))
        self.assertIn(0, values, 'el fondo revisado tiene que existir como clase real (FR-040)')
        self.assertIn(1, values, 'el camino etiquetado tiene que aparecer')

    def test_image_and_mask_share_the_exact_same_grid(self):
        """La alineación píxel a píxel que exige la especificación, comprobada tesela a tesela."""
        archive, meta = self.open_package(self.run_export())
        for entry in meta['tiles']:
            _, image_profile, image_transform, image_crs, _ = read_raster(archive, entry['image'])
            _, mask_profile, mask_transform, mask_crs, _ = read_raster(archive, entry['mask'])

            self.assertEqual(image_transform, mask_transform)
            self.assertEqual(image_crs, mask_crs)
            self.assertEqual((image_profile['width'], image_profile['height']),
                             (mask_profile['width'], mask_profile['height']))

    def test_class_pixels_match_the_mask(self):
        archive, meta = self.open_package(self.run_export())
        for tile in meta['tiles']:
            data, _, _, _, _ = read_raster(archive, tile['mask'])
            for index, count in tile['class_pixels'].items():
                self.assertEqual(int((data[0] == int(index)).sum()), count)


class ReviewedAreaTest(ExportTestBase):
    """El fondo lo crean las áreas revisadas, no la ausencia de etiquetas (D18, FR-040)."""

    def test_without_reviewed_areas_nothing_is_exported(self):
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 6))

        with self.assertRaises(export.ExportError) as caught:
            self.run_export()
        self.assertEqual(caught.exception.code, 'no_reviewed_tiles')

    def test_unreviewed_ground_stays_ignored_instead_of_becoming_background(self):
        """La distinción que decide la calidad del dataset.

        Lo que hay fuera del área revisada no es «no hay camino»: es «nadie lo ha mirado». Si
        saliera como 0, cada camino no etiquetado enseñaría al modelo que no es un camino.
        """
        # Solo el cuadrante superior izquierdo revisado, y un camino dentro de él.
        self._review_box(self.dataset, self.task, 0, 0, 12, 12)
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 4))

        archive, meta = self.open_package(self.run_export())
        self.assertTrue(meta['tiles'])

        for entry in meta['tiles']:
            data, _, _, _, _ = read_raster(archive, entry['mask'])
            self.assertGreaterEqual(entry['reviewed_fraction'],
                                    self.dataset['min_reviewed_fraction'])

        # Ninguna tesela puede caer entera fuera del área revisada: las de la mitad inferior
        # derecha no llegan al umbral y no se exportan.
        self.assertLess(len(meta['tiles']), 25)

    def test_an_ignore_label_wins_inside_a_reviewed_area(self):
        """Marcar un trozo dudoso dentro de una zona revisada es justo para lo que sirve."""
        self._review_all(self.dataset, self.task)
        # 1 m de lado sobre una tesela de 6,4 m: un 2,4 % ignorado, que deja la tesela por encima
        # del 90 % revisado y por tanto exportable. Con un cuadrado grande la propia tesela caería
        # por debajo del umbral y el test no probaría nada.
        self._add_label(self.dataset, self.task, class_index=None, geometry=square(1, 1, 1))

        archive, meta = self.open_package(self.run_export())
        first = next(t for t in meta['tiles'] if t['row'] == 0 and t['column'] == 0)
        data, _, _, _, _ = read_raster(archive, first['mask'])

        self.assertIn(255, np.unique(data).tolist(),
                      'el trozo marcado como dudoso vuelve a ignorarse')
        self.assertIn(0, np.unique(data).tolist(), 'el resto sigue siendo fondo revisado')

    def test_hard_negative_areas_are_counted(self):
        """FR-043: se puede vigilar qué proporción del dataset son negativos difíciles."""
        self._review_all(self.dataset, self.task, hard_negative=True)

        _, meta = self.open_package(self.run_export())
        self.assertTrue(all(t['hard_negative'] for t in meta['tiles']))
        self.assertEqual(meta['curation']['hard_negative_fraction'], 1.0)
        self.assertEqual(meta['curation']['negative_tiles'], len(meta['tiles']),
                         'sin ninguna clase pintada, toda tesela revisada es un negativo')


class ElevationTest(ExportTestBase):
    def test_a_task_without_elevation_is_skipped_with_a_reason(self):
        """Una tarea sin DTM aportaría teselas de 3 bandas y rompería el paquete (FR-044)."""
        other = self._task_with_orthophoto(project=self.task.project, with_dtm=False,
                                           available_assets=['orthophoto.tif'])
        dataset = store.update_dataset(self.dataset['id'], lambda d: dict(
            d, tasks=d['tasks'] + [{'task_id': str(other.id), 'project_id': other.project_id,
                                    'added_at': models.now_iso()}]))
        self._review_all(dataset, self.task)
        self._review_all(dataset, other)

        _, meta = self.open_package(self.run_export(dataset=store.get_dataset(dataset['id'])))

        skipped = {s['task_id'] for s in meta['skipped_tasks']}
        self.assertEqual(skipped, {str(other.id)})
        self.assertEqual({t['task_id'] for t in meta['tiles']}, {str(self.task.id)})

    def test_the_dsm_is_used_when_the_dtm_is_missing(self):
        """La caída DTM -> DSM que pide la especificación, en el sentido pedido y solo en ese."""
        from .base import make_dtm

        other = self._task_with_orthophoto(project=self.task.project, with_dtm=False,
                                           available_assets=['orthophoto.tif', 'dsm.tif'])
        make_dtm(other.get_asset_download_path('dsm.tif'))

        dataset = store.update_dataset(self.dataset['id'], lambda d: dict(
            d, tasks=[{'task_id': str(other.id), 'project_id': other.project_id,
                       'added_at': models.now_iso()}]))
        self._review_all(dataset, other)

        _, meta = self.open_package(self.run_export(dataset=store.get_dataset(dataset['id'])))
        self.assertEqual(meta['source_tasks'][0]['elevation_source'], 'dsm')
        self.assertTrue(meta['tiles'])

    def test_elevation_can_be_switched_off(self):
        """`none` deja las dos bandas a cero pero **mantiene** las cinco.

        Un paquete con 3 bandas y otro con 5 no los carga el mismo código, y descubrirlo a mitad de
        un entrenamiento cuesta más que dos bandas de ceros.
        """
        dataset = store.update_dataset(self.dataset['id'],
                                       lambda d: dict(d, elevation_source='none'))
        self._review_all(dataset, self.task)

        archive, meta = self.open_package(self.run_export(dataset=store.get_dataset(dataset['id'])))
        data, _, _, _, _ = read_raster(archive, meta['tiles'][0]['image'])

        self.assertEqual(data.shape[0], 5)
        self.assertEqual(float(data[3].max()), 0.0)
        self.assertEqual(float(data[4].max()), 0.0)


class TileFilteringTest(ExportTestBase):
    def test_tiles_outside_the_reviewed_area_are_skipped(self):
        """FR-041: solo un rincón revisado, así que la mayoría de la rejilla se descarta."""
        self._review_box(self.dataset, self.task, 0, 0, 8, 8)
        _, meta = self.open_package(self.run_export())

        self.assertGreaterEqual(len(meta['tiles']), 1)
        for tile in meta['tiles']:
            self.assertGreaterEqual(tile['reviewed_fraction'],
                                    self.dataset['min_reviewed_fraction'])

    def test_tiles_without_enough_valid_pixels_are_skipped(self):
        """El cuadrante inferior derecho de la ortofoto sintética tiene alfa 0 (D7).

        Revisarlo entero no debe bastar para que entre: son píxeles sin datos de vuelo, y
        enseñarían al modelo bordes artificiales.
        """
        self._review_all(self.dataset, self.task)
        _, meta = self.open_package(self.run_export())

        for tile in meta['tiles']:
            self.assertGreaterEqual(tile['valid_fraction'], self.dataset['min_valid_fraction'])

        # La esquina inferior derecha es la que no tiene datos: ninguna tesela de ahí sobrevive.
        corners = {(t['row'], t['column']) for t in meta['tiles']}
        rows = max(r for r, _ in corners)
        cols = max(c for _, c in corners)
        self.assertNotIn((rows, cols), corners)

    def test_pixels_without_imagery_return_to_ignore(self):
        """Un píxel sin ortofoto no puede estar etiquetado, diga lo que diga el área revisada."""
        self._review_all(self.dataset, self.task)
        archive, meta = self.open_package(self.run_export())

        for entry in meta['tiles']:
            image, _, _, _, _ = read_raster(archive, entry['image'])
            mask, _, _, _, _ = read_raster(archive, entry['mask'])
            self.assertEqual(entry['reviewed_fraction'],
                             round(float((mask[0] != 255).sum()) / mask[0].size, 6))

    def test_thresholds_are_configurable_per_dataset(self):
        # 5 m de lado, menos que los 6,4 m de una tesela: ninguna queda revisada del todo.
        self._review_box(self.dataset, self.task, 0, 0, 5, 5)

        # Con el umbral por defecto (90 %) tampoco entra ninguna, así que primero se comprueba que
        # bajándolo sí entran: si no, el test de abajo pasaría por el motivo equivocado.
        relaxed = store.update_dataset(self.dataset['id'],
                                       lambda d: dict(d, min_reviewed_fraction=0.5))
        _, meta = self.open_package(self.run_export(dataset=relaxed))
        self.assertTrue(meta['tiles'])

        strict = store.update_dataset(self.dataset['id'],
                                      lambda d: dict(d, min_reviewed_fraction=1.0))
        with self.assertRaises(export.ExportError):
            self.run_export(dataset=strict)


class SplitTest(ExportTestBase):
    def setUp(self):
        super().setUp()
        # Ortofoto sin el cuadrante sin datos. Con él, el umbral de píxeles válidos tumba teselas
        # **después** de repartirlas, y si el sorteo manda el entrenamiento a esa esquina el
        # paquete sale sin train — que es un caso real, lo cubre `_check_written_split`, y aquí
        # solo introduciría azar en un test sobre el reparto.
        self.task = self._task_with_orthophoto(nodata_corner=False)
        self.dataset = self._create_dataset(self.task, tile_size_px=64)
        self._review_all(self.dataset, self.task)

    def test_every_tile_gets_a_split(self):
        _, meta = self.open_package(self.run_export())
        self.assertTrue(meta['tiles'])
        self.assertTrue({t['split'] for t in meta['tiles']} <= {'train', 'val'})
        self.assertEqual(meta['split']['strategy'], 'geographic_blocks')

    def test_no_val_tile_overlaps_a_train_tile(self):
        """La propiedad que justifica todo el reparto por bloques (D19).

        Con teselas solapadas, un split aleatorio pondría píxeles de validación dentro del
        entrenamiento y la métrica dejaría de significar nada. Aquí se comprueba sobre las
        extensiones reales, no sobre los índices.
        """
        _, meta = self.open_package(self.run_export())

        train = [t['bounds'] for t in meta['tiles'] if t['split'] == 'train']
        val = [t['bounds'] for t in meta['tiles'] if t['split'] == 'val']
        self.assertTrue(train and val, 'el split debe producir los dos lados')

        for a in train:
            for b in val:
                overlaps = not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])
                self.assertFalse(overlaps,
                                 'la tesela de train {} solapa con la de val {}'.format(a, b))

    def test_the_split_is_stable_across_exports(self):
        first = {t['tile_id']: t['split'] for t in self.open_package(self.run_export())[1]['tiles']}
        second = {t['tile_id']: t['split'] for t in self.open_package(self.run_export())[1]['tiles']}
        self.assertEqual(first, second)

    def test_a_different_dataset_gets_a_different_seed(self):
        """La semilla es el identificador del dataset: dos datasets no heredan el mismo reparto."""
        other = self._create_dataset(self.task, tile_size_px=64, name='Otro')
        self._review_all(other, self.task)

        # Rejilla de 16x16 en bloques de 2: 64 bloques y 13 a validación. Con la rejilla de 8x8 y
        # bloques de 4 solo hay 4 bloques y uno de val, así que dos semillas distintas coinciden
        # una de cada cuatro veces: el test habría fallado un día sí y tres no.
        grid = [('t', r, c) for r in range(16) for c in range(16)]
        mine = split.assign_tiles(grid, block_tiles=2, seed=self.dataset['id'])
        theirs = split.assign_tiles(grid, block_tiles=2, seed=other['id'])
        self.assertNotEqual(mine, theirs)


class UnavailableTaskTest(ExportTestBase):
    def test_a_deleted_task_is_skipped_instead_of_failing(self):
        """Invariante 5: una tarea no disponible no rompe la exportación de las demás."""
        self._review_all(self.dataset, self.task)

        other = self._task_with_orthophoto(project=self.task.project)
        dataset = store.update_dataset(self.dataset['id'], lambda d: dict(
            d, tasks=d['tasks'] + [{'task_id': str(other.id), 'project_id': other.project_id,
                                    'added_at': models.now_iso()}]))
        self._review_all(dataset, other)

        other_id = str(other.id)
        other.delete()

        _, meta = self.open_package(self.run_export(dataset=store.get_dataset(dataset['id'])))
        self.assertTrue(meta['tiles'], 'la tarea que sigue disponible debe exportarse')
        self.assertEqual({t['task_id'] for t in meta['tiles']}, {str(self.task.id)})
        self.assertNotIn(other_id, [s['task_id'] for s in meta['source_tasks']])


class DeterminismTest(ExportTestBase):
    def setUp(self):
        super().setUp()
        self._review_all(self.dataset, self.task)
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 4))

    def test_two_exports_without_changes_produce_the_same_tiles_and_masks(self):
        """FR-031, invariante 6. No se exige que el zip sea idéntico byte a byte: solo su contenido
        salvo marcas de tiempo."""
        first_archive, first = self.open_package(self.run_export())
        second_archive, second = self.open_package(self.run_export())

        self.assertEqual([t['image'] for t in first['tiles']],
                         [t['image'] for t in second['tiles']])

        for tile in first['tiles']:
            self.assertEqual(first_archive.read(tile['mask']),
                             second_archive.read(tile['mask']),
                             'la misma tesela debe dar la misma máscara')

        for key in ('schema_version', 'resolution_cm_px', 'tile_size_px', 'ignore_index',
                    'classes', 'normalization'):
            self.assertEqual(first[key], second[key])

    def test_only_timestamps_differ_between_exports(self):
        _, first = self.open_package(self.run_export())
        _, second = self.open_package(self.run_export())

        first['dataset'].pop('exported_at')
        second['dataset'].pop('exported_at')
        self.assertEqual(first, second)


class ProgressTest(ExportTestBase):
    def setUp(self):
        super().setUp()
        self._review_all(self.dataset, self.task)

    def test_progress_is_reported_while_building(self):
        """FR-030: el usuario ve avanzar la exportación, no un cero durante minutos."""
        seen = []
        self.run_export(progress_callback=lambda percent: seen.append(percent))

        self.assertTrue(seen, 'debe reportarse progreso')
        self.assertEqual(seen, sorted(seen), 'el progreso no puede retroceder')
        self.assertLessEqual(max(seen), 100)

    def test_cancelling_stops_the_export(self):
        with self.assertRaises(export.Cancelled):
            self.run_export(should_cancel=lambda: True)

    def test_a_cancelled_export_leaves_no_half_written_package(self):
        """Un zip a medias parece un paquete válido y le falta la mitad."""
        import os
        with self.assertRaises(export.Cancelled):
            self.run_export(should_cancel=lambda: True)
        directory = export.exports_dir(self.dataset['id'])
        leftovers = os.listdir(directory) if os.path.isdir(directory) else []
        self.assertEqual(leftovers, [])
