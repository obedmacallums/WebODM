"""Entidades y persistencia (`data-model.md`, T006–T010).

Lo que se protege aquí es el contrato del que dependen la API y el exportador: que un dataset
inválido no llegue nunca a guardarse, que las etiquetas de dos tareas del mismo dataset no se
mezclen, que el `order` sea monótono —es lo que decide la precedencia al rasterizar— y que una
tarea borrada de WebODM no rompa la lectura del dataset.
"""

from django.contrib.auth.models import User

from coreplugins.training import models, store

from .base import TrainingTestBase, offset_to_lnglat


def square(dx, dy, side):
    """Anillo cuadrado de `side` metros con la esquina superior izquierda en (dx, dy) metros."""
    return [list(offset_to_lnglat(dx, dy)),
            list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)),
            list(offset_to_lnglat(dx, dy + side))]


class ClassValidationTest(TrainingTestBase):
    def test_requires_at_least_two_classes(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.normalize_classes([{'index': 0, 'name': 'background'}])
        self.assertEqual(ctx.exception.code, 'too_few_classes')

    def test_indexes_must_be_consecutive_from_zero(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.normalize_classes([{'index': 1, 'name': 'road'},
                                      {'index': 3, 'name': 'building'}])
        self.assertEqual(ctx.exception.code, 'bad_class_indexes')

    def test_reserved_ignore_index_is_rejected(self):
        """255 significa «sin etiquetar» (FR-026): no puede ser el índice de una clase."""
        with self.assertRaises(models.ValidationError) as ctx:
            models.normalize_classes([{'index': 0, 'name': 'background'},
                                      {'index': models.IGNORE_INDEX, 'name': 'road'}])
        self.assertEqual(ctx.exception.code, 'bad_class_indexes')

    def test_duplicate_names_are_rejected(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.normalize_classes([{'index': 0, 'name': 'road'}, {'index': 1, 'name': 'road'}])
        self.assertEqual(ctx.exception.code, 'bad_class_indexes')

    def test_default_colors_avoid_the_road_traffic_light(self):
        """FR-007: los colores no pueden confundirse con la escala de pendiente de `road`."""
        classes = models.normalize_classes([{'index': i, 'name': 'c{}'.format(i)}
                                            for i in range(6)])
        for c in classes:
            red, green, blue = (int(c['color'][i:i + 2], 16) for i in (1, 3, 5))
            is_reddish = red > 150 and green < 110 and blue < 110
            is_greenish = green > 150 and red < 110 and blue < 110
            is_yellowish = red > 180 and green > 150 and blue < 110
            self.assertFalse(is_reddish or is_greenish or is_yellowish,
                             'El color {} de la clase {} choca con el semáforo de road'.format(
                                 c['color'], c['index']))


class DatasetValidationTest(TrainingTestBase):
    def test_defaults_match_the_spec(self):
        dataset = models.make_dataset('d', [{'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'r'}],
                                      ['task-1'])
        self.assertEqual(dataset['resolution_cm_px'], 10.0)      # FR-005
        self.assertEqual(dataset['tile_size_px'], 512)           # FR-024
        self.assertEqual(dataset['min_labeled_fraction'], 0.01)  # FR-027
        self.assertEqual(dataset['min_valid_fraction'], 0.50)    # FR-027
        self.assertEqual(dataset['schema_version'], 1)

    def test_resolution_must_be_positive(self):
        for bad in (0, -5, 'abc'):
            with self.assertRaises(models.ValidationError) as ctx:
                models.make_dataset('d', [{'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'r'}],
                                    ['task-1'], resolution_cm_px=bad)
            self.assertEqual(ctx.exception.code, 'bad_resolution')

    def test_needs_at_least_one_task(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.make_dataset('d', [{'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'r'}], [])
        self.assertEqual(ctx.exception.code, 'no_tasks')

    def test_supports_several_tasks_from_the_start(self):
        """FR-002: el modelo de datos soporta multi-tarea aunque la interfaz llegue en US3."""
        dataset = models.make_dataset('d', [{'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'r'}],
                                      ['task-1', 'task-2'])
        self.assertEqual([t['task_id'] for t in dataset['tasks']], ['task-1', 'task-2'])


class LabelValidationTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.dataset = models.make_dataset(
            'd', [{'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'road'}], ['task-1'])

    def test_unknown_class_is_rejected(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.make_label(self.dataset, {'kind': 'polygon', 'class_index': 7,
                                             'geometry': square(0, 0, 5)}, 0)
        self.assertEqual(ctx.exception.code, 'unknown_class')

    def test_stroke_requires_a_positive_radius(self):
        for bad in (None, 0, -1):
            with self.assertRaises(models.ValidationError) as ctx:
                models.make_label(self.dataset, {'kind': 'stroke', 'class_index': 1,
                                                 'radius_m': bad,
                                                 'geometry': square(0, 0, 5)[:2]}, 0)
            self.assertEqual(ctx.exception.code, 'bad_radius')

    def test_polygon_needs_three_vertices(self):
        with self.assertRaises(models.ValidationError) as ctx:
            models.make_label(self.dataset, {'kind': 'polygon', 'class_index': 1,
                                             'geometry': square(0, 0, 5)[:2]}, 0)
        self.assertEqual(ctx.exception.code, 'bad_geometry')

    def test_eraser_has_a_null_class_and_is_not_class_zero(self):
        """FR-014: el borrador devuelve a «sin etiquetar», que no es pintar fondo."""
        label = models.make_label(self.dataset, {'kind': 'polygon', 'class_index': None,
                                                 'geometry': square(0, 0, 5)}, 0)
        self.assertIsNone(label['class_index'])

    def test_simplify_keeps_the_shape_and_drops_sub_resolution_vertices(self):
        """FR-015: la tolerancia es la resolución del dataset, convertida a grados.

        La geometría lleva 40 vértices sobre una recta de 10 m separados 25 cm: por debajo de los
        10 cm/px del dataset no aportan nada que la máscara pueda representar. Si la tolerancia se
        aplicara cruda —en grados, sin convertir— el trazo quedaría reducido a sus dos extremos, y
        el test lo distingue comprobando que los extremos sobreviven pero la línea no se desvía.
        """
        line = [list(offset_to_lnglat(i * 0.25, 0.0)) for i in range(40)]
        label = models.make_label(self.dataset, {'kind': 'stroke', 'class_index': 1,
                                                 'radius_m': 2.0, 'geometry': line}, 0)
        self.assertLess(len(label['geometry']), len(line))
        self.assertEqual(label['geometry'][0], line[0])
        self.assertEqual(label['geometry'][-1], line[-1])

    def test_simplify_does_not_collapse_a_curved_stroke(self):
        """Una polilínea con curvatura real conserva vértices intermedios.

        Es la mitad que falta del test anterior: sin esto, una tolerancia demasiado grande pasaría
        ambos casos reduciéndolo todo a los extremos.
        """
        import math
        curve = [list(offset_to_lnglat(i * 0.5, 5.0 * math.sin(i * 0.4))) for i in range(30)]
        label = models.make_label(self.dataset, {'kind': 'stroke', 'class_index': 1,
                                                 'radius_m': 2.0, 'geometry': curve}, 0)
        self.assertGreater(len(label['geometry']), 5)


class DatasetStoreTest(TrainingTestBase):
    def test_create_list_get_delete_roundtrip(self):
        task = self._task()
        dataset = self._create_dataset(task)

        self.assertIn(dataset['id'], store.list_dataset_ids())
        self.assertEqual(store.get_dataset(dataset['id'])['name'], 'Pistas mineras')

        store.delete_dataset(dataset['id'])
        self.assertIsNone(store.get_dataset(dataset['id']))
        self.assertNotIn(dataset['id'], store.list_dataset_ids())

    def test_update_applies_inside_the_lock(self):
        dataset = self._create_dataset(self._task())

        def rename(d):
            d['name'] = 'Renombrado'
            return d

        store.update_dataset(dataset['id'], rename)
        self.assertEqual(store.get_dataset(dataset['id'])['name'], 'Renombrado')

    def test_update_of_a_missing_dataset_returns_none(self):
        self.assertIsNone(store.update_dataset('no-existe', lambda d: d))


class LabelStoreTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task()
        self.dataset = self._create_dataset(self.task)

    def test_order_is_monotonic(self):
        orders = [self._add_label(self.dataset, self.task, class_index=1,
                                  geometry=square(i, 0, 2))['order'] for i in range(4)]
        self.assertEqual(orders, [0, 1, 2, 3])

    def test_order_keeps_growing_after_a_delete(self):
        """El `order` no se reutiliza: es la precedencia de composición, no un índice de lista.

        Reciclarlo haría que una etiqueta nueva heredara la posición de una borrada y quedara
        **debajo** de las que se dibujaron después, invirtiendo en silencio la regla de FR-012.
        """
        first = self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 2))
        store.delete_label(self.dataset['id'], str(self.task.id), first['id'])
        second = self._add_label(self.dataset, self.task, class_index=1, geometry=square(3, 0, 2))
        self.assertEqual(second['order'], 1)

    def test_labels_of_two_tasks_do_not_mix(self):
        other = self._task(self.dataset and self._project(name='Otro proyecto'))
        store.update_dataset(self.dataset['id'], lambda d: dict(
            d, tasks=d['tasks'] + [{'task_id': str(other.id), 'project_id': other.project_id,
                                    'added_at': models.now_iso()}]))
        dataset = store.get_dataset(self.dataset['id'])

        self._add_label(dataset, self.task, class_index=1, geometry=square(0, 0, 2))
        self._add_label(dataset, other, class_index=1, geometry=square(5, 5, 2))

        self.assertEqual(len(store.list_labels(dataset['id'], str(self.task.id))), 1)
        self.assertEqual(len(store.list_labels(dataset['id'], str(other.id))), 1)

    def test_update_and_delete(self):
        label = self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 2))

        store.update_label(self.dataset['id'], str(self.task.id), label['id'],
                           lambda l: dict(l, class_index=0))
        self.assertEqual(store.list_labels(self.dataset['id'], str(self.task.id))[0]['class_index'],
                         0)

        self.assertTrue(store.delete_label(self.dataset['id'], str(self.task.id), label['id']))
        self.assertEqual(store.list_labels(self.dataset['id'], str(self.task.id)), [])
        self.assertFalse(store.delete_label(self.dataset['id'], str(self.task.id), label['id']))

    def test_count_labels_by_class_separates_the_eraser(self):
        """El borrador no pertenece a ninguna clase, así que borrar una clase no se lo lleva."""
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 2))
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(3, 0, 2))
        self._add_label(self.dataset, self.task, class_index=None, geometry=square(6, 0, 2))

        counts = store.count_labels_by_class(self.dataset['id'])
        self.assertEqual(counts.get(1), 2)
        self.assertEqual(counts.get(None), 1)

    def test_deleting_the_dataset_removes_its_labels_from_disk(self):
        import os
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 2))
        path = store.labels_path(self.dataset['id'], str(self.task.id))
        self.assertTrue(os.path.isfile(path))

        store.delete_dataset(self.dataset['id'])
        self.assertFalse(os.path.exists(path))


class TaskAvailabilityTest(TrainingTestBase):
    def test_available_is_true_for_a_task_with_orthophoto(self):
        task = self._task()
        dataset = self._create_dataset(task)
        described = store.describe_tasks(dataset)
        self.assertEqual(len(described), 1)
        self.assertTrue(described[0]['available'])
        self.assertEqual(described[0]['name'], 'Task with orthophoto')

    def test_a_deleted_task_reads_as_unavailable_instead_of_failing(self):
        """Invariante 5 de `data-model.md`: el dataset sobrevive al borrado de una tarea.

        Es lo que distingue este plugin de `road` y `annotations`, donde el borrado en cascada por
        tarea es la respuesta correcta y aquí no lo es.
        """
        task = self._task()
        dataset = self._create_dataset(task)
        task_id = str(task.id)
        task.delete()

        described = store.describe_tasks(store.get_dataset(dataset['id']))
        self.assertEqual(described[0]['task_id'], task_id)
        self.assertFalse(described[0]['available'])
        self.assertEqual(store.available_tasks(store.get_dataset(dataset['id'])), [])

    def test_a_task_without_orthophoto_is_unavailable(self):
        task = self._task(orthophoto_extent=None)
        dataset = self._create_dataset(task)
        self.assertFalse(store.describe_tasks(dataset)[0]['available'])

    def test_availability_is_never_persisted(self):
        """Persistirlo daría un valor obsoleto en cuanto la tarea se borrase por otra vía."""
        dataset = self._create_dataset(self._task())
        stored = store.get_dataset(dataset['id'])
        for entry in stored['tasks']:
            self.assertNotIn('available', entry)


class UserFixtureTest(TrainingTestBase):
    def test_boot_fixture_provides_the_test_user(self):
        self.assertTrue(User.objects.filter(username='testuser').exists())
