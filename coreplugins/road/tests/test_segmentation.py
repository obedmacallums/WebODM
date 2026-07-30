"""`segmentation.py` — corredor del eje y recorte + invocación a `geodeep.segment`
(`007` FR-005, FR-008, `research.md` D25, D26, D31).

`gdalwarp` corre de verdad (está en la imagen y no depende de red); `geodeep` se sustituye por un
doble inyectado en `sys.modules`, así que estos tests no dependen de la librería real ni de
descargar ningún modelo (`plan.md`, Technical Context).
"""

import os
import sys
import types
from unittest import mock

import numpy as np
import rasterio
from rasterio.transform import from_origin

from .. import segmentation
from .base import DEM_EPSG, DEM_ORIGIN, DEM_RES, axis_vertices, RoadTestBase


def make_orthophoto(path, size=480, res=DEM_RES, origin=DEM_ORIGIN, epsg=DEM_EPSG):
    """GeoTIFF RGB sintético, mismo grid que `make_road_dem`, para recortar de verdad con
    `gdalwarp` en estos tests."""
    transform = from_origin(origin[0], origin[1], res, res)
    data = np.full((3, size, size), 128, dtype=np.uint8)
    with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=3,
                       dtype='uint8', crs='EPSG:{}'.format(epsg), transform=transform) as dst:
        dst.write(data)


def _fake_geodeep_modules(mask, capture=None):
    """Módulos `geodeep` y `geodeep.segmentation` de doble, inyectables en `sys.modules`.

    `mask` es lo que `segment()` devuelve. `capture`, si se pasa, recibe los argumentos con los
    que se llamó a `segment()` y `save_mask_to_raster()`, para poder comprobarlos.
    """
    geodeep_mod = types.ModuleType('geodeep')
    geodeep_seg_mod = types.ModuleType('geodeep.segmentation')

    class FakeModels:
        cache_dir = None

    geodeep_mod.models = FakeModels()

    def fake_segment(geotiff, model, output_type='default', progress_callback=None):
        if capture is not None:
            capture['segment'] = {'geotiff': geotiff, 'model': model,
                                  'output_type': output_type}
        if progress_callback is not None:
            progress_callback('Loading model', 5)
            progress_callback('Processing tile 0/1', 90)
            progress_callback('Done', 5)
        return mask

    def fake_save_mask_to_raster(geotiff, mask_arr, outfile):
        # Réplica fiel de `geodeep.segmentation.save_mask_to_raster`: el mask puede tener un
        # tamaño distinto del ráster de entrada (remuestreo a la resolución nativa del modelo), y
        # el transform se reescala en función de ese tamaño real, no del de entrada.
        if capture is not None:
            capture['save'] = {'geotiff': geotiff, 'outfile': outfile}
        with rasterio.open(geotiff) as src:
            p = src.profile
            p['width'] = mask_arr.shape[1]
            p['height'] = mask_arr.shape[0]
            p['count'] = 1
            p['dtype'] = 'uint8'
            p['transform'] = p['transform'] * rasterio.Affine.scale(
                src.profile['width'] / p['width'], src.profile['height'] / p['height'])
        with rasterio.open(outfile, 'w', **p) as dst:
            dst.write(mask_arr.astype('uint8'), 1)

    geodeep_mod.segment = fake_segment
    geodeep_seg_mod.save_mask_to_raster = fake_save_mask_to_raster
    return geodeep_mod, geodeep_seg_mod


class BuildCorridorTest(RoadTestBase):
    def test_corridor_covers_the_search_half_width_plus_margin(self):
        import rasterio.warp
        from django.contrib.gis.geos import Point, Polygon as GEOSPolygon

        crs = 'EPSG:{}'.format(DEM_EPSG)
        vertices = axis_vertices(vertices=2)

        corridor = segmentation.build_corridor(vertices, half_width=4.0, crs=crs)

        self.assertEqual(corridor['type'], 'Polygon')

        # `corridor` está en 4326; reproyectamos a nativo para comparar en metros sin depender de
        # que un buffer en grados tenga la forma esperada.
        lons = [c[0] for c in corridor['coordinates'][0]]
        lats = [c[1] for c in corridor['coordinates'][0]]
        xs, ys = rasterio.warp.transform('EPSG:4326', crs, lons, lats)
        poly_native = GEOSPolygon(list(zip(xs, ys)))

        px, py = rasterio.warp.transform('EPSG:4326', crs,
                                         [v[0] for v in vertices], [v[1] for v in vertices])
        mid_x = (px[0] + px[-1]) / 2.0
        mid_y = (py[0] + py[-1]) / 2.0

        # Un punto a 4.0 + 1.0 m del eje (dentro del margen de 2.0 m) cae dentro; uno a
        # 4.0 + 3.0 m (fuera del margen) cae fuera.
        self.assertTrue(poly_native.contains(Point(mid_x + 5.0, mid_y)))
        self.assertFalse(poly_native.contains(Point(mid_x + 7.0, mid_y)))


class RunSegmentationTest(RoadTestBase):
    def _corridor_for(self, vertices, half_width=4.0):
        crs = 'EPSG:{}'.format(DEM_EPSG)
        return segmentation.build_corridor(vertices, half_width, crs)

    def test_missing_geodeep_library_raises_a_clear_error(self):
        orthophoto = os.path.join(self._tmpdir(), 'orthophoto.tif')
        make_orthophoto(orthophoto)
        corridor = self._corridor_for(axis_vertices())

        with mock.patch.dict(sys.modules, {'geodeep': None}):
            with self.assertRaises(RuntimeError) as ctx:
                segmentation.run_segmentation(orthophoto, corridor)

        self.assertIn('GeoDeep', str(ctx.exception))

    def test_gdalwarp_failure_raises_a_clear_error(self):
        orthophoto = os.path.join(self._tmpdir(), 'orthophoto.tif')
        make_orthophoto(orthophoto)
        # Un corredor sin ninguna intersección con la ortofoto hace que gdalwarp falle al recortar.
        corridor = {'type': 'Polygon', 'coordinates': [[[0.0, 0.0], [0.0, 0.001],
                                                        [0.001, 0.001], [0.001, 0.0], [0.0, 0.0]]]}
        fake_geodeep, fake_geodeep_seg = _fake_geodeep_modules(mask=np.ones((10, 10), dtype='uint8'))

        with mock.patch.dict(sys.modules, {'geodeep': fake_geodeep,
                                           'geodeep.segmentation': fake_geodeep_seg}):
            with self.assertRaises(RuntimeError) as ctx:
                segmentation.run_segmentation(orthophoto, corridor)

        self.assertIn('gdalwarp', str(ctx.exception))

    def test_happy_path_crops_and_segments_returning_a_georeferenced_mask(self):
        orthophoto = os.path.join(self._tmpdir(), 'orthophoto.tif')
        make_orthophoto(orthophoto)
        corridor = self._corridor_for(axis_vertices())
        mask = np.ones((20, 20), dtype='uint8')
        capture = {}
        fake_geodeep, fake_geodeep_seg = _fake_geodeep_modules(mask=mask, capture=capture)

        progress_calls = []
        with mock.patch.dict(sys.modules, {'geodeep': fake_geodeep,
                                           'geodeep.segmentation': fake_geodeep_seg}):
            mask_path = segmentation.run_segmentation(
                orthophoto, corridor, progress_callback=lambda t, p: progress_calls.append((t, p)))

        self.assertTrue(os.path.exists(mask_path))
        self.assertEqual(capture['segment']['model'], 'roads')
        self.assertEqual(capture['segment']['output_type'], 'default')
        self.assertTrue(progress_calls)  # el progreso de geodeep.segment llegó hasta aquí

        with rasterio.open(mask_path) as ds:
            self.assertEqual(ds.count, 1)
            self.assertIsNotNone(ds.crs)

    def _tmpdir(self):
        import tempfile
        d = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, d, ignore_errors=True)
        return d
