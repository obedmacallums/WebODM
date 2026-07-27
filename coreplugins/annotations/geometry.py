"""Validación de vértices y cálculo de longitudes en un CRS proyectado (`research.md` D11).

Las coordenadas de una polilínea viajan siempre en EPSG:4326, orden ``[lng, lat]``
(`data-model.md`). Este módulo no depende de ningún ráster: la elección de a qué CRS
proyectar (el del DEM cuando la línea es sobre el terreno, o ``task.epsg``/UTM cuando es
plana) la resuelve quien llama, pasando el CRS de destino explícito.
"""

import math

import rasterio.warp
from rasterio.crs import CRS
from django.utils.translation import gettext_lazy as _

MIN_VERTICES = 2
MAX_VERTICES = 500


def validate_vertices(vertices):
    """Valida `vertices` como lista de `[lng, lat]` (FR-002, FR-023).

    Devuelve `(ok, error)`: `error` es `None` si `ok` es `True`.
    """
    if not isinstance(vertices, list) or len(vertices) < MIN_VERTICES:
        return False, _('Se necesitan al menos 2 vértices.')
    if len(vertices) > MAX_VERTICES:
        return False, _('No se admiten más de {} vértices.').format(MAX_VERTICES)

    parsed = []
    for v in vertices:
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            return False, _('Cada vértice debe ser un par [lng, lat].')
        try:
            lng, lat = float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return False, _('Las coordenadas de los vértices deben ser numéricas.')
        if not (-180.0 <= lng <= 180.0 and -90.0 <= lat <= 90.0):
            return False, _('Las coordenadas de los vértices están fuera de rango.')
        parsed.append((lng, lat))

    distinct = {(round(lng, 9), round(lat, 9)) for lng, lat in parsed}
    if len(distinct) < 2:
        return False, _('El trazado necesita al menos dos posiciones distintas.')

    return True, None


def utm_epsg_for(lng, lat):
    """EPSG de la zona UTM que contiene `(lng, lat)`."""
    zone = int(math.floor((lng + 180.0) / 6.0)) % 60 + 1
    return 32600 + zone if lat >= 0 else 32700 + zone


def resolve_crs(crs):
    """Normaliza `crs` (``None`` | EPSG entero | objeto `CRS`) a un `rasterio.crs.CRS`."""
    if crs is None:
        return None
    if isinstance(crs, CRS):
        return crs
    if isinstance(crs, int):
        return CRS.from_epsg(crs)
    return CRS.from_user_input(crs)


def project_vertices(vertices, crs=None):
    """Proyecta `[[lng, lat], ...]` (EPSG:4326) al CRS métrico `crs`.

    Si `crs` es `None`, usa el UTM de la zona del centroide del trazado (`research.md` D11).
    Devuelve una lista de tuplas `(x, y)` en las unidades nativas del CRS resultante.
    """
    resolved = resolve_crs(crs)
    if resolved is None:
        avg_lng = sum(v[0] for v in vertices) / len(vertices)
        avg_lat = sum(v[1] for v in vertices) / len(vertices)
        resolved = CRS.from_epsg(utm_epsg_for(avg_lng, avg_lat))

    xs = [float(v[0]) for v in vertices]
    ys = [float(v[1]) for v in vertices]
    px, py = rasterio.warp.transform(CRS.from_epsg(4326), resolved, xs, ys)
    return list(zip(px, py))


def polyline_length(coords, unit_factor=1.0):
    """Longitud euclídea acumulada de `coords` (secuencia de `(x, y)`), en metros."""
    total = 0.0
    for i in range(1, len(coords)):
        x0, y0 = coords[i - 1]
        x1, y1 = coords[i]
        total += math.hypot(x1 - x0, y1 - y0)
    return total * unit_factor


def plan_length(vertices, crs=None, unit_factor=1.0):
    """Longitud en planta de una polilínea EPSG:4326 (`data-model.md`, campo `plan_length`)."""
    coords = project_vertices(vertices, crs)
    return polyline_length(coords, unit_factor)
