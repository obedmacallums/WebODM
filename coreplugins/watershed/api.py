import os

from rest_framework import status
from rest_framework.response import Response
from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponse


class WatershedException(Exception):
    pass


def calc_watershed(dem, lat, lng, snap_distance):
    import os
    import tempfile
    import traceback
    import rasterio
    from rasterio.transform import rowcol
    from pyproj import Transformer
    from PIL import Image
    import numpy as np
    from webodm import settings
    import whitebox

    LOG_FILE = "/webodm/coreplugins/watershed/watershed_debug.log"

    def log(msg):
        with open(LOG_FILE, 'a') as f:
            f.write(msg + "\n")
            f.flush()

    # Clear log on each run
    with open(LOG_FILE, 'w') as f:
        f.write("")

    try:
        tmpdir = os.path.join(settings.MEDIA_TMP, os.path.basename(tempfile.mkdtemp('_watershed', dir=settings.MEDIA_TMP)))

        wbt = whitebox.WhiteboxTools()
        wbt.set_verbose_mode(True)

        from datetime import datetime
        log("=== WATERSHED DEBUG v10 - {} ===".format(datetime.now().isoformat()))
        log("DEM: {}".format(dem))
        log("Point: lat={}, lng={}".format(lat, lng))
        log("Snap distance: {}".format(snap_distance))
        log("Temp dir: {}".format(tmpdir))

        # Open DEM to get CRS, bounds, transform, profile
        with rasterio.open(dem) as src:
            dem_crs = src.crs
            dem_bounds = src.bounds
            dem_transform = src.transform
            dem_profile = src.profile.copy()
            dem_shape = (src.height, src.width)

        log("DEM CRS: {}".format(dem_crs))
        log("DEM bounds: {}".format(dem_bounds))
        log("DEM shape: {}".format(dem_shape))
        log("DEM transform: {}".format(dem_transform))

        # Transform observer point from EPSG:4326 to DEM CRS
        transformer = Transformer.from_crs("EPSG:4326", dem_crs, always_xy=True)
        point_x, point_y = transformer.transform(lng, lat)

        log("Transformed point: x={}, y={}".format(point_x, point_y))

        # Validate point is within DEM bounds
        if not (dem_bounds.left <= point_x <= dem_bounds.right and dem_bounds.bottom <= point_y <= dem_bounds.top):
            log("ERROR: Point outside DEM bounds!")
            return {'error': 'Selected point is outside the DEM bounds.'}

        # Step 1: Breach depressions to condition the DEM
        breached_path = os.path.join(tmpdir, "breached.tif")
        log("Step 1: breach_depressions...")
        ret = wbt.breach_depressions(dem, breached_path)
        log("breach_depressions returned: {}, file exists: {}".format(ret, os.path.isfile(breached_path)))

        if not os.path.isfile(breached_path):
            log("ERROR: breached.tif not created")
            return {'error': 'DEM conditioning (breach depressions) failed.'}

        # Step 2: D8 flow direction
        flow_dir_path = os.path.join(tmpdir, "flow_dir.tif")
        log("Step 2: d8_pointer...")
        ret = wbt.d8_pointer(breached_path, flow_dir_path)
        log("d8_pointer returned: {}, file exists: {}".format(ret, os.path.isfile(flow_dir_path)))

        if not os.path.isfile(flow_dir_path):
            log("ERROR: flow_dir.tif not created")
            return {'error': 'Flow direction computation failed.'}

        # Step 3: D8 flow accumulation
        flow_accum_path = os.path.join(tmpdir, "flow_accum.tif")
        log("Step 3: d8_flow_accumulation...")
        ret = wbt.d8_flow_accumulation(breached_path, flow_accum_path, out_type='cells')
        log("d8_flow_accumulation returned: {}, file exists: {}".format(ret, os.path.isfile(flow_accum_path)))

        if not os.path.isfile(flow_accum_path):
            log("ERROR: flow_accum.tif not created")
            return {'error': 'Flow accumulation computation failed.'}

        # Step 4: Snap pour point to nearest high flow accumulation cell
        row, col = rowcol(dem_transform, point_x, point_y)
        row = max(0, min(row, dem_shape[0] - 1))
        col = max(0, min(col, dem_shape[1] - 1))

        log("Original pour point pixel: row={}, col={}".format(row, col))

        # Read flow accumulation to find nearest stream cell
        with rasterio.open(flow_accum_path) as src:
            flow_accum_data = src.read(1)
            fa_nodata = src.nodata
            fa_dtype = src.dtypes[0]

        log("Flow accum dtype: {}, nodata: {}".format(fa_dtype, fa_nodata))

        # Create a valid mask (exclude nodata and negatives)
        valid_fa = flow_accum_data.copy().astype(np.float64)
        if fa_nodata is not None:
            valid_fa[flow_accum_data == fa_nodata] = 0
        valid_fa[valid_fa < 0] = 0

        log("Flow accum valid min: {}, max: {}, mean: {}".format(
            valid_fa[valid_fa > 0].min() if np.any(valid_fa > 0) else 0,
            valid_fa.max(), valid_fa.mean()))
        log("Flow accum at clicked pixel [{},{}]: {}".format(row, col, valid_fa[row, col]))

        # Convert snap_distance from meters to pixels
        pixel_size = dem_transform[0]  # meters per pixel
        snap_radius_px = max(1, int(snap_distance / pixel_size))
        log("Pixel size: {}m, snap_distance: {}m, snap_radius: {}px".format(pixel_size, snap_distance, snap_radius_px))

        # Search for highest flow accumulation cell within snap_distance only
        r_min = max(0, row - snap_radius_px)
        r_max = min(dem_shape[0], row + snap_radius_px + 1)
        c_min = max(0, col - snap_radius_px)
        c_max = min(dem_shape[1], col + snap_radius_px + 1)

        search_window = valid_fa[r_min:r_max, c_min:c_max]
        max_val = search_window.max()

        log("Search radius {}px ({}m): window {}x{}, max_fa={}".format(
            snap_radius_px, snap_distance, r_max - r_min, c_max - c_min, max_val))

        if max_val > 1:
            max_idx = np.unravel_index(np.argmax(search_window), search_window.shape)
            snapped_row = r_min + max_idx[0]
            snapped_col = c_min + max_idx[1]
            dist_m = np.sqrt((snapped_row - row) ** 2 + (snapped_col - col) ** 2) * pixel_size
            log("Snapped to: row={}, col={} (flow_accum={}, dist={}m)".format(
                snapped_row, snapped_col, valid_fa[snapped_row, snapped_col], dist_m))
        else:
            log("ERROR: No stream found within {}m of clicked point".format(snap_distance))
            return {'error': 'No drainage channel found within {}m. Try clicking closer to a stream or increase the snap distance.'.format(int(snap_distance))}

        # Create pour point raster at snapped location
        pour_raster = np.zeros(dem_shape, dtype=np.int32)
        pour_raster[snapped_row, snapped_col] = 1

        pour_point_path = os.path.join(tmpdir, "pour_point.tif")
        pour_profile = dem_profile.copy()
        pour_profile.update(dtype=rasterio.int32, count=1, nodata=0)
        with rasterio.open(pour_point_path, 'w', **pour_profile) as dst:
            dst.write(pour_raster, 1)

        log("Pour point raster created: {}".format(os.path.isfile(pour_point_path)))

        # Step 6: Delineate watershed
        watershed_path = os.path.join(tmpdir, "watershed.tif")
        log("Step 6: watershed...")
        ret = wbt.watershed(flow_dir_path, pour_point_path, watershed_path)
        log("watershed returned: {}, file exists: {}".format(ret, os.path.isfile(watershed_path)))

        if not os.path.isfile(watershed_path):
            log("ERROR: watershed.tif not created")
            return {'error': 'Watershed delineation failed.'}

        # Read watershed raster and create RGBA PNG overlay
        log("Reading watershed result...")
        with rasterio.open(watershed_path) as src:
            data = src.read(1)
            nodata = src.nodata
            raster_crs = src.crs
            raster_bounds = src.bounds
            raster_transform = src.transform
            pixel_width = raster_transform[0]
            pixel_height = abs(raster_transform[4])

        # Create watershed mask
        if nodata is not None:
            watershed_mask = (data != nodata) & (data > 0)
        else:
            watershed_mask = data > 0

        # Calculate watershed area
        pixel_area = pixel_width * pixel_height
        watershed_pixel_count = int(np.sum(watershed_mask))
        watershed_area = watershed_pixel_count * pixel_area

        # Crop to bounding box of watershed pixels (with padding)
        ws_rows, ws_cols = np.where(watershed_mask)
        pad = 10  # pixels padding
        crop_r_min = max(0, ws_rows.min() - pad)
        crop_r_max = min(data.shape[0], ws_rows.max() + pad + 1)
        crop_c_min = max(0, ws_cols.min() - pad)
        crop_c_max = min(data.shape[1], ws_cols.max() + pad + 1)

        log("Cropping to rows [{}, {}], cols [{}, {}] (from {}x{})".format(
            crop_r_min, crop_r_max, crop_c_min, crop_c_max, data.shape[0], data.shape[1]))

        cropped_mask = watershed_mask[crop_r_min:crop_r_max, crop_c_min:crop_c_max]
        crop_h, crop_w = cropped_mask.shape

        # Create RGBA only for cropped region
        rgba = np.zeros((crop_h, crop_w, 4), dtype=np.uint8)
        rgba[cropped_mask] = [0, 150, 255, 150]

        png_path = os.path.join(tmpdir, "watershed.png")
        img = Image.fromarray(rgba, 'RGBA')
        img.save(png_path)

        log("PNG size: {}x{}".format(crop_w, crop_h))

        # Calculate cropped bounds in CRS coordinates using the transform directly
        # transform * (col, row) gives (x, y)
        crop_x_min = raster_transform[2] + crop_c_min * raster_transform[0]  # left
        crop_x_max = raster_transform[2] + crop_c_max * raster_transform[0]  # right
        crop_y_max = raster_transform[5] + crop_r_min * raster_transform[4]  # top (transform[4] is negative)
        crop_y_min = raster_transform[5] + crop_r_max * raster_transform[4]  # bottom

        log("Crop CRS bounds: x=[{}, {}], y=[{}, {}]".format(crop_x_min, crop_x_max, crop_y_min, crop_y_max))

        # Transform cropped bounds to EPSG:4326
        transformer_back = Transformer.from_crs(raster_crs, "EPSG:4326", always_xy=True)
        west_lng, south_lat = transformer_back.transform(crop_x_min, crop_y_min)
        east_lng, north_lat = transformer_back.transform(crop_x_max, crop_y_max)

        log("Watershed unique values: {}".format(np.unique(data)))
        log("Watershed nodata: {}".format(nodata))
        log("Watershed mask pixel count: {}".format(watershed_pixel_count))
        log("Watershed area: {}".format(watershed_area))
        log("Bounds: [[{}, {}], [{}, {}]]".format(south_lat, west_lng, north_lat, east_lng))
        log("PNG saved: {}".format(png_path))
        log("=== WATERSHED COMPLETE ===")

        return {
            'output': {
                'bounds': [[south_lat, west_lng], [north_lat, east_lng]],
                'image': png_path,
                'area': watershed_area,
                'pixel_count': watershed_pixel_count
            }
        }

    except Exception as e:
        log("EXCEPTION: {}".format(str(e)))
        log(traceback.format_exc())
        return {'error': str(e)}


class TaskWatershedGenerate(TaskView):
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
                raise WatershedException('{} is not a valid layer.'.format(layer))

            lat = float(request.data.get('lat', 0))
            lng = float(request.data.get('lng', 0))
            snap_distance = float(request.data.get('snap_distance', 100))

            if lat == 0 and lng == 0:
                raise WatershedException('Invalid coordinates.')

            celery_task_id = run_function_async(calc_watershed, dem, lat, lng, snap_distance).task_id
            return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)
        except WatershedException as e:
            return Response({'error': str(e)}, status=status.HTTP_200_OK)


class TaskWatershedResult(GetTaskResult):
    def get(self, request, celery_task_id=None, **kwargs):
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
