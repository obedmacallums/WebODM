"""Vistas REST del plugin (`contracts/rest-api.md`).

Toda vista extiende `TaskView` y resuelve el acceso con `get_and_check_task`; las que modifican
estado añaden `check_project_perms(..., ('change_project',))`, igual que `realign`. Un fallo de
permiso sale como `404` y no como `403`: es lo que hace `check_project_perms` del core,
deliberadamente, para no revelar que la tarea existe.

Los errores viajan siempre con la misma forma, `{"error", "code"}`: el frontend distingue por
`code` y muestra `error`, de modo que cambiar la redacción de un mensaje no rompe la interfaz.
"""

import datetime
import uuid

from rest_framework import status
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.response import Response
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from app.api.common import check_project_perms
from app.plugins.views import TaskView
from app.plugins.worker import run_function_async

from . import axis as axis_module
from . import compute, export, geometry, sources, store

# Códigos de error de `contracts/rest-api.md`.
ERR_INVALID_PARAMETER = 'invalid_parameter'
ERR_INVALID_AXIS = 'invalid_axis'
ERR_NO_ELEVATION_MODEL = 'no_elevation_model'
ERR_UNAVAILABLE_VARIANT = 'unavailable_variant'
ERR_NOT_FOUND = 'not_found'
ERR_ANALYSIS_RUNNING = 'analysis_running'
ERR_CONFIRMATION_REQUIRED = 'confirmation_required'
ERR_RESULT_MISSING = 'result_missing'


def error(message, code, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    payload = {'error': str(message), 'code': code}
    payload.update(extra)
    return Response(payload, status=http_status)


def no_elevation_model():
    return error(_('La tarea no tiene DSM ni DTM.'), ERR_NO_ELEVATION_MODEL)


def _now():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def _abort_celery_task(celery_task_id):
    from worker.tasks import TestSafeAsyncResult
    res = TestSafeAsyncResult(celery_task_id)
    if not res.ready():
        res.backend.store_result(celery_task_id, result=None, state="ABORTED", traceback=None)


def _analysis_response(task, analysis):
    """Entrada del índice más el estado derivado `stale` (`data-model.md` §2)."""
    payload = dict(analysis)
    payload['stale'] = sources.is_stale(task, analysis)
    return payload


def _resolve_model_and_variant(task, data):
    """`(model, variant, described, error_response)` a partir del cuerpo de la petición."""
    models = sources.available_models(task)
    if not models:
        return None, None, None, no_elevation_model()

    model = data.get('model') or sources.default_model(task)
    if model not in models:
        return None, None, None, error(
            _('El modelo %(model)s no está disponible en esta tarea.') % {'model': model},
            ERR_INVALID_PARAMETER)

    variant = data.get('variant') or sources.VARIANT_ORIGINAL
    if variant not in sources.available_variants(task, model):
        return None, None, None, error(
            _('La variante %(variant)s no está disponible para este modelo.') % {
                'variant': variant},
            ERR_UNAVAILABLE_VARIANT)

    try:
        described = sources.describe(task, model, variant)
    except Exception as e:
        return None, None, None, error(
            _('No se pudo leer el modelo de elevación: %(err)s') % {'err': e},
            ERR_NO_ELEVATION_MODEL)

    return model, variant, described, None


def _request_data(request):
    """Normaliza el cuerpo, que llega como JSON o como `multipart/form-data` con un archivo.

    En multipart todo viaja como texto, así que `params` y `axis` se aceptan además como cadenas
    JSON: es lo que puede mandar un `<form>` sin construir el cuerpo a mano.
    """
    import json

    if not request.FILES:
        return request.data

    data = {}
    for key, value in request.data.items():
        if key in ('params', 'axis') and isinstance(value, str):
            try:
                data[key] = json.loads(value)
            except ValueError:
                data[key] = value
        elif key == 'confirm':
            data[key] = str(value).lower() in ('1', 'true', 'yes', 'on')
        else:
            data[key] = value
    return data


def _resolve_axis(task, data, described, request=None, model='dtm'):
    """`(axis_source, nombre_sugerido, error_response)`.

    Dos vías con la misma salida: una polilínea de `annotations` o un GeoJSON subido. Que ambas
    terminen en el mismo `AxisSource` es lo que permite que el resto del flujo —estimación,
    candado, worker, exportación— no sepa por dónde entró el eje.
    """
    upload = request.FILES.get('file') if request is not None and request.FILES else None
    if upload is not None:
        if upload.size > sources.MAX_UPLOAD_BYTES:
            return None, None, error(
                _('El archivo pesa %(size)s bytes y el máximo es %(max)s.') % {
                    'size': upload.size, 'max': sources.MAX_UPLOAD_BYTES},
                ERR_INVALID_AXIS)
        try:
            vertices, warning = axis_module.axis_from_geojson(
                upload.read(), upload.name, task, model)
            source = axis_module.build_axis_source(
                axis_module.KIND_UPLOAD, upload.name, vertices, described['crs'],
                described['unit_factor'])
        except axis_module.InvalidAxis as e:
            return None, None, error(e, ERR_INVALID_AXIS)
        source['warning'] = str(warning) if warning else None
        return source, upload.name, None

    spec = data.get('axis') or {}
    kind = spec.get('kind') or axis_module.KIND_ANNOTATION
    ref = spec.get('ref')

    if kind != axis_module.KIND_ANNOTATION:
        return None, None, error(_('Origen de eje no admitido: %(kind)s.') % {'kind': kind},
                                 ERR_INVALID_AXIS)
    if not ref:
        return None, None, error(_('Falta la referencia del eje.'), ERR_INVALID_AXIS)

    try:
        source, name = axis_module.axis_source_from_annotation(
            str(task.id), ref, described['crs'], described['unit_factor'])
    except axis_module.InvalidAxis as e:
        return None, None, error(e, ERR_INVALID_AXIS)

    if source is None:
        return None, None, error(
            _('No se encontró una polilínea 2D con la referencia %(ref)s en esta tarea.') % {
                'ref': ref},
            ERR_INVALID_AXIS)
    return source, name, None


class Capabilities(TaskView):
    """`GET task/<pk>/capabilities`: qué puede ofrecer el plugin sobre esta tarea.

    Existe para que el panel se dibuje sin opciones muertas: los modelos que hay, las variantes por
    modelo, los ejes disponibles y los rangos de parámetros —cuyo suelo depende de la resolución
    del ráster— salen de aquí y no de constantes duplicadas en el frontend.
    """

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        models = sources.available_models(task)
        if not models:
            return no_elevation_model()

        model = sources.default_model(task)
        try:
            described = sources.describe(task, model)
        except Exception as e:
            return error(_('No se pudo leer el modelo de elevación: %(err)s') % {'err': e},
                         ERR_NO_ELEVATION_MODEL)

        resolution = described['resolution']
        return Response({
            'models': models,
            'default_model': model,
            'variants': {m: sources.available_variants(task, m) for m in models},
            'resolution': resolution,
            'vertical_unit': described['vertical_unit'],
            'annotations_available': axis_module.annotations_available(),
            'axes': axis_module.describe_axes(str(task.id), described['crs'],
                                              described['unit_factor']),
            'defaults': sources.defaults_for(resolution),
            'ranges': sources.ranges_for(resolution),
            # Aparte de `ranges` porque es un enum, no un intervalo: el panel dibuja un selector,
            # no un deslizador (`006` contracts/rest-api-delta.md).
            'edge_modes': list(sources.EDGE_MODES),
            'max_vertices': geometry.MAX_VERTICES,
            'max_upload_bytes': sources.MAX_UPLOAD_BYTES,
        }, status=status.HTTP_200_OK)


class AnalysisList(TaskView):
    """`GET`/`POST task/<pk>/analyses`."""

    def get(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        return Response({
            'running': store.get_running(str(task.id)),
            'analyses': [_analysis_response(task, a) for a in store.list_analyses(str(task.id))],
        }, status=status.HTTP_200_OK)

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        data = _request_data(request)
        model, variant, described, failure = _resolve_model_and_variant(task, data)
        if failure is not None:
            return failure

        params, err = sources.validate_params(data.get('params'), described['resolution'])
        if err:
            return error(err, ERR_INVALID_PARAMETER)

        source, suggested_name, failure = _resolve_axis(task, data, described, request, model)
        if failure is not None:
            return failure

        estimate = compute.estimate(source['plan_length'], params)

        # Un eje tiene como mucho un análisis en la tarea: relanzarlo **pisa** el anterior
        # conservando su `id` y su `name` (FR-037). La confirmación existe porque sustituir es
        # destructivo y porque un análisis muy caro merece un aviso antes de ocupar el worker
        # — pero no hay tope que impida lanzarlo (FR-043).
        existing = store.find_analysis_by_axis(str(task.id), source['kind'], source['ref'])
        if not data.get('confirm'):
            reason = ('replaces_existing' if existing is not None
                      else 'costly' if estimate['warn'] else None)
            if reason is not None:
                return error(
                    _('Este análisis sustituirá al que ya existe para ese eje.') if existing
                    else _('El análisis es costoso: %(n)s muestras.') % {'n': estimate['samples']},
                    ERR_CONFIRMATION_REQUIRED, status.HTTP_409_CONFLICT,
                    reason=reason, estimate=estimate,
                    existing_analysis_id=existing['id'] if existing else None)

        analysis_id = existing['id'] if existing is not None else str(uuid.uuid4())
        acquired, running = store.acquire_running(str(task.id), analysis_id)
        if not acquired:
            return error(_('Ya hay un análisis en curso en esta tarea.'), ERR_ANALYSIS_RUNNING,
                         status.HTTP_409_CONFLICT,
                         running_analysis_id=running.get('analysis_id'))

        try:
            # El resultado anterior se descarta antes de empezar: si el nuevo cálculo falla o se
            # cancela, dejar los tramos viejos bajo unos parámetros nuevos sería peor que no tener
            # nada — el usuario los leería como si describieran lo que acaba de pedir.
            if existing is not None:
                store.delete_segments(str(task.id), analysis_id)

            analysis = {
                'id': analysis_id,
                'name': str(data.get('name')
                            or (existing or {}).get('name')
                            or suggested_name or _('Camino'))[:255],
                'axis': source,
                'model': model,
                'variant': variant,
                'params': params,
                # Los umbrales del semáforo sobreviven al recálculo: son una preferencia de lectura
                # del usuario, no un producto del cálculo, y devolverlos a los de fábrica cada vez
                # que se afina un parámetro sería un paso atrás en cada iteración.
                'color_thresholds': ((existing or {}).get('color_thresholds')
                                     or list(sources.COLOR_THRESHOLDS_DEFAULT)),
                'status': 'running',
                'progress': 0.0,
                'error': None,
                'celery_task_id': None,
                'source_mtime': sources.source_mtime(task, model, variant),
                'summary': None,
                'created_at': (existing or {}).get('created_at') or _now(),
                'updated_at': _now(),
                'created_by': request.user.id,
            }
            store.upsert_analysis(str(task.id), analysis)

            async_result = run_function_async(
                compute.run_analysis,
                str(task.id), analysis_id, described['path'], source['vertices'], params,
                analysis['source_mtime'],
                with_progress=True, with_cancel=True,
            )
        except Exception:
            # Sin esto, un fallo al lanzar deja el candado tomado y la tarea inutilizable.
            store.release_running(str(task.id), analysis_id)
            raise

        # Bajo `CELERY_TASK_ALWAYS_EAGER` (tests) el trabajo ya terminó y escribió su estado final
        # antes de que volvamos aquí: anotar el id entonces resucitaría un candado ya liberado y
        # dejaría un `celery_task_id` en un análisis completado, que el botón de cancelar leería
        # como "todavía se puede parar".
        def attach(analysis):
            if analysis.get('status') == 'running':
                analysis['celery_task_id'] = async_result.task_id
            return analysis

        store.attach_celery_task(str(task.id), analysis_id, async_result.task_id)
        store.update_analysis(str(task.id), analysis_id, attach)

        return Response({'analysis_id': analysis_id, 'celery_task_id': async_result.task_id,
                         'estimate': estimate}, status=status.HTTP_202_ACCEPTED)


class AnalysisEstimate(TaskView):
    """`POST task/<pk>/analyses/estimate`: cuánto costaría, sin lanzar nada (`research.md` D11).

    El conteo es aritmética pura sobre la longitud del eje, así que responde de inmediato y sin
    tocar el ráster. Existe porque la decisión de no poner tope duro (FR-043) obliga a darle al
    usuario con qué decidir.
    """

    def post(self, request, pk=None):
        task = self.get_and_check_task(request, pk)

        data = _request_data(request)
        model, variant, described, failure = _resolve_model_and_variant(task, data)
        if failure is not None:
            return failure

        params, err = sources.validate_params(data.get('params'), described['resolution'])
        if err:
            return error(err, ERR_INVALID_PARAMETER)

        source, _name, failure = _resolve_axis(task, data, described, request, model)
        if failure is not None:
            return failure

        return Response(compute.estimate(source['plan_length'], params),
                        status=status.HTTP_200_OK)


class AnalysisDetail(TaskView):
    """`GET`/`PATCH`/`DELETE task/<pk>/analyses/<analysis_id>`."""

    PATCHABLE = ('name', 'color_thresholds')

    def patch(self, request, pk=None, analysis_id=None):
        """Solo `name` y `color_thresholds`.

        Cualquier otro campo se rechaza en vez de ignorarse: aceptar un `params` por aquí dejaría
        un análisis cuyos parámetros ya no describen sus propios tramos, y nadie se enteraría.

        `updated_at` **no se toca**: marca cuándo se calculó el resultado, y ni renombrar ni mover
        los umbrales del semáforo recalculan nada (FR-030).
        """
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        analysis = store.get_analysis(str(task.id), analysis_id)
        if analysis is None:
            return error(_('El análisis no existe en esta tarea.'), ERR_NOT_FOUND,
                         status.HTTP_404_NOT_FOUND)

        unknown = [k for k in request.data if k not in self.PATCHABLE]
        if unknown:
            return error(
                _('Solo se pueden modificar %(allowed)s. Recibido: %(got)s.') % {
                    'allowed': ', '.join(self.PATCHABLE), 'got': ', '.join(sorted(unknown))},
                ERR_INVALID_PARAMETER)

        changes = {}
        if 'name' in request.data:
            name = str(request.data['name'] or '').strip()
            if not name:
                return error(_('El nombre no puede estar vacío.'), ERR_INVALID_PARAMETER)
            changes['name'] = name[:255]

        if 'color_thresholds' in request.data:
            thresholds, err = sources.validate_color_thresholds(request.data['color_thresholds'])
            if err:
                return error(err, ERR_INVALID_PARAMETER)
            changes['color_thresholds'] = thresholds

        def mutate(a):
            a.update(changes)
            return a

        updated = store.update_analysis(str(task.id), analysis_id, mutate)
        return Response(_analysis_response(task, updated), status=status.HTTP_200_OK)

    def delete(self, request, pk=None, analysis_id=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        analysis = store.get_analysis(str(task.id), analysis_id)
        if analysis is None:
            return error(_('El análisis no existe en esta tarea.'), ERR_NOT_FOUND,
                         status.HTTP_404_NOT_FOUND)

        # Cancelar antes de borrar: un worker vivo volvería a escribir el archivo de tramos justo
        # detrás, y el candado quedaría tomado sobre un análisis que ya no existe.
        if analysis.get('status') == 'running':
            cancel_analysis(task, analysis)

        store.delete_segments(str(task.id), analysis_id)
        store.remove_analysis(str(task.id), analysis_id)
        store.release_running(str(task.id), analysis_id)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def get(self, request, pk=None, analysis_id=None):
        task = self.get_and_check_task(request, pk)
        analysis = store.get_analysis(str(task.id), analysis_id)
        if analysis is None:
            return error(_('El análisis no existe en esta tarea.'), ERR_NOT_FOUND,
                         status.HTTP_404_NOT_FOUND)

        payload = _analysis_response(task, analysis)
        payload['segments'] = []

        if analysis.get('status') == 'completed':
            document = store.read_segments(str(task.id), analysis_id)
            if document is None:
                return error(_('El resultado de este análisis ya no está disponible.'),
                             ERR_RESULT_MISSING, status.HTTP_410_GONE)
            payload['segments'] = document.get('segments', [])

        return Response(payload, status=status.HTTP_200_OK)


class _IgnoreFormatQueryParam(DefaultContentNegotiation):
    """Negociación de contenido que **no** mira el parámetro `?format=`.

    `format` es un nombre reservado por DRF (`URL_FORMAT_OVERRIDE`): lo usa para elegir renderer, y
    ante un valor que no corresponde a ninguno —`csv`, `geojson`— responde `404` *antes* de
    ejecutar la vista. El contrato de esta feature usa `?format=csv|geojson` con otro significado,
    así que aquí se desactiva esa negociación y el primer renderer (JSON) atiende las respuestas de
    error; la descarga en sí sale como `HttpResponse` y no pasa por renderer.
    """

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class AnalysisExport(TaskView):
    """`GET task/<pk>/analyses/<analysis_id>/export?format=csv|geojson`.

    No exige `change_project`: descargar no modifica nada, y un usuario con acceso de lectura tiene
    que poder llevarse el resultado a su hoja de cálculo o a QGIS.
    """

    content_negotiation_class = _IgnoreFormatQueryParam

    FORMATS = {
        'csv': ('text/csv', export.to_csv),
        'geojson': ('application/geo+json', export.to_geojson),
    }

    def get(self, request, pk=None, analysis_id=None):
        task = self.get_and_check_task(request, pk)

        fmt = (request.query_params.get('format') or 'csv').lower()
        if fmt not in self.FORMATS:
            return error(_('Formato no admitido: %(fmt)s. Use csv o geojson.') % {'fmt': fmt},
                         ERR_INVALID_PARAMETER)

        analysis = store.get_analysis(str(task.id), analysis_id)
        if analysis is None:
            return error(_('El análisis no existe en esta tarea.'), ERR_NOT_FOUND,
                         status.HTTP_404_NOT_FOUND)

        document = store.read_segments(str(task.id), analysis_id)
        if document is None:
            return error(_('El resultado de este análisis ya no está disponible.'),
                         ERR_RESULT_MISSING, status.HTTP_410_GONE)

        content_type, render = self.FORMATS[fmt]
        response = HttpResponse(render(analysis, document.get('segments', [])),
                                content_type=content_type)
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(
            export.filename(task.name, analysis.get('name'), fmt))
        return response


class AnalysisCancel(TaskView):
    """`POST task/<pk>/analyses/<analysis_id>/cancel`.

    Idempotente: sobre un análisis que ya terminó responde `200` sin cambiar nada. No conserva
    resultado parcial (FR-034).
    """

    def post(self, request, pk=None, analysis_id=None):
        task = self.get_and_check_task(request, pk)
        check_project_perms(request, task.project, ('change_project',))

        analysis = store.get_analysis(str(task.id), analysis_id)
        if analysis is None:
            return error(_('El análisis no existe en esta tarea.'), ERR_NOT_FOUND,
                         status.HTTP_404_NOT_FOUND)

        if analysis.get('status') == 'running':
            cancel_analysis(task, analysis)
            analysis = store.get_analysis(str(task.id), analysis_id)

        return Response(_analysis_response(task, analysis), status=status.HTTP_200_OK)


def cancel_analysis(task, analysis):
    """Aborta la tarea de Celery, marca `canceled`, borra el parcial y libera el candado."""
    analysis_id = analysis['id']
    celery_task_id = analysis.get('celery_task_id')
    if celery_task_id:
        try:
            _abort_celery_task(celery_task_id)
        except Exception:
            # Sin backend de resultados no se puede abortar, pero el estado sí debe quedar limpio.
            pass

    store.delete_segments(str(task.id), analysis_id)

    def mutate(a):
        a.update({'status': 'canceled', 'progress': None, 'celery_task_id': None,
                  'updated_at': _now()})
        return a

    store.update_analysis(str(task.id), analysis_id, mutate)
    store.release_running(str(task.id), analysis_id)
