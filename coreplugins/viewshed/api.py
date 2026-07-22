import os

from rest_framework import status
from rest_framework.response import Response
from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from django.utils.translation import gettext_lazy as _


def calc_viewshed(dem, lat, lng, observer_height, epsg=None):
    import os
    import subprocess
    import tempfile
    import shutil
    from webodm import settings
    from osgeo import gdal, osr

    gdal_viewshed_bin = shutil.which("gdal_viewshed")
    gdal_polygonize_bin = shutil.which("gdal_polygonize.py") or shutil.which("gdal_polygonize")
    ogr2ogr_bin = shutil.which("ogr2ogr")

    if gdal_viewshed_bin is None:
        return {'error': 'Cannot find gdal_viewshed'}
    if gdal_polygonize_bin is None:
        return {'error': 'Cannot find gdal_polygonize'}
    if ogr2ogr_bin is None:
        return {'error': 'Cannot find ogr2ogr'}

    ds = gdal.Open(dem)
    if ds is None:
        return {'error': 'Cannot open elevation model'}

    dem_srs = osr.SpatialReference()
    if epsg:
        dem_srs.ImportFromEPSG(int(epsg))
    else:
        dem_srs.ImportFromWkt(ds.GetProjection())
    dem_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    wgs84_srs = osr.SpatialReference()
    wgs84_srs.ImportFromEPSG(4326)
    wgs84_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(wgs84_srs, dem_srs)
    ox, oy, _z = transform.TransformPoint(lng, lat)

    gt = ds.GetGeoTransform()
    px = (ox - gt[0]) / gt[1]
    py = (oy - gt[3]) / gt[5]

    out_of_bounds_error = 'El punto seleccionado esta fuera del area con datos de elevacion.'

    if px < 0 or py < 0 or px >= ds.RasterXSize or py >= ds.RasterYSize:
        ds = None
        return {'error': out_of_bounds_error}

    band = ds.GetRasterBand(1)
    nodata = band.GetNoDataValue()
    value = band.ReadAsArray(int(px), int(py), 1, 1)
    ds = None

    if value is None or (nodata is not None and float(value[0][0]) == nodata):
        return {'error': out_of_bounds_error}

    tmpdir = os.path.join(settings.MEDIA_TMP, os.path.basename(tempfile.mkdtemp('_viewshed', dir=settings.MEDIA_TMP)))

    viewshed_tif = os.path.join(tmpdir, "viewshed.tif")
    p = subprocess.Popen([gdal_viewshed_bin,
                          "-ox", str(ox), "-oy", str(oy),
                          "-oz", str(observer_height),
                          "-tz", "0",
                          "-vv", "255", "-iv", "0", "-ov", "0",
                          dem, viewshed_tif], cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return {'error': 'Error calling gdal_viewshed: {}'.format(err.decode('utf-8').strip())}

    viewshed_shp = os.path.join(tmpdir, "viewshed.shp")
    p = subprocess.Popen([gdal_polygonize_bin, viewshed_tif, "-f", "ESRI Shapefile", viewshed_shp],
                          cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return {'error': 'Error calling gdal_polygonize: {}'.format(err.decode('utf-8').strip())}

    outfile = os.path.join(tmpdir, "viewshed.geojson")
    p = subprocess.Popen([ogr2ogr_bin, "-f", "GeoJSON", "-t_srs", "EPSG:4326",
                          "-where", "DN=255", outfile, viewshed_shp],
                          cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        return {'error': 'Error calling ogr2ogr: {}'.format(err.decode('utf-8').strip())}

    if not os.path.isfile(outfile):
        return {'error': 'Cannot find output file: {}'.format(outfile)}

    return {'file': outfile}


class TaskViewshedGenerate(TaskView):
    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        if task.dsm_extent is not None:
            dem = os.path.abspath(task.get_asset_download_path("dsm.tif"))
        elif task.dtm_extent is not None:
            dem = os.path.abspath(task.get_asset_download_path("dtm.tif"))
        else:
            return Response({'error': _('La tarea no tiene modelo de elevación.')})

        try:
            lat = float(request.data.get('lat'))
            lng = float(request.data.get('lng'))
        except (TypeError, ValueError):
            return Response({'error': _('Las coordenadas del punto no son válidas.')})

        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return Response({'error': _('Las coordenadas del punto están fuera de rango.')})

        try:
            observer_height = float(request.data.get('observer_height', 1.6))
        except (TypeError, ValueError):
            return Response({'error': _('La altura del observador debe ser un valor numérico.')})

        if not (0 <= observer_height <= 500):
            return Response({'error': _('La altura del observador debe estar entre 0 y 500 metros.')})

        celery_task_id = run_function_async(calc_viewshed, dem, lat, lng, observer_height, task.epsg).task_id
        return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)


class TaskViewshedDownload(GetTaskResult):
    pass
