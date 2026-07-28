"""Modelos de elevación de la tarea: disponibilidad, rutas, resolución y obsolescencia.

Cubre `research.md` D1 (de dónde sale el ráster, original o realineado), D7 (unidades) y D12
(obsolescencia), más los defectos y rangos de parámetros de `data-model.md` §4.

La disponibilidad se resuelve por las columnas `dsm_extent` / `dtm_extent` de la base de datos,
**sin tocar el disco**: preguntar por un archivo que puede estar en un volumen remoto para dibujar
un desplegable es un coste que no hace falta pagar.
"""

import os

import rasterio
from django.utils.translation import gettext_lazy as _

from app.geoutils import get_rasterio_to_meters_factor

ASSET_BY_MODEL = {'dsm': 'dsm.tif', 'dtm': 'dtm.tif'}

VARIANT_ORIGINAL = 'original'
VARIANT_REALIGNED = 'realigned'

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

# `data-model.md` §4. El defecto de `sample_step` no está aquí porque depende de la resolución del
# DEM: se resuelve en `defaults_for()`.
DEFAULTS = {
    'segment_length': 5.0,
    'search_half_width': 10.0,
    'break_threshold': 15.0,
    'min_consecutive_samples': 3,
}
COLOR_THRESHOLDS_DEFAULT = [8.0, 12.0]

RANGES = {
    'segment_length': (0.5, 100.0),
    'search_half_width': (1.0, 50.0),
    'sample_step': (None, 5.0),          # el mínimo es la resolución del DEM
    'break_threshold': (2.0, 200.0),
    'min_consecutive_samples': (1, 20),
}

MIN_SAMPLE_STEP = 0.1


class NoElevationModel(Exception):
    """La tarea no tiene DSM ni DTM (`400 no_elevation_model`)."""
    pass


class UnavailableVariant(Exception):
    """Se pidió una variante que esta tarea no ofrece (`400 unavailable_variant`)."""
    pass


def available_models(task):
    """Modelos de elevación presentes en la tarea, sin tocar el disco."""
    models = []
    if task.dsm_extent is not None:
        models.append('dsm')
    if task.dtm_extent is not None:
        models.append('dtm')
    return models


def default_model(task):
    """DTM si está, DSM si no.

    Al revés que en `annotations`, y a propósito: el ancho de un camino se mide sobre el terreno.
    Un DSM incluye la vegetación del borde y los vehículos aparcados, que son justo los quiebres
    falsos que la detección de bordes confundiría con la calzada.
    """
    models = available_models(task)
    if 'dtm' in models:
        return 'dtm'
    return models[0] if models else None


def original_path(task, model):
    return os.path.abspath(task.get_asset_download_path(ASSET_BY_MODEL[model]))


def corrected_rasters(task_id):
    """Rásteres corregidos que ofrece `realign` para la tarea, o `{}`.

    Se habla con el plugin hermano por el framework, nunca importando su paquete: es lo que
    permite degradar con elegancia si está ausente, deshabilitado o expone un contrato mayor del
    que sabemos leer (`contracts/consumed-contracts.md` §2).
    """
    try:
        from app.plugins.functions import get_plugin_by_name
        plugin = get_plugin_by_name('realign')
        if plugin is None:
            return {}
        version = getattr(plugin, 'contract_version', None)
        if version is None or version() > 1:
            return {}
        return plugin.corrected_rasters(task_id) or {}
    except Exception:
        # Un fallo hablando con otro plugin no puede tumbar el análisis: se degrada a originales.
        return {}


def available_variants(task, model):
    """Variantes del modelo `model` en esta tarea: siempre `original`, más `realigned` si la hay."""
    variants = [VARIANT_ORIGINAL]
    if model in corrected_rasters(task.id):
        variants.append(VARIANT_REALIGNED)
    return variants


def dem_path(task, model, variant=VARIANT_ORIGINAL):
    """Ruta del ráster a muestrear. Lanza `UnavailableVariant` si se pide una que no existe."""
    if variant == VARIANT_REALIGNED:
        corrected = corrected_rasters(task.id)
        if model not in corrected:
            raise UnavailableVariant(model)
        return corrected[model]
    return original_path(task, model)


def _vertical_unit_label(ds):
    try:
        return ds.crs.linear_units or 'metre'
    except Exception:
        return 'metre'


def describe(task, model, variant=VARIANT_ORIGINAL):
    """Metadatos del ráster elegido: resolución en metros, factor a metros y unidad vertical.

    Es la única función del módulo que abre el archivo.
    """
    path = dem_path(task, model, variant)
    with rasterio.open(path) as ds:
        unit_factor = get_rasterio_to_meters_factor(ds)
        resolution = min(abs(ds.res[0]), abs(ds.res[1])) * unit_factor
        return {
            'path': path,
            'resolution': resolution,
            'unit_factor': unit_factor,
            'vertical_unit': _vertical_unit_label(ds),
            'crs': ds.crs,
            'nodata': ds.nodata,
        }


def source_mtime(task, model, variant=VARIANT_ORIGINAL):
    try:
        return os.stat(dem_path(task, model, variant)).st_mtime
    except (OSError, UnavailableVariant, KeyError):
        return None


def is_stale(task, analysis):
    """Estado derivado `stale` (`research.md` D12): el DEM cambió bajo los pies del análisis.

    Un reproceso de la tarea reescribe el archivo, así que el `mtime` cambia siempre que cambia el
    dato. Un DEM ausente o ilegible cuenta como obsoleto.
    """
    try:
        current = os.stat(dem_path(task, analysis['model'],
                                   analysis.get('variant', VARIANT_ORIGINAL))).st_mtime
    except (OSError, UnavailableVariant, KeyError, TypeError):
        return True
    return current != analysis.get('source_mtime')


def defaults_for(resolution):
    """Parámetros por defecto para un DEM de resolución `resolution` (metros)."""
    defaults = dict(DEFAULTS)
    defaults['sample_step'] = max(resolution, MIN_SAMPLE_STEP)
    defaults['color_thresholds'] = list(COLOR_THRESHOLDS_DEFAULT)
    return defaults


def ranges_for(resolution):
    """Rangos admitidos, con el mínimo de `sample_step` acotado por la resolución del DEM.

    Muestrear más fino que el píxel inventa detalle que no existe, así que el suelo del rango no
    es una constante sino una propiedad del ráster.
    """
    ranges = {k: list(v) for k, v in RANGES.items()}
    ranges['sample_step'][0] = resolution
    return ranges


def validate_params(params, resolution):
    """Valida y completa los parámetros de cálculo (`data-model.md` §4, FR-042).

    Devuelve `(params_completos, error)`. `error` es un mensaje ya redactado con el rango
    admitido: un "parámetro inválido" a secas obliga al usuario a adivinar cuál y por qué.
    """
    params = dict(params or {})
    resolved = defaults_for(resolution)
    ranges = ranges_for(resolution)

    for key in ('segment_length', 'search_half_width', 'sample_step', 'break_threshold'):
        if params.get(key) is None:
            continue
        try:
            value = float(params[key])
        except (TypeError, ValueError):
            return None, _('%(key)s debe ser un número.') % {'key': key}
        low, high = ranges[key]
        if not (low <= value <= high):
            return None, _('%(key)s debe estar entre %(low)s y %(high)s.') % {
                'key': key, 'low': round(low, 4), 'high': high}
        resolved[key] = value

    if params.get('min_consecutive_samples') is not None:
        try:
            value = int(params['min_consecutive_samples'])
        except (TypeError, ValueError):
            return None, _('min_consecutive_samples debe ser un número entero.')
        low, high = ranges['min_consecutive_samples']
        if not (low <= value <= high):
            return None, _('min_consecutive_samples debe estar entre %(low)s y %(high)s.') % {
                'low': low, 'high': high}
        resolved['min_consecutive_samples'] = value

    resolved.pop('color_thresholds', None)

    # Coherencia entre parámetros: un tramo más corto que el paso de muestreo puede quedarse sin
    # ninguna muestra, y entonces no hay pendiente que ajustar.
    if resolved['segment_length'] < resolved['sample_step']:
        return None, _('segment_length (%(seg)s) no puede ser menor que sample_step (%(step)s).') % {
            'seg': resolved['segment_length'], 'step': resolved['sample_step']}

    return resolved, None


def validate_color_thresholds(value):
    """Valida `[warn, alert]` en % (`data-model.md` §4). Devuelve `(valor, error)`."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None, _('color_thresholds debe ser una lista de dos números.')
    try:
        warn, alert = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None, _('color_thresholds debe ser una lista de dos números.')
    if not (0.0 < warn < alert <= 100.0):
        return None, _('color_thresholds debe cumplir 0 < aviso < alerta <= 100.')
    return [warn, alert], None
