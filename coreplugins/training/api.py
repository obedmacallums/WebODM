"""Vistas REST del plugin (`contracts/rest-api.md`).

Dos familias de vistas, y la diferencia no es de estilo:

- **Datasets**: `APIView` con `IsAuthenticated`. Un dataset referencia varias tareas (FR-002) y
  sobrevive al borrado de cualquiera de ellas, así que no puede colgar de `TaskView`: la identidad
  del recurso no es una tarea.
- **Etiquetas**: `TaskView`, porque sí viven en el contexto de una tarea concreta y el acceso se
  resuelve con el mismo `get_and_check_task` que usan `road` y `annotations`.

Los errores viajan siempre con la forma `{"error", "code"}`: el frontend distingue por `code` y
muestra `error`, de modo que cambiar la redacción de un mensaje no rompe la interfaz.

Un fallo de permiso sale como `404` y no como `403`: es lo que hace `check_project_perms` del core,
deliberadamente, para no revelar que el recurso existe.
"""

import os
import uuid

# `Task.objects.get` lanza `django.core.exceptions.ValidationError` con un pk mal formado, y esa
# clase no hereda de `ValueError`: sin capturarla, un identificador basura sería un 500 y no un 404.
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _
from rest_framework import exceptions, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from app.api.common import check_project_perms
from app.models import Task
from app.plugins.views import TaskView
from app.plugins.worker import run_function_async

from . import export as export_module
from . import models, regions, store

# Códigos de error de `contracts/rest-api.md`.
ERR_NO_ORTHOPHOTO = 'no_orthophoto'
ERR_CLASS_IN_USE = 'class_in_use'
ERR_DATASET_HAS_LABELS = 'dataset_has_labels'
ERR_TASK_NOT_IN_DATASET = 'task_not_in_dataset'
ERR_NOTHING_TO_EXPORT = 'nothing_to_export'
ERR_NO_AVAILABLE_TASKS = 'no_available_tasks'
ERR_EXPORT_NOT_READY = 'export_not_ready'
ERR_ALL_TILES_FILTERED = 'all_tiles_filtered'
ERR_NO_REVIEWED_TILES = 'no_reviewed_tiles'
ERR_NOT_FOUND = 'not_found'
# Selección asistida (`010/contracts/rest-api.md`).
ERR_BAD_POINTS = 'bad_points'
ERR_BAD_SETTINGS = 'bad_settings'
ERR_BAD_BOUNDS = 'bad_bounds'
ERR_ASSIST_UNAVAILABLE = 'assist_unavailable'


def error(message, code, http_status=status.HTTP_400_BAD_REQUEST, **extra):
    payload = {'error': str(message), 'code': code}
    payload.update(extra)
    return Response(payload, status=http_status)


def validation_error(exc):
    """Traduce un `models.ValidationError` a la respuesta que fija el contrato."""
    return error(exc.message, exc.code, **exc.extra)


def _serialize(dataset):
    """El dataset tal y como lo ve el cliente: con `available` calculado por tarea.

    `describe_tasks` consulta la base de datos, así que se hace aquí y no en el store: el estado
    derivado no debe filtrarse al documento guardado (`data-model.md` §Tarea del dataset).
    """
    payload = dict(dataset)
    payload['tasks'] = store.describe_tasks(dataset)
    payload.pop('exports', None)
    return payload


def _visible_tasks(request, dataset):
    """Identificadores de las tareas del dataset que este usuario puede ver."""
    referenced = [t['task_id'] for t in dataset.get('tasks') or []]
    if not referenced:
        return set()
    visible = set()
    for task in Task.objects.filter(pk__in=referenced).select_related('project'):
        if task.public or task.project.public or request.user.has_perm('view_project',
                                                                       task.project):
            visible.add(str(task.id))
    return visible


def _can_see(request, dataset):
    """Un dataset es visible para su creador y para quien pueda ver alguna de sus tareas.

    No se exige poder ver **todas**: un dataset multi-tarea cuyo dueño comparte solo un proyecto
    seguiría siendo suyo, y esconderlo entero lo dejaría sin forma de recuperarlo.
    """
    if request.user.is_superuser:
        return True
    if dataset.get('created_by') is not None and dataset['created_by'] == request.user.id:
        return True
    return bool(_visible_tasks(request, dataset))


def _get_visible_dataset(request, dataset_id):
    dataset = store.get_dataset(dataset_id)
    if dataset is None or not _can_see(request, dataset):
        raise exceptions.NotFound()
    return dataset


class DatasetList(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request):
        return Response([_serialize(d) for d in store.list_datasets()
                         if _can_see(request, d)])

    def post(self, request):
        data = request.data
        try:
            tasks = models.normalize_tasks(data.get('tasks'))
        except models.ValidationError as exc:
            return validation_error(exc)

        # Los permisos se comprueban antes que la forma del dataset: una tarea ajena debe salir
        # como 404 aunque el resto del cuerpo sea inválido, para no confirmar que existe.
        resolved = []
        for entry in tasks:
            task = _load_task_for_write(request, entry['task_id'])
            if task.orthophoto_extent is None:
                return error(_('La tarea «%(name)s» no tiene ortofoto.') % {'name': task.name},
                             ERR_NO_ORTHOPHOTO)
            resolved.append({'task_id': str(task.id), 'project_id': task.project_id,
                             'added_at': entry.get('added_at') or models.now_iso()})

        try:
            dataset = models.make_dataset(
                data.get('name'), data.get('classes'), resolved,
                resolution_cm_px=data.get('resolution_cm_px'),
                tile_size_px=data.get('tile_size_px'),
                tile_overlap_px=data.get('tile_overlap_px'),
                elevation_source=data.get('elevation_source'),
                pixel_dtype=data.get('pixel_dtype'),
                min_reviewed_fraction=data.get('min_reviewed_fraction'),
                min_valid_fraction=data.get('min_valid_fraction'),
                val_fraction=data.get('val_fraction'),
                split_block_tiles=data.get('split_block_tiles'),
                stroke_width_m=data.get('stroke_width_m'),
                created_by=request.user.id)
        except models.ValidationError as exc:
            return validation_error(exc)

        store.create_dataset(dataset)
        return Response(_serialize(dataset), status=status.HTTP_201_CREATED)


def _patch_settings(current, data):
    """Aplica los ajustes de exportación que vengan en el PATCH, validándolos.

    Se validan aquí con las mismas funciones que en la creación y no con un `float()` a secas: un
    `val_fraction` de 1,5 o un solape mayor que la tesela se guardarían sin protestar y reventarían
    mucho más tarde, durante una exportación de varios minutos.
    """
    if 'tile_overlap_px' in data and data['tile_overlap_px'] is not None:
        current['tile_overlap_px'] = models.validate_overlap(
            data['tile_overlap_px'], current['tile_size_px'])

    if 'elevation_source' in data and data['elevation_source'] is not None:
        source = str(data['elevation_source']).strip().lower()
        if source not in models.ELEVATION_SOURCES:
            raise models.ValidationError(
                _('La fuente de elevación debe ser una de %(list)s.')
                % {'list': ', '.join(models.ELEVATION_SOURCES)}, 'bad_elevation_source')
        current['elevation_source'] = source

    if 'pixel_dtype' in data and data['pixel_dtype'] is not None:
        dtype = str(data['pixel_dtype']).strip().lower()
        if dtype not in models.PIXEL_DTYPES:
            raise models.ValidationError(
                _('El tipo de píxel debe ser uno de %(list)s.')
                % {'list': ', '.join(models.PIXEL_DTYPES)}, 'bad_pixel_dtype')
        current['pixel_dtype'] = dtype

    for field in ('min_reviewed_fraction', 'min_valid_fraction', 'val_fraction'):
        if field in data and data[field] is not None:
            current[field] = models.validate_fraction(data[field], field)

    if 'split_block_tiles' in data and data['split_block_tiles'] is not None:
        current['split_block_tiles'] = int(models.validate_positive(
            data['split_block_tiles'],
            _('El bloque de split debe ser un número de teselas mayor que cero.'),
            'bad_split_block'))

    if 'stroke_width_m' in data and data['stroke_width_m'] is not None:
        current['stroke_width_m'] = models.validate_positive(
            data['stroke_width_m'],
            _('El ancho por defecto del trazo debe ser mayor que cero.'), 'bad_stroke_width')

    if 'assist' in data and data['assist'] is not None:
        # Cambio parcial sobre lo que ya había: la interfaz mueve un control cada vez, y exigir los
        # tres en cada PATCH haría que tocar la tolerancia reescribiera la granularidad con lo que
        # el navegador creyera recordar. Ninguno de los tres toca las etiquetas ya guardadas
        # (FR-023): describen cómo se calcularán las selecciones siguientes.
        current['assist'] = models.normalize_assist(data['assist'], current.get('assist'))


def _load_task_for_write(request, task_id):
    """La tarea, comprobando que el usuario puede **modificar** su proyecto.

    Añadir una tarea a un dataset o etiquetar sobre ella es escritura, así que no basta con
    `view_project`: se exige `change_project`, igual que `realign` y que la creación de análisis
    de `road`.
    """
    try:
        task = Task.objects.select_related('project').get(pk=task_id)
    except (Task.DoesNotExist, ValueError, DjangoValidationError):
        raise exceptions.NotFound()
    check_project_perms(request, task.project, ('view_project', 'change_project'))
    return task


class DatasetDetail(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, dataset_id):
        return Response(_serialize(_get_visible_dataset(request, dataset_id)))

    def patch(self, request, dataset_id):
        dataset = _get_visible_dataset(request, dataset_id)
        data = request.data

        if 'resolution_cm_px' in data:
            conflict = self._check_resolution_change(dataset, data['resolution_cm_px'])
            if conflict is not None:
                return conflict

        removed_indexes = []
        if 'classes' in data:
            try:
                new_classes = models.normalize_classes(data['classes'])
            except models.ValidationError as exc:
                return validation_error(exc)

            kept = {c['index'] for c in new_classes}
            removed_indexes = [c['index'] for c in dataset['classes'] if c['index'] not in kept]
            if removed_indexes:
                counts = store.count_labels_by_class(dataset_id)
                affected = sum(counts.get(i, 0) for i in removed_indexes)
                if affected and not data.get('confirm'):
                    return error(
                        _('Esas clases tienen %(n)s etiquetas que se perderán.') % {'n': affected},
                        ERR_CLASS_IN_USE, status.HTTP_409_CONFLICT, label_count=affected,
                        removed_class_indexes=removed_indexes)

        def mutate(current):
            if 'name' in data:
                name = str(data['name'] or '').strip()
                if name:
                    current['name'] = name[:255]
            if 'classes' in data:
                current['classes'] = new_classes
            for field in ('resolution_cm_px', 'tile_size_px'):
                if field in data and data[field] is not None:
                    current[field] = (float(data[field]) if field == 'resolution_cm_px'
                                      else int(data[field]))
            _patch_settings(current, data)
            return current

        try:
            updated = store.update_dataset(dataset_id, mutate)
        except models.ValidationError as exc:
            return validation_error(exc)
        except (TypeError, ValueError):
            return error(_('Valor inválido.'), 'bad_request')

        if removed_indexes:
            _drop_labels_of_classes(dataset_id, updated, removed_indexes)

        return Response(_serialize(updated))

    def _check_resolution_change(self, dataset, raw):
        """La resolución se congela en cuanto hay etiquetas (`data-model.md` §Dataset).

        No es una limitación técnica —las etiquetas son vectoriales y se reexportan a cualquier
        escala— sino honestidad: `simplify` ya descartó los vértices por debajo de la resolución
        original (FR-015), y bajar a una más fina no los recuperaría. Permitirlo presentaría como
        más preciso algo que no lo es.
        """
        try:
            new_resolution = float(raw)
        except (TypeError, ValueError):
            return error(_('La resolución debe ser mayor que cero.'), 'bad_resolution')
        if new_resolution <= 0:
            return error(_('La resolución debe ser mayor que cero.'), 'bad_resolution')
        if new_resolution != dataset['resolution_cm_px'] and store.has_any_label(dataset['id']):
            return error(_('El dataset ya tiene etiquetas: su resolución no puede cambiar.'),
                         ERR_DATASET_HAS_LABELS, status.HTTP_409_CONFLICT)
        return None

    def delete(self, request, dataset_id):
        _get_visible_dataset(request, dataset_id)
        store.delete_dataset(dataset_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _drop_labels_of_classes(dataset_id, dataset, indexes):
    """Borra las etiquetas de las clases desaparecidas, tarea por tarea.

    El borrador (`class_index` nulo) nunca entra aquí: no pertenece a ninguna clase, así que
    quitar una clase no puede llevárselo.
    """
    targets = set(indexes)
    for entry in dataset.get('tasks') or []:
        task_id = entry['task_id']
        for label in list(store.list_labels(dataset_id, task_id)):
            if label.get('class_index') in targets:
                store.delete_label(dataset_id, task_id, label['id'])


class _LabelViewBase(TaskView):
    """Resuelve el par (dataset, tarea) y el permiso, que es lo que comparten las dos vistas."""

    def resolve(self, request, dataset_id, pk, write):
        task = self.get_and_check_task(request, pk)
        if write:
            check_project_perms(request, task.project, ('change_project', ))

        dataset = store.get_dataset(dataset_id)
        if dataset is None:
            raise exceptions.NotFound()
        if not models.dataset_has_task(dataset, str(task.id)):
            return task, dataset, error(_('La tarea no pertenece a este dataset.'),
                                        ERR_TASK_NOT_IN_DATASET, status.HTTP_404_NOT_FOUND)
        return task, dataset, None


class LabelList(_LabelViewBase):
    def get(self, request, dataset_id=None, pk=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=False)
        if failure is not None:
            return failure
        return Response(store.list_labels(dataset_id, str(task.id)))

    def post(self, request, dataset_id=None, pk=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=True)
        if failure is not None:
            return failure

        data = request.data
        try:
            # La procedencia la declara el cliente pero se valida: solo `manual` y `assisted` son
            # cosas que un navegador puede producir de verdad (`models.validate_source`).
            source = models.validate_source(data.get('source'))
            # `make_label` valida antes de tocar el disco, pero el `order` definitivo lo asigna el
            # store dentro del lock: dos usuarios dibujando a la vez no pueden recibir el mismo.
            label = store.add_label(
                dataset_id, str(task.id),
                lambda order: models.make_label(dataset, data, order, source=source))
        except models.ValidationError as exc:
            return validation_error(exc)

        return Response(label, status=status.HTTP_201_CREATED)


class LabelDetail(_LabelViewBase):
    def patch(self, request, dataset_id=None, pk=None, label_id=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=True)
        if failure is not None:
            return failure

        data = request.data
        errors = []

        def mutate(label):
            payload = {
                'kind': label['kind'],
                'class_index': (data.get('class_index') if 'class_index' in data
                                else label.get('class_index')),
                'geometry': data.get('geometry', label['geometry']),
                'radius_m': data.get('radius_m', label.get('radius_m')),
                'hard_negative': (data.get('hard_negative') if 'hard_negative' in data
                                  else label.get('hard_negative', False)),
            }
            try:
                # Se reconstruye entera en vez de parchear campo a campo: así la geometría nueva
                # pasa por la misma validación y la misma simplificación (FR-015) que al crearla.
                rebuilt = models.make_label(dataset, payload, label['order'],
                                            label_id=label['id'],
                                            source=label.get('source', models.SOURCE_MANUAL))
            except models.ValidationError as exc:
                errors.append(exc)
                return label
            rebuilt['created_at'] = label.get('created_at', rebuilt['created_at'])
            return rebuilt

        updated = store.update_label(dataset_id, str(task.id), label_id, mutate)
        if errors:
            return validation_error(errors[0])
        if updated is None:
            raise exceptions.NotFound()
        return Response(updated)

    def delete(self, request, dataset_id=None, pk=None, label_id=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=True)
        if failure is not None:
            return failure
        if not store.delete_label(dataset_id, str(task.id), label_id):
            raise exceptions.NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Selección asistida (`010`) ----------------------------------------------------------

def _parse_points(raw):
    """`[(lng, lat), ...]` a partir del cuerpo de la petición.

    Un punto es un clic (US1) y varios son un arrastre (US2): el backend no distingue los dos
    gestos, y por eso no hay dos endpoints.
    """
    if not isinstance(raw, (list, tuple)) or not raw:
        raise models.ValidationError(_('Hace falta al menos un punto.'), ERR_BAD_POINTS)

    points = []
    for item in raw:
        if isinstance(item, dict):
            lng = item.get('lon', item.get('lng', item.get('longitude')))
            lat = item.get('lat', item.get('latitude'))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            lng, lat = item[0], item[1]
        else:
            raise models.ValidationError(_('Cada punto debe llevar latitud y longitud.'),
                                        ERR_BAD_POINTS)
        try:
            lng, lat = float(lng), float(lat)
        except (TypeError, ValueError):
            raise models.ValidationError(_('Las coordenadas deben ser números.'), ERR_BAD_POINTS)
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            raise models.ValidationError(_('Coordenadas fuera del rango geográfico.'),
                                         ERR_BAD_POINTS)
        points.append((lng, lat))
    return points


def _assist_settings(dataset, data):
    """Los tres ajustes efectivos: lo que venga en la petición, y si no, lo del dataset.

    Aceptarlos en la petición **y** guardarlos en el dataset no es duplicar: permite previsualizar
    con un valor antes de decidir quedárselo, que es como se usa un control deslizante.
    """
    stored = dataset.get('assist') or models.default_assist()
    return models.normalize_assist({
        'granularity': data.get('granularity'),
        'tolerance': data.get('tolerance'),
        'elevation_weight': data.get('elevation_weight'),
    }, stored)


def assist_unavailable(exc):
    """Respuesta cuando `scikit-image` no está disponible.

    Es el único punto del plugin que depende de una dependencia instalada por el framework, y puede
    faltar de verdad: un arranque en el que `check_requirements()` no llegó a correr, o un
    `site-packages` a medio instalar. Lo que **no** puede pasar es que eso tumbe el etiquetado a
    mano, que no la necesita para nada (FR-026, Principio III). Sale como `409` con un código propio
    para que la interfaz pueda esconder la herramienta en vez de enseñar un error genérico.
    """
    return error(
        _('La selección asistida no está disponible: falta una dependencia del plugin (%(detail)s). '
          'El etiquetado a mano sigue funcionando.') % {'detail': exc},
        ERR_ASSIST_UNAVAILABLE, status.HTTP_409_CONFLICT)


def _provider(task, dataset, settings):
    return regions.CellProvider(
        str(task.id),
        dataset['resolution_cm_px'],
        granularity=settings['granularity'],
        elevation_weight=settings['elevation_weight'],
        elevation_source=dataset.get('elevation_source', models.DEFAULT_ELEVATION_SOURCE))


class RegionSelect(_LabelViewBase):
    """`POST datasets/<id>/tasks/<task>/regions` — la geometría de unas regiones del terreno.

    **No crea etiquetas.** Devuelve geometría y el cliente decide si la guarda, por el endpoint de
    etiquetas que ya existía. Separarlo mantiene toda la validación de etiquetas en un solo sitio y
    permite que el arrastre de US2 previsualice en vivo y escriba una sola vez al soltar.
    """

    def post(self, request, dataset_id=None, pk=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=True)
        if failure is not None:
            return failure

        data = request.data
        try:
            points = _parse_points(data.get('points'))
            settings = _assist_settings(dataset, data)
        except models.ValidationError as exc:
            return validation_error(exc)

        try:
            with _provider(task, dataset, settings) as provider:
                selection = provider.select(points, tolerance=settings['tolerance'])
                geometry = provider.geometry(selection.regions)
                payload = {
                    'geometry': geometry,
                    'region_count': len(selection.regions),
                    'elevation_source': provider.elevation_source,
                    'band_count': provider.band_count,
                    'truncated': selection.truncated,
                    'prepared_cells': provider.prepared_cells,
                }
        except regions.NoOrthophoto:
            return error(_('La tarea «%(name)s» no tiene ortofoto.') % {'name': task.name},
                         ERR_NO_ORTHOPHOTO, status.HTTP_409_CONFLICT)
        except ImportError as exc:
            return assist_unavailable(exc)

        if geometry is None:
            # Pinchar fuera de la huella del vuelo **no es un error** (FR-025). Devolverlo como 400
            # obligaría a la interfaz a enseñar una alerta roja por algo que el usuario hace cada
            # dos por tres sin equivocarse en nada.
            payload.update({
                'reason': 'no_data',
                'message': _('Ese punto está fuera de la zona cubierta por el vuelo.'),
            })

        return Response(payload)


class RegionStatus(_LabelViewBase):
    """`GET .../regions/status` — qué parte del encuadre ya está preparada (FR-024).

    Existe para poder anunciar la espera **antes** de que ocurra. Sin esto, el primer clic sobre una
    zona nueva deja el cursor colgado un segundo sin explicación, y un segundo sin explicación se
    interpreta como que la herramienta no ha registrado el clic.

    Es la **única** ruta de esta feature que mira el encuadre. `POST regions` no lo hace ni puede
    hacerlo: si la respuesta dependiera de la vista, FR-008 se caería.
    """

    def get(self, request, dataset_id=None, pk=None):
        task, dataset, failure = self.resolve(request, dataset_id, pk, write=False)
        if failure is not None:
            return failure

        try:
            bounds = _parse_bounds(request.query_params.get('bounds'))
            settings = _assist_settings(dataset, request.query_params)
        except models.ValidationError as exc:
            return validation_error(exc)

        try:
            with _provider(task, dataset, settings) as provider:
                grid = provider.grid
                minx, miny = grid.lnglat_to_xy(bounds[0], bounds[1])
                maxx, maxy = grid.lnglat_to_xy(bounds[2], bounds[3])
                cells = grid.cells_for_bounds(min(minx, maxx), min(miny, maxy),
                                              max(minx, maxx), max(miny, maxy))
                ready = sum(1 for row, col in cells if provider.is_ready(row, col))
                payload = {
                    'cells_total': len(cells),
                    'cells_ready': ready,
                    'estimated_seconds': round((len(cells) - ready) * regions.SECONDS_PER_CELL, 1),
                    'elevation_source': provider.elevation_source,
                }
        except regions.NoOrthophoto:
            return error(_('La tarea «%(name)s» no tiene ortofoto.') % {'name': task.name},
                         ERR_NO_ORTHOPHOTO, status.HTTP_409_CONFLICT)

        return Response(payload)


def _parse_bounds(raw):
    """`minLon,minLat,maxLon,maxLat` a cuatro flotantes."""
    parts = str(raw or '').split(',')
    if len(parts) != 4:
        raise models.ValidationError(
            _('`bounds` debe ser minLon,minLat,maxLon,maxLat.'), ERR_BAD_BOUNDS)
    try:
        values = [float(p) for p in parts]
    except (TypeError, ValueError):
        raise models.ValidationError(_('`bounds` debe llevar cuatro números.'), ERR_BAD_BOUNDS)
    if not (-180 <= values[0] <= 180 and -180 <= values[2] <= 180
            and -90 <= values[1] <= 90 and -90 <= values[3] <= 90):
        raise models.ValidationError(_('`bounds` cae fuera del rango geográfico.'), ERR_BAD_BOUNDS)
    return values


# --- Exportación -------------------------------------------------------------------------

def run_export_async(dataset_id, export_id, progress_callback=None, should_cancel=None):
    """Función de worker: construye el paquete y cierra su entrada en el índice.

    IMPORTANTE — debe ser **self-contained**: WebODM la ejecuta reejecutando su código fuente en un
    namespace vacío (`app/plugins/worker.py: eval_async` hace `eval(compile(source), ns, ns)` con
    `ns = {}`), sin los globals de este módulo. Por eso todos los imports van **dentro** y son
    **absolutos**, y todo lo auxiliar se alcanza a través del módulo importado — nunca por nombre
    libre ni con imports relativos (`from . import ...`), que fallarían con
    `KeyError: "'__name__' not in globals"`. Mismo patrón que `coreplugins/road/compute.py`.

    `rasterio` y `numpy` no se importan aquí: los importa `export.py`, y llegan cargados con él.
    Traerlos a este cuerpo solo alargaría la función sin cambiar nada.

    La entrada del índice se cierra **siempre**, salga por donde salga: sin eso una exportación
    fallida se quedaría en `running` para siempre, porque el error solo vive en el resultado de
    Celery y ese se pierde al recargar la página.
    """
    import datetime
    from coreplugins.training import export, store

    def _finish(mutation):
        def mutate(entry):
            entry.update(mutation)
            entry['updated_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
            return entry
        store.update_export(dataset_id, export_id, mutate)

    def _report(percent):
        if progress_callback is not None:
            # El worker espera `(status, porcentaje)`; `build_package` solo conoce el porcentaje.
            progress_callback('exporting', percent)
        _finish({'progress': percent, 'status': 'running'})

    dataset = store.get_dataset(dataset_id)
    if dataset is None:
        _finish({'status': 'failed', 'error': 'El dataset ya no existe.', 'celery_task_id': None})
        return {'error': 'dataset_missing'}

    try:
        result = export.build_package(dataset, export_id=export_id,
                                      progress_callback=_report, should_cancel=should_cancel)
    except export.Cancelled:
        # Un paquete a medias no se conserva: sería un zip truncado indistinguible de uno bueno.
        export.delete_package(dataset_id, export_id)
        _finish({'status': 'canceled', 'progress': None, 'celery_task_id': None})
        return {'canceled': True}
    except export.ExportError as e:
        # Lleva `code` porque no es un fallo del sistema sino algo que el usuario puede arreglar, y
        # el frontend decide por el código qué le sugiere hacer (`contracts/rest-api.md`).
        export.delete_package(dataset_id, export_id)
        _finish({'status': 'failed', 'progress': None, 'error': e.message,
                 'error_code': e.code, 'celery_task_id': None})
        return {'error': e.message, 'code': e.code}
    except Exception as e:
        export.delete_package(dataset_id, export_id)
        _finish({'status': 'failed', 'progress': None, 'error': str(e), 'error_code': None,
                 'celery_task_id': None})
        return {'error': str(e)}

    _finish({'status': 'completed', 'progress': 100, 'error': None, 'celery_task_id': None,
             'tile_count': result['tile_count'], 'size_bytes': result['size_bytes'],
             'train_tiles': result['train_tiles'], 'val_tiles': result['val_tiles']})
    return {'export_id': export_id, 'tile_count': result['tile_count']}


def _abort_celery_task(celery_task_id):
    from worker.tasks import TestSafeAsyncResult
    res = TestSafeAsyncResult(celery_task_id)
    if not res.ready():
        res.backend.store_result(celery_task_id, result=None, state="ABORTED", traceback=None)


class ExportList(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, dataset_id):
        _get_visible_dataset(request, dataset_id)
        return Response(store.list_exports(dataset_id))

    def post(self, request, dataset_id):
        dataset = _get_visible_dataset(request, dataset_id)

        if not store.available_tasks(dataset):
            return error(_('Ninguna tarea de este dataset está disponible.'),
                         ERR_NO_AVAILABLE_TASKS)
        if not store.has_any_label(dataset_id):
            return error(_('El dataset no tiene ninguna etiqueta.'), ERR_NOTHING_TO_EXPORT)

        export_id = str(uuid.uuid4())
        entry = {
            'id': export_id,
            'dataset_id': dataset_id,
            'status': 'running',
            'progress': 0,
            'error': None,
            'tile_count': 0,
            'size_bytes': 0,
            'created_at': models.now_iso(),
            'updated_at': models.now_iso(),
            'created_by': request.user.id,
            'celery_task_id': None,
        }
        store.upsert_export(dataset_id, entry)

        try:
            async_result = run_function_async(
                run_export_async, dataset_id, export_id,
                with_progress=True, with_cancel=True)
        except Exception:
            # Sin esto, un fallo al lanzar dejaría una exportación en `running` para siempre.
            store.remove_export(dataset_id, export_id)
            raise

        # Bajo `CELERY_TASK_ALWAYS_EAGER` (tests) el trabajo ya terminó y escribió su estado final
        # antes de volver aquí: anotar el id entonces dejaría un `celery_task_id` en una
        # exportación completada, que el botón de cancelar leería como «todavía se puede parar».
        store.update_export(dataset_id, export_id, lambda e: dict(
            e, celery_task_id=async_result.task_id if e.get('status') == 'running'
            else e.get('celery_task_id')))

        finished = store.get_export(dataset_id, export_id)
        # «No hay nada que exportar», «no hay nada revisado» y «lo revisado no supera los umbrales»
        # son tres problemas distintos con soluciones distintas: responder lo mismo a todos dejaría
        # al usuario sin saber si le falta etiquetar, marcar revisado o bajar el umbral
        # (`contracts/rest-api.md`).
        if finished and finished.get('error_code') == 'no_reviewed_tiles':
            store.remove_export(dataset_id, export_id)
            return error(finished.get('error'), ERR_NO_REVIEWED_TILES, tile_count=0)
        if finished and finished.get('status') == 'completed' and not finished.get('tile_count'):
            store.remove_export(dataset_id, export_id)
            export_module.delete_package(dataset_id, export_id)
            return error(_('Todas las teselas quedaron descartadas por los umbrales del dataset.'),
                         ERR_ALL_TILES_FILTERED, tile_count=0)

        return Response({'export_id': export_id, 'celery_task_id': async_result.task_id},
                        status=status.HTTP_202_ACCEPTED)


class ExportDetail(APIView):
    permission_classes = (IsAuthenticated, )

    def delete(self, request, dataset_id, export_id):
        """Cancela si corre; borra el paquete si terminó."""
        _get_visible_dataset(request, dataset_id)
        entry = store.get_export(dataset_id, export_id)
        if entry is None:
            raise exceptions.NotFound()

        if entry.get('status') == 'running' and entry.get('celery_task_id'):
            _abort_celery_task(entry['celery_task_id'])

        export_module.delete_package(dataset_id, export_id)
        store.remove_export(dataset_id, export_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExportDownload(APIView):
    permission_classes = (IsAuthenticated, )

    def get(self, request, dataset_id, export_id):
        dataset = _get_visible_dataset(request, dataset_id)
        entry = store.get_export(dataset_id, export_id)
        if entry is None:
            raise exceptions.NotFound()
        if entry.get('status') != 'completed':
            return error(_('La exportación todavía no ha terminado.'), ERR_EXPORT_NOT_READY,
                         status.HTTP_409_CONFLICT, status_value=entry.get('status'))

        path = export_module.package_path(dataset_id, export_id)
        if not os.path.isfile(path):
            raise exceptions.NotFound()

        # El fichero ya está construido en disco: la petición solo lo sirve, nunca lo genera
        # (FR-030). Mismo patrón que la exportación de `road` (`road/api.py:598-602`).
        with open(path, 'rb') as f:
            response = HttpResponse(f.read(), content_type='application/zip')
        response['Content-Disposition'] = 'attachment; filename="{}"'.format(
            _package_filename(dataset, entry))
        return response


def _package_filename(dataset, entry):
    """`<nombre-del-dataset>-<fecha>.zip` (`contracts/dataset-package.md`)."""
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in dataset['name']).strip('-')
    return '{}-{}.zip'.format(safe or 'dataset', (entry.get('created_at') or '')[:10])
