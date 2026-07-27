"""Selección de modelo de elevación, densificación y muestreo (`research.md` D3, D4, D10, D11,
D12; `data-model.md`, entidad `ElevationSampling`).

Las cotas se reportan tal como las entrega el ráster, sin conversión de datum vertical
(FR-018): `vertex_z` nunca se convierte de unidad. Las magnitudes agregadas
(`surface_length`, `elevation_gain`) sí viajan siempre en metros (`data-model.md`), asumiendo
—como es habitual en un DSM/DTM de un mismo archivo— que la unidad vertical coincide con la
unidad lineal del CRS horizontal del ráster.
"""

import os
import math
import datetime

import rasterio
import rasterio.warp
from rasterio.crs import CRS
from app.geoutils import get_rasterio_to_meters_factor

from . import geometry

MIN_STEP = 0.25
MAX_STEP = 10.0
MAX_SAMPLES = 20000

ASSET_BY_MODEL = {'dsm': 'dsm.tif', 'dtm': 'dtm.tif'}


class IncompleteCoverage(Exception):
    """Cobertura de elevación incompleta a lo largo del trazado (FR-021, FR-022)."""

    def __init__(self, missing_ranges, missing_samples, total_samples):
        self.missing_ranges = missing_ranges
        self.missing_samples = missing_samples
        self.total_samples = total_samples
        super().__init__('incomplete_coverage')


class LimitExceeded(Exception):
    """Tope de vértices o de puntos densificados superado (FR-023)."""
    pass


def _now():
    return datetime.datetime.utcnow().isoformat() + 'Z'


def available_models(task):
    """Modelos de elevación presentes en la tarea, sin tocar el disco (`research.md` D10)."""
    models = []
    if task.dsm_extent is not None:
        models.append('dsm')
    if task.dtm_extent is not None:
        models.append('dtm')
    return models


def default_model(task):
    models = available_models(task)
    if 'dsm' in models:
        return 'dsm'
    return models[0] if models else None


def dem_path(task, model):
    return os.path.abspath(task.get_asset_download_path(ASSET_BY_MODEL[model]))


def is_stale(task, elevation_block):
    """Estado derivado `stale`: compara `source_mtime` con el `mtime` actual del DEM
    (FR-020, `research.md` D12). Un reproceso reescribe el archivo, así que la marca cambia
    siempre que el dato cambia."""
    try:
        path = dem_path(task, elevation_block['model'])
        return os.stat(path).st_mtime != elevation_block.get('source_mtime')
    except (OSError, KeyError):
        return True


def _to_meters_factor(ds):
    return get_rasterio_to_meters_factor(ds)


def _vertical_unit_label(ds):
    try:
        return ds.crs.linear_units or 'metre'
    except Exception:
        return 'metre'


def capabilities(task):
    """Respuesta de `GET task/<pk>/elevation` (`contracts/rest-api.md`)."""
    models = available_models(task)
    if not models:
        return {
            'available': [], 'default_model': None, 'resolution': None,
            'default_step': None, 'step_range': None,
            'max_vertices': geometry.MAX_VERTICES, 'max_samples': MAX_SAMPLES,
            'vertical_unit': None,
        }

    model = default_model(task)
    with rasterio.open(dem_path(task, model)) as ds:
        unit_factor = _to_meters_factor(ds)
        resolution_m = min(abs(ds.res[0]), abs(ds.res[1])) * unit_factor
        vertical_unit = _vertical_unit_label(ds)

    return {
        'available': models,
        'default_model': model,
        'resolution': resolution_m,
        'default_step': max(resolution_m, MIN_STEP),
        'step_range': [resolution_m, MAX_STEP],
        'max_vertices': geometry.MAX_VERTICES,
        'max_samples': MAX_SAMPLES,
        'vertical_unit': vertical_unit,
    }


def validate_step(step, resolution_m):
    """Devuelve `(step, error)`. `step` es `None` -> paso por defecto (`data-model.md`)."""
    if step is None:
        return max(resolution_m, MIN_STEP), None
    try:
        step = float(step)
    except (TypeError, ValueError):
        return None, 'invalid_step'
    if not (resolution_m <= step <= MAX_STEP):
        return None, 'step_out_of_range'
    return step, None


def _densify_projected(coords, step):
    """`coords`: lista de `(x, y)` proyectadas. `step`: paso en esas mismas unidades.

    Devuelve una lista de `(x, y, distancia_acumulada)` que conserva cada vértice original
    como ancla exacta y añade puntos intermedios cada `step` (`research.md` D3, D4).
    """
    out = [(coords[0][0], coords[0][1], 0.0)]
    cum = 0.0
    for i in range(1, len(coords)):
        x0, y0 = coords[i - 1]
        x1, y1 = coords[i]
        seg_len = math.hypot(x1 - x0, y1 - y0)
        if seg_len > 0:
            n_steps = int(seg_len // step)
            for k in range(1, n_steps + 1):
                d_local = k * step
                if d_local >= seg_len:
                    break
                t = d_local / seg_len
                out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, cum + d_local))
        cum += seg_len
        out.append((x1, y1, cum))
    return out


def _contiguous_ranges(indices):
    ranges = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            ranges.append((start, prev))
            start = prev = i
    ranges.append((start, prev))
    return ranges


def _sample(ds, xy, nodata):
    """Muestrea `ds` en `xy` (coordenadas del CRS del ráster). `None` = sin dato (FR-021)."""
    zs = []
    for v in ds.sample(xy):
        z = float(v[0])
        if (nodata is not None and z == nodata) or math.isnan(z):
            zs.append(None)
        else:
            zs.append(z)
    return zs


def sample_polyline(task, vertices, model, step=None):
    """Muestrea `vertices` (EPSG:4326) sobre el DEM `model` de la tarea.

    Devuelve el dict `ElevationSampling` (sin `stale`, que es un estado derivado que calcula
    el llamador con `task` a mano). Lanza `ValueError` con `error`/`reason` en un diccionario
    si el paso es inválido, `LimitExceeded` si se supera `MAX_SAMPLES`, o `IncompleteCoverage`
    si falta dato en algún tramo (FR-021, FR-022; nunca se rellena ni interpola).
    """
    path = dem_path(task, model)
    with rasterio.open(path) as ds:
        unit_factor = _to_meters_factor(ds)
        resolution_m = min(abs(ds.res[0]), abs(ds.res[1])) * unit_factor
        vertical_unit = _vertical_unit_label(ds)
        nodata = ds.nodata

        step_m, err = validate_step(step, resolution_m)
        if err:
            raise ValueError(err)
        step_native = step_m / unit_factor

        proj = geometry.project_vertices(vertices, ds.crs)
        densified = _densify_projected(proj, step_native)

        if len(densified) > MAX_SAMPLES:
            raise LimitExceeded()

        xy_dense = [(p[0], p[1]) for p in densified]
        zs_raw = _sample(ds, xy_dense, nodata)

        missing_idx = [i for i, z in enumerate(zs_raw) if z is None]
        if missing_idx:
            total_native = densified[-1][2] or 1.0
            missing_ranges = [
                [densified[a][2] / total_native, densified[b][2] / total_native]
                for a, b in _contiguous_ranges(missing_idx)
            ]
            raise IncompleteCoverage(missing_ranges, len(missing_idx), len(densified))

        vertex_z = _sample(ds, proj, nodata)
        plan_length = geometry.polyline_length(proj, unit_factor)

        surface_length = 0.0
        elevation_gain = 0.0
        prev = None
        for (x, y, cum), z in zip(densified, zs_raw):
            z_m = z * unit_factor
            if prev is not None:
                _px, _py, pcum, pz_m = prev
                horiz_m = (cum - pcum) * unit_factor
                surface_length += math.hypot(horiz_m, z_m - pz_m)
                elevation_gain += abs(z_m - pz_m)
            prev = (x, y, cum, z_m)

        source_mtime = os.stat(path).st_mtime

    return {
        'model': model,
        'vertex_z': vertex_z,
        'step': step_m,
        'surface_length': surface_length,
        'elevation_gain': elevation_gain,
        'sample_count': len(densified),
        'vertical_unit': vertical_unit,
        'sampled_at': _now(),
        'source_mtime': source_mtime,
        # No es parte de `ElevationSampling` (`data-model.md`): plan_length en el mismo CRS
        # que el DEM, para que ambas longitudes sean coherentes entre sí (`research.md` D11).
        # El llamador lo extrae con `.pop('plan_length')` antes de persistir el bloque.
        'plan_length': plan_length,
    }


def densified_coordinates_for_polyline(task, polyline, step=None):
    """`[[lng, lat, z], ...]` a lo largo de una polilínea `draped` ya persistida, densificada
    al `step` indicado (el suyo propio si se omite). Recalculada bajo demanda, nunca persistida
    (`research.md` D5). Usada por la exportación (FR-034) y por `get_densified` del contrato
    para otros plugins (FR-038). Lanza `IncompleteCoverage` si el DEM ya no cubre el trazado
    (p. ej. un reproceso que reemplazó el DEM) — el llamador decide cómo degradar. Lanza
    `LimitExceeded` si el `step` pedido produciría más de `MAX_SAMPLES` puntos (FR-023), y
    `ValueError` si el `step` está fuera de rango.
    """
    elevation_block = polyline['elevation']
    model = elevation_block['model']
    step = step if step is not None else elevation_block['step']

    path = dem_path(task, model)
    with rasterio.open(path) as ds:
        unit_factor = _to_meters_factor(ds)
        resolution_m = min(abs(ds.res[0]), abs(ds.res[1])) * unit_factor
        nodata = ds.nodata

        # El `step` puede venir de fuera sin pasar por `sample_polyline` (query param de
        # `GET .../densified`, o el contrato de otro plugin): un 0 reventaba en la división
        # entera de `_densify_projected`, y un valor negativo o desmedido devolvía la línea
        # sin densificar como si fuera un resultado válido. También cubre el `step` persistido
        # cuando un reproceso ha cambiado la resolución del DEM.
        step_m, err = validate_step(step, resolution_m)
        if err:
            raise ValueError(err)

        proj = geometry.project_vertices(polyline['vertices'], ds.crs)
        densified = _densify_projected(proj, step_m / unit_factor)

        if len(densified) > MAX_SAMPLES:
            raise LimitExceeded()

        xy = [(p[0], p[1]) for p in densified]
        zs = _sample(ds, xy, nodata)

        missing_idx = [i for i, z in enumerate(zs) if z is None]
        if missing_idx:
            total_native = densified[-1][2] or 1.0
            missing_ranges = [
                [densified[a][2] / total_native, densified[b][2] / total_native]
                for a, b in _contiguous_ranges(missing_idx)
            ]
            raise IncompleteCoverage(missing_ranges, len(missing_idx), len(densified))

        xs = [p[0] for p in densified]
        ys = [p[1] for p in densified]
        lons, lats = rasterio.warp.transform(ds.crs, CRS.from_epsg(4326), xs, ys)

    return [[lons[i], lats[i], zs[i]] for i in range(len(densified))]
