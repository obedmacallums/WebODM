"""API de etiquetas (`contracts/rest-api.md` §Etiquetas).

Siempre en el contexto de un par (dataset, tarea), que es la unidad de bloqueo y de fichero.
"""

import math

from coreplugins.training import store

from .base import TrainingTestBase, offset_to_lnglat


def square(dx, dy, side):
    return [list(offset_to_lnglat(dx, dy)), list(offset_to_lnglat(dx + side, dy)),
            list(offset_to_lnglat(dx + side, dy + side)), list(offset_to_lnglat(dx, dy + side))]


def line(dx, dy, length, points=2):
    return [list(offset_to_lnglat(dx + length * i / (points - 1), dy)) for i in range(points)]


class LabelApiTest(TrainingTestBase):
    def setUp(self):
        super().setUp()
        self.task = self._task()
        self.dataset = self._create_dataset(self.task)
        self._login()

    def _url(self, *extra):
        return self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'labels', *extra)

    # --- Alta ---------------------------------------------------------------------------

    def test_create_a_polygon_returns_the_assigned_order(self):
        """El `order` viaja en la respuesta para que el frontend dibuje en el orden correcto sin
        volver a pedir la lista entera tras cada trazo."""
        res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                             'geometry': square(0, 0, 4)}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['order'], 0)
        self.assertEqual(res.data['class_index'], 1)
        self.assertEqual(res.data['source'], 'manual')

    def test_create_a_stroke_keeps_its_radius_in_meters(self):
        res = self.client.post(self._url(), {'kind': 'stroke', 'class_index': 1, 'radius_m': 2.5,
                                             'geometry': line(0, 10, 20)}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['radius_m'], 2.5)

    def test_create_an_eraser_with_a_null_class(self):
        """FR-014: el borrador devuelve al estado «sin etiquetar», que no es la clase 0."""
        res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': None,
                                             'geometry': square(0, 0, 4)}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertIsNone(res.data['class_index'])

    def test_orders_grow_with_each_label(self):
        orders = []
        for i in range(3):
            res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                                 'geometry': square(i * 5, 0, 4)}, format='json')
            orders.append(res.data['order'])
        self.assertEqual(orders, [0, 1, 2])

    def test_geometry_is_simplified_when_stored(self):
        """FR-015: los vértices por debajo de la resolución del dataset no llegan al disco."""
        dense = [list(offset_to_lnglat(i * 0.2, 5.0)) for i in range(60)]
        res = self.client.post(self._url(), {'kind': 'stroke', 'class_index': 1, 'radius_m': 1.0,
                                             'geometry': dense}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertLess(len(res.data['geometry']), len(dense))

    # --- Errores ------------------------------------------------------------------------

    def test_unknown_class_is_rejected(self):
        res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 9,
                                             'geometry': square(0, 0, 4)}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'unknown_class')

    def test_stroke_without_radius_is_rejected(self):
        res = self.client.post(self._url(), {'kind': 'stroke', 'class_index': 1,
                                             'geometry': line(0, 0, 10)}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_radius')

    def test_stroke_with_non_positive_radius_is_rejected(self):
        res = self.client.post(self._url(), {'kind': 'stroke', 'class_index': 1, 'radius_m': -2,
                                             'geometry': line(0, 0, 10)}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_radius')

    def test_polygon_with_too_few_vertices_is_rejected(self):
        res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                             'geometry': line(0, 0, 10)}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'bad_geometry')

    def test_a_task_outside_the_dataset_is_404(self):
        stranger = self._task(project=self.task.project)
        url = self._api('datasets', self.dataset['id'], 'tasks', stranger.id, 'labels')
        res = self.client.post(url, {'kind': 'polygon', 'class_index': 1,
                                     'geometry': square(0, 0, 4)}, format='json')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data['code'], 'task_not_in_dataset')

    def test_requires_authentication(self):
        """El anónimo no pasa. Sale `404` y no `403` a propósito.

        Es lo que hace `check_project_perms` del core, deliberadamente: un `403` confirmaría que
        esa tarea existe. Las rutas de dataset, que no cuelgan de ninguna tarea, sí responden
        `403` porque ahí no hay existencia que ocultar.
        """
        self.client.logout()
        self.assertEqual(self.client.get(self._url()).status_code, 404)

    # --- Lectura, modificación y borrado ------------------------------------------------

    def test_list_returns_labels_in_composition_order(self):
        for i in range(3):
            self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                           'geometry': square(i * 5, 0, 4)}, format='json')
        res = self.client.get(self._url())
        self.assertEqual(res.status_code, 200)
        self.assertEqual([l['order'] for l in res.data], [0, 1, 2])

    def test_labels_survive_a_reload(self):
        """US1, escenario de aceptación: lo dibujado sigue ahí al volver."""
        self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                       'geometry': square(0, 0, 4)}, format='json')
        self.client.post(self._url(), {'kind': 'stroke', 'class_index': 0, 'radius_m': 3,
                                       'geometry': line(0, 12, 15)}, format='json')

        reloaded = self.client.get(self._url()).data
        self.assertEqual(len(reloaded), 2)
        self.assertEqual([l['class_index'] for l in reloaded], [1, 0])
        self.assertEqual([l['kind'] for l in reloaded], ['polygon', 'stroke'])

    def test_patch_moves_a_vertex(self):
        created = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                                 'geometry': square(0, 0, 4)}, format='json').data
        moved = square(0, 0, 8)
        res = self.client.patch(self._url(created['id']), {'geometry': moved}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertAlmostEqual(res.data['geometry'][2][0], moved[2][0], places=6)
        self.assertEqual(res.data['order'], created['order'])

    def test_patch_changes_the_class(self):
        created = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                                 'geometry': square(0, 0, 4)}, format='json').data
        res = self.client.patch(self._url(created['id']), {'class_index': 0}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['class_index'], 0)

    def test_patch_to_an_unknown_class_is_rejected(self):
        created = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                                 'geometry': square(0, 0, 4)}, format='json').data
        res = self.client.patch(self._url(created['id']), {'class_index': 9}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.data['code'], 'unknown_class')

    def test_delete_removes_only_that_label(self):
        first = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                               'geometry': square(0, 0, 4)}, format='json').data
        self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                       'geometry': square(6, 0, 4)}, format='json')

        res = self.client.delete(self._url(first['id']))
        self.assertEqual(res.status_code, 204)
        remaining = store.list_labels(self.dataset['id'], str(self.task.id))
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0]['id'], first['id'])

    def test_delete_of_a_missing_label_is_404(self):
        self.assertEqual(self.client.delete(self._url('no-existe')).status_code, 404)

    def test_read_only_user_cannot_write(self):
        """Ver el proyecto no basta para etiquetar: escribir exige `change_project`."""
        self.client.logout()
        self._grant_read_only('testuser2', self.task.project)
        self.client.login(username='testuser2', password='test1234')

        self.assertEqual(self.client.get(self._url()).status_code, 200)
        res = self.client.post(self._url(), {'kind': 'polygon', 'class_index': 1,
                                             'geometry': square(0, 0, 4)}, format='json')
        self.assertEqual(res.status_code, 404)


class BrushGeometryTest(TrainingTestBase):
    """El radio del pincel es una medida sobre el terreno (FR-010, FR-012b)."""

    def setUp(self):
        super().setUp()
        self.task = self._task()
        self.dataset = self._create_dataset(self.task)
        self._login()

    def test_stored_stroke_length_matches_the_meters_drawn(self):
        """20 m dibujados siguen midiendo 20 m tras guardarse.

        Es la comprobación de que la conversión a grados de la simplificación no deforma la
        geometría: si la tolerancia se aplicara en las unidades equivocadas, la longitud cambiaría.
        """
        url = self._api('datasets', self.dataset['id'], 'tasks', self.task.id, 'labels')
        stored = self.client.post(url, {'kind': 'stroke', 'class_index': 1, 'radius_m': 2.5,
                                        'geometry': line(0, 10, 20, points=9)},
                                  format='json').data

        first, last = stored['geometry'][0], stored['geometry'][-1]
        mean_lat = math.radians((first[1] + last[1]) / 2)
        dx = (last[0] - first[0]) * 111320.0 * math.cos(mean_lat)
        dy = (last[1] - first[1]) * 110540.0
        self.assertAlmostEqual(math.hypot(dx, dy), 20.0, delta=0.5)
