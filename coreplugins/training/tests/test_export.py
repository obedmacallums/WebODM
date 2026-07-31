"""Paquete exportado (`export.py`, `contracts/dataset-package.md`).

Este es el contrato más caro de cambiar de la feature: lo consume a ciegas la imagen de
entrenamiento, desde otra máquina y sin acceso a WebODM. Lo que se comprueba aquí es que el
paquete se baste a sí mismo (FR-029) y que sus filtros y su determinismo se comporten como
promete el contrato.
"""

import io
import json
import zipfile

import numpy as np
from PIL import Image

from coreplugins.training import export, models, store

from .base import TrainingTestBase, offset_to_lnglat


def square(dx, dy, side):
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]


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
        return archive, json.loads(archive.read('manifest.json'))


class PackageStructureTest(ExportTestBase):
    def setUp(self):
        super().setUp()
        # Un fondo que cubre la mitad superior y un camino encima: la composición mínima que
        # produce teselas con contenido de dos clases.
        self._add_label(self.dataset, self.task, class_index=0, geometry=square(0, 0, 15))
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 4))

    def test_package_pairs_every_image_with_its_mask(self):
        archive, manifest = self.open_package(self.run_export())

        images = [n for n in archive.namelist() if n.startswith('images/')]
        labels = [n for n in archive.namelist() if n.startswith('labels/')]
        self.assertTrue(images, 'el paquete debe traer teselas')
        self.assertEqual(len(images), len(labels))
        self.assertEqual(len(images), len(manifest['tiles']))

        for name in images:
            self.assertIn(name.replace('images/', 'labels/'), labels,
                          'cada imagen necesita su máscara con el mismo nombre')

    def test_manifest_declares_everything_the_trainer_needs(self):
        """FR-028 y FR-029: el manifiesto se basta solo, sin acceso a WebODM ni a la spec."""
        _, manifest = self.open_package(self.run_export())

        self.assertEqual(manifest['schema_version'], 1)
        self.assertEqual(manifest['ignore_index'], 255)
        self.assertEqual(manifest['resolution_cm_px'], 10.0)
        self.assertEqual(manifest['tile_size_px'], 64)
        self.assertEqual([(c['index'], c['name']) for c in manifest['classes']],
                         [(0, 'background'), (1, 'road')])

        self.assertEqual(manifest['dataset']['id'], self.dataset['id'])
        self.assertIn('exported_at', manifest['dataset'])

        source = manifest['source_tasks'][0]
        self.assertEqual(source['task_id'], str(self.task.id))
        self.assertEqual(source['crs'], 'EPSG:32719')
        self.assertAlmostEqual(source['native_resolution_cm_px'], 5.0, places=3)

    def test_each_tile_entry_locates_itself(self):
        _, manifest = self.open_package(self.run_export())
        tile = manifest['tiles'][0]

        for field in ('image', 'label', 'task_id', 'row', 'column', 'bounds',
                      'labeled_fraction', 'valid_fraction', 'class_pixels'):
            self.assertIn(field, tile)

        west, south, east, north = tile['bounds']
        self.assertLess(west, east)
        self.assertLess(south, north)
        self.assertTrue(-180 <= west <= 180 and -90 <= south <= 90,
                        'los bounds van en coordenadas geográficas')

    def test_images_are_three_channel_rgb_without_alpha(self):
        """D7: el alfa decide si la tesela entra, pero no se exporta — el modelo espera 3 canales."""
        archive, manifest = self.open_package(self.run_export())
        image = Image.open(io.BytesIO(archive.read(manifest['tiles'][0]['image'])))

        self.assertEqual(image.mode, 'RGB')
        self.assertEqual(image.size, (64, 64))

    def test_masks_are_single_channel_without_palette(self):
        archive, manifest = self.open_package(self.run_export())
        mask = Image.open(io.BytesIO(archive.read(manifest['tiles'][0]['label'])))

        self.assertEqual(mask.mode, 'L')
        self.assertEqual(mask.size, (64, 64))
        self.assertIsNone(mask.getpalette(),
                          'sin paleta: son índices, y una paleta invitaría a reinterpretarlos')

    def test_mask_values_are_class_indexes_or_ignore(self):
        archive, manifest = self.open_package(self.run_export())
        values = set()
        for tile in manifest['tiles']:
            values |= set(np.unique(np.array(Image.open(io.BytesIO(archive.read(tile['label']))))))

        self.assertTrue(values <= {0, 1, 255},
                        'valores inesperados en las máscaras: {}'.format(sorted(values)))
        self.assertIn(255, values, 'la presencia del 255 es la prueba de FR-026')

    def test_class_pixels_match_the_mask(self):
        archive, manifest = self.open_package(self.run_export())
        for tile in manifest['tiles']:
            mask = np.array(Image.open(io.BytesIO(archive.read(tile['label']))))
            for index, count in tile['class_pixels'].items():
                self.assertEqual(int((mask == int(index)).sum()), count)


class TileFilteringTest(ExportTestBase):
    def test_tiles_without_labels_are_skipped(self):
        """FR-027: solo un rincón etiquetado, así que la mayoría de las 25 teselas se descarta."""
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 3))
        _, manifest = self.open_package(self.run_export())

        self.assertLess(len(manifest['tiles']), 25)
        self.assertGreaterEqual(len(manifest['tiles']), 1)
        for tile in manifest['tiles']:
            self.assertGreaterEqual(tile['labeled_fraction'],
                                    self.dataset['min_labeled_fraction'])

    def test_tiles_without_enough_valid_pixels_are_skipped(self):
        """El cuadrante inferior derecho de la ortofoto sintética tiene alfa 0 (D7).

        Etiquetarlo entero no debe bastar para que entre: son píxeles sin datos de vuelo, y
        enseñarían al modelo bordes artificiales.
        """
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(20, 20, 9))
        _, manifest = self.open_package(self.run_export())

        for tile in manifest['tiles']:
            self.assertGreaterEqual(tile['valid_fraction'], self.dataset['min_valid_fraction'])

    def test_a_dataset_with_no_labels_produces_no_tiles(self):
        result = self.run_export()
        _, manifest = self.open_package(result)
        self.assertEqual(manifest['tiles'], [])
        self.assertEqual(result['tile_count'], 0)

    def test_thresholds_are_configurable_per_dataset(self):
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 3))

        strict = store.update_dataset(self.dataset['id'],
                                      lambda d: dict(d, min_labeled_fraction=0.99))
        _, manifest = self.open_package(self.run_export(dataset=strict))
        self.assertEqual(manifest['tiles'], [])


class UnavailableTaskTest(ExportTestBase):
    def test_a_deleted_task_is_skipped_instead_of_failing(self):
        """Invariante 5: una tarea no disponible no rompe la exportación de las demás."""
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 8))

        other = self._task_with_orthophoto(project=self.task.project)
        dataset = store.update_dataset(self.dataset['id'], lambda d: dict(
            d, tasks=d['tasks'] + [{'task_id': str(other.id), 'project_id': other.project_id,
                                    'added_at': models.now_iso()}]))
        self._add_label(dataset, other, class_index=1, geometry=square(0, 0, 8))

        other_id = str(other.id)
        other.delete()

        _, manifest = self.open_package(self.run_export(dataset=store.get_dataset(dataset['id'])))
        self.assertTrue(manifest['tiles'], 'la tarea que sigue disponible debe exportarse')
        self.assertEqual({t['task_id'] for t in manifest['tiles']}, {str(self.task.id)})
        self.assertNotIn(other_id, [s['task_id'] for s in manifest['source_tasks']])


class DeterminismTest(ExportTestBase):
    def test_two_exports_without_changes_produce_the_same_tiles_and_masks(self):
        """FR-031, invariante 6. No se exige que el zip sea idéntico byte a byte: solo su contenido
        salvo marcas de tiempo."""
        self._add_label(self.dataset, self.task, class_index=0, geometry=square(0, 0, 15))
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 4))

        first_archive, first = self.open_package(self.run_export())
        second_archive, second = self.open_package(self.run_export())

        self.assertEqual([t['image'] for t in first['tiles']],
                         [t['image'] for t in second['tiles']])

        for tile in first['tiles']:
            self.assertEqual(first_archive.read(tile['label']),
                             second_archive.read(tile['label']),
                             'la misma tesela debe dar la misma máscara')

        for key in ('schema_version', 'resolution_cm_px', 'tile_size_px', 'ignore_index',
                    'classes'):
            self.assertEqual(first[key], second[key])

    def test_only_timestamps_differ_between_exports(self):
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 6))
        _, first = self.open_package(self.run_export())
        _, second = self.open_package(self.run_export())

        first['dataset'].pop('exported_at')
        second['dataset'].pop('exported_at')
        self.assertEqual(first, second)


class ProgressTest(ExportTestBase):
    def test_progress_is_reported_while_building(self):
        """FR-030: el usuario ve avanzar la exportación, no un cero durante minutos."""
        self._add_label(self.dataset, self.task, class_index=0, geometry=square(0, 0, 20))
        seen = []
        self.run_export(progress_callback=lambda percent: seen.append(percent))

        self.assertTrue(seen, 'debe reportarse progreso')
        self.assertEqual(seen, sorted(seen), 'el progreso no puede retroceder')
        self.assertLessEqual(max(seen), 100)

    def test_cancelling_stops_the_export(self):
        self._add_label(self.dataset, self.task, class_index=0, geometry=square(0, 0, 20))
        with self.assertRaises(export.Cancelled):
            self.run_export(should_cancel=lambda: True)
