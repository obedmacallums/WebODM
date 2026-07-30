"""Endpoint de la máscara (`008` US1/US3, `contracts/rest-api-delta.md`).

El punto delicado es FR-017: «máscara vacía» y «no hay máscara» **no son lo mismo** y no pueden
responder igual. La primera es un resultado —el modelo corrió y no vio calzada, lo que explica por
qué los tramos salieron sin borde—; la segunda no lo es.
"""

import os

from rest_framework import status

from .test_api_analyses import AnalysesApiTestBase
from .test_mask_store import MASK_PAYLOAD

from coreplugins.road import store


class AnalysisMaskEndpointTest(AnalysesApiTestBase):

    def _mask_url(self, task, analysis_id):
        return self._url(task, 'analyses/{}/mask'.format(analysis_id))

    def _analysis(self, task):
        self._login()
        return self._create(task).data['analysis_id']

    def test_returns_the_stored_mask(self):
        task = self._task_with_dem()
        analysis_id = self._analysis(task)
        store.write_mask(str(task.id), analysis_id, MASK_PAYLOAD)

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['features']), 1)
        self.assertEqual(res.data['features'][0]['properties']['class'], 'road')

    def test_reports_resolution_and_tolerance(self):
        """`resolution_m` sostiene el aviso de precisión del panel (`FR-016`).

        Viaja en la respuesta y no como constante del frontend: si el modelo cambiara de
        resolución, un número escrito a mano en el JS dejaría de ser cierto sin que nadie se
        entere.
        """
        task = self._task_with_dem()
        analysis_id = self._analysis(task)
        store.write_mask(str(task.id), analysis_id, MASK_PAYLOAD)

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertEqual(res.data['resolution_m'], 0.2)
        self.assertEqual(res.data['simplify_tolerance_m'], 0.2)

    def test_empty_mask_is_a_result_not_an_error(self):
        """El modelo corrió y no vio calzada: `200` con `features: []` (`FR-017`, caso b)."""
        task = self._task_with_dem()
        analysis_id = self._analysis(task)
        store.write_mask(str(task.id), analysis_id, dict(MASK_PAYLOAD, features=[]))

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['features'], [])

    def test_missing_mask_is_not_the_same_as_an_empty_one(self):
        """Sin máscara guardada: `404 mask_missing` (`FR-017`, caso c).

        **Este es el test que impide mentirle al usuario.** Si esto respondiera `200` con lista
        vacía, el panel diría «el modelo no detectó calzada» cuando la verdad es que nunca se
        guardó nada, y el usuario sacaría una conclusión falsa sobre su calle.
        """
        task = self._task_with_dem()
        analysis_id = self._analysis(task)

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['code'], 'mask_missing')

    def test_unknown_analysis_reports_not_found(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.get(self._mask_url(task, '00000000-0000-0000-0000-000000000000'))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data['code'], 'not_found')

    def test_requires_authentication(self):
        task = self._task_with_dem()
        analysis_id = self._analysis(task)
        store.write_mask(str(task.id), analysis_id, MASK_PAYLOAD)
        self.client.logout()

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertIn(res.status_code,
                      (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN,
                       status.HTTP_404_NOT_FOUND))

    def test_route_is_not_swallowed_by_the_generic_analysis_pattern(self):
        """`plugin.py` avisa de que un `MountPoint` sin `$` resuelve por prefijo.

        Si `analyses/<analysis_id>` se registrara antes, se tragaría `analyses/<id>/mask` y este
        endpoint devolvería el detalle del análisis en vez de la máscara.
        """
        task = self._task_with_dem()
        analysis_id = self._analysis(task)
        store.write_mask(str(task.id), analysis_id, MASK_PAYLOAD)

        res = self.client.get(self._mask_url(task, analysis_id))

        self.assertIn('features', res.data)
        self.assertNotIn('segments', res.data)
