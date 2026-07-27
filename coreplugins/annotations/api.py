import re
import json
import uuid
import datetime

from rest_framework import status
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from app.plugins.views import TaskView
from app.api.common import check_project_perms

from . import store, geometry, elevation, contract
from .contract import serialize_polyline

DEFAULT_NAME_RE = re.compile(r'^Polilínea (\d+)$')


def _now():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def _default_name(existing_names):
    """Menor `N` libre para `"Polilínea N"` cuando el nombre llega vacío (FR-003)."""
    used = set()
    for name in existing_names:
        m = DEFAULT_NAME_RE.match(name or '')
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return 'Polilínea {}'.format(n)


class AnnotationsTaskView(TaskView):
    """Vista base: resolución de tarea y permisos (`research.md` D9), formato de error
    `{"error": ...}` uniforme (`contracts/rest-api.md`)."""

    def check_write_perms(self, request, task):
        check_project_perms(request, task.project, ('change_project',))

    def error(self, message, http_status=status.HTTP_400_BAD_REQUEST, **extra):
        body = {'error': message}
        body.update(extra)
        return Response(body, status=http_status)


def _elevation_error(view, exc):
    """Traduce una excepción de `elevation.py` a la respuesta HTTP de `contracts/rest-api.md`."""
    if isinstance(exc, ValueError):
        return view.error(_('El paso de densificación es inválido.'))
    if isinstance(exc, elevation.LimitExceeded):
        return view.error(_('El trazado supera el límite de puntos densificados. '
                             'Reduce el trazado o aumenta el paso.'))
    if isinstance(exc, elevation.IncompleteCoverage):
        return view.error(
            _('Parte del recorrido no tiene datos de elevación.'),
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            reason='incomplete_coverage',
            missing_ranges=exc.missing_ranges,
            missing_samples=exc.missing_samples,
            total_samples=exc.total_samples,
        )
    raise exc


def _resample(view, task, vertices, model, step):
    """Muestrea `vertices` con `model`/`step` ya resueltos. Devuelve
    `(elevation_dict, plan_length, error_response)`; `error_response` no es `None` si algo
    falló y ya está listo para devolverse tal cual (la polilínea previa queda intacta,
    `data-model.md` transiciones: todo o nada)."""
    try:
        elev = elevation.sample_polyline(task, vertices, model, step)
    except (ValueError, elevation.LimitExceeded, elevation.IncompleteCoverage) as e:
        return None, None, _elevation_error(view, e)
    plan_length = elev.pop('plan_length')
    return elev, plan_length, None


def _sample_for_creation(view, task, vertices, request):
    """Resuelve `model`/`step` del body de creación y muestrea (FR-007 a FR-011)."""
    models = elevation.available_models(task)
    if not models:
        return None, None, view.error(_('La tarea no tiene modelo de elevación.'))

    model = request.data.get('model') or elevation.default_model(task)
    if model not in models:
        return None, None, view.error(_('Modelo de elevación no disponible en esta tarea.'))

    step = request.data.get('step')
    return _resample(view, task, vertices, model, step)


class PolylineList(AnnotationsTaskView):
    """`GET`/`POST task/<pk>/polylines` (FR-001 a FR-003, FR-007, FR-024)."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        doc = store.get_document(pk)
        return Response({
            'version': doc['version'],
            'polylines': [serialize_polyline(p, task) for p in doc['polylines']],
        }, status=status.HTTP_200_OK)

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        self.check_write_perms(request, task)

        vertices = request.data.get('vertices')
        ok, err = geometry.validate_vertices(vertices)
        if not ok:
            return self.error(err)
        vertices = [[float(v[0]), float(v[1])] for v in vertices]

        mode = request.data.get('mode') or 'flat'
        if mode not in ('flat', 'draped'):
            return self.error(_('El modo debe ser "flat" o "draped".'))

        name = (request.data.get('name') or '').strip()
        if not name:
            name = _default_name(p.get('name') for p in store.list_polylines(pk))

        now = _now()
        polyline = {
            'id': str(uuid.uuid4()),
            'name': name[:255],
            'mode': mode,
            'vertices': vertices,
            'created_at': now,
            'created_by': request.user.username,
            'updated_at': now,
        }

        if mode == 'draped':
            elev, plan_length, err_response = _sample_for_creation(self, task, vertices, request)
            if err_response is not None:
                return err_response
            polyline['elevation'] = elev
            polyline['plan_length'] = plan_length
        else:
            polyline['plan_length'] = geometry.plan_length(vertices, task.epsg)

        store.upsert_polyline(pk, polyline)
        return Response(serialize_polyline(polyline, task), status=status.HTTP_201_CREATED)


class ElevationCapabilities(AnnotationsTaskView):
    """`GET task/<pk>/elevation` (FR-009, FR-010, FR-016)."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        return Response(elevation.capabilities(task), status=status.HTTP_200_OK)


class PolylineDetail(AnnotationsTaskView):
    """`DELETE`/`PATCH task/<pk>/polylines/<id>` (FR-004, FR-005, FR-019)."""

    def delete(self, request, pk=None, polyline_id=None):
        task = self.get_and_check_task(request, pk)
        self.check_write_perms(request, task)

        removed = store.remove_polyline(pk, polyline_id)
        if not removed:
            return self.error(_('La polilínea no existe.'), status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def patch(self, request, pk=None, polyline_id=None):
        task = self.get_and_check_task(request, pk)
        self.check_write_perms(request, task)

        polyline = store.get_polyline(pk, polyline_id)
        if polyline is None:
            return self.error(_('La polilínea no existe.'), status.HTTP_404_NOT_FOUND)

        # El tipo se fija al crear y ya no se convierte (contrato v2): un PATCH que intente
        # cambiarlo se rechaza en vez de ignorarse en silencio.
        if 'mode' in request.data and request.data.get('mode') != polyline['mode']:
            return self.error(_('El tipo de una polilínea no se puede cambiar. Crea una nueva.'))

        updated = dict(polyline)
        changed = False

        if 'name' in request.data:
            name = (request.data.get('name') or '').strip()
            if not name:
                others = (p.get('name') for p in store.list_polylines(pk) if p['id'] != polyline_id)
                name = _default_name(others)
            updated['name'] = name[:255]
            changed = True

        if 'vertices' in request.data:
            vertices = request.data.get('vertices')
            ok, err = geometry.validate_vertices(vertices)
            if not ok:
                return self.error(err)
            vertices = [[float(v[0]), float(v[1])] for v in vertices]
            updated['vertices'] = vertices

            if updated['mode'] == 'draped':
                # FR-019: se vuelve a muestrear con el mismo model/step; si pierde cobertura,
                # la operación se rechaza entera y `polyline` (ya devuelto arriba) no se toca.
                prev_elevation = updated.get('elevation')
                if not prev_elevation:
                    # Una polilínea sobre el terreno siempre se guarda con su muestreo; si el
                    # documento llega sin él, el PATCH no tiene con qué remuestrear. Se responde
                    # como error de la petición en vez de reventar con un 500 sin explicación.
                    return self.error(
                        _('La polilínea no conserva su muestreo de elevación. Vuelve a crearla.'))
                elev, plan_length, err_response = _resample(
                    self, task, vertices, prev_elevation['model'], prev_elevation['step'])
                if err_response is not None:
                    return err_response
                updated['elevation'] = elev
                updated['plan_length'] = plan_length
            else:
                updated['plan_length'] = geometry.plan_length(vertices, task.epsg)
            changed = True

        if not changed:
            return self.error(_('No se indicó ningún cambio.'))

        updated['updated_at'] = _now()
        store.upsert_polyline(pk, updated)
        return Response(serialize_polyline(updated, task), status=status.HTTP_200_OK)


class PolylineDensified(AnnotationsTaskView):
    """`GET task/<pk>/polylines/<id>/densified[?step=<m>]` (FR-038)."""

    def get(self, request, pk=None, polyline_id=None):
        self.get_and_check_task(request, pk)

        step = None
        step_param = request.query_params.get('step')
        if step_param is not None:
            try:
                step = float(step_param)
            except (TypeError, ValueError):
                return self.error(_('El paso de densificación es inválido.'))

        try:
            result = contract.get_densified(pk, polyline_id, step)
        except ValueError as e:
            # `get_densified` y `elevation` comparten `ValueError`: la polilínea plana viene del
            # contrato, el paso fuera de rango de la validación del muestreo.
            if str(e) == 'flat_polyline':
                return self.error(_('Solo las polilíneas sobre el terreno se pueden densificar.'))
            return _elevation_error(self, e)
        except (elevation.LimitExceeded, elevation.IncompleteCoverage) as e:
            return _elevation_error(self, e)

        if result is None:
            return self.error(_('La polilínea no existe.'), status.HTTP_404_NOT_FOUND)
        return Response(result, status=status.HTTP_200_OK)


def _geojson_response(fc, filename):
    response = HttpResponse(json.dumps(fc), content_type='application/geo+json')
    response['Content-Disposition'] = 'attachment; filename="{}"'.format(filename)
    return response


def _geometry_mode(view, request):
    """`(modo, error_response)`. `densified` solo cambia algo en las 3D; sobre una 2D el propio
    `_feature` ya cae a los vértices."""
    geometry_mode = request.query_params.get('geometry', 'vertices')
    if geometry_mode not in ('vertices', 'densified'):
        return None, view.error(_('El parámetro geometry debe ser "vertices" o "densified".'))
    return geometry_mode, None


class PolylineExport(AnnotationsTaskView):
    """`GET task/<pk>/polylines/export[?geometry=vertices|densified]` (FR-032 a FR-035).

    Exporta la tarea entera, mezclando 2D y 3D. Desde v2 el panel exporta de una en una; esta
    ruta se conserva porque el botón de descarga del panel de capas del core baja el grupo
    completo y esa parte la dibuja el core, no el plugin."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        geometry_mode, err = _geometry_mode(self, request)
        if err is not None:
            return err

        fc = contract.export_feature_collection(task, geometry_mode)
        return _geojson_response(fc, contract.export_filename(task))


class PolylineSingleExport(AnnotationsTaskView):
    """`GET task/<pk>/polylines/<id>/export[?geometry=vertices|densified]` (FR-032 a FR-035).

    Una sola polilínea, con el tipo en el nombre del archivo (`…-2d.geojson` / `…-3d.geojson`)."""

    def get(self, request, pk=None, polyline_id=None):
        task = self.get_and_check_task(request, pk)

        geometry_mode, err = _geometry_mode(self, request)
        if err is not None:
            return err

        polyline = store.get_polyline(pk, polyline_id)
        if polyline is None:
            return self.error(_('La polilínea no existe.'), status.HTTP_404_NOT_FOUND)

        fc = contract.export_polyline_feature_collection(task, polyline, geometry_mode)
        return _geojson_response(fc, contract.export_filename(task, polyline))
