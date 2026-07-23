import os
import datetime

from rest_framework import status, exceptions
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from app.plugins.views import TaskView, GetTaskResult
from app.plugins.worker import run_function_async
from app.plugins.functions import get_plugins_persistent_path
from app.api.common import check_project_perms

from . import transform, store, corrections


# Productos ráster 2D que el plugin puede realinear (comparten georreferenciación).
PRODUCT_ASSETS = {
    'orthophoto': 'orthophoto.tif',
    'dsm': 'dsm.tif',
    'dtm': 'dtm.tif',
}


def available_products(task):
    """Productos ráster 2D presentes en la tarea (FR-016), por sus *extent* en BD."""
    extents = {
        'orthophoto': task.orthophoto_extent,
        'dsm': task.dsm_extent,
        'dtm': task.dtm_extent,
    }
    return [name for name, ext in extents.items() if ext is not None]


def _now():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def _out_dir(pk):
    return get_plugins_persistent_path('realign', 'task_{}'.format(pk))


def _corrected_path(pk, product_type):
    return os.path.join(_out_dir(pk), '{}.tif'.format(product_type))


def _remove_corrected(pk):
    d = _out_dir(pk)
    if os.path.isdir(d):
        for f in os.listdir(d):
            if f.endswith('.tif'):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass


def _validate_points(raw):
    """Valida y normaliza la lista de pares de puntos. Devuelve (points, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, _('El campo "points" debe ser una lista.')
    points = []
    for p in raw:
        try:
            s, t = p['source'], p['target']
            slat, slng = float(s['lat']), float(s['lng'])
            tlat, tlng = float(t['lat']), float(t['lng'])
        except (KeyError, TypeError, ValueError):
            return None, _('Cada par debe tener source y target con lat/lng numéricos.')
        if not (-90 <= slat <= 90 and -90 <= tlat <= 90 and -180 <= slng <= 180 and -180 <= tlng <= 180):
            return None, _('Coordenadas fuera de rango.')
        points.append({
            'id': p.get('id'),
            'source': {'lat': slat, 'lng': slng},
            'target': {'lat': tlat, 'lng': tlng},
            'enabled': p.get('enabled', True),
        })
    return points, None


def _fit_for_task(task, points):
    enabled = [p for p in points if p.get('enabled', True)]
    return transform.similarity_from_latlng(enabled, task.epsg or 4326)


def _transform_dict(fit, epsg):
    # Los valores (translation, cos/sin, scale) están en las unidades de este CRS proyectado;
    # se guarda el EPSG para poder reinterpretarlos (p. ej. reusarlos en la nube de puntos, FR-017).
    return {
        'crs': 'EPSG:{}'.format(epsg), 'scale': fit['scale'], 'rotation_deg': fit['rotation_deg'],
        'translation': {'x': fit['tx'], 'y': fit['ty']}, 'cos': fit['cos'], 'sin': fit['sin'],
        'n_points': fit['n'], 'rmse_m': fit['rmse'], 'degenerate': fit['degenerate'],
    }


def _points_with_residuals(points, fit):
    res = fit.get('residuals', [])
    enabled_idx = 0
    out = []
    for p in points:
        r = None
        if p.get('enabled', True) and not fit['degenerate'] and enabled_idx < len(res):
            r = res[enabled_idx]
            enabled_idx += 1
        out.append(dict(p, residual_m=r))
    return out


def _state_response(task, pk):
    products = available_products(task)
    state = store.get_state(pk)
    if state is None:
        return {
            'state': 'previewing', 'points': [], 'transform': None,
            'products': products, 'corrected_available': False,
        }
    corrected = state.get('corrected_paths') or {}
    corrected_available = (state.get('state') == 'applied'
                           and any(os.path.isfile(p) for p in corrected.values()))
    return {
        'state': state.get('state', 'previewing'),
        'points': state.get('points', []),
        'transform': state.get('transform'),
        'products': products,
        'corrected_available': corrected_available,
        'updated_at': state.get('updated_at'),
    }


class RealignState(TaskView):
    """Estado de realineación de una tarea (FR-012, FR-013, FR-016)."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        return Response(_state_response(task, pk), status=status.HTTP_200_OK)

    def put(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        points, err = _validate_points(request.data.get('points'))
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)

        fit = _fit_for_task(task, points)
        state = store.get_state(pk) or {}
        # Editar puntos vuelve a estado de previsualización (los corregidos previos se
        # regenerarán desde el original al volver a aplicar — FR-010).
        state.update({
            'state': 'previewing',
            'points': _points_with_residuals(points, fit),
            'transform': _transform_dict(fit, task.epsg or 4326),
            'products': available_products(task),
            'updated_at': _now(),
        })
        store.set_state(pk, state)
        return Response(_state_response(task, pk), status=status.HTTP_200_OK)

    def delete(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))
        _remove_corrected(pk)
        store.del_state(pk)
        return Response({'ok': True}, status=status.HTTP_200_OK)


class RealignApply(TaskView):
    """Genera los productos corregidos de forma asíncrona (FR-008, FR-010, FR-014, FR-015)."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        points, err = _validate_points(request.data.get('points'))
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        if points is None or len(points) == 0:
            state = store.get_state(pk)
            points = state.get('points', []) if state else []

        enabled = [p for p in points if p.get('enabled', True)]
        if len(enabled) < 1:
            return Response({'error': _('Se necesita al menos un par de puntos para aplicar.')},
                            status=status.HTTP_400_BAD_REQUEST)

        fit = _fit_for_task(task, points)
        if fit['degenerate']:
            return Response({'error': _('Los puntos no permiten calcular la transformación (coincidentes o insuficientes).')},
                            status=status.HTTP_400_BAD_REQUEST)

        products = available_products(task)
        if not products:
            return Response({'error': _('La tarea no tiene productos ráster 2D para realinear.')},
                            status=status.HTTP_400_BAD_REQUEST)

        product_list = [{'type': t, 'src': os.path.abspath(task.get_asset_download_path(PRODUCT_ASSETS[t]))}
                        for t in products]
        T = {'scale': fit['scale'], 'cos': fit['cos'], 'sin': fit['sin'], 'tx': fit['tx'], 'ty': fit['ty']}

        state = store.get_state(pk) or {}
        state.update({
            'state': 'applying',
            'points': _points_with_residuals(points, fit),
            'transform': _transform_dict(fit, task.epsg or 4326),
            'products': products,
            'updated_at': _now(),
        })
        store.set_state(pk, state)

        celery_task_id = run_function_async(
            corrections.run_correction_pipeline,
            str(pk), product_list, _out_dir(pk), T, request.user.id
        ).task_id
        return Response({'celery_task_id': celery_task_id}, status=status.HTTP_200_OK)


class RealignRevert(TaskView):
    """Revierte al estado original, conservando los originales (FR-011, FR-014)."""

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))
        _remove_corrected(pk)
        state = store.get_state(pk) or {}
        state.update({'state': 'reverted', 'corrected_paths': {}, 'updated_at': _now()})
        store.set_state(pk, state)
        return Response({'state': 'reverted'}, status=status.HTTP_200_OK)


class RealignStatus(GetTaskResult):
    """Sondeo del pipeline asíncrono de aplicar (patrón GetTaskResult del framework)."""
    pass


class RealignTiles(TaskView):
    """Tiles PNG del producto corregido, servidos por el plugin (D5, FR-008)."""

    def get(self, request, pk=None, type=None, z=None, x=None, y=None, ext=None):
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()

        from rio_tiler.io import COGReader
        from rio_tiler.errors import TileOutsideBounds, InvalidColorMapName
        from rio_tiler.profiles import img_profiles
        from rio_tiler.colormap import cmap as colormap

        z, x, y = int(z), int(x), int(y)

        # Mismo esquema que el tiler del core (app/api/tiler.py): las capas del frontend usan
        # tileSize 512 y piden z+1 en la URL; con size=512 se compensa restando 1 al zoom.
        tilesize = request.query_params.get('size') or 256
        try:
            tilesize = int(tilesize)
            if tilesize not in (256, 512):
                raise ValueError()
        except ValueError:
            raise exceptions.ValidationError(_("Parámetro size inválido"))
        if tilesize == 512:
            z -= 1

        # El core adjunta color_map/rescale a la URL de la capa original (Map.jsx: viridis +
        # rescale con min/max reales para dsm/dtm) y redirectCoreLayer los preserva al
        # redirigir — se honran aquí para que el corregido se vea igual que el original.
        default_color_map = None if type == 'orthophoto' else 'gray'
        color_map_name = request.query_params.get('color_map') or default_color_map
        cmap_obj = None
        if color_map_name:
            try:
                cmap_obj = colormap.get(color_map_name)
            except InvalidColorMapName:
                raise exceptions.ValidationError(_("Parámetro color_map inválido"))

        rescale_param = request.query_params.get('rescale')
        if rescale_param:
            try:
                rescale = [float(v) for v in rescale_param.split(',')]
            except ValueError:
                raise exceptions.ValidationError(_("Parámetro rescale inválido"))
        else:
            rescale = [0, 255] if type == 'orthophoto' else [0, 1000]

        options = img_profiles.get('png', {})

        try:
            with COGReader(path) as src:
                if not src.tile_exists(z, x, y):
                    raise exceptions.NotFound(_("Fuera de límites"))
                nodata = 0 if type == 'orthophoto' else None
                tile = src.tile(x, y, z, tilesize=tilesize, nodata=nodata)
                img = tile.post_process(in_range=(rescale,))
                render_kwargs = {'img_format': 'PNG', **options}
                if cmap_obj is not None:
                    render_kwargs['colormap'] = cmap_obj
                return HttpResponse(img.render(**render_kwargs), content_type='image/png')
        except TileOutsideBounds:
            raise exceptions.NotFound(_("Fuera de límites"))


class RealignTileJson(TaskView):
    """TileJSON del producto corregido (bounds leídos del COG corregido)."""

    def get(self, request, pk=None, type=None):
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()

        from rio_tiler.io import COGReader

        with COGReader(path) as src:
            minzoom, maxzoom = src.minzoom, src.maxzoom
            # rio-tiler 2.1.x expone COGReader.bounds ya en EPSG:4326 ([w, s, e, n]).
            bounds = list(src.bounds)

        tile_url = '/api/plugins/realign/task/{}/realign/tiles/{}/{{z}}/{{x}}/{{y}}.png'.format(pk, type)
        return Response({
            'tilejson': '2.1.0',
            'name': 'realign_{}'.format(type),
            'version': '1.0.0',
            'scheme': 'xyz',
            'tiles': [tile_url],
            'minzoom': minzoom,
            'maxzoom': maxzoom + 3,
            'bounds': bounds,
        })


class RealignDownload(TaskView):
    """Descarga del GeoTIFF corregido desde el directorio persistente del plugin."""

    def get(self, request, pk=None, type=None):
        from app.api.tasks import download_file_response
        task = self.get_and_check_task(request, pk)
        path = _corrected_path(pk, type)
        if not os.path.isfile(path):
            raise exceptions.NotFound()
        return download_file_response(request, path, 'attachment',
                                      download_filename='{}_realigned.tif'.format(type))
