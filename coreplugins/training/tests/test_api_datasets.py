"""API de datasets (`contracts/rest-api.md` §Datasets).

Los errores se comprueban por su `code` y no por el mensaje: el contrato fija que el frontend
distingue por `code`, así que un test que mirara la redacción convertiría cada mejora de un texto
en un fallo de la suite.
"""

from coreplugins.training import store

from .base import TrainingTestBase, offset_to_lnglat


class DatasetApiTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task()
        self._login()

    def _cleanup(self, dataset_id):
        self.addCleanup(store.delete_dataset, dataset_id)

    # --- Alta ---------------------------------------------------------------------------

    def test_create_returns_the_dataset_with_its_defaults(self):
        res = self.client.post(self._api('datasets'),
                               self._dataset_payload(self.task, tile_size_px=None,
                                                     resolution_cm_px=None),
                               format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self._cleanup(res.data['id'])
        self.assertEqual(res.data['resolution_cm_px'], 10.0)
        self.assertEqual(res.data['tile_size_px'], 512)
        self.assertEqual([c['index'] for c in res.data['classes']], [0, 1])
        self.assertTrue(res.data['classes'][0]['color'])

    def test_create_rejects_a_task_without_orthophoto(self):
        """FR: sin ortofoto no hay nada que etiquetar, y debe decirse al crear, no al exportar."""
        blind = self._task(project=self.task.project, orthophoto_extent=None)
        res = self.client.post(self._api('datasets'), self._dataset_payload(blind), format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'no_orthophoto')

    def test_create_rejects_fewer_than_two_classes(self):
        res = self.client.post(self._api('datasets'),
                               self._dataset_payload(self.task,
                                                     classes=[{'index': 0, 'name': 'bg'}]),
                               format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'too_few_classes')

    def test_create_rejects_non_consecutive_class_indexes(self):
        res = self.client.post(self._api('datasets'),
                               self._dataset_payload(self.task, classes=[
                                   {'index': 1, 'name': 'road'}, {'index': 4, 'name': 'building'}]),
                               format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_class_indexes')

    def test_create_rejects_a_non_positive_resolution(self):
        res = self.client.post(self._api('datasets'),
                               self._dataset_payload(self.task, resolution_cm_px=0),
                               format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_resolution')

    def test_create_requires_authentication(self):
        self.client.logout()
        res = self.client.post(self._api('datasets'), self._dataset_payload(self.task),
                               format='json')
        self.assertIn(res.status_code, (401, 403))

    def test_create_rejects_a_task_the_user_cannot_see(self):
        other_project = Project_of(self, 'testuser2')
        other_task = self._task(project=other_project)
        res = self.client.post(self._api('datasets'), self._dataset_payload(other_task),
                               format='json')
        self.assertEqual(res.status_code, 404)

    # --- Listado y detalle --------------------------------------------------------------

    def test_list_returns_the_users_datasets(self):
        dataset = self._create_dataset(self.task)
        res = self.client.get(self._api('datasets'))
        self.assertEqual(res.status_code, 200)
        self.assertIn(dataset['id'], [d['id'] for d in res.data])

    def test_list_hides_datasets_of_other_users(self):
        other_project = Project_of(self, 'testuser2')
        other_task = self._task(project=other_project)
        hidden = self._create_dataset(other_task, owner='testuser2')
        res = self.client.get(self._api('datasets'))
        self.assertNotIn(hidden['id'], [d['id'] for d in res.data])

    def test_detail_includes_task_availability(self):
        dataset = self._create_dataset(self.task)
        res = self.client.get(self._api('datasets', dataset['id']))
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.data['tasks'][0]['available'])
        self.assertEqual(res.data['tasks'][0]['task_id'], str(self.task.id))

    def test_detail_of_a_dataset_whose_task_disappeared_still_opens(self):
        """Invariante 5: el dataset sobrevive al borrado de una de sus tareas."""
        dataset = self._create_dataset(self.task)
        self.task.delete()
        res = self.client.get(self._api('datasets', dataset['id']))
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.data['tasks'][0]['available'])

    def test_detail_of_a_missing_dataset_is_404(self):
        self.assertEqual(self.client.get(self._api('datasets', 'no-existe')).status_code, 404)

    # --- Modificación -------------------------------------------------------------------

    def test_patch_renames_the_dataset(self):
        dataset = self._create_dataset(self.task)
        res = self.client.patch(self._api('datasets', dataset['id']), {'name': 'Otro nombre'},
                                format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['name'], 'Otro nombre')

    def test_patch_can_rename_a_class_without_touching_its_labels(self):
        """Renombrar una clase es inocuo: el contrato con las máscaras es el índice, no el nombre."""
        dataset = self._create_dataset(self.task)
        self._add_label(dataset, self.task, class_index=1, geometry=_square(0, 0, 3))
        res = self.client.patch(self._api('datasets', dataset['id']),
                                {'classes': [{'index': 0, 'name': 'background'},
                                             {'index': 1, 'name': 'pista'}]}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['classes'][1]['name'], 'pista')
        self.assertEqual(len(store.list_labels(dataset['id'], str(self.task.id))), 1)

    def test_patch_refuses_to_drop_a_class_with_labels_without_confirmation(self):
        """FR-006: borrar una clase etiquetada exige confirmación y dice cuánto se pierde."""
        dataset = self._create_dataset(self.task, classes=[
            {'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'road'},
            {'index': 2, 'name': 'building'}])
        self._add_label(dataset, self.task, class_index=2, geometry=_square(0, 0, 3))
        self._add_label(dataset, self.task, class_index=2, geometry=_square(5, 0, 3))

        res = self.client.patch(self._api('datasets', dataset['id']),
                                {'classes': [{'index': 0, 'name': 'bg'},
                                             {'index': 1, 'name': 'road'}]}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['code'], 'class_in_use')
        self.assertEqual(res.data['label_count'], 2)

    def test_patch_drops_a_class_with_labels_when_confirmed(self):
        dataset = self._create_dataset(self.task, classes=[
            {'index': 0, 'name': 'bg'}, {'index': 1, 'name': 'road'},
            {'index': 2, 'name': 'building'}])
        self._add_label(dataset, self.task, class_index=2, geometry=_square(0, 0, 3))

        res = self.client.patch(self._api('datasets', dataset['id']),
                                {'confirm': True,
                                 'classes': [{'index': 0, 'name': 'bg'},
                                             {'index': 1, 'name': 'road'}]}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(len(res.data['classes']), 2)
        self.assertEqual(store.list_labels(dataset['id'], str(self.task.id)), [])

    def test_patch_refuses_to_change_the_resolution_once_labeled(self):
        """`data-model.md`: la resolución se congela tras etiquetar porque `simplify` ya se aplicó
        con su tolerancia, y bajar a una más fina no recuperaría los vértices descartados."""
        dataset = self._create_dataset(self.task)
        self._add_label(dataset, self.task, class_index=1, geometry=_square(0, 0, 3))
        res = self.client.patch(self._api('datasets', dataset['id']), {'resolution_cm_px': 5.0},
                                format='json')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['code'], 'dataset_has_labels')

    def test_patch_allows_changing_the_resolution_while_empty(self):
        dataset = self._create_dataset(self.task)
        res = self.client.patch(self._api('datasets', dataset['id']), {'resolution_cm_px': 5.0},
                                format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['resolution_cm_px'], 5.0)

    # --- Borrado ------------------------------------------------------------------------

    def test_delete_removes_the_dataset_and_its_labels(self):
        import os
        dataset = self._create_dataset(self.task)
        self._add_label(dataset, self.task, class_index=1, geometry=_square(0, 0, 3))
        path = store.labels_path(dataset['id'], str(self.task.id))

        res = self.client.delete(self._api('datasets', dataset['id']))
        self.assertEqual(res.status_code, 204)
        self.assertIsNone(store.get_dataset(dataset['id']))
        self.assertFalse(os.path.exists(path))

    def test_delete_of_a_dataset_of_another_user_is_404(self):
        other_task = self._task(project=Project_of(self, 'testuser2'))
        hidden = self._create_dataset(other_task, owner='testuser2')
        self.assertEqual(self.client.delete(self._api('datasets', hidden['id'])).status_code, 404)


class AssistSettingsTest(TrainingTestBase):
    """Ajustes de selección asistida en el dataset (`010`, T008 y T049).

    Los tres viven en el dataset y no en el navegador porque describen cómo se etiqueta ese terreno,
    no una preferencia de sesión: quien vuelve al día siguiente encuentra lo que dejó (FR-022).
    """

    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task)
        self._login()

    def _patch(self, assist):
        return self.client.patch(self._api('datasets', self.dataset['id']), {'assist': assist},
                                 format='json')

    def test_a_new_dataset_has_the_defaults(self):
        res = self.client.get(self._api('datasets', self.dataset['id']))
        self.assertEqual(res.data['assist'],
                         {'granularity': 'medium', 'tolerance': 0.0, 'elevation_weight': 1.0})

    def test_a_dataset_created_before_the_feature_gets_them_on_read(self):
        """`with_defaults` los rellena al leer, sin reescribir el documento en disco."""
        store.update_dataset(self.dataset['id'],
                             lambda d: {k: v for k, v in d.items() if k != 'assist'})
        res = self.client.get(self._api('datasets', self.dataset['id']))
        self.assertEqual(res.data['assist']['granularity'], 'medium')

    def test_the_settings_persist(self):
        self.assertEqual(self._patch({'granularity': 'coarse', 'tolerance': 0.3}).status_code, 200)
        res = self.client.get(self._api('datasets', self.dataset['id']))
        self.assertEqual(res.data['assist']['granularity'], 'coarse')
        self.assertEqual(res.data['assist']['tolerance'], 0.3)

    def test_a_partial_change_keeps_the_others(self):
        """Mover un control no puede reescribir los otros dos con lo que el navegador recuerde."""
        self._patch({'granularity': 'fine', 'tolerance': 0.4, 'elevation_weight': 0.5})
        self._patch({'tolerance': 0.1})
        res = self.client.get(self._api('datasets', self.dataset['id']))
        self.assertEqual(res.data['assist'],
                         {'granularity': 'fine', 'tolerance': 0.1, 'elevation_weight': 0.5})

    def test_an_unknown_granularity_is_rejected(self):
        res = self._patch({'granularity': 'enorme'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_settings')

    def test_a_tolerance_out_of_range_is_rejected(self):
        self.assertEqual(self._patch({'tolerance': 2.0}).data['code'], 'bad_settings')

    def test_an_elevation_weight_out_of_range_is_rejected(self):
        self.assertEqual(self._patch({'elevation_weight': -1}).data['code'], 'bad_settings')

    def test_zero_elevation_weight_is_valid(self):
        """El cero no es «sin valor»: es «no quiero canales de terreno» (FR-013)."""
        self.assertEqual(self._patch({'elevation_weight': 0}).status_code, 200)
        res = self.client.get(self._api('datasets', self.dataset['id']))
        self.assertEqual(res.data['assist']['elevation_weight'], 0.0)

    def test_changing_the_settings_does_not_touch_existing_labels(self):
        """FR-023. Los ajustes describen lo que se va a calcular, no lo que ya se decidió."""
        label = self._add_label(self.dataset, self.task, class_index=1,
                                geometry=_square(0, 0, 4))
        before = store.list_labels(self.dataset['id'], str(self.task.id))

        self._patch({'granularity': 'coarse', 'tolerance': 0.9, 'elevation_weight': 0.0})

        after = store.list_labels(self.dataset['id'], str(self.task.id))
        self.assertEqual(before, after)
        self.assertEqual(after[0]['id'], label['id'])


def Project_of(test, username):
    from app.models import Project
    from django.contrib.auth.models import User
    return Project.objects.create(owner=User.objects.get(username=username), name='Ajeno')


def _square(dx, dy, side):
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]
