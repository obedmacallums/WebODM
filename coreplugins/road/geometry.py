"""Geometría del eje: proyección, progresivas, tramificación y transversales (`research.md` D6, D7).

Las coordenadas del eje viajan siempre en EPSG:4326, orden `[lng, lat]` (`data-model.md`). Aquí se
proyectan al CRS **del propio DEM** con `rasterio.warp.transform` — mismo criterio que
`annotations.geometry` —, de modo que la geometría medida y el ráster muestreado vivan en el mismo
sistema y no haga falta un reproyectado intermedio ni `pyproj`.

Todo lo que sigue trabaja en **unidades nativas del ráster**. La conversión a metros la hace quien
llama, con el factor de `app.geoutils.get_rasterio_to_meters_factor`: mezclar ambas escalas dentro
de este módulo es la vía más rápida a un ancho medido en grados.
"""

import math

import numpy as np
import rasterio.warp
from rasterio.crs import CRS
from django.utils.translation import gettext_lazy as _

MIN_VERTICES = 2
MAX_VERTICES = 500

WGS84 = CRS.from_epsg(4326)


def validate_vertices(vertices):
    """Valida `vertices` como lista de `[lng, lat]` (`data-model.md` §3).

    Devuelve `(ok, error)`: `error` es `None` si `ok` es `True`. Réplica deliberada de
    `annotations.geometry.validate_vertices`: `road` no importa módulos internos de otro plugin,
    solo su contrato público.
    """
    if not isinstance(vertices, (list, tuple)) or len(vertices) < MIN_VERTICES:
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
        if math.isnan(lng) or math.isnan(lat):
            return False, _('Las coordenadas de los vértices deben ser numéricas.')
        parsed.append((lng, lat))

    distinct = {(round(lng, 9), round(lat, 9)) for lng, lat in parsed}
    if len(distinct) < 2:
        return False, _('El eje necesita al menos dos posiciones distintas.')

    return True, None


def project_vertices(vertices, crs):
    """Proyecta `[[lng, lat], ...]` (EPSG:4326) al CRS `crs`, en sus unidades nativas."""
    xs = [float(v[0]) for v in vertices]
    ys = [float(v[1]) for v in vertices]
    px, py = rasterio.warp.transform(WGS84, crs, xs, ys)
    return list(zip(px, py))


def unproject_points(points, crs):
    """Inversa de `project_vertices`: `[(x, y), ...]` -> `[[lng, lat], ...]`."""
    if not points:
        return []
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    lons, lats = rasterio.warp.transform(crs, WGS84, xs, ys)
    return [[lons[i], lats[i]] for i in range(len(points))]


def cumulative_stations(coords):
    """Progresiva acumulada en cada vértice de `coords` (secuencia de `(x, y)`)."""
    cum = [0.0]
    for i in range(1, len(coords)):
        x0, y0 = coords[i - 1]
        x1, y1 = coords[i]
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return cum


def polyline_length(coords):
    """Longitud euclídea acumulada de `coords`, en las unidades de `coords`."""
    return cumulative_stations(coords)[-1]


def plan_length(vertices, crs, unit_factor=1.0):
    """Longitud en planta de un eje EPSG:4326, en metros (`data-model.md`, campo `plan_length`)."""
    return polyline_length(project_vertices(vertices, crs)) * unit_factor


def point_at_station(coords, cum, station):
    """Punto sobre la polilínea a la progresiva `station`, interpolando dentro del tramo.

    Devuelve `((x, y), i)`, con `i` el índice del tramo `coords[i] -> coords[i+1]` que lo contiene.
    """
    total = cum[-1]
    if station <= 0.0:
        return (coords[0][0], coords[0][1]), 0
    if station >= total:
        return (coords[-1][0], coords[-1][1]), max(len(coords) - 2, 0)

    # Búsqueda lineal: los ejes admitidos tienen como mucho 500 vértices (`MAX_VERTICES`), así
    # que una bisección solo añadiría código que mantener.
    for i in range(1, len(cum)):
        if cum[i] >= station:
            seg_len = cum[i] - cum[i - 1]
            if seg_len <= 0:
                return (coords[i][0], coords[i][1]), i - 1
            t = (station - cum[i - 1]) / seg_len
            x0, y0 = coords[i - 1]
            x1, y1 = coords[i]
            return (x0 + (x1 - x0) * t, y0 + (y1 - y0) * t), i - 1
    return (coords[-1][0], coords[-1][1]), max(len(coords) - 2, 0)


def points_at_stations(coords, cum, stations):
    """Versión vectorizada de `point_at_station` para muchas progresivas a la vez.

    El pipeline pide del orden de 10⁴–10⁶ muestras del eje: resolverlas una a una con la búsqueda
    lineal de `point_at_station` cuesta `O(vértices)` cada una y se nota. Aquí se localizan todas
    de golpe con `searchsorted` y se interpolan con numpy.
    """
    stations = np.asarray(stations, dtype='float64')
    cum_arr = np.asarray(cum, dtype='float64')
    xs = np.asarray([c[0] for c in coords], dtype='float64')
    ys = np.asarray([c[1] for c in coords], dtype='float64')

    clipped = np.clip(stations, 0.0, cum_arr[-1])
    i = np.clip(np.searchsorted(cum_arr, clipped, side='left'), 1, len(cum_arr) - 1)
    seg_len = cum_arr[i] - cum_arr[i - 1]
    # Vértices duplicados dan un tramo de longitud nula: `t = 0` devuelve el vértice, que es la
    # respuesta correcta, y evita el aviso de división por cero.
    t = np.where(seg_len > 0, (clipped - cum_arr[i - 1]) / np.where(seg_len > 0, seg_len, 1.0), 0.0)
    return (xs[i - 1] + (xs[i] - xs[i - 1]) * t,
            ys[i - 1] + (ys[i] - ys[i - 1]) * t)


def substring(coords, cum, station_start, station_end):
    """Geometría en planta entre dos progresivas, conservando los vértices originales intermedios.

    Un tramo que cruza un quiebre del eje debe dibujarse con ese quiebre, no como la cuerda entre
    sus extremos: si no, la capa del mapa recorta las curvas.
    """
    start_pt, start_i = point_at_station(coords, cum, station_start)
    end_pt, _end_i = point_at_station(coords, cum, station_end)
    points = [start_pt]
    for i in range(1, len(coords)):
        if station_start < cum[i] < station_end:
            points.append((coords[i][0], coords[i][1]))
    points.append(end_pt)
    return points


def left_normal(p0, p1):
    """Vector unitario perpendicular a la cuerda `p0 -> p1`, apuntando a su **izquierda** (D6).

    Con `x` al este e `y` al norte, girar la dirección de avance 90° en sentido antihorario
    (`(dx, dy) -> (-dy, dx)`) da el lado izquierdo del sentido de trazado. Fijar la convención es
    lo que hace interpretable la asimetría del camino: `offset_left` siempre cae del mismo lado.

    Devuelve `None` si los dos puntos coinciden y no hay dirección que perpendicular.
    """
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    norm = math.hypot(dx, dy)
    if norm <= 0:
        return None
    return (-dy / norm, dx / norm)


def segmentize(coords, segment_length):
    """Divide la polilínea proyectada en tramos consecutivos de `segment_length`.

    Invariantes (`data-model.md` §6), verificados en `tests/test_geometry.py`:

    - El primer tramo empieza en `0.0` y el último termina exactamente en la longitud total.
    - El `station_end` de un tramo es el `station_start` del siguiente: ni huecos ni solapamientos.
    - El último tramo conserva su longitud real, que puede ser menor que `segment_length`.
    - Un eje más corto que un tramo produce **un** tramo, no cero.

    Devuelve una lista de dicts con `index`, `station_start`, `station_end`, `length`, `points`
    (geometría en planta), `midpoint` y `normal` (unitario, hacia la izquierda del avance).
    """
    if segment_length <= 0:
        raise ValueError('segment_length debe ser positivo')

    cum = cumulative_stations(coords)
    total = cum[-1]
    if total <= 0:
        raise ValueError('El eje tiene longitud nula')

    # El `-1e-9` absorbe el error de coma flotante de la división: sin él, una longitud que es
    # múltiplo exacto del paso genera un tramo final de longitud ~0.
    count = max(1, int(math.ceil(total / segment_length - 1e-9)))

    segments = []
    for i in range(count):
        station_start = i * segment_length
        station_end = total if i == count - 1 else min((i + 1) * segment_length, total)
        points = substring(coords, cum, station_start, station_end)
        mid_station = 0.5 * (station_start + station_end)
        midpoint, _i = point_at_station(coords, cum, mid_station)
        # La perpendicular es a la **cuerda** del tramo (D6): con tramos cortos, cuerda y tangente
        # son indistinguibles a efectos de medición, y no introduce dependencia entre tramos
        # vecinos como haría una tangente suavizada.
        normal = left_normal(points[0], points[-1])
        if normal is None:
            normal = left_normal(coords[0], coords[-1])
        segments.append({
            'index': i,
            'station_start': station_start,
            'station_end': station_end,
            'length': station_end - station_start,
            'points': points,
            'midpoint': midpoint,
            'normal': normal,
        })
    return segments


def section_stations(station_start, station_end, spacing):
    """Progresivas de las transversales de un tramo, de la primera a la última.

    Con `spacing` a 0 —el defecto— devuelve **una** progresiva, la del punto medio: el ancho se
    mide una vez por tramo, que es como funcionó siempre. Con un espaciado positivo el tramo se
    reparte en `n = max(1, round(longitud / spacing))` franjas iguales y se mide en el centro de
    cada una.

    Centradas y no desde el borde por dos razones: ninguna transversal cae en la junta entre
    tramos —donde el ancho pertenecería por igual a los dos vecinos— y el reparto queda simétrico
    respecto del punto medio, así que medir varias veces no sesga el tramo hacia su principio.

    El `max(1, ...)` es lo que garantiza que un tramo más corto que el espaciado siga midiéndose:
    quedarse sin ancho por un detalle de aritmética sería peor que medirlo una sola vez.
    """
    length = station_end - station_start
    if spacing <= 0 or length <= 0:
        return [0.5 * (station_start + station_end)]

    n = max(1, int(round(length / spacing)))
    width = length / n
    return [station_start + (i + 0.5) * width for i in range(n)]


def cross_section_offsets(half_width, step):
    """Distancias con signo del muestreo transversal, del lado derecho al izquierdo.

    Positivo = izquierda del sentido de avance (dirección de `left_normal`), negativo = derecha.
    El `0.0` central siempre está presente, en el índice `len(offsets) // 2`: es el punto del eje,
    desde el que `profile.detect_edges` recorre hacia afuera.
    """
    if step <= 0:
        raise ValueError('step debe ser positivo')
    n = int(math.floor(half_width / step + 1e-9))
    return [k * step for k in range(-n, n + 1)]


def cross_section_points(midpoint, normal, offsets):
    """Puntos `(x, y)` del muestreo transversal, uno por cada distancia de `offsets`."""
    mx, my = midpoint
    nx, ny = normal
    return [(mx + d * nx, my + d * ny) for d in offsets]
