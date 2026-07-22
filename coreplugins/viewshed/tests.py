import os
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from rest_framework import status
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

from .api import calc_viewshed

TEST_EXTENT = Polygon.from_bbox([-82.8325, 27.9578, -82.8310, 27.9593])


class ViewshedApiTest(BootTestCase):
    """Tests de la vista TaskViewshedGenerate (FR-001, FR-005, FR-010, FR-012)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _task_with_dsm(self, owner_username="testuser"):
        owner = User.objects.get(username=owner_username)
        project = Project.objects.create(owner=owner, name="Viewshed test project")
        return Task.objects.create(project=project, status=status_codes.COMPLETED,
                                    available_assets=["dsm.tif"], dsm_extent=TEST_EXTENT)

    def test_no_elevation_model(self):
        user = User.objects.get(username="testuser")
        project = Project.objects.create(owner=user, name="Viewshed test project (no DEM)")
        task = Task.objects.create(project=project, status=status_codes.COMPLETED,
                                    available_assets=["orthophoto.tif"])

        self.client.login(username="testuser", password="test1234")
        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('error', res.data)

    def test_permission_denied(self):
        task = self._task_with_dsm(owner_username="testuser")

        self.client.login(username="testuser2", password="test1234")
        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    @patch('coreplugins.viewshed.api.run_function_async')
    def test_invalid_observer_height_negative(self, mock_run):
        task = self._task_with_dsm()
        self.client.login(username="testuser", password="test1234")

        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318, 'observer_height': -5})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('error', res.data)
        mock_run.assert_not_called()

    @patch('coreplugins.viewshed.api.run_function_async')
    def test_invalid_observer_height_non_numeric(self, mock_run):
        task = self._task_with_dsm()
        self.client.login(username="testuser", password="test1234")

        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318, 'observer_height': 'abc'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('error', res.data)
        mock_run.assert_not_called()

    @patch('coreplugins.viewshed.api.run_function_async')
    def test_invalid_observer_height_too_high(self, mock_run):
        task = self._task_with_dsm()
        self.client.login(username="testuser", password="test1234")

        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318, 'observer_height': 501})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('error', res.data)
        mock_run.assert_not_called()

    @patch('coreplugins.viewshed.api.run_function_async')
    def test_valid_request_uses_default_height_and_launches_job(self, mock_run):
        mock_run.return_value.task_id = 'fake-celery-id'
        task = self._task_with_dsm()
        self.client.login(username="testuser", password="test1234")

        # Sin observer_height en el body: debe usar el default 1.6 (FR-004, ya en US1)
        res = self.client.post("/api/plugins/viewshed/task/{}/viewshed/generate".format(task.id),
                                {'lat': 27.9585, 'lng': -82.8318})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data.get('celery_task_id'), 'fake-celery-id')
        mock_run.assert_called_once()

        args, kwargs = mock_run.call_args
        # run_function_async(calc_viewshed, dem, lat, lng, observer_height, epsg)
        self.assertEqual(args[4], 1.6)


def _make_synthetic_dsm(path):
    """Crea un DSM sintético (100x100, 2m/px, UTM 33N) con una colina que
    corta el raster en dos, para poder verificar que gdal_viewshed oculta lo
    que hay detras de un obstaculo topografico (ejemplo del spec)."""
    from osgeo import gdal, osr
    import numpy as np

    size = 100
    pixel_size = 2.0
    origin_x, origin_y = 500000.0, 5000000.0

    elevation = np.full((size, size), 100.0, dtype=np.float32)
    elevation[45:55, :] = 160.0  # "colina" transversal

    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, size, size, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((origin_x, pixel_size, 0, origin_y, 0, -pixel_size))

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(32633)
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    band.WriteArray(elevation)
    band.FlushCache()
    ds = None


def _latlng_for_pixel(dem_path, col, row):
    from osgeo import gdal, osr

    ds = gdal.Open(dem_path)
    gt = ds.GetGeoTransform()

    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    wgs84.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(srs, wgs84)
    x = gt[0] + col * gt[1]
    y = gt[3] + row * gt[5]
    lng, lat, _z = transform.TransformPoint(x, y)
    ds = None
    return lat, lng


def _visible_area(geojson_path):
    from osgeo import ogr

    ds = ogr.Open(geojson_path)
    layer = ds.GetLayer()
    area = 0.0
    for feature in layer:
        geom = feature.GetGeometryRef()
        if geom is not None:
            area += geom.GetArea()
    ds = None
    return area


class ViewshedCalcTest(unittest.TestCase):
    """Tests de calc_viewshed() contra un DSM sintetico (FR-003, FR-004, FR-010, FR-011)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="viewshed_calc_test_")
        self.dem_path = os.path.join(self.tmpdir, "dsm.tif")
        _make_synthetic_dsm(self.dem_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_calc_viewshed_success(self):
        lat, lng = _latlng_for_pixel(self.dem_path, 20, 20)
        result = calc_viewshed(self.dem_path, lat, lng, 1.6, epsg=32633)

        self.assertNotIn('error', result)
        self.assertIn('file', result)
        self.assertTrue(os.path.isfile(result['file']))

        with open(result['file']) as f:
            geojson = json.load(f)
        self.assertEqual(geojson.get('type'), 'FeatureCollection')

    def test_calc_viewshed_out_of_coverage(self):
        # Punto lejos del extent del raster sintetico (FR-010)
        result = calc_viewshed(self.dem_path, 0.0, 0.0, 1.6, epsg=32633)
        self.assertIn('error', result)

    def test_calc_viewshed_higher_observer_sees_more_or_equal_area(self):
        lat, lng = _latlng_for_pixel(self.dem_path, 20, 20)

        low = calc_viewshed(self.dem_path, lat, lng, 1.6, epsg=32633)
        high = calc_viewshed(self.dem_path, lat, lng, 30, epsg=32633)

        self.assertNotIn('error', low)
        self.assertNotIn('error', high)
        self.assertGreaterEqual(_visible_area(high['file']), _visible_area(low['file']))
