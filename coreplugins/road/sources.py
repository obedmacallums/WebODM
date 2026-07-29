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

# Criterios de detección de borde (`006` FR-001). `break` es el original de D3 y el defecto:
# debe producir resultados idénticos a los de antes de existir esta elección (FR-002).
EDGE_MODE_BREAK = 'break'
EDGE_MODE_SURFACE = 'surface'
EDGE_MODES = (EDGE_MODE_BREAK, EDGE_MODE_SURFACE)

# Cómo se resume el ancho cuando el tramo se mide en varias transversales. `median` es el defecto
# y elige una sección **real** —la de ancho mediano— reportándola entera, así que los bordes que
# se dibujan están sobre el terreno. `mean` promedia los dos lados por separado: es sensible a un
# solo bache, y sus puntos de borde son sintéticos, pero permite comparar los dos criterios sobre
# el mismo DEM sin volver a volar.
WIDTH_AGGREGATION_MEDIAN = 'median'
WIDTH_AGGREGATION_MEAN = 'mean'
WIDTH_AGGREGATIONS = (WIDTH_AGGREGATION_MEDIAN, WIDTH_AGGREGATION_MEAN)

# `data-model.md` §4. El defecto de `sample_step` no está aquí porque depende de la resolución del
# DEM: se resuelve en `defaults_for()`.
DEFAULTS = {
    'segment_length': 5.0,
    'search_half_width': 10.0,
    'break_threshold': 15.0,
    'min_consecutive_samples': 3,
    'edge_mode': EDGE_MODE_BREAK,
    # Solo lo usa el modo `surface`, pero se acepta y persiste también en `break` para que cambiar
    # de modo sobre un análisis existente no pierda el valor ya ajustado (`006` data-model §4).
    'surface_tolerance': 0.06,
    # 0 = pasada de coherencia desactivada: es lo que garantiza que ningún análisis existente
    # cambie de resultado (`006` FR-012).
    'coherence_window': 0,
    # Ventana horizontal (m) de la mediana móvil que suaviza el perfil transversal antes de
    # detectar bordes. 0 = apagado, que es el comportamiento de siempre. Existe por los DTM
    # fotogramétricos sobre rodadura rugosa (caminos mineros): sus rachas de ruido superan el
    # filtro de `min_consecutive` y producen bordes falsos pegados al eje.
    'smooth_window': 0.0,
    # Separación (m) entre transversales dentro de un tramo. 0 = una sola, en el punto medio, que
    # es como funcionó siempre. Con un valor positivo el ancho pasa de ser una muestra puntual a
    # una estadística del tramo: se mide varias veces y se reporta la sección de ancho mediano.
    # Va aparte de `segment_length` a propósito — acortar el tramo para medir el ancho más a
    # menudo degradaría la pendiente longitudinal, que se ajusta sobre la base del tramo.
    'cross_section_spacing': 0.0,
    'width_aggregation': WIDTH_AGGREGATION_MEDIAN,
}
COLOR_THRESHOLDS_DEFAULT = [8.0, 12.0]

# Umbrales del semáforo de ancho. No hay defecto fijo: se deducen del ancho medio del propio
# análisis (`derive_width_thresholds`), porque la escala de una calle y la de una rampa minera no
# se parecen. El mínimo sale a `WIDTH_ALERT_FACTOR` del ancho medio —un tramo que pierde una
# quinta parte de la calzada es lo que hay que ver de un vistazo— y el holgado, al ancho medio.
WIDTH_ALERT_FACTOR = 0.8
# Tope de validación: ni el muestreo puede alcanzar más de `2 * search_half_width` (2 x 50 m).
WIDTH_THRESHOLD_MAX = 100.0

RANGES = {
    'segment_length': (0.5, 100.0),
    'search_half_width': (1.0, 50.0),
    'sample_step': (None, 5.0),          # el mínimo es la resolución del DEM
    'break_threshold': (2.0, 200.0),
    'min_consecutive_samples': (1, 20),
    'surface_tolerance': (0.02, 0.50),
    'coherence_window': (0, 5),
    'smooth_window': (0.0, 5.0),
    'cross_section_spacing': (0.0, 20.0),
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

    for key in ('segment_length', 'search_half_width', 'sample_step', 'break_threshold',
                'surface_tolerance', 'smooth_window', 'cross_section_spacing'):
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

    for key in ('min_consecutive_samples', 'coherence_window'):
        if params.get(key) is None:
            continue
        try:
            value = int(params[key])
        except (TypeError, ValueError):
            return None, _('%(key)s debe ser un número entero.') % {'key': key}
        low, high = ranges[key]
        if not (low <= value <= high):
            return None, _('%(key)s debe estar entre %(low)s y %(high)s.') % {
                'key': key, 'low': low, 'high': high}
        resolved[key] = value

    # Enums, no rangos: el mensaje enumera los valores admitidos (`006` FR-004).
    for key, allowed in (('edge_mode', EDGE_MODES),
                         ('width_aggregation', WIDTH_AGGREGATIONS)):
        if params.get(key) is None:
            continue
        if params[key] not in allowed:
            return None, _('%(key)s debe ser uno de: %(modes)s.') % {
                'key': key, 'modes': ', '.join(allowed)}
        resolved[key] = params[key]

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


def validate_width_thresholds(value):
    """Valida `[mínimo, holgado]` en metros. Devuelve `(valor, error)`.

    Misma forma que `color_thresholds` —dos números ascendentes— y lectura inversa: el semáforo
    del ancho pinta de rojo por **debajo** del mínimo, porque en un camino quedarse corto de ancho
    es el problema. Sin tope superior fijo más allá del ancho máximo que el propio muestreo puede
    alcanzar (`2 * search_half_width`), redondeado al alza.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None, _('width_thresholds debe ser una lista de dos números.')
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None, _('width_thresholds debe ser una lista de dos números.')
    if not (0.0 < low < high <= WIDTH_THRESHOLD_MAX):
        return None, _('width_thresholds debe cumplir 0 < mínimo < holgado <= %(max)s.') % {
            'max': WIDTH_THRESHOLD_MAX}
    return [low, high], None


def derive_width_thresholds(mean_width):
    """Umbrales de ancho deducidos del ancho medio medido, o `None` si no hay ninguno.

    Una constante no puede servir a la vez a una calle de 6 m y a una rampa minera de 25: con
    umbrales de calle la mina sale toda verde y con umbrales de mina la calle sale toda roja, y en
    los dos casos el control nace inútil. Deducirlos del propio análisis lo deja centrado en su
    escala sea cual sea, y el usuario solo mueve el deslizador si su criterio difiere del ancho que
    el camino ya tiene.

    Se deducen en cada lectura y **no se guardan**: así un recálculo que cambie el ancho medio los
    vuelve a centrar, mientras que unos umbrales fijados a mano —esos sí guardados— mandan siempre.
    """
    if not mean_width or mean_width <= 0:
        return None
    return [round(WIDTH_ALERT_FACTOR * mean_width, 2), round(float(mean_width), 2)]
