import os

from rest_framework import status
from rest_framework.response import Response
from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse


class HillshadeException(Exception):
    pass


def calc_hillshade(dem, azimuth, altitude):
    import os
    import tempfile
    import rasterio
    from pyproj import Transformer
    from PIL import Image
    import numpy as np
    from webodm import settings
    import whitebox

    tmpdir = os.path.join(settings.MEDIA_TMP, os.path.basename(tempfile.mkdtemp('_hillshade', dir=settings.MEDIA_TMP)))

    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)

    output_tif = os.path.join(tmpdir, "hillshade.tif")

    # Use multidirectional hillshade for full 360° shading
    ret = wbt.multidirectional_hillshade(
        dem=dem,
        output=output_tif,
        altitude=float(altitude),
        full_mode=True
    )

    if ret != 0 or not os.path.isfile(output_tif):
        # Fallback to directional hillshade
        ret = wbt.hillshade(
            dem=dem,
            output=output_tif,
            azimuth=float(azimuth),
            altitude=float(altitude)
        )

    if not os.path.isfile(output_tif):
        return {'error': 'Hillshade computation failed. No output generated.'}

    # Read hillshade raster and create RGBA PNG overlay
    with rasterio.open(output_tif) as src:
        data = src.read(1).astype(np.float64)
        nodata = src.nodata
        raster_crs = src.crs
        raster_bounds = src.bounds

    # Create a nodata mask
    if nodata is not None:
        valid_mask = data != nodata
    else:
        valid_mask = np.ones(data.shape, dtype=bool)

    # Normalize to 0-255
    valid_data = data[valid_mask]
    if valid_data.size > 0:
        dmin = valid_data.min()
        dmax = valid_data.max()
        if dmax > dmin:
            normalized = np.clip((data - dmin) / (dmax - dmin) * 255, 0, 255).astype(np.uint8)
        else:
            normalized = np.full(data.shape, 128, dtype=np.uint8)
    else:
        return {'error': 'Hillshade output contains no valid data.'}

    # Create grayscale RGBA (gray value with semi-transparency)
    rgba = np.zeros((data.shape[0], data.shape[1], 4), dtype=np.uint8)
    rgba[valid_mask, 0] = normalized[valid_mask]
    rgba[valid_mask, 1] = normalized[valid_mask]
    rgba[valid_mask, 2] = normalized[valid_mask]
    rgba[valid_mask, 3] = 180  # Semi-transparent

    png_path = os.path.join(tmpdir, "hillshade.png")
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


class TaskHillshadeGenerate(TaskView):
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
                raise HillshadeException('{} is not a valid layer.'.format(layer))

            azimuth = float(request.data.get('azimuth', 315))
            altitude = float(request.data.get('altitude', 30))

            if not (0 <= azimuth <= 360):
                raise HillshadeException('Azimuth must be between 0 and 360.')
            if not (0 <= altitude <= 90):
                raise HillshadeException('Altitude must be between 0 and 90.')

            celery_task_id = run_function_async(calc_hillshade, dem, azimuth, altitude).task_id
            return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)
        except HillshadeException as e:
            return Response({'error': str(e)}, status=status.HTTP_200_OK)


class TaskHillshadeResult(GetTaskResult):
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
