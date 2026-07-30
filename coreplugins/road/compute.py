"""Pipeline de análisis: muestreo por bloques del DEM y métricas por tramo (`research.md` D2, D9).

`analyze` recorre el eje **por bloques de tramos consecutivos**. Por cada bloque se lee una única
ventana del ráster a un array `numpy` y todas las muestras del bloque —eje y transversales— se
resuelven por indexación vectorizada. La alternativa evidente, `ds.sample()` punto a punto (lo que
usa `annotations`), hace una lectura por muestra: con un camino de 1 km y los parámetros por
defecto se pasa de ~2.000 muestras a ~40.000, y de ahí escala con la longitud. Leer por ventanas
convierte cientos de miles de lecturas en unas pocas decenas, y da el punto natural donde reportar
progreso y comprobar cancelación.

Todo el cálculo ocurre en **unidades nativas del ráster** y se convierte a metros al construir la
respuesta: mezclar las dos escalas a mitad del pipeline es la vía más rápida a un ancho medido en
grados.
"""

import contextlib
import math
import time

import numpy as np
import rasterio
from rasterio.windows import Window

from app.geoutils import get_rasterio_to_meters_factor

from . import coherence, geometry, profile, segmentation

# Techo de píxeles por lectura. 4 M en float32 son 16 MB: el DEM de un vuelo grande no cabe
# cómodamente en la memoria del worker, y el eje solo cubre una franja estrecha de él.
MAX_WINDOW_PIXELS = 4_000_000

# Fracción del progreso total reservada a la etapa de segmentación en modo `segmentation`
# (`007/FR-009`, `research.md` D27): sin esto, el usuario ve el progreso congelado mientras el
# modelo de IA corre, y solo salta al terminar. El resto del progreso —el bucle de bloques que ya
# existía— ocupa el resto. No aplica a `break` ni `surface`.
SEGMENTATION_PROGRESS_SHARE = 0.4

# Tasa de muestras por segundo para la estimación previa (`research.md` D11).
#
# Calibrada el 2026-07-28 midiendo un análisis real: 1 km de eje con los parámetros por defecto
# sobre un DTM de 2,2 cm (tarea Noria, 14145×29379 px) da 200 tramos, 50.400 muestras y 0,37 s
# — unas 135.000 muestras/s. Se deja algo por debajo a propósito: a un usuario al que se le
# anuncian 22 s y espera 40 le molesta más que al revés.
SAMPLES_PER_SECOND = 120_000.0

# A partir de aquí la creación pide confirmación explícita. **No es un tope**: sin `confirm` se
# responde 409 con la estimación, y con `confirm: true` se lanza igual (FR-043).
#
# 8 M de muestras son ~60 s a la tasa medida, que es donde la espera empieza a molestar de verdad.
# Con los valores por defecto no salta ni en un camino de 10 km (~500.000 muestras): lo que lo
# dispara es bajar mucho el `sample_step`, que es justamente la decisión que conviene avisar.
WARN_SAMPLES = 8_000_000

STATUS_MEASURED = 'measured'
STATUS_NO_EDGE = 'no_edge'
STATUS_NO_COVERAGE = 'no_coverage'
# Ancho presente pero con al menos un borde procedente de la vecindad (`006` data-model §6): el
# usuario distingue así lo medido de lo deducido sin perder el número.
STATUS_INFERRED = 'inferred'


class Canceled(Exception):
    """El usuario canceló el análisis mientras el muestreo estaba en marcha."""
    pass


def block_size_for(segment_length, half_width, resolution, max_pixels=MAX_WINDOW_PIXELS):
    """Cuántos tramos caben en una lectura sin pasarse del techo de memoria.

    Estimación para el caso recto y alineado con los ejes del ráster: la ventana de un bloque de
    `n` tramos mide del orden de `(n·L + 2·W) x (2·W)`. Es solo el punto de partida — un eje curvo
    genera ventanas mayores que la estimación, y por eso `_read_block` vuelve a comprobar el
    tamaño real y parte el bloque si hace falta.
    """
    if resolution <= 0:
        return 1
    band = 2.0 * half_width
    if band <= 0:
        return 1
    budget = max_pixels * resolution * resolution / band - band
    return max(1, int(budget // segment_length))


def _axis_stations(station_start, station_end, step):
    """Progresivas de muestreo del eje dentro de un tramo, extremos incluidos."""
    if step <= 0:
        return np.array([station_start, station_end])
    count = int(math.floor((station_end - station_start) / step + 1e-9))
    stations = station_start + step * np.arange(count + 1)
    if stations[-1] < station_end - 1e-9:
        stations = np.append(stations, station_end)
    return stations


def _sample(ds, xs, ys):
    """Muestrea el ráster en `(xs, ys)` por vecino más próximo, leyendo **una** ventana.

    Devuelve un array float con `NaN` donde no hay dato: fuera del ráster, en el `nodata` del
    archivo o en un `NaN` original. Nunca se rellena ni se interpola (FR-022).

    El vecino más próximo es coherente con el remuestreo `near` que `realign` aplica a los DEM:
    interpolar aquí inventaría cotas que el producto corregido no tiene.
    """
    empty = np.full(xs.shape, np.nan, dtype='float64')
    if xs.size == 0:
        return empty

    inv = ~ds.transform
    cols = inv.a * xs + inv.b * ys + inv.c
    rows = inv.d * xs + inv.e * ys + inv.f
    col_idx = np.floor(cols).astype(np.int64)
    row_idx = np.floor(rows).astype(np.int64)

    inside = ((row_idx >= 0) & (row_idx < ds.height)
              & (col_idx >= 0) & (col_idx < ds.width))
    if not inside.any():
        return empty

    r0 = int(row_idx[inside].min())
    r1 = int(row_idx[inside].max()) + 1
    c0 = int(col_idx[inside].min())
    c1 = int(col_idx[inside].max()) + 1

    data = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype('float64')
    values = empty
    values[inside] = data[row_idx[inside] - r0, col_idx[inside] - c0]

    if ds.nodata is not None:
        values[values == ds.nodata] = np.nan
    return values


def _window_pixels(ds, xs, ys):
    """Píxeles que ocuparía la ventana necesaria para muestrear `(xs, ys)`."""
    if xs.size == 0:
        return 0
    inv = ~ds.transform
    cols = inv.a * xs + inv.b * ys + inv.c
    rows = inv.d * xs + inv.e * ys + inv.f
    width = float(np.ptp(cols)) + 2.0
    height = float(np.ptp(rows)) + 2.0
    return width * height


def _to_list(values):
    """Array de numpy -> lista de `float | None`, que es como lo consume `profile`."""
    return [None if math.isnan(v) else float(v) for v in values]


def _section_result(offsets, cross_values, params, unit_factor, mask_values=None):
    """Bordes y ancho de **una** transversal, en metros."""
    cross_list = _to_list(cross_values)

    # El suavizado alimenta SOLO la detección basada en elevación: `cross_slope` y las cotas se
    # siguen midiendo sobre el dato crudo. `smooth_window` va en metros y los offsets en unidad
    # nativa, de ahí la conversión; con la ventana a 0 (el defecto) `median_kernel` devuelve 1 y
    # `detect_list` es el propio perfil — el comportamiento de siempre, muestra a muestra.
    detect_list = cross_list
    window = params.get('smooth_window') or 0.0
    if window > 0 and len(offsets) > 1:
        kernel = profile.median_kernel(window / unit_factor, offsets[1] - offsets[0])
        detect_list = profile.median_smooth(cross_list, kernel)

    edge_mode = params.get('edge_mode')
    if edge_mode == 'surface':
        # La tolerancia es vertical y no se convierte; la semilla es horizontal y va en la unidad
        # de `offsets`, que aquí es la nativa del CRS (`006` D18).
        edges = profile.detect_edges_surface(
            offsets, detect_list, params['surface_tolerance'],
            params['min_consecutive_samples'],
            seed_half_width=profile.SURFACE_SEED_HALF_WIDTH / unit_factor)
    elif edge_mode == 'segmentation':
        # `007/FR-015b`: `smooth_window` no interviene aquí — la máscara es una clasificación
        # binaria, no una señal continua que suavizar. Se usa `mask_values` crudo, no `detect_list`.
        edges = profile.detect_edges_segmentation(
            offsets, mask_values, params['min_consecutive_samples'])
    else:
        edges = profile.detect_edges(offsets, detect_list, params['break_threshold'],
                                     params['min_consecutive_samples'])

    left, right = edges['left'], edges['right']
    offset_left = None if left['offset'] is None else left['offset'] * unit_factor
    offset_right = None if right['offset'] is None else right['offset'] * unit_factor
    measured = left['reason'] is None and right['reason'] is None

    if not measured:
        cross = None
    elif edge_mode == 'surface':
        # D19: el bombeo ES la pendiente de la referencia ajustada, medida exactamente sobre las
        # muestras que el criterio consideró calzada.
        cross = edges['reference']['cross_slope']
    else:
        # `007/FR-010`: en modo segmentación la pendiente transversal se deriva igual que en modo
        # `break` — de las muestras de elevación entre los bordes hallados, no de la máscara.
        cross = profile.cross_slope(offsets, cross_list, left['index'], right['index'])

    return {
        'edges': edges,
        'left': left,
        'right': right,
        'offset_left': offset_left,
        'offset_right': offset_right,
        'width': offset_left + offset_right if measured else None,
        'cross_slope': cross,
        'cross_list': cross_list,
    }


def _representative(sections):
    """Índice de la transversal que representa al tramo: la de ancho **mediano** entre las que
    midieron.

    Se elige una sección real y se reporta entera —ancho, lados, bombeo y puntos de borde— en vez
    de promediar. Promediar produciría un par (izquierda, derecha) que no se midió en ningún punto
    y unos puntos de borde sintéticos, que no están sobre el terreno; así todo lo que sale del
    tramo es autoconsistente y `width == offset_left + offset_right` sigue siendo exacto.

    Con un número par de secciones medidas se toma la mediana **baja**, para que siempre sea una
    sección existente. Si ninguna midió se devuelve la central: sus motivos son los que mejor
    describen el tramo, que es lo único que hay que reportar entonces.
    """
    measured = [i for i, s in enumerate(sections) if s['width'] is not None]
    if not measured:
        return len(sections) // 2
    measured.sort(key=lambda i: sections[i]['width'])
    return measured[(len(measured) - 1) // 2]


def _segment_metrics(segment, offsets, params, unit_factor, axis_values, cross_values,
                     mask_values=None):
    """Métricas de un tramo a partir de sus muestras ya leídas.

    `cross_values` trae **una fila por transversal** del tramo (`data-model.md` §6): una sola con
    el espaciado apagado, que es el defecto y el comportamiento de siempre. `mask_values`, con la
    misma forma, solo se pasa en modo `segmentation` (`007/FR-005`); en los otros dos modos es
    `None` y cada sección lo recibe así.
    """
    stations = segment['_stations']
    fit = profile.fit_grade(stations - stations[0], _to_list(axis_values))

    rows = cross_values.reshape(len(segment['_section_midpoints']), len(offsets))
    if mask_values is not None:
        mask_rows = [_to_list(r) for r in mask_values.reshape(
            len(segment['_section_midpoints']), len(offsets))]
    else:
        mask_rows = [None] * len(rows)
    sections = [_section_result(offsets, row, params, unit_factor, mask_values=mrow)
               for row, mrow in zip(rows, mask_rows)]
    pick = _representative(sections)
    chosen = sections[pick]
    midpoint = segment['_section_midpoints'][pick]

    # Con la media el resumen no es ninguna transversal concreta, así que tampoco tiene un punto
    # de medición: se declara el centro del tramo. La sección mediana sigue haciendo de portadora
    # de lo que necesita una transversal real (los motivos, el perfil, los índices de borde).
    averaging = (params.get('width_aggregation') == 'mean'
                 and any(s['width'] is not None for s in sections))
    if averaging:
        midpoint = segment['midpoint']

    # La dispersión de lo que se midió: es lo que distingue un tramo uniforme de uno que se
    # estrecha, y sin ella la mediana escondería justo el defecto que se buscaba.
    measured_widths = [s['width'] for s in sections if s['width'] is not None]

    edges = chosen['edges']
    left, right = chosen['left'], chosen['right']
    cross_list = chosen['cross_list']

    if fit is None:
        # Sin al menos dos muestras válidas del eje no hay rasante que ajustar: el tramo no tiene
        # cobertura, y con ella se van también la cota y la pendiente (`data-model.md` §6).
        status = STATUS_NO_COVERAGE
        elevation = grade = grade_deg = None
        width = cross = None
        offset_left = offset_right = None
        left_reason = left['reason'] or profile.NO_DATA
        right_reason = right['reason'] or profile.NO_DATA
        edge_left_pt = edge_right_pt = None
    else:
        elevation = profile.evaluate(fit, 0.5 * (stations[-1] - stations[0]))
        grade = fit['grade']
        grade_deg = fit['grade_deg']
        left_reason, right_reason = left['reason'], right['reason']
        offset_left = chosen['offset_left']
        offset_right = chosen['offset_right']

        if left_reason is None and right_reason is None:
            status = STATUS_MEASURED
            width = offset_left + offset_right
            cross = chosen['cross_slope']
        else:
            status = STATUS_NO_EDGE
            width = None
            cross = None

        edge_left_pt = _edge_point(midpoint, segment['normal'], offsets, left['index'])
        edge_right_pt = _edge_point(midpoint, segment['normal'], offsets, right['index'])

        if averaging:
            # Cada lado se promedia por separado, así que `width == izquierda + derecha` sigue
            # siendo exacto —la media de las sumas es la suma de las medias— y la regla dibujada
            # mide lo que dice el popup. Los puntos de borde pasan a ser construidos: no hay
            # ninguna transversal donde el camino tuviera exactamente estas dos distancias.
            complete = [s for s in sections if s['width'] is not None]
            offset_left = sum(s['offset_left'] for s in complete) / len(complete)
            offset_right = sum(s['offset_right'] for s in complete) / len(complete)
            width = offset_left + offset_right
            status = STATUS_MEASURED
            left_reason = right_reason = None
            crosses = [s['cross_slope'] for s in complete if s['cross_slope'] is not None]
            cross = sum(crosses) / len(crosses) if crosses else None
            info = {'midpoint': midpoint, 'normal': segment['normal']}
            edge_left_pt = _offset_point(info, offset_left, unit_factor, +1)
            edge_right_pt = _offset_point(info, offset_right, unit_factor, -1)

    return {
        'status': status,
        'elevation': elevation,
        'grade': grade,
        'grade_deg': grade_deg,
        'width': width,
        'offset_left': offset_left,
        'offset_right': offset_right,
        'cross_slope': cross,
        # Cuántas veces se midió el ancho en este tramo y cuántas dieron resultado, más el rango
        # de lo medido: es el indicador de regularidad que una sola transversal no puede dar.
        'width_sections': len(sections),
        'width_measured_sections': len(measured_widths),
        'width_min': min(measured_widths) if measured_widths else None,
        'width_max': max(measured_widths) if measured_widths else None,
        # Todo lo que se reporta sale de esta transversal, así que su punto sobre el eje y su
        # perfil viajan con ella: es donde se dibuja la regla, desde donde se miden los dos lados
        # y sobre lo que la coherencia recalcula el bombeo si mueve un borde.
        '_midpoint': midpoint,
        '_cross_row': rows[pick],
        'left_reason': left_reason,
        'right_reason': right_reason,
        # Origen por lado (`006` FR-019): en la detección todo borde presente es medido; la
        # pasada de coherencia es la única que puede poner `inferred`.
        'left_edge_source': 'measured' if offset_left is not None else None,
        'right_edge_source': 'measured' if offset_right is not None else None,
        '_edge_left': edge_left_pt,
        '_edge_right': edge_right_pt,
        # El bombeo de la referencia sobrevive para la reparación (D22): si la coherencia mueve
        # un borde en modo superficie, la referencia —que es de la calzada, no del borde— sigue
        # siendo válida y evita recalcular el ajuste.
        '_reference_cross': (edges.get('reference') or {}).get('cross_slope')
                            if params.get('edge_mode') == 'surface' else None,
    }


def _edge_point(midpoint, normal, offsets, index):
    if index is None:
        return None
    mx, my = midpoint
    nx, ny = normal
    d = offsets[index]
    return (mx + d * nx, my + d * ny)


def analyze(dem_path, vertices, params, progress_callback=None, should_cancel=None,
           orthophoto_path=None):
    """Ejecuta el análisis completo y devuelve `{'segments': [...], 'summary': {...}}`.

    No persiste nada ni conoce la tarea: eso es cosa de `run_analysis`. Separarlo es lo que permite
    ejercitar el pipeline entero en un test sin montar el andamiaje del worker.

    `orthophoto_path` solo se usa en modo `segmentation` (`007/FR-005`); se ignora en los otros dos
    modos aunque se pase. Un fallo de la etapa de segmentación —librería ausente, `gdalwarp`
    ausente, sin red para el modelo— se propaga como cualquier otra excepción de este pipeline:
    `run_analysis` ya la captura y marca el análisis como `failed` (`research.md` D28, caso 1).
    """
    started = time.time()

    def canceled():
        """Un chequeo de cancelación que falla no debe abortar un pipeline por lo demás sano:
        bajo `CELERY_TASK_ALWAYS_EAGER` no hay backend de resultados y esto revienta."""
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False

    segmentation_mode = params.get('edge_mode') == 'segmentation'
    if segmentation_mode and not orthophoto_path:
        raise RuntimeError('orthophoto_path is required for segmentation mode')

    with contextlib.ExitStack() as stack:
        ds = stack.enter_context(rasterio.open(dem_path))
        unit_factor = get_rasterio_to_meters_factor(ds)
        resolution = min(abs(ds.res[0]), abs(ds.res[1]))

        seg_len_native = params['segment_length'] / unit_factor
        half_width_native = params['search_half_width'] / unit_factor
        step_native = params['sample_step'] / unit_factor

        spacing_native = (params.get('cross_section_spacing') or 0.0) / unit_factor

        coords = geometry.project_vertices(vertices, ds.crs)
        segments = geometry.segmentize(coords, seg_len_native)
        offsets = geometry.cross_section_offsets(half_width_native, step_native)
        cum = geometry.cumulative_stations(coords)

        for segment in segments:
            segment['_stations'] = _axis_stations(segment['station_start'],
                                                  segment['station_end'], step_native)
            # Con el espaciado apagado esto devuelve exactamente el punto medio que `segmentize`
            # ya había calculado: una transversal por tramo, como siempre.
            segment['_section_midpoints'] = [
                geometry.point_at_station(coords, cum, station)[0]
                for station in geometry.section_stations(segment['station_start'],
                                                         segment['station_end'], spacing_native)]

        # Fase de segmentación (`007/FR-005`, `FR-008`; `research.md` D25, D26, D27): corre una
        # sola vez para todo el eje, antes del bucle de bloques, y no cuando el modo es otro.
        mask_ds = None
        mask_document = None
        if segmentation_mode:
            def _segmentation_progress(text, perc):
                if progress_callback is not None:
                    progress_callback(text, min(max(perc, 0.0), 100.0) * SEGMENTATION_PROGRESS_SHARE)

            with rasterio.open(orthophoto_path) as ortho_ds:
                ortho_crs = ortho_ds.crs
            corridor = segmentation.build_corridor(vertices, params['search_half_width'],
                                                   ortho_crs)
            mask_path = segmentation.run_segmentation(
                orthophoto_path, corridor, progress_callback=_segmentation_progress)
            mask_ds = stack.enter_context(rasterio.open(mask_path))
            # Vectorizado del ráster que se acaba de escribir (`008` FR-001, `research.md` D34):
            # el mismo fichero que el bucle de abajo muestrea, sin una segunda pasada del modelo.
            # Barato frente a la inferencia: 0,036 s contra 13,49 s en el corredor de 293 m.
            mask_document = segmentation.vectorize_mask(mask_path)

        block = block_size_for(seg_len_native, half_width_native, resolution)
        total_samples = 0
        results = []

        # La reparación necesita ver todos los tramos a la vez y recalcular el bombeo de los que
        # toque, así que cuando está activada se retiene el perfil transversal de cada tramo
        # (D22). Con la ventana a 0 no se retiene nada y la memoria es la de siempre. Peor caso
        # realista: 2.000 tramos x 1.001 muestras ~ 16 MB en float64.
        window = int(params.get('coherence_window') or 0)
        retained = [] if window > 0 else None

        # `007/FR-009`: en modo segmentación el bucle de bloques ocupa el tramo de progreso que
        # deja libre la segmentación, no el 0-100 % completo. En los otros dos modos es igual que
        # siempre: `base_progress = 0`, `loop_share = 1.0`.
        base_progress = SEGMENTATION_PROGRESS_SHARE * 100.0 if segmentation_mode else 0.0
        loop_share = (1.0 - SEGMENTATION_PROGRESS_SHARE) if segmentation_mode else 1.0

        index = 0
        while index < len(segments):
            if canceled():
                raise Canceled()

            size = min(block, len(segments) - index)
            chunk, size = _read_block(ds, segments, index, size, offsets, cum, coords,
                                      mask_ds=mask_ds)
            total_samples += sum(c['axis'].size + c['cross'].size for c in chunk)

            for segment, sampled in zip(segments[index:index + size], chunk):
                metrics = _segment_metrics(segment, offsets, params, unit_factor,
                                           sampled['axis'], sampled['cross'], sampled.get('mask'))
                results.append(_build_segment(segment, metrics, offsets, unit_factor))
                if retained is not None:
                    # El perfil y el punto de la sección representativa, no los del tramo: la
                    # reparación mueve bordes sobre la misma transversal que se reportó.
                    retained.append({
                        'cross': metrics['_cross_row'],
                        'normal': segment['normal'],
                        'midpoint': metrics['_midpoint'],
                        'reference_cross': metrics['_reference_cross'],
                    })

            index += size
            if progress_callback is not None:
                progress_callback('Analizando el camino',
                                  base_progress + loop_share * 100.0 * index / len(segments))

        # La coherencia va antes de la reproyección: mueve puntos de borde, y reproyectar dos
        # veces es justo el coste que la pasada única de abajo evita (D22).
        if retained is not None:
            _apply_coherence(results, retained, offsets, params, unit_factor, window)

        # Una sola reproyección para todos los puntos de todos los tramos: `rasterio.warp.transform`
        # tiene un coste fijo por llamada nada despreciable, y hacerlo por tramo eran cuatro
        # llamadas × miles de tramos.
        _unproject_in_place(results, ds.crs)

    summary = _summarize(results, total_samples, time.time() - started)
    # `mask` es `None` salvo en modo `segmentation`: los otros modos no producen máscara y no deben
    # persistir ninguna (`008` FR-006).
    return {'segments': results, 'summary': summary, 'mask': mask_document}


def _apply_coherence(segments, retained, offsets, params, unit_factor, window):
    """Aplica `coherence.repair_edges` sobre los tramos ya construidos (`006` FR-011..FR-018).

    Trabaja en metros —los offsets de los tramos ya están convertidos— y recompone ancho, estado,
    bombeo y puntos de borde de los tramos que la reparación tocó. Los `no_coverage` quedan fuera
    del todo: sin rasante no hay borde que votar ni que recibir.
    """
    eligible = [s['status'] != STATUS_NO_COVERAGE for s in segments]
    left_seq = [s['offset_left'] if ok else None for s, ok in zip(segments, eligible)]
    right_seq = [s['offset_right'] if ok else None for s, ok in zip(segments, eligible)]

    left_rep, right_rep = coherence.repair_edges(left_seq, right_seq, window)

    step = offsets[1] - offsets[0] if len(offsets) > 1 else 1.0
    surface_mode = params.get('edge_mode') == 'surface'

    for i, (segment, ok) in enumerate(zip(segments, eligible)):
        if not ok:
            continue
        (lo, lsrc), (ro, rsrc) = left_rep[i], right_rep[i]
        segment['left_edge_source'] = lsrc
        segment['right_edge_source'] = rsrc
        if lsrc != coherence.INFERRED and rsrc != coherence.INFERRED:
            continue   # nada cambió en este tramo; los motivos y métricas quedan como estaban

        segment['offset_left'], segment['offset_right'] = lo, ro
        # Los motivos NO se tocan (FR-020): siguen diciendo por qué no hubo borde medido.

        info = retained[i]
        for side, value in (('edge_left', lo), ('edge_right', ro)):
            segment[side] = _offset_point(info, value, unit_factor,
                                          +1 if side == 'edge_left' else -1)

        if lo is None or ro is None:
            segment.update({'width': None, 'cross_slope': None, 'status': STATUS_NO_EDGE})
            continue

        segment['width'] = lo + ro
        segment['status'] = STATUS_INFERRED
        if surface_mode and info['reference_cross'] is not None:
            # D19/D22: la referencia es de la calzada, no del borde — mover el borde no la
            # invalida y el bombeo retenido sigue siendo el correcto.
            segment['cross_slope'] = info['reference_cross']
        else:
            cross_list = _to_list(info['cross'])
            li = _nearest_offset_index(offsets, lo / unit_factor, step)
            ri = _nearest_offset_index(offsets, -ro / unit_factor, step)
            segment['cross_slope'] = profile.cross_slope(offsets, cross_list, li, ri)


def _nearest_offset_index(offsets, d, step):
    index = int(round((d - offsets[0]) / step))
    return max(0, min(len(offsets) - 1, index))


def _offset_point(info, offset_m, unit_factor, sign):
    """Punto `(x, y)` nativo de un borde a `offset_m` metros del eje, o `None`."""
    if offset_m is None:
        return None
    mx, my = info['midpoint']
    nx, ny = info['normal']
    d = sign * offset_m / unit_factor
    return [mx + d * nx, my + d * ny]


def _unproject_in_place(segments, crs):
    """Convierte a EPSG:4326, de una vez, toda la geometría acumulada en `segments`."""
    flat = []
    slots = []
    for segment in segments:
        for key in ('geometry', 'cross_section'):
            for i, point in enumerate(segment[key]):
                slots.append((segment, key, i))
                flat.append(point)
        for key in ('midpoint', 'section_midpoint', 'edge_left', 'edge_right'):
            if segment[key] is not None:
                slots.append((segment, key, None))
                flat.append(segment[key])

    converted = geometry.unproject_points(flat, crs)
    for (segment, key, i), point in zip(slots, converted):
        if i is None:
            segment[key] = point
        else:
            segment[key][i] = point


def _read_block(ds, segments, index, size, offsets, cum, coords, mask_ds=None):
    """Lee de una vez las muestras de `size` tramos desde `index`, partiendo si no caben.

    La estimación analítica de `block_size_for` supone un eje recto; uno curvo genera una ventana
    mayor de lo previsto, así que el tamaño real se vuelve a comprobar aquí antes de leer.

    `mask_ds`, en modo `segmentation`, es la máscara ya abierta (`analyze()`): se muestrea con las
    mismas coordenadas `(xs, ys)` que el DEM, asumiendo que comparten CRS con la ortofoto —cierto
    en el caso normal de un mismo proyecto ODM (`research.md` D25). El particionado de bloques se
    decide en función de `ds`, no de `mask_ds`: es la ventana del DEM la que fija el techo de
    memoria, y la máscara se muestrea punto a punto con su propio transform, sin ventana propia.
    """
    while True:
        chunk = []
        xs_all, ys_all = [], []
        for segment in segments[index:index + size]:
            axis_x, axis_y = geometry.points_at_stations(coords, cum, segment['_stations'])
            # Una tirada de puntos por transversal, concatenadas: `_segment_metrics` las vuelve a
            # separar en filas. La ventana de lectura no crece por medir más veces dentro del mismo
            # tramo —su extensión ya la fijan la longitud del bloque y el semiancho—, así que el
            # dimensionado de `block_size_for` sigue siendo válido.
            cross_xy = []
            for section_midpoint in segment['_section_midpoints']:
                cross_xy.extend(geometry.cross_section_points(section_midpoint,
                                                              segment['normal'], offsets))
            chunk.append({'n_axis': axis_x.size, 'n_cross': len(cross_xy)})
            xs_all.extend(axis_x.tolist() + [p[0] for p in cross_xy])
            ys_all.extend(axis_y.tolist() + [p[1] for p in cross_xy])

        xs = np.asarray(xs_all, dtype='float64')
        ys = np.asarray(ys_all, dtype='float64')

        if size > 1 and _window_pixels(ds, xs, ys) > MAX_WINDOW_PIXELS:
            size = max(1, size // 2)
            continue

        values = _sample(ds, xs, ys)
        mask_values = _sample(mask_ds, xs, ys) if mask_ds is not None else None
        out = []
        cursor = 0
        for entry in chunk:
            n_axis, n_cross = entry['n_axis'], entry['n_cross']
            item = {
                'axis': values[cursor:cursor + n_axis],
                'cross': values[cursor + n_axis:cursor + n_axis + n_cross],
            }
            if mask_values is not None:
                item['mask'] = mask_values[cursor + n_axis:cursor + n_axis + n_cross]
            out.append(item)
            cursor += n_axis + n_cross
        return out, size


def _build_segment(segment, metrics, offsets, unit_factor):
    """Tramo en el esquema de `data-model.md` §6: metros y porcentajes.

    La geometría sale de aquí todavía en el CRS del ráster; `_unproject_in_place` la pasa a
    EPSG:4326 al final, en una sola operación para todos los tramos.
    """
    # Dos puntos distintos, y la distinción importa: `midpoint` es el centro del tramo —donde el
    # cliente planta la regla del ancho, para que las reglas queden regularmente espaciadas— y
    # `section_midpoint` es dónde se midió de verdad, sobre la transversal representativa. La
    # transversal exportada y los puntos de borde salen de esta última: son el dato.
    section_midpoint = metrics['_midpoint']
    cross_ends = geometry.cross_section_points(section_midpoint, segment['normal'],
                                               [offsets[0], offsets[-1]])

    return {
        'index': segment['index'],
        'station_start': segment['station_start'] * unit_factor,
        'station_end': segment['station_end'] * unit_factor,
        'length': segment['length'] * unit_factor,
        'geometry': [list(p) for p in segment['points']],
        'midpoint': list(segment['midpoint']),
        'section_midpoint': list(section_midpoint),
        'elevation': metrics['elevation'],
        'grade': metrics['grade'],
        'grade_deg': metrics['grade_deg'],
        'width': metrics['width'],
        'offset_left': metrics['offset_left'],
        'offset_right': metrics['offset_right'],
        'cross_slope': metrics['cross_slope'],
        'width_sections': metrics['width_sections'],
        'width_measured_sections': metrics['width_measured_sections'],
        'width_min': metrics['width_min'],
        'width_max': metrics['width_max'],
        'status': metrics['status'],
        'left_reason': metrics['left_reason'],
        'right_reason': metrics['right_reason'],
        'left_edge_source': metrics['left_edge_source'],
        'right_edge_source': metrics['right_edge_source'],
        'cross_section': [list(p) for p in cross_ends],
        'edge_left': (list(metrics['_edge_left']) if metrics['_edge_left'] is not None else None),
        'edge_right': (list(metrics['_edge_right']) if metrics['_edge_right'] is not None
                       else None),
    }


def _summarize(segments, samples, duration):
    """Agregados de `data-model.md` §5. Los tramos sin cobertura no aportan a las estadísticas."""
    grades = [s['grade'] for s in segments if s['grade'] is not None]
    widths = [s['width'] for s in segments if s['width'] is not None]

    def stats(values):
        if not values:
            return None, None, None
        return min(values), max(values), sum(values) / len(values)

    min_grade, max_grade, mean_grade = stats(grades)
    min_width, max_width, mean_width = stats(widths)

    return {
        'segment_count': len(segments),
        'measured_count': sum(1 for s in segments if s['status'] == STATUS_MEASURED),
        # Los `inferred` cuentan en las estadísticas de ancho —tienen ancho— pero no como
        # medidos: el agregado no borra la distinción que el tramo declara (`006` data-model §5).
        'inferred_count': sum(1 for s in segments if s['status'] == STATUS_INFERRED),
        'no_edge_count': sum(1 for s in segments if s['status'] == STATUS_NO_EDGE),
        'no_data_count': sum(1 for s in segments
                             if profile.NO_DATA in (s['left_reason'], s['right_reason'])),
        'no_coverage_count': sum(1 for s in segments if s['status'] == STATUS_NO_COVERAGE),
        'length': segments[-1]['station_end'] if segments else 0.0,
        'min_grade': min_grade,
        'max_grade': max_grade,
        'mean_grade': mean_grade,
        'min_width': min_width,
        'max_width': max_width,
        'mean_width': mean_width,
        'samples': int(samples),
        'duration': duration,
    }


def estimate(plan_length, params):
    """Coste previo del análisis, sin tocar el ráster (`research.md` D11).

    Es aritmética pura sobre la longitud del eje, así que responde de inmediato. No existe tope
    que impida lanzar: se estima y se avisa (FR-043).
    """
    segment_length = params['segment_length']
    step = params['sample_step']
    segments = max(1, int(math.ceil(plan_length / segment_length - 1e-9)))
    per_cross = int(math.floor(params['search_half_width'] / step + 1e-9)) * 2 + 1
    axis_samples = int(math.ceil(plan_length / step)) + segments
    # Las transversales por tramo salen del mismo reparto que usa `geometry.section_stations`, o
    # el coste anunciado se quedaría corto justo cuando más importa.
    spacing = params.get('cross_section_spacing') or 0.0
    per_segment = max(1, int(round(segment_length / spacing))) if spacing > 0 else 1
    cross_sections = segments * per_segment
    samples = cross_sections * per_cross + axis_samples
    return {
        'segments': segments,
        'cross_sections': cross_sections,
        'samples': samples,
        'estimated_seconds': samples / SAMPLES_PER_SECOND,
        'warn': samples > WARN_SAMPLES,
    }


def run_analysis(task_id, analysis_id, dem_path, vertices, params, source_mtime=None,
                 progress_callback=None, should_cancel=None, orthophoto_path=None):
    """Función de worker: calcula, persiste los tramos y cierra la entrada del índice.

    IMPORTANTE — debe ser **self-contained**: WebODM la ejecuta reejecutando su código fuente en un
    namespace vacío (`app/plugins/worker.py: eval_async` hace `eval(compile(source), ns, ns)` con
    `ns = {}`), sin los globals del módulo. Por eso todos los imports van **dentro** y son
    **absolutos**, y las funciones y constantes auxiliares se alcanzan a través del módulo
    importado (`compute.*`) — nunca por nombre libre ni con imports relativos (`from . import ...`).
    Mismo patrón que `coreplugins/realign/corrections.py`. `segmentation` no se importa aquí de
    forma directa por el mismo motivo que `coherence` no lo hacía en `006/D23`: entra ya cargado
    por el propio import de `compute`, que lo usa internamente en modo `segmentation`.

    El candado de ejecución se libera **siempre**, salga por donde salga: dejarlo tomado inutiliza
    la funcionalidad para esa tarea hasta que alguien borre el estado a mano.
    """
    import datetime
    from coreplugins.road import compute, store

    def _now():
        return datetime.datetime.utcnow().isoformat() + 'Z'

    def _finish(mutation):
        def mutate(analysis):
            analysis.update(mutation)
            analysis['updated_at'] = _now()
            return analysis
        store.update_analysis(task_id, analysis_id, mutate)

    def _report(status, perc):
        if progress_callback is not None:
            progress_callback(status, perc)
        _finish({'progress': max(0.0, min(1.0, perc / 100.0)), 'status': 'running'})

    try:
        result = compute.analyze(dem_path, vertices, params,
                                 progress_callback=_report, should_cancel=should_cancel,
                                 orthophoto_path=orthophoto_path)
    except compute.Canceled:
        # Sin resultados parciales (FR-034): lo que había a medias no se conserva.
        store.delete_segments(task_id, analysis_id)
        store.delete_mask(task_id, analysis_id)
        _finish({'status': 'canceled', 'progress': None, 'celery_task_id': None})
        store.release_running(task_id, analysis_id)
        return {'canceled': True}
    except Exception as e:
        # Sin esto el análisis se quedaba en 'running' para siempre: el fallo solo vivía en el
        # resultado de Celery, que se pierde al recargar la página.
        store.delete_segments(task_id, analysis_id)
        store.delete_mask(task_id, analysis_id)
        _finish({'status': 'failed', 'progress': None, 'error': str(e),
                 'celery_task_id': None})
        store.release_running(task_id, analysis_id)
        return {'error': str(e)}

    store.write_segments(task_id, analysis_id, {
        'version': store.SCHEMA_VERSION,
        'analysis_id': analysis_id,
        'generated_at': _now(),
        'segments': result['segments'],
    })
    # Máscara del modelo (`008` FR-001): solo la produce el modo `segmentation`, y se guarda aparte
    # del documento de tramos para no encarecer las lecturas que no la usan (`research.md` D35).
    # Sin imports nuevos aquí: esta función es self-contained —`run_function_async` la recompila
    # desde su código fuente en un espacio de nombres vacío— y alcanza `segmentation` a través del
    # import de módulo que ya tiene `compute`, igual que `coherence` en `006`/D23 (`research.md` D41).
    mask_document = result.get('mask')
    has_mask = mask_document is not None
    if has_mask:
        store.write_mask(task_id, analysis_id, {
            'version': store.MASK_SCHEMA_VERSION,
            'analysis_id': analysis_id,
            'generated_at': _now(),
            'resolution_m': mask_document['resolution_m'],
            'simplify_tolerance_m': mask_document['simplify_tolerance_m'],
            'features': mask_document['features'],
        })
    _finish({'status': 'completed', 'progress': None, 'error': None, 'has_mask': has_mask,
             'summary': result['summary'], 'source_mtime': source_mtime,
             'celery_task_id': None})
    store.release_running(task_id, analysis_id)
    return {'segments': result['summary']['segment_count']}
