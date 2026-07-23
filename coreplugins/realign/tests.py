import os
import shutil
import tempfile
import unittest

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from guardian.shortcuts import assign_perm
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

from . import transform, corrections

TEST_EXTENT = Polygon.from_bbox([-82.8325, 27.9578, -82.8310, 27.9593])
# Pares de puntos de control de ejemplo (cerca de Tampa, UTM 17N / EPSG:32617).
POINTS_OK = [
    {'id': 1, 'source': {'lat': 27.9580, 'lng': -82.8320}, 'target': {'lat': 27.9581, 'lng': -82.8319}, 'enabled': True},
    {'id': 2, 'source': {'lat': 27.9590, 'lng': -82.8315}, 'target': {'lat': 27.9591, 'lng': -82.8314}, 'enabled': True},
    {'id': 3, 'source': {'lat': 27.9585, 'lng': -82.8312}, 'target': {'lat': 27.9586, 'lng': -82.8311}, 'enabled': True},
]
POINTS_DEGENERATE = [
    {'id': 1, 'source': {'lat': 27.9585, 'lng': -82.8318}, 'target': {'lat': 27.9586, 'lng': -82.8317}, 'enabled': True},
    {'id': 2, 'source': {'lat': 27.9585, 'lng': -82.8318}, 'target': {'lat': 27.9590, 'lng': -82.8310}, 'enabled': True},
]


class RealignStateTest(BootTestCase):
    """Tests de los endpoints de realineación (US1–US4)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Realign test project"):
        owner = User.objects.get(username="testuser")
        return Project.objects.create(owner=owner, name=name)

    def _task(self, project, **kwargs):
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif"], orthophoto_extent=TEST_EXTENT, epsg=32617)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _url(self, task, suffix="state"):
        return "/api/plugins/realign/task/{}/realign/{}".format(task.id, suffix)

    # --- US1 -----------------------------------------------------------------

    def test_state_lists_available_2d_products(self):
        task = self._task(self._project(), available_assets=["orthophoto.tif", "dsm.tif"], dsm_extent=TEST_EXTENT)
        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("orthophoto", res.data["products"])
        self.assertIn("dsm", res.data["products"])
        self.assertNotIn("dtm", res.data["products"])
        self.assertEqual(res.data["state"], "previewing")
        self.assertFalse(res.data["corrected_available"])

    def test_state_no_2d_products(self):
        task = self._task(self._project("no rasters"), available_assets=["georeferenced_model.laz"],
                          orthophoto_extent=None)
        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["products"], [])

    def test_state_permission_denied(self):
        task = self._task(self._project())
        self.client.login(username="testuser2", password="test1234")
        res = self.client.get(self._url(task))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- US4: persistencia (FR-012, FR-013) ----------------------------------

    def test_put_state_persists_points_with_residuals(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['points']), 3)
        self.assertIn('residual_m', res.data['points'][0])
        self.assertIsNotNone(res.data['transform'])
        self.assertFalse(res.data['transform']['degenerate'])
        # El transform registra el CRS en el que viven sus valores (task.epsg).
        self.assertEqual(res.data['transform']['crs'], 'EPSG:32617')

        # Recuperación idéntica en un GET posterior (otra "sesión").
        res2 = self.client.get(self._url(task))
        self.assertEqual(len(res2.data['points']), 3)
        self.assertEqual(res2.data['state'], 'previewing')

    def test_put_state_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    # --- US2: aplicar (FR-014, FR-015) ---------------------------------------

    def test_apply_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': POINTS_OK}, format='json')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_apply_insufficient_points(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': []}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_apply_degenerate_points(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        res = self.client.post(self._url(task, "apply"), {'points': POINTS_DEGENERATE}, format='json')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    # --- US3: revertir (FR-011, FR-014) --------------------------------------

    def test_revert_requires_change_project(self):
        project = self._project()
        assign_perm('view_project', User.objects.get(username="testuser2"), project)
        task = self._task(project)
        self.client.login(username="testuser2", password="test1234")
        res = self.client.post(self._url(task, "revert"))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_revert_sets_state(self):
        task = self._task(self._project())
        self.client.login(username="testuser", password="test1234")
        self.client.put(self._url(task), {'points': POINTS_OK}, format='json')
        res = self.client.post(self._url(task, "revert"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['state'], 'reverted')
        res2 = self.client.get(self._url(task))
        self.assertEqual(res2.data['state'], 'reverted')

    def test_pipeline_self_contained_under_eval_async(self):
        """El worker reejecuta el source en un namespace vacío (app/plugins/worker.py:
        eval_async). Verifica que run_correction_pipeline es self-contained: sin imports
        relativos ni referencias a globals del módulo (regresión del bug de 'apply')."""
        import inspect
        from . import corrections, store

        tmp = tempfile.mkdtemp(prefix="realign_worker_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        src = os.path.join(tmp, "orthophoto.tif")
        _make_synthetic_raster(src)
        out_dir = os.path.join(tmp, "out")

        task_id = "eval-model-task"
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 100.0, 'ty': -50.0}
        products = [{'type': 'orthophoto', 'src': src}]

        # Ejecutar tal cual lo hace el worker: source → compile → eval en ns vacío.
        source = inspect.getsource(corrections.run_correction_pipeline)
        ns = {}
        exec(compile(source, 'file', 'exec'), ns, ns)
        result = ns['run_correction_pipeline'](task_id, products, out_dir, T, None)

        self.assertIn('orthophoto', result['corrected'])
        self.assertTrue(os.path.isfile(os.path.join(out_dir, 'orthophoto.tif')))
        st = store.get_state(task_id)
        self.assertEqual(st['state'], 'applied')
        self.assertIn('orthophoto', st['corrected_paths'])

    def test_tilejson_of_corrected_product(self):
        """El tilejson del corregido debe responder 200 con bounds en EPSG:4326.
        (Regresión: usaba COGReader.crs, inexistente en rio-tiler 2.1 → 500 → el frontend
        nunca cambiaba de capa y 'se veía igual')."""
        from app.plugins.functions import get_plugins_persistent_path
        from . import corrections

        task = self._task(self._project())
        out_dir = get_plugins_persistent_path('realign', 'task_{}'.format(task.id))
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        tmp_src = os.path.join(out_dir, '_src.tif')
        _make_synthetic_raster(tmp_src, bands=3)
        corrections.apply_similarity_to_raster(
            tmp_src, os.path.join(out_dir, 'orthophoto.tif'),
            {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}, 'near')

        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task, "tilejson/orthophoto"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data['bounds']), 4)
        self.assertTrue(all(isinstance(v, (int, float)) for v in res.data['bounds']))
        self.assertTrue(res.data['tiles'][0].endswith('{z}/{x}/{y}.png'))

        # Esquema del core (Map.jsx TILESIZE=512): la capa pide z+1 en la URL con size=512 y el
        # tiler compensa restando 1 (regresión: se ignoraba size → 404 masivo → ortofoto invisible).
        import math
        w, s, e, n = res.data['bounds']
        lat, lng, zoom = (s + n) / 2.0, (w + e) / 2.0, 16
        ntiles = 2 ** zoom
        tx = int((lng + 180.0) / 360.0 * ntiles)
        lr = math.radians(lat)
        ty = int((1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * ntiles)
        base = self._url(task, "tiles/orthophoto/{}/{}/{}.png")
        r256 = self.client.get(base.format(zoom, tx, ty))
        self.assertEqual(r256.status_code, status.HTTP_200_OK)
        # Con size=512, el mismo tile se pide con z+1 y las MISMAS coordenadas de grilla z.
        r512 = self.client.get(base.format(zoom + 1, tx, ty) + "?size=512")
        self.assertEqual(r512.status_code, status.HTTP_200_OK)
        self.assertEqual(r512['Content-Type'], 'image/png')

    def test_dsm_tile_honors_color_map_and_rescale(self):
        """El tile de dsm/dtm debe usar el color_map/rescale de la URL (los que el core
        adjunta a la capa original: viridis + min/max reales), no el gris fijo anterior.
        (Regresión: se ignoraban esos parámetros y el DSM/DTM corregido se veía plano/gris
        en vez de igual al original)."""
        from app.plugins.functions import get_plugins_persistent_path
        from . import corrections

        task = self._task(self._project())
        out_dir = get_plugins_persistent_path('realign', 'task_{}'.format(task.id))
        self.addCleanup(shutil.rmtree, out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        tmp_src = os.path.join(out_dir, '_dsm_src.tif')
        _make_synthetic_raster(tmp_src, bands=1)
        corrections.apply_similarity_to_raster(
            tmp_src, os.path.join(out_dir, 'dsm.tif'),
            {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 0.0, 'ty': 0.0}, 'near')

        self.client.login(username="testuser", password="test1234")
        res = self.client.get(self._url(task, "tilejson/dsm"))
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        import math
        w, s, e, n = res.data['bounds']
        lat, lng, zoom = (s + n) / 2.0, (w + e) / 2.0, 16
        ntiles = 2 ** zoom
        tx = int((lng + 180.0) / 360.0 * ntiles)
        lr = math.radians(lat)
        ty = int((1.0 - math.log(math.tan(lr) + 1.0 / math.cos(lr)) / math.pi) / 2.0 * ntiles)
        base = self._url(task, "tiles/dsm/{}/{}/{}.png".format(zoom, tx, ty))

        # Sin parámetros: cae al comportamiento previo (gray, 0-1000) — no debe romperse.
        r_default = self.client.get(base)
        self.assertEqual(r_default.status_code, status.HTTP_200_OK)
        self.assertEqual(r_default['Content-Type'], 'image/png')

        # Con los parámetros que el core adjunta a la capa original: deben honrarse.
        r_viridis = self.client.get(base + "?color_map=viridis&rescale=0,255")
        self.assertEqual(r_viridis.status_code, status.HTTP_200_OK)
        self.assertEqual(r_viridis['Content-Type'], 'image/png')
        # El color_map cambia la salida (gray vs viridis no pueden ser idénticos para data no nula).
        self.assertNotEqual(r_default.content, r_viridis.content)

        # color_map inválido → 400, no 500.
        r_bad = self.client.get(base + "?color_map=not_a_real_colormap")
        self.assertEqual(r_bad.status_code, status.HTTP_400_BAD_REQUEST)


class RealignTransformTest(unittest.TestCase):
    """Paridad de transform.fit_similarity con los mismos casos que similarity.js (T022)."""

    def test_translation_only(self):
        r = transform.fit_similarity([(0, 0, 10, 5)])
        self.assertAlmostEqual(r['scale'], 1.0)
        self.assertAlmostEqual(r['rotation_deg'], 0.0)
        self.assertAlmostEqual(r['tx'], 10.0)
        self.assertAlmostEqual(r['ty'], 5.0)
        self.assertAlmostEqual(r['rmse'], 0.0)

    def test_known_similarity_recovered(self):
        import math
        T = dict(scale=2.0, cos=math.cos(math.pi / 2), sin=math.sin(math.pi / 2), tx=100.0, ty=50.0)
        srcs = [(0, 0), (10, 0), (0, 10), (7, 3), (-5, 8)]
        pairs = []
        for x, y in srcs:
            qx, qy = transform.apply_similarity(T, x, y)
            pairs.append((x, y, qx, qy))
        r = transform.fit_similarity(pairs)
        self.assertAlmostEqual(r['scale'], 2.0, places=6)
        self.assertAlmostEqual(r['rotation_deg'], 90.0, places=6)
        self.assertAlmostEqual(r['tx'], 100.0, places=5)
        self.assertAlmostEqual(r['ty'], 50.0, places=5)
        self.assertLess(r['rmse'], 1e-6)

    def test_degenerate_coincident_sources(self):
        r = transform.fit_similarity([(0, 0, 1, 1), (0, 0, 2, 2)])
        self.assertTrue(r['degenerate'])
        self.assertFalse(r['ok'])


def _make_synthetic_raster(path, bands=1):
    from osgeo import gdal, osr
    size = 64
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, size, size, bands, gdal.GDT_Byte)
    ds.SetGeoTransform((500000.0, 1.0, 0, 5000000.0, 0, -1.0))
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())
    import numpy as np
    for b in range(1, bands + 1):
        ds.GetRasterBand(b).WriteArray(np.full((size, size), 128, dtype=np.uint8))
    ds.FlushCache()
    ds = None


class RealignCorrectionsTest(unittest.TestCase):
    """Pipeline GDAL: aplica una similitud conocida y verifica el COG corregido (T023, FR-009)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="realign_corr_")
        self.src = os.path.join(self.tmp, "orthophoto.tif")
        _make_synthetic_raster(self.src)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_translation_shifts_origin_and_keeps_north_up(self):
        from osgeo import gdal
        orig_gt = gdal.Open(self.src).GetGeoTransform()

        out = os.path.join(self.tmp, "orthophoto_corr.tif")
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 100.0, 'ty': -50.0}
        corrections.apply_similarity_to_raster(self.src, out, T, resampling='near')

        self.assertTrue(os.path.isfile(out))
        out_gt = gdal.Open(out).GetGeoTransform()
        # Origen desplazado por (tx, ty); north-up (sin términos de rotación).
        self.assertAlmostEqual(out_gt[0], orig_gt[0] + 100.0, places=3)
        self.assertAlmostEqual(out_gt[3], orig_gt[3] - 50.0, places=3)
        self.assertAlmostEqual(out_gt[2], 0.0, places=6)
        self.assertAlmostEqual(out_gt[4], 0.0, places=6)

        # El original no cambió (FR-009).
        self.assertEqual(gdal.Open(self.src).GetGeoTransform(), orig_gt)

    def test_compose_geotransform_translation(self):
        gt = (500000.0, 1.0, 0.0, 5000000.0, 0.0, -1.0)
        T = {'scale': 1.0, 'cos': 1.0, 'sin': 0.0, 'tx': 10.0, 'ty': 20.0}
        new_gt = corrections.compose_geotransform(gt, T)
        self.assertAlmostEqual(new_gt[0], 500010.0)
        self.assertAlmostEqual(new_gt[3], 5000020.0)
        self.assertAlmostEqual(new_gt[1], 1.0)
        self.assertAlmostEqual(new_gt[5], -1.0)
