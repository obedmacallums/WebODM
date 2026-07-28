"""Vistas REST del plugin (`contracts/rest-api.md`).

Toda vista extiende `TaskView` y resuelve el acceso con `get_and_check_task`; las que modifican
estado añaden `check_project_perms(..., ('change_project',))`, igual que `realign`.

Los errores viajan siempre con la misma forma, `{"error", "code"}`: el frontend distingue por
`code` y muestra `error`, de modo que cambiar la redacción de un mensaje no rompe la interfaz.
"""

from rest_framework import status
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _

from app.plugins.views import TaskView

from . import geometry, sources

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


class Capabilities(TaskView):
    """`GET task/<pk>/capabilities`: qué puede ofrecer el plugin sobre esta tarea.

    Existe para que el panel se dibuje sin opciones muertas: los modelos que hay, las variantes
    por modelo, los ejes disponibles y los rangos de parámetros —cuyo suelo depende de la
    resolución del ráster— salen de aquí y no de constantes duplicadas en el frontend.
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
            'annotations_available': False,
            'axes': [],
            'defaults': sources.defaults_for(resolution),
            'ranges': sources.ranges_for(resolution),
            'max_vertices': geometry.MAX_VERTICES,
            'max_upload_bytes': sources.MAX_UPLOAD_BYTES,
        }, status=status.HTTP_200_OK)
