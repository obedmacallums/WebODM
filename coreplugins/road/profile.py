"""Matemática de perfiles: detección de bordes y ajuste de pendientes (`research.md` D3, D4, D5).

**Este módulo no hace entrada/salida.** No abre rásteres, no toca la base de datos y no conoce
`Task`: opera sobre arrays en memoria. Es deliberado — la detección de bordes es la parte que más
puede equivocarse en silencio, y aislarla así permite probarla de forma exacta contra perfiles
sintéticos, sin depender de un vuelo real (`plan.md`, Structure Decision).

Convenios que atraviesan todo el módulo:

- Las distancias transversales llevan signo: **positivo = izquierda** del sentido de avance del eje
  (la dirección de `geometry.left_normal`), negativo = derecha. El `0.0` es el eje.
- Distancias y cotas van en la **misma unidad**. Las pendientes salen en % (y en grados donde se
  indique), así que mezclar metros con grados de longitud aquí produce un número plausible y
  equivocado.
- Una cota ausente se representa con `None`, nunca con un centinela numérico ni interpolada
  (FR-022).
"""

import math

import numpy as np

# Motivos de "sin borde" (FR-021). La distinción sale casi gratis del propio recorrido y es lo que
# separa problemas que el usuario resuelve de formas distintas.
NO_BREAK = 'no_break'          # se recorrió todo el semiancho sin encontrar quiebre
NO_DATA = 'no_data'            # el DEM se quedó sin dato antes de completar el recorrido
BREAK_AT_AXIS = 'break_at_axis'  # el terreno se rompe sobre el propio eje: no hay calzada que medir


def _clean(xs, ys):
    """Pares `(x, y)` con `y` presente y finito, como arrays de numpy."""
    keep = [(float(x), float(y)) for x, y in zip(xs, ys)
            if y is not None and not (isinstance(y, float) and math.isnan(y))]
    if not keep:
        return np.empty(0), np.empty(0)
    arr = np.asarray(keep, dtype=float)
    return arr[:, 0], arr[:, 1]


def fit_line(xs, ys):
    """Recta `y = a·x + b` por mínimos cuadrados. Devuelve `(a, b)` o `None`.

    Se usa la forma cerrada en vez de `numpy.polyfit` para no arrastrar sus avisos de rango en los
    casos degenerados, que aquí son normales: un tramo con dos muestras es un ajuste válido —la
    recta que une los extremos— y no una anomalía que reportar.
    """
    x, y = _clean(xs, ys)
    n = x.size
    if n < 2:
        return None
    mean_x = x.mean()
    denom = float(((x - mean_x) ** 2).sum())
    if denom <= 0.0:
        # Todas las muestras a la misma abscisa: no hay pendiente que estimar.
        return None
    mean_y = y.mean()
    a = float(((x - mean_x) * (y - mean_y)).sum() / denom)
    return a, float(mean_y - a * mean_x)


def fit_grade(stations, elevations):
    """Pendiente longitudinal de un tramo por mínimos cuadrados (`research.md` D4).

    `stations` son progresivas y `elevations` cotas, ambas en la misma unidad. Devuelve
    `{'slope', 'intercept', 'grade', 'grade_deg'}` con `grade` en % y `grade_deg` en grados, o
    `None` si no hay muestras suficientes.

    Se ajusta sobre **todas** las muestras del tramo, no sobre sus extremos: con tramos de 5 m
    sobre un DEM de 5 cm hay ~100 muestras, y usar solo los extremos entrega la pendiente al ruido
    de dos píxeles — el semáforo pasaría de verde a rojo entre tramos vecinos sin que el terreno
    cambie.
    """
    fit = fit_line(stations, elevations)
    if fit is None:
        return None
    a, b = fit
    return {
        'slope': a,
        'intercept': b,
        'grade': a * 100.0,
        'grade_deg': math.degrees(math.atan(a)),
    }


def evaluate(fit, x):
    """Valor del ajuste de `fit_grade` en `x` (la cota del tramo en su punto medio)."""
    return fit['slope'] * x + fit['intercept']


def _center_index(distances):
    """Índice del `0.0` del perfil transversal, o el más próximo a él."""
    best, best_abs = 0, None
    for i, d in enumerate(distances):
        current = abs(d)
        if best_abs is None or current < best_abs:
            best, best_abs = i, current
    return best


def _scan_side(distances, elevations, center, direction, threshold, min_consecutive):
    """Recorre un lado del perfil desde el eje hacia afuera buscando el quiebre.

    `direction` es `+1` (índices crecientes: lado izquierdo) o `-1` (lado derecho). Devuelve
    `(offset, index, reason)`: con borde, `reason` es `None`; sin él, `offset` e `index` son `None`
    y `reason` dice por qué.

    El borde es la **primera muestra de la primera racha** de al menos `min_consecutive`
    pendientes locales consecutivas por encima del umbral, no la muestra de pendiente máxima: eso
    sitúa el borde en el arranque del quiebre, que es el borde de calzada, y no a mitad del talud.
    El requisito de racha es lo que separa un quiebre real del ruido de un DEM fotogramétrico.

    Caso aparte: si la racha arranca en el **propio eje**, el borde caería a distancia cero y la
    "calzada" de ese lado sería un punto. No es un ancho de 0 m: es que el eje no pasa por una
    calzada en ese tramo (trazado desplazado, o terreno roto ahí mismo). Se reporta como
    `break_at_axis` en vez de devolver un ancho nulo que además dejaría la pendiente transversal
    sin muestras que ajustar. Encontrado sobre un DSM real; ningún perfil sintético lo producía.
    """
    n = len(distances)
    if elevations[center] is None:
        return None, None, NO_DATA

    run_start = None      # índice de la muestra donde arranca la racha en curso
    run_length = 0
    i = center

    while True:
        j = i + direction
        if j < 0 or j >= n:
            # Se recorrió todo el semiancho sin completar una racha.
            return None, None, NO_BREAK
        if elevations[j] is None:
            return None, None, NO_DATA

        span = distances[j] - distances[i]
        if span == 0:
            i = j
            continue
        slope_pct = abs((elevations[j] - elevations[i]) / span) * 100.0

        if slope_pct > threshold:
            if run_length == 0:
                run_start = i
            run_length += 1
            if run_length >= min_consecutive:
                if run_start == center:
                    return None, None, BREAK_AT_AXIS
                return distances[run_start], run_start, None
        else:
            run_length = 0
            run_start = None

        i = j


def detect_edges(distances, elevations, threshold, min_consecutive):
    """Bordes de calzada a ambos lados del eje (`research.md` D3, D3b).

    `distances` es la lista de distancias con signo del muestreo transversal, ascendente y con el
    `0.0` del eje incluido; `elevations` sus cotas alineadas, con `None` donde no hay dato.
    `threshold` es el quiebre en % y `min_consecutive` la longitud mínima de la racha.

    Devuelve `{'left': {...}, 'right': {...}}`, cada lado con `offset` (distancia **positiva** del
    eje al borde), `index` (posición en `distances`) y `reason` (`None`, `no_break`, `no_data` o
    `break_at_axis`).
    """
    if len(distances) != len(elevations):
        raise ValueError('distances y elevations deben tener la misma longitud')
    if len(distances) == 0:
        return {'left': {'offset': None, 'index': None, 'reason': NO_DATA},
                'right': {'offset': None, 'index': None, 'reason': NO_DATA}}

    center = _center_index(distances)

    left_offset, left_index, left_reason = _scan_side(
        distances, elevations, center, +1, threshold, min_consecutive)
    right_offset, right_index, right_reason = _scan_side(
        distances, elevations, center, -1, threshold, min_consecutive)

    return {
        'left': {
            'offset': None if left_offset is None else abs(left_offset),
            'index': left_index,
            'reason': left_reason,
        },
        'right': {
            'offset': None if right_offset is None else abs(right_offset),
            'index': right_index,
            'reason': right_reason,
        },
    }


# --- Criterio de superficie (`006` FR-005..FR-010, D17, D18) -------------------------------
#
# Donde `detect_edges` busca **lo afilado** (pendiente local sostenida), esto busca **lo alto**:
# la calzada termina donde el perfil se aparta de una recta ajustada a la propia calzada más de
# una tolerancia, y se mantiene apartado. Medido sobre un DEM urbano real (D17): el bordillo llega
# difuminado en ~1 m (10-30 % de pendiente local) mientras el ruido produce picos de una sola
# muestra mucho más afilados — el quiebre persigue al ruido; la separación, al bordillo.

# Semiancho de la semilla del ajuste, en la unidad de `distances`. Pequeño a propósito: cuanto más
# estrecho, menos probable que cruce un bordillo cercano, y el reajuste (D18) corrige el resto.
# Es una constante interna, no un parámetro (FR-028).
SURFACE_SEED_HALF_WIDTH = 0.5


def _surface_seed_fit(distances, elevations, center, seed_half_width):
    """Recta semilla sobre las muestras a `±seed_half_width` del eje, o `None`."""
    d0 = distances[center]
    xs, ys = [], []
    for d, z in zip(distances, elevations):
        if abs(d - d0) <= seed_half_width + 1e-9:
            xs.append(d)
            ys.append(z)
    return fit_line(xs, ys)


def _scan_side_surface(distances, elevations, center, direction, fit, tolerance,
                       min_consecutive):
    """Recorre un lado desde el eje hacia afuera buscando la separación sostenida.

    Mismo contrato de salida que `_scan_side`. El borde es la **última muestra conforme** —el pie
    del quiebre—, no la primera que se aparta: esa ya está a más de `tolerance` por encima de la
    calzada. Si la separación arranca en la primera muestra junto al eje, no hay calzada que medir
    a ese lado (`break_at_axis`), igual que en el modo de quiebre.
    """
    n = len(distances)
    a, b = fit
    run_start = None
    run_length = 0
    i = center + direction

    while 0 <= i < n:
        z = elevations[i]
        if z is None:
            return None, None, NO_DATA
        if abs(z - (a * distances[i] + b)) > tolerance:
            if run_length == 0:
                run_start = i
            run_length += 1
            if run_length >= min_consecutive:
                if run_start == center + direction:
                    return None, None, BREAK_AT_AXIS
                edge = run_start - direction
                return distances[edge], edge, None
        else:
            run_length = 0
            run_start = None
        i += direction

    return None, None, NO_BREAK


def _surface_roadway_bounds(distances, elevations, center, side_results):
    """Muestras de calzada para el reajuste: del eje hacia afuera hasta el borde provisional
    (inclusive), el primer hueco de datos o el final del perfil."""
    xs, ys = [distances[center]], [elevations[center]]
    for direction, (offset, index, reason) in ((+1, side_results[0]), (-1, side_results[1])):
        if reason == BREAK_AT_AXIS:
            continue   # el scan dictaminó que a ese lado no hay calzada: nada que aportar
        i = center + direction
        while 0 <= i < len(distances):
            if elevations[i] is None:
                break
            if index is not None and (i - index) * direction > 0:
                break
            xs.append(distances[i])
            ys.append(elevations[i])
            i += direction
    return xs, ys


def detect_edges_surface(distances, elevations, tolerance, min_consecutive,
                         seed_half_width=SURFACE_SEED_HALF_WIDTH):
    """Bordes por separación respecto de la referencia de calzada (`006` FR-005..FR-008).

    Mismo contrato de salida que `detect_edges`, con los mismos tres motivos (FR-010), más una
    clave `reference` con la recta ajustada: su pendiente **es** el bombeo del tramo en este modo
    (D19), medida exactamente sobre las muestras que el criterio consideró calzada.

    `tolerance` va en la unidad vertical del perfil; `seed_half_width` en la de `distances` (el
    llamador lo convierte si sus distancias no están en metros).

    Dos pasadas (D18): la semilla de `±seed_half_width` puede pisar la acera si el eje va
    descentrado, así que la recta se rehace usando solo las muestras entre los bordes
    provisionales y la detección se repite. Comparar contra la recta ajustada —no contra la cota
    del eje— absorbe el peralte, que es lo que le faltaba a la alternativa descartada en D3.
    """
    if len(distances) != len(elevations):
        raise ValueError('distances y elevations deben tener la misma longitud')

    no_side = {'offset': None, 'index': None, 'reason': NO_DATA}
    if len(distances) == 0:
        return {'left': dict(no_side), 'right': dict(no_side), 'reference': None}

    center = _center_index(distances)
    if elevations[center] is None:
        return {'left': dict(no_side), 'right': dict(no_side), 'reference': None}

    fit = _surface_seed_fit(distances, elevations, center, seed_half_width)
    if fit is None:
        # Semilla no ajustable: sin muestras suficientes junto al eje no hay referencia posible.
        return {'left': dict(no_side), 'right': dict(no_side), 'reference': None}

    left = right = None
    for _pass in range(2):
        left = _scan_side_surface(distances, elevations, center, +1, fit, tolerance,
                                  min_consecutive)
        right = _scan_side_surface(distances, elevations, center, -1, fit, tolerance,
                                   min_consecutive)
        if _pass == 0:
            refit = fit_line(*_surface_roadway_bounds(distances, elevations, center,
                                                      (left, right)))
            if refit is None:
                break   # la calzada acotada no da para una recta: se queda la semilla
            fit = refit

    left_offset, left_index, left_reason = left
    right_offset, right_index, right_reason = right
    return {
        'left': {
            'offset': None if left_offset is None else abs(left_offset),
            'index': left_index,
            'reason': left_reason,
        },
        'right': {
            'offset': None if right_offset is None else abs(right_offset),
            'index': right_index,
            'reason': right_reason,
        },
        'reference': {
            'slope': fit[0],
            'intercept': fit[1],
            'cross_slope': fit[0] * 100.0,
        },
    }


def cross_slope(distances, elevations, left_index, right_index):
    """Pendiente transversal (bombeo o peralte) **entre los dos bordes** (`research.md` D5).

    Mismo estimador que `fit_grade` aplicado al perfil transversal, restringido a las muestras de
    la calzada: fuera de ella la cifra dejaría de significar bombeo y pasaría a significar "la
    inclinación del terreno alrededor". Sin ambos bordes no hay calzada delimitada y se devuelve
    `None` (FR-022: no se estima con lo que haya).

    El signo sigue el convenio del módulo: positivo = la calzada sube hacia la izquierda del
    sentido de avance.
    """
    if left_index is None or right_index is None:
        return None
    lo, hi = sorted((left_index, right_index))
    fit = fit_line(distances[lo:hi + 1], elevations[lo:hi + 1])
    if fit is None:
        return None
    return fit[0] * 100.0
