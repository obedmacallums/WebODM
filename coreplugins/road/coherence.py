"""Coherencia longitudinal de los bordes (`006` FR-011..FR-018, `research.md` D20).

El borde de una calle es una línea continua, y la detección por tramo no usa esa información: en el
caso real que motivó esto, un bordillo recto salía con offsets de 1,25 → 0,10 → 1,50 m entre tramos
vecinos. Esta pasada repara atípicos y huecos cortos con la mediana de la vecindad, y **declara**
cada reparación: el origen (`measured` | `inferred` | `None`) viaja con el borde hasta el usuario.

**Este módulo no sabe qué es un DEM.** Opera sobre la secuencia de offsets ya detectados, en orden
de progresiva, un lado cada vez. Es la otra mitad de la separación que `profile` inaugura: aquel ve
un perfil y ningún vecino; este ve la secuencia y ningún perfil.

Las dos propiedades que hacen segura la inferencia, y que los tests fijan antes que ninguna otra
cosa:

- **Solo votan los bordes medidos.** Un relleno nunca es evidencia para el siguiente, así que el
  frente de inferencia no avanza más de `window` tramos desde la última medición real: un
  descampado de diez tramos se queda sin bordes por mucho que la ventana insista.
- **El umbral de atípico sale de los datos.** Cuánto varía legítimamente un borde entre vecinos
  depende de la calle (un ensanche varía; un bordillo recto no), así que se estima con el MAD de
  la propia vecindad en vez de pedirle un número al usuario. El suelo de `MIN_TOLERANCE` evita que
  una vecindad casualmente idéntica (MAD 0) declare atípica cualquier desviación minúscula.
"""

# 3 sigmas equivalentes: 1.4826 convierte el MAD en desviación típica para una normal.
MAD_SIGMAS = 3.0 * 1.4826

# Suelo del umbral de atípico, en metros (FR-017): una desviación de hasta 0,30 m nunca se
# considera atípica, por muy uniforme que sea la vecindad.
MIN_TOLERANCE = 0.30

MEASURED = 'measured'
INFERRED = 'inferred'


def _median(values):
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def _repair_side(offsets, window):
    """Repara un lado. `offsets` son los bordes **medidos** (float) o `None`, en orden de
    progresiva. Devuelve una lista de `(offset, origen)` de la misma longitud.

    La vecindad se lee siempre de la lista original: por construcción, ningún valor inferido
    puede influir en otro (FR-013).
    """
    n = len(offsets)
    result = []
    for i in range(n):
        own = offsets[i]
        neighbors = [offsets[j]
                     for j in range(max(0, i - window), min(n, i + window + 1))
                     if j != i and offsets[j] is not None]
        if len(neighbors) < 2:
            # Sin evidencia suficiente no se toca nada (FR-014): ni para rellenar ni para dudar
            # de lo medido.
            result.append((own, MEASURED if own is not None else None))
            continue

        med = _median(neighbors)
        mad = _median([abs(v - med) for v in neighbors])
        tolerance = max(MAD_SIGMAS * mad, MIN_TOLERANCE)

        if own is None:
            result.append((med, INFERRED))            # hueco corto: se rellena y se declara
        elif abs(own - med) > tolerance:
            result.append((med, INFERRED))            # atípico: se sustituye y se declara
        else:
            result.append((own, MEASURED))
    return result


def repair_edges(left_offsets, right_offsets, window):
    """Repara los dos lados por separado (FR-011): un lado con evidencia no presta bordes al
    otro. Con `window == 0` es la identidad exacta (FR-012).

    Devuelve `(left, right)`, cada uno como lista de `(offset, origen)`.
    """
    if len(left_offsets) != len(right_offsets):
        raise ValueError('los dos lados deben tener la misma longitud de secuencia')
    if window <= 0:
        identity = lambda seq: [(v, MEASURED if v is not None else None) for v in seq]
        return identity(left_offsets), identity(right_offsets)
    return _repair_side(left_offsets, window), _repair_side(right_offsets, window)
