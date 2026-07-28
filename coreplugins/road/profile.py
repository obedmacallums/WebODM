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

# Motivos de "sin borde" (FR-021). La distinción sale gratis del propio recorrido y es lo que
# separa "aquí el camino se funde con el terreno" de "aquí no hay datos".
NO_BREAK = 'no_break'
NO_DATA = 'no_data'


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
    eje al borde), `index` (posición en `distances`) y `reason` (`None`, `no_break` o `no_data`).
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
