"""API de exportación (`contracts/rest-api.md` §Exportación).

Bajo `CELERY_TASK_ALWAYS_EAGER` —que es como corre la suite— el trabajo termina antes de que la
vista devuelva, así que estos tests ven el estado final. La ejecución con Celery real es el
Escenario 4 de `quickstart.md` y **ningún test la cubre**: `run_function_async` recompila la
función por código fuente en un espacio de nombres vacío, y eso solo falla en ejecución.
"""

import json
import os
import zipfile

from coreplugins.training import export, store

from .base import TrainingTestBase, offset_to_lnglat


def square(dx, dy, side):
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]


class ExportApiTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task_with_orthophoto()
        self.dataset = self._create_dataset(self.task, tile_size_px=64)
        self.addCleanup(export.delete_all_packages, self.dataset['id'])
        self._login()

    def _url(self, *extra):
        return self._api('datasets', self.dataset['id'], 'exports', *extra)

    def _label_something(self):
        """Lo mínimo para que una exportación produzca teselas: revisar y etiquetar.

        El área revisada es tan imprescindible como la etiqueta: sin ella la máscara sale entera a
        255 y no hay tesela que llegue al umbral (D18).
        """
        self._review_all(self.dataset, self.task)
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(2, 2, 5))

    # --- Lanzar ---------------------------------------------------------------------------

    def test_post_launches_the_export_and_returns_202(self):
        self._label_something()
        res = self.client.post(self._url(), {}, format='json')

        self.assertEqual(res.status_code, 202, res.data)
        self.assertIn('export_id', res.data)
        self.assertIn('celery_task_id', res.data)

    def test_the_export_completes_and_records_its_size(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']

        entry = store.get_export(self.dataset['id'], export_id)
        self.assertEqual(entry['status'], 'completed', entry.get('error'))
        self.assertIsNone(entry['error'])
        self.assertEqual(entry['progress'], 100)
        self.assertGreater(entry['tile_count'], 0)
        self.assertGreater(entry['size_bytes'], 0)

    def test_export_without_labels_is_rejected_with_its_own_code(self):
        """`nothing_to_export` y `all_tiles_filtered` son problemas distintos con soluciones
        distintas: faltar etiquetas o que las que hay no superen los umbrales."""
        res = self.client.post(self._url(), {}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'nothing_to_export')

    def test_export_without_reviewed_areas_says_so(self):
        """Etiquetar sin revisar no basta, y el mensaje tiene que decir qué falta (FR-041)."""
        self._add_label(self.dataset, self.task, class_index=1, geometry=square(0, 0, 3))

        res = self.client.post(self._url(), {}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'no_reviewed_tiles')
        self.assertIn('revisadas', res.data['error'])

    def test_export_whose_tiles_are_all_filtered_says_so(self):
        self._review_box(self.dataset, self.task, 0, 0, 5, 5)
        store.update_dataset(self.dataset['id'], lambda d: dict(d, min_reviewed_fraction=1.0))

        res = self.client.post(self._url(), {}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'no_reviewed_tiles')
        self.assertIn('tile_count', res.data)

    def test_export_without_available_tasks_is_rejected(self):
        self._label_something()
        self.task.delete()

        res = self.client.post(self._url(), {}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'no_available_tasks')

    def test_requires_authentication(self):
        self.client.logout()
        self.assertIn(self.client.post(self._url(), {}, format='json').status_code, (401, 403))

    def test_another_users_dataset_is_404(self):
        self.client.logout()
        self.client.login(username='testuser2', password='test1234')
        self.assertEqual(self.client.post(self._url(), {}, format='json').status_code, 404)

    # --- Listar ---------------------------------------------------------------------------

    def test_list_shows_status_and_progress(self):
        self._label_something()
        self.client.post(self._url(), {}, format='json')

        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data), 1)
        for field in ('id', 'status', 'progress', 'tile_count', 'size_bytes', 'created_at'):
            self.assertIn(field, res.data[0])

    def test_list_is_empty_before_any_export(self):
        self.assertEqual(self.client.get(self._url()).data, [])

    # --- Descargar ------------------------------------------------------------------------

    def test_download_returns_the_package_as_an_attachment(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']

        res = self.client.get(self._url(export_id, 'download'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('attachment', res['Content-Disposition'])
        self.assertIn('.zip', res['Content-Disposition'])

    def test_downloaded_package_is_a_readable_zip_with_its_metadata(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']

        path = export.package_path(self.dataset['id'], export_id)
        with zipfile.ZipFile(path) as archive:
            meta = json.loads(archive.read('dataset.json'))
        self.assertEqual(meta['schema_version'], 2)
        self.assertEqual(meta['ignore_index'], 255)
        self.assertEqual(meta['background_index'], 0)

    def test_downloading_an_unfinished_export_is_rejected(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']
        store.update_export(self.dataset['id'], export_id,
                            lambda e: dict(e, status='running', progress=40))

        res = self.client.get(self._url(export_id, 'download'))
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['code'], 'export_not_ready')

    def test_downloading_a_missing_export_is_404(self):
        self.assertEqual(self.client.get(self._url('no-existe', 'download')).status_code, 404)

    # --- Borrar ---------------------------------------------------------------------------

    def test_delete_removes_the_package_from_disk(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']
        path = export.package_path(self.dataset['id'], export_id)
        self.assertTrue(os.path.isfile(path))

        res = self.client.delete(self._url(export_id))
        self.assertEqual(res.status_code, 204)
        self.assertFalse(os.path.exists(path))
        self.assertIsNone(store.get_export(self.dataset['id'], export_id))

    def test_deleting_the_dataset_takes_its_packages_with_it(self):
        self._label_something()
        export_id = self.client.post(self._url(), {}, format='json').data['export_id']
        path = export.package_path(self.dataset['id'], export_id)

        self.client.delete(self._api('datasets', self.dataset['id']))
        self.assertFalse(os.path.exists(path),
                         'un paquete huérfano ocuparía disco para siempre sin nadie que lo borre')


class AsyncFunctionShapeTest(TrainingTestBase):
    """La función despachada al worker debe ser self-contained (D9, Principio IV paso 3).

    `run_function_async` la recompila con `ns = {}`, sin los globals de su módulo. Este test
    reproduce ese mecanismo exacto —`getsource` + `exec` en un diccionario vacío— porque es lo
    único que detecta un import relativo o una referencia a un nombre del módulo antes de que
    falle en producción. No sustituye a la verificación con Celery real, pero sí atrapa la clase
    de error que en `realign` costó una funcionalidad rota.
    """

    def test_the_exported_function_survives_recompilation_in_an_empty_namespace(self):
        import inspect

        from coreplugins.training import api

        source = inspect.getsource(api.run_export_async)
        namespace = {}
        exec(compile(source, 'file', 'exec'), namespace, namespace)
        self.assertIn('run_export_async', namespace)

    def test_the_recompiled_function_actually_runs(self):
        import inspect

        from coreplugins.training import api

        task = self._task_with_orthophoto()
        dataset = self._create_dataset(task, tile_size_px=64)
        self.addCleanup(export.delete_all_packages, dataset['id'])
        self._add_label(dataset, task, class_index=1, geometry=square(0, 0, 12))

        entry = {'id': 'recompiled', 'status': 'running', 'progress': 0, 'error': None,
                 'tile_count': 0, 'size_bytes': 0, 'created_at': '2026-07-30T00:00:00Z',
                 'celery_task_id': None}
        store.upsert_export(dataset['id'], entry)

        # El mismo camino que `eval_async`: código fuente, namespace vacío, llamada por nombre.
        namespace = {}
        exec(compile(inspect.getsource(api.run_export_async), 'file', 'exec'),
             namespace, namespace)
        namespace['run_export_async'](dataset['id'], 'recompiled')

        finished = store.get_export(dataset['id'], 'recompiled')
        self.assertEqual(finished['status'], 'completed', finished.get('error'))
        self.assertGreater(finished['tile_count'], 0)
