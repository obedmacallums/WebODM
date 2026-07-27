import os
import json
import time
import shutil
import threading
import unittest
import subprocess
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from django.db import connection as db_connection
from django.test import SimpleTestCase, TransactionTestCase
from guardian.shortcuts import assign_perm
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

from . import store, elevation

# Extent de prueba en la zona UTM 15N (EPSG:32615), coherente con el DEM sintético por defecto.
TEST_EXTENT = Polygon.from_bbox([-93.87, 45.00, -93.86, 45.01])
DEM_EPSG = 32615
DEM_ORIGIN = (500000.0, 4984000.0)  # (x, y) esquina superior izquierda, UTM metros
DEM_SIZE = 200
DEM_RES = 1.0
DEM_NODATA = -9999.0


def _make_dem(path, size=DEM_SIZE, res=DEM_RES, origin=DEM_ORIGIN, epsg=DEM_EPSG,
              nodata=DEM_NODATA, slope=0.05, base=100.0, nodata_patch=None,
              wave_amplitude=0.0, wave_period=10.0):
    """Genera un GeoTIFF sintético `size x size` a resolución `res` m/px: una rampa de
    elevación este-oeste de pendiente conocida (`base + slope * columna`), con un parche
    opcional de `nodata` (research.md D3, D4). `nodata_patch` es `(row0, row1, col0, col1)`.
    `wave_amplitude`/`wave_period` superponen una ondulación senoidal: sin rugosidad, la
    superficie es un plano exacto y la longitud sobre el terreno de un trazado recto no
    cambiaría con el paso de densificación (T027 necesita que sí cambie, como en un DSM real).
    """
    transform = from_origin(origin[0], origin[1], res, res)
    cols = np.arange(size)
    rows = np.arange(size)
    col_grid, _row_grid = np.meshgrid(cols, rows)
    data = (base + slope * col_grid).astype(np.float32)
    if wave_amplitude:
        data = data + wave_amplitude * np.sin(2 * np.pi * col_grid / wave_period)
        data = data.astype(np.float32)

    if nodata_patch is not None:
        r0, r1, c0, c1 = nodata_patch
        data[r0:r1, c0:c1] = nodata

    with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=1,
                        dtype='float32', crs='EPSG:{}'.format(epsg), transform=transform,
                        nodata=nodata) as dst:
        dst.write(data, 1)


def _pixel_to_lnglat(row, col, origin=DEM_ORIGIN, res=DEM_RES, epsg=DEM_EPSG):
    """Convierte una celda del DEM sintético a `[lng, lat]` (EPSG:4326), para construir
    trazados de prueba con cobertura garantizada."""
    import rasterio.warp
    from rasterio.crs import CRS

    x = origin[0] + (col + 0.5) * res
    y = origin[1] - (row + 0.5) * res
    lng, lat = rasterio.warp.transform(CRS.from_epsg(epsg), CRS.from_epsg(4326), [x], [y])
    return [lng[0], lat[0]]


class AnnotationsTestBase(BootTestCase):
    """Andamiaje común para los tests del plugin (patrón de `coreplugins/realign/tests.py`)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Annotations test project"):
        owner = User.objects.get(username="testuser")
        return Project.objects.create(owner=owner, name=name)

    def _task(self, project, **kwargs):
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif"], orthophoto_extent=TEST_EXTENT,
                        epsg=DEM_EPSG)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _task_with_dem(self, project, asset='dsm.tif', dem_kwargs=None, **task_kwargs):
        """Tarea con un DEM sintético ya escrito en su ruta de asset esperada."""
        extent_field = 'dsm_extent' if asset == 'dsm.tif' else 'dtm_extent'
        task_kwargs.setdefault('available_assets', ['orthophoto.tif', asset])
        task_kwargs.setdefault(extent_field, TEST_EXTENT)
        task = self._task(project, **task_kwargs)

        path = task.get_asset_download_path(asset)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _make_dem(path, **(dem_kwargs or {}))
        self.addCleanup(shutil.rmtree, task.task_path(), ignore_errors=True)
        return task

    def _url(self, task, suffix="polylines"):
        return "/api/plugins/annotations/task/{}/{}".format(task.id, suffix)

    def _login(self, username="testuser"):
        self.client.login(username=username, password="test1234")

    def _covered_vertices(self, n=3, row_span=(20, 180), col_span=(20, 180)):
        """`n` vértices en línea recta dentro del DEM sintético, lejos de los bordes."""
        r0, r1 = row_span
        c0, c1 = col_span
        return [
            _pixel_to_lnglat(r0 + (r1 - r0) * i / (n - 1), c0 + (c1 - c0) * i / (n - 1))
            for i in range(n)
        ]


# --- User Story 1: trazar y conservar (T012-T014) --------------------------------------------

FLAT_VERTICES = [[-93.8690, 45.0050], [-93.8680, 45.0055], [-93.8670, 45.0052]]


class PolylineCreateListTest(AnnotationsTestBase):
    """T012 — alta y listado de polilíneas planas (FR-002, FR-003)."""

    def test_create_and_list_flat_polyline(self):
        task = self._task(self._project())
        self._login()
        res = self.client.post(self._url(task), {'name': 'Camino norte', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.data['name'], 'Camino norte')
        self.assertEqual(res.data['mode'], 'flat')
        self.assertEqual(len(res.data['vertices']), 3)
        self.assertGreater(res.data['plan_length'], 0)
        self.assertNotIn('elevation', res.data)

        res2 = self.client.get(self._url(task))
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.data['version'], 1)
        self.assertEqual(len(res2.data['polylines']), 1)
        self.assertEqual(res2.data['polylines'][0]['id'], res.data['id'])

    def test_reject_single_vertex(self):
        task = self._task(self._project())
        self._login()
        res = self.client.post(self._url(task), {'name': 'x', 'vertices': [FLAT_VERTICES[0]]}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('error', res.data)

    def test_reject_coincident_vertices(self):
        task = self._task(self._project())
        self._login()
        v = [FLAT_VERTICES[0], FLAT_VERTICES[0]]
        res = self.client.post(self._url(task), {'name': 'x', 'vertices': v}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_reject_too_many_vertices(self):
        task = self._task(self._project())
        self._login()
        vertices = [[-93.87 + i * 0.00001, 45.0] for i in range(501)]
        res = self.client.post(self._url(task), {'name': 'x', 'vertices': vertices}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_default_name_when_empty(self):
        task = self._task(self._project())
        self._login()
        res1 = self.client.post(self._url(task), {'name': '', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(res1.data['name'], 'Polilínea 1')
        res2 = self.client.post(self._url(task), {'name': '  ', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(res2.data['name'], 'Polilínea 2')

    def test_empty_task_returns_empty_list(self):
        task = self._task(self._project())
        self._login()
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['polylines'], [])


class PolylineDeleteTest(AnnotationsTestBase):
    """T016 — DELETE por HTTP (además del borrado en cascada de T014). Cubre también el
    enrutado exacto de `plugin.py`: sin anclar cada MountPoint con '$', Django resuelve por
    prefijo y 'polylines' se "traga" 'polylines/<id>' antes de llegar a `PolylineDetail`."""

    def test_delete_removes_polyline(self):
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json')
        polyline_id = created.data['id']

        res = self.client.delete(self._url(task, "polylines/{}".format(polyline_id)))
        self.assertEqual(res.status_code, 204)
        self.assertEqual(store.list_polylines(task.id), [])

    def test_delete_unknown_id_returns_404(self):
        task = self._task(self._project())
        self._login()
        res = self.client.delete(self._url(task, "polylines/does-not-exist"))
        self.assertEqual(res.status_code, 404)

    def test_delete_requires_change_project(self):
        project = self._project()
        task = self._task(project)
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json')
        self.client.logout()
        self.client.login(username="testuser2", password="test1234")
        res = self.client.delete(self._url(task, "polylines/{}".format(created.data['id'])))
        self.assertEqual(res.status_code, 404)
        self.assertEqual(len(store.list_polylines(task.id)), 1)


class PolylinePermissionsTest(AnnotationsTestBase):
    """T013 — lectura con `view_project`, escritura exige `change_project` (FR-025)."""

    def test_read_with_view_project(self):
        project = self._project()
        task = self._task(project)
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, 200)

    def test_write_without_change_project_returns_404(self):
        project = self._project()
        task = self._task(project)
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(res.status_code, 404)

    def test_public_task_is_readable(self):
        project = self._project()
        task = self._task(project, public=True)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, 200)


class PolylineCascadeDeleteTest(AnnotationsTestBase):
    """T014 — `task_removed` borra el documento entero (FR-027)."""

    def test_task_removed_signal_deletes_document(self):
        from app.plugins import signals as plugin_signals

        task = self._task(self._project())
        self._login()
        self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(len(store.list_polylines(task.id)), 1)

        plugin_signals.task_removed.send(sender=self.__class__, task_id=task.id)

        self.assertEqual(store.list_polylines(task.id), [])


# --- User Story 2: elevación (T025-T028) ------------------------------------------------------

class ElevationCapabilitiesTest(AnnotationsTestBase):
    """T028 — tarea sin DEM: `elevation` vacío y `draped` rechazado (FR-009)."""

    def test_task_without_dem_reports_no_models_available(self):
        task = self._task(self._project())
        self._login()
        res = self.client.get(self._url(task, "elevation"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['available'], [])
        self.assertIsNone(res.data['default_model'])

    def test_draped_creation_without_dem_returns_400(self):
        task = self._task(self._project())
        self._login()
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': FLAT_VERTICES
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_task_with_dem_reports_default_step_and_range(self):
        task = self._task_with_dem(self._project())
        self._login()
        res = self.client.get(self._url(task, "elevation"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['available'], ['dsm'])
        self.assertEqual(res.data['default_model'], 'dsm')
        self.assertAlmostEqual(res.data['resolution'], DEM_RES, places=3)
        self.assertAlmostEqual(res.data['default_step'], max(DEM_RES, 0.25), places=3)
        self.assertAlmostEqual(res.data['step_range'][0], DEM_RES, places=3)
        self.assertEqual(res.data['step_range'][1], 10.0)


class ElevationDensificationTest(AnnotationsTestBase):
    """T025 — paso por defecto, rango y tope de puntos densificados (FR-014, FR-023)."""

    def test_default_step_used_when_omitted(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertAlmostEqual(res.data['elevation']['step'], max(DEM_RES, 0.25), places=3)

    def test_reject_step_out_of_range(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices, 'step': 0.01
        }, format='json')
        self.assertEqual(res.status_code, 400)

    def test_reject_too_many_densified_points(self):
        task = self._task_with_dem(self._project())
        self._login()
        # ~0.30 grados de longitud a lat 45 son ~23.5 km; al paso nativo (1 m) supera
        # ampliamente MAX_SAMPLES (20 000), sin necesidad de que el trazado tenga cobertura
        # real (el tope se comprueba antes de muestrear el ráster).
        far_vertices = [[-93.87, 45.00], [-93.57, 45.00]]
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': far_vertices, 'step': DEM_RES
        }, format='json')
        self.assertEqual(res.status_code, 400)


class ElevationCoverageTest(AnnotationsTestBase):
    """T026 — cobertura incompleta: 422, `missing_ranges` correcto, nada persiste (FR-021, FR-022)."""

    def test_vertex_outside_raster_returns_422_and_persists_nothing(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = [_pixel_to_lnglat(-50, 100), _pixel_to_lnglat(100, 100)]
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.data['reason'], 'incomplete_coverage')
        self.assertGreater(len(res.data['missing_ranges']), 0)
        self.assertGreater(res.data['missing_samples'], 0)
        self.assertEqual(store.list_polylines(task.id), [])

    def test_nodata_gap_returns_422_with_missing_ranges(self):
        task = self._task_with_dem(self._project(), dem_kwargs={'nodata_patch': (90, 110, 90, 110)})
        self._login()
        vertices = [_pixel_to_lnglat(20, 100), _pixel_to_lnglat(180, 100)]
        res = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json')
        self.assertEqual(res.status_code, 422)
        self.assertEqual(res.data['reason'], 'incomplete_coverage')
        rng = res.data['missing_ranges'][0]
        # El hueco (filas 90-110) cae en el tercio central del trazado (filas 20-180).
        self.assertGreater(rng[0], 0.3)
        self.assertLess(rng[1], 0.7)
        self.assertEqual(store.list_polylines(task.id), [])


class ElevationMetricsTest(AnnotationsTestBase):
    """T027 — `surface_length >= plan_length`, y cambia con el paso (FR-015)."""

    def test_surface_length_gte_plan_length_and_varies_with_step(self):
        task = self._task_with_dem(self._project(), dem_kwargs={'wave_amplitude': 2.0, 'wave_period': 8.0})
        self._login()
        vertices = self._covered_vertices(n=2)

        res1 = self.client.post(self._url(task), {
            'name': 'a', 'mode': 'draped', 'vertices': vertices, 'step': 1.0
        }, format='json')
        self.assertEqual(res1.status_code, 201, res1.content)
        self.assertGreaterEqual(res1.data['elevation']['surface_length'], res1.data['plan_length'])

        res2 = self.client.post(self._url(task), {
            'name': 'b', 'mode': 'draped', 'vertices': vertices, 'step': 5.0
        }, format='json')
        self.assertEqual(res2.status_code, 201, res2.content)
        self.assertNotAlmostEqual(
            res1.data['elevation']['surface_length'], res2.data['elevation']['surface_length'], places=2
        )


# --- User Story 3: exportar a GeoJSON (T038) ---------------------------------------------------

class ExportGeoJSONTest(AnnotationsTestBase):
    """T038 — `LineString` de 2/3 ordenadas, propiedades completas/omitidas, variante
    `geometry=densified` (FR-032 a FR-034)."""

    def test_export_flat_and_draped_polylines(self):
        task = self._task_with_dem(self._project())
        self._login()

        flat_res = self.client.post(self._url(task), {'name': 'Plana', 'vertices': FLAT_VERTICES}, format='json')
        self.assertEqual(flat_res.status_code, 201, flat_res.content)

        vertices = self._covered_vertices()
        draped_res = self.client.post(self._url(task), {
            'name': 'Elevada', 'mode': 'draped', 'vertices': vertices
        }, format='json')
        self.assertEqual(draped_res.status_code, 201, draped_res.content)

        res = self.client.get(self._url(task, "polylines/export"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/geo+json')
        self.assertIn('attachment', res['Content-Disposition'])

        fc = json.loads(res.content)
        self.assertEqual(fc['type'], 'FeatureCollection')
        self.assertEqual(len(fc['features']), 2)

        flat_feature = next(f for f in fc['features'] if f['properties']['name'] == 'Plana')
        self.assertEqual(flat_feature['geometry']['type'], 'LineString')
        self.assertEqual(len(flat_feature['geometry']['coordinates'][0]), 2)
        self.assertNotIn('surface_length_m', flat_feature['properties'])
        self.assertIn('plan_length_m', flat_feature['properties'])

        draped_feature = next(f for f in fc['features'] if f['properties']['name'] == 'Elevada')
        self.assertEqual(len(draped_feature['geometry']['coordinates']), len(vertices))
        self.assertEqual(len(draped_feature['geometry']['coordinates'][0]), 3)
        self.assertIn('surface_length_m', draped_feature['properties'])
        self.assertIn('elevation_model', draped_feature['properties'])
        self.assertIn('densify_step_m', draped_feature['properties'])

    def test_export_densified_variant_has_more_points(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        self.client.post(self._url(task), {
            'name': 'Elevada', 'mode': 'draped', 'vertices': vertices
        }, format='json')

        res = self.client.get(self._url(task, "polylines/export") + "?geometry=densified")
        self.assertEqual(res.status_code, 200)
        fc = json.loads(res.content)
        coords = fc['features'][0]['geometry']['coordinates']
        self.assertGreater(len(coords), len(vertices))
        self.assertEqual(len(coords[0]), 3)

    def test_export_invalid_geometry_param_returns_400(self):
        task = self._task(self._project())
        self._login()
        res = self.client.get(self._url(task, "polylines/export") + "?geometry=bogus")
        self.assertEqual(res.status_code, 400)


class SinglePolylineExportTest(AnnotationsTestBase):
    """Exportación de una sola polilínea, con el tipo en el nombre del archivo (FR-032)."""

    def _single_url(self, task, polyline_id, query=""):
        return self._url(task, "polylines/{}/export".format(polyline_id)) + query

    def test_export_flat_polyline_uses_2d_suffix_and_exports_only_that_one(self):
        task = self._task_with_dem(self._project(), name="Vuelo Norte")
        self._login()
        flat = self.client.post(self._url(task), {'name': 'Borde parcela', 'vertices': FLAT_VERTICES},
                                format='json').data
        self.client.post(self._url(task), {
            'name': 'Otra', 'mode': 'draped', 'vertices': self._covered_vertices()
        }, format='json')

        res = self.client.get(self._single_url(task, flat['id']))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res['Content-Type'], 'application/geo+json')
        self.assertIn('vuelo-norte-borde-parcela-2d.geojson', res['Content-Disposition'])

        fc = json.loads(res.content)
        self.assertEqual(fc['type'], 'FeatureCollection')
        self.assertEqual(len(fc['features']), 1)
        self.assertEqual(fc['features'][0]['properties']['name'], 'Borde parcela')
        self.assertEqual(len(fc['features'][0]['geometry']['coordinates'][0]), 2)

    def test_export_draped_polyline_uses_3d_suffix(self):
        task = self._task_with_dem(self._project(), name="Vuelo Norte")
        self._login()
        draped = self.client.post(self._url(task), {
            'name': 'Camino', 'mode': 'draped', 'vertices': self._covered_vertices()
        }, format='json').data

        res = self.client.get(self._single_url(task, draped['id']))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn('vuelo-norte-camino-3d.geojson', res['Content-Disposition'])
        self.assertEqual(len(json.loads(res.content)['features'][0]['geometry']['coordinates'][0]), 3)

    def test_export_densified_variant_of_a_single_polyline(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        draped = self.client.post(self._url(task), {
            'name': 'Camino', 'mode': 'draped', 'vertices': vertices
        }, format='json').data

        res = self.client.get(self._single_url(task, draped['id'], "?geometry=densified"))
        self.assertEqual(res.status_code, 200)
        coords = json.loads(res.content)['features'][0]['geometry']['coordinates']
        self.assertGreater(len(coords), len(vertices))

    def test_export_unknown_id_returns_404(self):
        task = self._task(self._project())
        self._login()
        res = self.client.get(self._single_url(task, "does-not-exist"))
        self.assertEqual(res.status_code, 404)

    def test_export_invalid_geometry_param_returns_400(self):
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES},
                                   format='json').data
        res = self.client.get(self._single_url(task, created['id'], "?geometry=bogus"))
        self.assertEqual(res.status_code, 400)


# --- User Story 4: editar (T044-T046) -----------------------------------------------------------

class PolylinePatchTest(AnnotationsTestBase):
    """T044 — PATCH: renombrado puro, cambio de geometría con re-muestreo, atomicidad (FR-004, FR-019)."""

    def _create_draped(self, task, vertices=None):
        vertices = vertices or self._covered_vertices()
        res = self.client.post(self._url(task), {
            'name': 'Original', 'mode': 'draped', 'vertices': vertices
        }, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        return res.data

    def test_rename_only_does_not_resample(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self._create_draped(task)
        old_sampled_at = created['elevation']['sampled_at']

        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])),
                                {'name': 'Nuevo nombre'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['name'], 'Nuevo nombre')
        self.assertEqual(res.data['elevation']['sampled_at'], old_sampled_at)
        self.assertEqual(res.data['vertices'], created['vertices'])

    def test_geometry_change_resamples(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self._create_draped(task)
        new_vertices = self._covered_vertices(row_span=(30, 170), col_span=(30, 170))

        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])),
                                {'vertices': new_vertices}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['vertices'], new_vertices)
        self.assertNotEqual(res.data['elevation']['sampled_at'], created['elevation']['sampled_at'])

    def test_geometry_change_losing_coverage_is_atomic(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self._create_draped(task)
        bad_vertices = [_pixel_to_lnglat(-50, 100), _pixel_to_lnglat(100, 100)]

        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])),
                                {'vertices': bad_vertices}, format='json')
        self.assertEqual(res.status_code, 422)

        unchanged = self.client.get(self._url(task))
        self.assertEqual(unchanged.data['polylines'][0]['vertices'], created['vertices'])

    def test_patch_unknown_id_returns_404(self):
        task = self._task(self._project())
        self._login()
        res = self.client.patch(self._url(task, "polylines/does-not-exist"), {'name': 'x'}, format='json')
        self.assertEqual(res.status_code, 404)

    def test_patch_requires_change_project(self):
        project = self._project()
        task = self._task(project)
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data
        self.client.logout()
        self.client.login(username="testuser2", password="test1234")
        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])), {'name': 'y'}, format='json')
        self.assertEqual(res.status_code, 404)


class PolylineTypeIsImmutableTest(AnnotationsTestBase):
    """El tipo (2D/3D) se fija al crear y ya no se convierte: las rutas de conversión
    desaparecieron y un PATCH que intente cambiar `mode` se rechaza (contrato v2)."""

    def test_elevate_and_flatten_routes_are_gone(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data

        for route in ('elevate', 'flatten'):
            res = self.client.post(self._url(task, "polylines/{}/{}".format(created['id'], route)))
            self.assertEqual(res.status_code, 404, "la ruta {} debería haber desaparecido".format(route))

    def test_patch_rejects_mode_change(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data
        self.assertEqual(created['mode'], 'flat')

        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])),
                                {'mode': 'draped'}, format='json')
        self.assertEqual(res.status_code, 400, res.content)

        unchanged = self.client.get(self._url(task))
        self.assertEqual(unchanged.data['polylines'][0]['mode'], 'flat')

    def test_patch_accepts_same_mode_alongside_other_changes(self):
        """Reenviar el mismo `mode` no es un intento de conversión: no debe estorbar."""
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data

        res = self.client.patch(self._url(task, "polylines/{}".format(created['id'])),
                                {'mode': 'flat', 'name': 'y'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['name'], 'y')


class PolylineStaleTest(AnnotationsTestBase):
    """T046 — `stale: true` cuando el DEM cambia después del muestreo (FR-020)."""

    def test_stale_after_dem_mtime_changes(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json').data
        self.assertFalse(created['elevation']['stale'])

        dem_path = task.get_asset_download_path('dsm.tif')
        future = os.path.getmtime(dem_path) + 3600
        os.utime(dem_path, (future, future))

        res = self.client.get(self._url(task))
        self.assertTrue(res.data['polylines'][0]['elevation']['stale'])


# --- User Story 5: contrato para otros plugins (T053-T054) -------------------------------------

class PluginContractTest(AnnotationsTestBase):
    """T053 — `contract_version`, `get_polylines`, `get_polyline` y `get_densified` desde el objeto
    `Plugin`, sin pasar por la API REST (FR-036 a FR-038). Es exactamente lo que haría otro plugin
    consumidor tras `get_plugin_by_name("annotations")`."""

    def _plugin(self):
        from app.plugins.functions import get_plugin_by_name
        plugin = get_plugin_by_name("annotations")
        self.assertIsNotNone(plugin, "el plugin annotations debe estar registrado y habilitado")
        return plugin

    def test_contract_version(self):
        self.assertEqual(self._plugin().contract_version(), 2)

    def test_elevate_is_no_longer_part_of_the_contract(self):
        """v2 retiró la conversión: un consumidor que aún la llame debe fallar de forma evidente,
        no encontrarse un método que ya no se mantiene."""
        self.assertFalse(hasattr(self._plugin(), 'elevate'))

    def test_get_polylines_empty_task(self):
        task = self._task(self._project())
        self.assertEqual(self._plugin().get_polylines(task.id), [])

    def test_get_polylines_and_get_polyline_match_rest_schema(self):
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data

        plugin = self._plugin()
        lines = plugin.get_polylines(task.id)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], created)

        self.assertEqual(plugin.get_polyline(task.id, created['id']), created)
        self.assertIsNone(plugin.get_polyline(task.id, 'does-not-exist'))

    def test_get_densified_on_flat_polyline_raises_value_error(self):
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data

        with self.assertRaises(ValueError):
            self._plugin().get_densified(task.id, created['id'])

    def test_get_densified_matches_the_stored_sampling(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json').data

        densified = self._plugin().get_densified(task.id, created['id'])
        self.assertEqual(densified['step'], created['elevation']['step'])
        self.assertEqual(densified['model'], created['elevation']['model'])
        self.assertGreater(densified['sample_count'], len(vertices))
        self.assertEqual(len(densified['coordinates'][0]), 3)


class PolylineDensifiedEndpointTest(AnnotationsTestBase):
    """T054 — `GET .../densified`: recálculo con `step` alternativo, rechazo sobre polilíneas
    planas y rechazo por exceso de puntos (FR-038, FR-023)."""

    def test_densified_with_default_step(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json').data

        res = self.client.get(self._url(task, "polylines/{}/densified".format(created['id'])))
        self.assertEqual(res.status_code, 200, res.content)
        self.assertAlmostEqual(res.data['step'], created['elevation']['step'], places=3)
        self.assertEqual(res.data['model'], created['elevation']['model'])
        self.assertEqual(res.data['sample_count'], len(res.data['coordinates']))
        self.assertEqual(len(res.data['coordinates'][0]), 3)

    def test_densified_with_alternate_step_recalculates(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices, 'step': 1.0
        }, format='json').data

        res = self.client.get(
            self._url(task, "polylines/{}/densified".format(created['id'])) + "?step=5.0")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertAlmostEqual(res.data['step'], 5.0, places=3)
        self.assertLess(res.data['sample_count'], created['elevation']['sample_count'])

    def test_densified_rejects_flat_polyline(self):
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data

        res = self.client.get(self._url(task, "polylines/{}/densified".format(created['id'])))
        self.assertEqual(res.status_code, 400)

    def test_densified_rejects_step_exceeding_max_samples(self):
        task = self._task_with_dem(self._project())
        self._login()
        vertices = self._covered_vertices()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': vertices
        }, format='json').data

        res = self.client.get(
            self._url(task, "polylines/{}/densified".format(created['id'])) + "?step=0.001")
        self.assertEqual(res.status_code, 400)

    def test_densified_unknown_id_returns_404(self):
        task = self._task_with_dem(self._project())
        self._login()
        res = self.client.get(self._url(task, "polylines/does-not-exist/densified"))
        self.assertEqual(res.status_code, 404)


class DensifiedStepValidationTest(AnnotationsTestBase):
    """El `step` del query param no pasaba por `validate_step`: era el único camino en el que un
    valor del usuario llegaba crudo a `_densify_projected`. Un 0 abortaba con
    `ZeroDivisionError` (HTTP 500) y los valores negativos o por encima de `MAX_STEP` devolvían
    la línea sin densificar como si fueran válidos."""

    def _draped_polyline(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': self._covered_vertices()
        }, format='json').data
        return task, created

    def _densified(self, task, created, query=""):
        return self.client.get(
            self._url(task, "polylines/{}/densified".format(created['id'])) + query)

    def test_step_zero_returns_400(self):
        task, created = self._draped_polyline()
        self.assertEqual(self._densified(task, created, "?step=0").status_code, 400)

    def test_negative_step_returns_400(self):
        task, created = self._draped_polyline()
        self.assertEqual(self._densified(task, created, "?step=-5").status_code, 400)

    def test_step_above_max_returns_400(self):
        task, created = self._draped_polyline()
        res = self._densified(task, created, "?step={}".format(elevation.MAX_STEP + 1))
        self.assertEqual(res.status_code, 400)

    def test_step_below_dem_resolution_returns_400(self):
        task, created = self._draped_polyline()
        # Por debajo de la resolución del DEM el muestreo no aporta dato nuevo; `validate_step`
        # ya lo rechazaba al crear, y ahora también aquí.
        self.assertEqual(self._densified(task, created, "?step=0.0001").status_code, 400)

    def test_valid_step_still_works(self):
        """La validación no debe cerrarle la puerta a un `step` legítimo."""
        task, created = self._draped_polyline()
        res = self._densified(task, created, "?step=5.0")
        self.assertEqual(res.status_code, 200, res.content)
        self.assertAlmostEqual(res.data['step'], 5.0, places=3)

    def test_flat_polyline_still_reports_its_own_error(self):
        """`ValueError` lo comparten la polilínea plana y el paso inválido: el mensaje no se
        debe confundir al distinguirlos."""
        task = self._task(self._project())
        self._login()
        created = self.client.post(self._url(task), {
            'name': 'x', 'vertices': FLAT_VERTICES}, format='json').data
        res = self._densified(task, created)
        self.assertEqual(res.status_code, 400)
        self.assertIn('terreno', res.data['error'])


class CorruptedDocumentTest(AnnotationsTestBase):
    """Un documento con el bloque `elevation` incompleto no debería tumbar la petición ni
    exportar geometría recortada: son datos que el plugin nunca escribe así, pero que puede
    encontrarse (documento heredado, edición manual del store, reproceso a medias)."""

    def _draped_polyline(self):
        task = self._task_with_dem(self._project())
        self._login()
        created = self.client.post(self._url(task), {
            'name': 'x', 'mode': 'draped', 'vertices': self._covered_vertices()
        }, format='json').data
        return task, created

    def _mutate_stored(self, task, polyline_id, mutate):
        stored = store.get_polyline(task.id, polyline_id)
        mutate(stored)
        store.upsert_polyline(task.id, stored)

    def test_patch_without_elevation_block_returns_400(self):
        task, created = self._draped_polyline()
        self._mutate_stored(task, created['id'], lambda p: p.pop('elevation'))

        res = self.client.patch(
            self._url(task, "polylines/{}".format(created['id'])),
            {'vertices': self._covered_vertices(n=4)}, format='json')
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn('error', res.data)

    def test_export_with_truncated_vertex_z_keeps_every_vertex(self):
        task, created = self._draped_polyline()
        n_vertices = len(created['vertices'])
        self._mutate_stored(task, created['id'],
                            lambda p: p['elevation'].update({'vertex_z': p['elevation']['vertex_z'][:1]}))

        res = self.client.get(self._url(task, "polylines/{}/export".format(created['id'])))
        self.assertEqual(res.status_code, 200)
        coords = json.loads(res.content)['features'][0]['geometry']['coordinates']
        self.assertEqual(len(coords), n_vertices, 'la exportación perdió vértices')
        self.assertTrue(all(len(c) == 2 for c in coords),
                        'sin cotas fiables se exporta en 2D, no una mezcla')


# --- Fase 8: regla del bus de anotaciones (T060) ------------------------------------------------

class AnnotationsBusRuleTest(AnnotationsTestBase):
    """T060 — el bus de `PluginsAPI.Map` se detiene en el primer valor *truthy*
    (`ApiFactory.js:95-102`): todo manejador debe devolver `false` ante un layer/formato ajeno
    antes de tocar nada, o rompe a cualquier otro plugin que en el futuro produzca anotaciones
    (`contracts/plugin-contract.md` §2.3, riesgo 1 de `research.md`).

    No hay entorno de tests JS para plugins en este fork: `jest.config.js` solo cubre
    `app/static/app/js` y es un archivo del core que no se toca (Principio I de la
    constitución). Se verifica la invariante de forma estática sobre el código fuente de
    `annotationsBridge.js`, localizando el cuerpo de cada callback por conteo de llaves (para no
    depender del formato exacto del archivo) y comprobando que la guarda de rechazo antecede a
    cualquier acción sobre el layer o el bus.
    """

    BRIDGE_PATH = os.path.join(os.path.dirname(__file__), 'public', 'annotationsBridge.js')

    @classmethod
    def _bridge_source(cls):
        with open(cls.BRIDGE_PATH, encoding='utf-8') as f:
            return f.read()

    @classmethod
    def _handler_body(cls, src, registration):
        """Cuerpo del callback registrado como `PluginsAPI.Map.<registration>((...) => { ... })`,
        delimitado contando llaves desde la primera que sigue a la marca."""
        marker = 'PluginsAPI.Map.{}('.format(registration)
        start = src.index(marker)
        brace_start = src.index('{', start)
        depth = 0
        i = brace_start
        while i < len(src):
            if src[i] == '{':
                depth += 1
            elif src[i] == '}':
                depth -= 1
                if depth == 0:
                    return src[brace_start + 1:i]
            i += 1
        raise AssertionError('no se encontró el cuerpo de {}'.format(registration))

    def test_toggle_handler_rejects_foreign_layer_before_acting(self):
        body = self._handler_body(self._bridge_source(), 'onToggleAnnotation')
        self.assertIn('return false', body)
        self.assertLess(body.index('return false'), body.index('meta.map'))

    def test_delete_handler_rejects_foreign_layer_before_acting(self):
        body = self._handler_body(self._bridge_source(), 'onDeleteAnnotation')
        self.assertIn('return false', body)
        self.assertLess(body.index('return false'), body.index('$.ajax'))

    def test_download_handler_rejects_other_formats_before_acting(self):
        body = self._handler_body(self._bridge_source(), 'onDownloadAnnotations')
        self.assertIn('return false', body)
        self.assertLess(body.index('return false'), body.index('downloadExport'))


# --- Unidades del frontend (`public/tests/*.test.js`) -------------------------------------------

JS_TESTS_DIR = os.path.join(os.path.dirname(__file__), 'public', 'tests')


def _js_runtime_available():
    """`node` con `jsdom` y `leaflet` resolubles desde `public/tests`. Fuera de la imagen (p. ej.
    el Mac del desarrollador, sin `node_modules`) no lo están y los casos se saltan: el frontend
    se prueba en Docker, igual que el resto de la suite."""
    if shutil.which('node') is None:
        return False
    # `require.resolve` y no `require`: Leaflet toca `window` al cargarse y sin DOM lanzaría,
    # haciendo pasar por ausente una dependencia que sí está.
    probe = subprocess.run(
        ['node', '-e', 'require.resolve("jsdom"); require.resolve("leaflet")'],
        cwd=JS_TESTS_DIR, capture_output=True)
    return probe.returncode == 0


@unittest.skipUnless(_js_runtime_available(), 'node/jsdom/leaflet no disponibles fuera de Docker')
class FrontendUnitTest(SimpleTestCase):
    """Ejecuta los tests de `public/tests` con el intérprete que ya trae la imagen.

    El `jest.config.js` del core solo cubre `app/static/app/js` y es un archivo de upstream que no
    se toca (Principio I), así que el plugin trae sus propios casos y los engancha aquí para que
    corran con la suite de siempre. Cargan los módulos reales de `public/`, no una copia.
    """

    def _run_js(self, script):
        proc = subprocess.run(['node', script], cwd=JS_TESTS_DIR,
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            self.fail('{} falló:\n{}\n{}'.format(script, proc.stdout, proc.stderr))

    def test_polyline_editor_vertex_insertion(self):
        self._run_js('polylineEditor.test.js')

    def test_annotations_bridge_delete_and_download(self):
        self._run_js('annotationsBridge.test.js')

    def test_panel_stacking_between_plugins(self):
        self._run_js('panelStacking.test.js')


# --- Concurrencia sobre el documento compartido de una tarea ------------------------------------

class StoreConcurrencyTest(TransactionTestCase):
    """El documento de una tarea es uno solo y lo comparten todos los usuarios con acceso a ella
    (FR-025), mientras que cada alta, borrado o arrastre de vértice es una petición que lo reescribe
    entero. Sin bloqueo, dos peticiones simultáneas leían la misma versión y la última en guardar
    borraba la polilínea de la otra, sin error visible en ninguna de las dos.

    Hace falta `TransactionTestCase`: con el `TestCase` normal todo el test vive dentro de una
    transacción que las otras conexiones no ven, y los hilos no compartirían datos.
    """

    TASK_ID = 'concurrency-test-task'
    WRITE_WINDOW = 0.5  # margen para que las dos escrituras se solapen de verdad

    def _write_in_thread(self, polyline_id, barrier, errors):
        try:
            barrier.wait()  # ambos hilos entran a la sección a la vez
            store.upsert_polyline(self.TASK_ID, {'id': polyline_id, 'name': polyline_id})
        except Exception as e:  # noqa: BLE001 - se reporta al hilo principal
            errors.append(e)
        finally:
            db_connection.close()

    def test_simultaneous_writers_keep_both_polylines(self):
        barrier = threading.Barrier(2, timeout=30)
        errors = []
        original_get_document = store.get_document

        def slow_get_document(task_id):
            # Ensancha la ventana leer-modificar-guardar hasta hacerla observable; sin el
            # bloqueo, los dos hilos leen aquí el mismo documento vacío.
            doc = original_get_document(task_id)
            time.sleep(self.WRITE_WINDOW)
            return doc

        with mock.patch.object(store, 'get_document', slow_get_document):
            threads = [threading.Thread(target=self._write_in_thread, args=(pid, barrier, errors))
                       for pid in ('A', 'B')]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            self.assertFalse(any(t.is_alive() for t in threads), 'un hilo se quedó bloqueado')

        self.assertEqual(errors, [], 'las escrituras concurrentes no deben fallar')
        ids = sorted(p['id'] for p in store.list_polylines(self.TASK_ID))
        self.assertEqual(ids, ['A', 'B'], 'una de las dos polilíneas se perdió')

    def test_simultaneous_delete_and_create_keep_the_survivor(self):
        """El borrado también relee dentro del bloqueo: no puede resucitar lo que se creó
        mientras tanto ni llevarse por delante una polilínea ajena."""
        store.upsert_polyline(self.TASK_ID, {'id': 'old', 'name': 'old'})
        barrier = threading.Barrier(2, timeout=30)
        errors = []
        original_get_document = store.get_document

        def slow_get_document(task_id):
            doc = original_get_document(task_id)
            time.sleep(self.WRITE_WINDOW)
            return doc

        def delete_old():
            try:
                barrier.wait()
                store.remove_polyline(self.TASK_ID, 'old')
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                db_connection.close()

        with mock.patch.object(store, 'get_document', slow_get_document):
            threads = [threading.Thread(target=delete_old),
                       threading.Thread(target=self._write_in_thread, args=('new', barrier, errors))]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=60)
            self.assertFalse(any(t.is_alive() for t in threads), 'un hilo se quedó bloqueado')

        self.assertEqual(errors, [])
        ids = sorted(p['id'] for p in store.list_polylines(self.TASK_ID))
        self.assertEqual(ids, ['new'], 'quedó {} en vez de solo la nueva'.format(ids))
