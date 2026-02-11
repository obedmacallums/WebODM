import os

from rest_framework import status
from rest_framework.response import Response
from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse


class ViewshedException(Exception):
    pass


def calc_viewshed(dem, lat, lng, height):
    import os
    import subprocess
    import tempfile
    import shutil
    import rasterio
    from pyproj import Transformer
    from PIL import Image
    import numpy as np
    from webodm import settings

    tmpdir = os.path.join(settings.MEDIA_TMP, os.path.basename(tempfile.mkdtemp('_viewshed', dir=settings.MEDIA_TMP)))

    gdal_viewshed_bin = shutil.which("gdal_viewshed")
    if gdal_viewshed_bin is None:
        return {'error': 'Cannot find gdal_viewshed'}

    # Open DEM to get CRS and bounds
    with rasterio.open(dem) as src:
        dem_crs = src.crs
        dem_bounds = src.bounds

    # Transform observer point from EPSG:4326 to DEM CRS
    transformer = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
    obs_x, obs_y = transformer.transform(lng, lat)

    # Validate point is within DEM bounds
    if not (dem_bounds.left <= obs_x <= dem_bounds.right and dem_bounds.bottom <= obs_y <= dem_bounds.top):
        return {'error': 'Selected point is outside the DEM bounds.'}

    # Run gdal_viewshed
    output_tif = os.path.join(tmpdir, "viewshed.tif")
    p = subprocess.Popen([
        gdal_viewshed_bin,
        "-ox", str(obs_x),
        "-oy", str(obs_y),
        "-oz", str(float(height)),
        "-vv", "255",
        "-iv", "0",
        "-ov", "0",
        "-om", "NORMAL",
        "-f", "GTiff",
        dem, output_tif
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()

    if p.returncode != 0:
        return {'error': 'gdal_viewshed failed: {}'.format(err.decode('utf-8').strip())}

    if not os.path.isfile(output_tif):
        return {'error': 'Viewshed computation failed. No output generated.'}

    # Read viewshed raster and create RGBA PNG overlay
    with rasterio.open(output_tif) as src:
        data = src.read(1)
        nodata = src.nodata
        raster_crs = src.crs
        raster_bounds = src.bounds

    # gdal_viewshed outputs: 255 = visible, 0 = not visible, nodata = outside range
    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    visible_mask = data == 255
    rgba[visible_mask] = [0, 200, 0, 128]  # Green semi-transparent

    png_path = os.path.join(tmpdir, "viewshed.png")
    img = Image.fromarray(rgba, 'RGBA')
    img.save(png_path)

    # Transform raster bounds to EPSG:4326
    transformer_back = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)
    west_lng, south_lat = transformer_back.transform(raster_bounds.left, raster_bounds.bottom)
    east_lng, north_lat = transformer_back.transform(raster_bounds.right, raster_bounds.top)

    return {
        'output': {
            'bounds': [[south_lat, west_lng], [north_lat, east_lng]],
            'image': png_path
        }
    }


class TaskViewshedGenerate(TaskView):
    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        layer = request.data.get('layer', None)
        if layer == 'DSM' and task.dsm_extent is None:
            return Response({'error': _('No DSM layer is available.')})
        elif layer == 'DTM' and task.dtm_extent is None:
            return Response({'error': _('No DTM layer is available.')})

        try:
            if layer == 'DSM':
                dem = os.path.abspath(task.get_asset_download_path("dsm.tif"))
            elif layer == 'DTM':
                dem = os.path.abspath(task.get_asset_download_path("dtm.tif"))
            else:
                raise ViewshedException('{} is not a valid layer.'.format(layer))

            lat = float(request.data.get('lat', 0))
            lng = float(request.data.get('lng', 0))
            height = float(request.data.get('height', 1.7))

            if lat == 0 and lng == 0:
                raise ViewshedException('Invalid coordinates.')

            celery_task_id = run_function_async(calc_viewshed, dem, lat, lng, height).task_id
            return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)
        except ViewshedException as e:
            return Response({'error': str(e)}, status=status.HTTP_200_OK)


class TaskViewshedResult(GetTaskResult):
    def get(self, request, celery_task_id=None, **kwargs):
        # If ?serve=image, serve the PNG file directly
        if request.query_params.get('serve') == 'image':
            from worker.tasks import TestSafeAsyncResult
            res = TestSafeAsyncResult(celery_task_id)
            if res.ready():
                result = res.get()
                output = result.get('output', None)
                if output and 'image' in output:
                    image_path = output['image']
                    if os.path.isfile(image_path):
                        with open(image_path, 'rb') as f:
                            return HttpResponse(f.read(), content_type='image/png')
            return Response({'error': 'Image not available'}, status=status.HTTP_404_NOT_FOUND)

        return super().get(request, celery_task_id=celery_task_id, **kwargs)
