"""Exportación del análisis a CSV y GeoJSON (`contracts/rest-api.md`, FR-033).

Dos formatos porque son dos destinos: el CSV se abre en una hoja de cálculo para hacer cuentas por
tramo, y el GeoJSON en QGIS para verlo sobre el terreno junto al resto de la cartografía.

Regla que atraviesa los dos: **una métrica que no se pudo medir viaja vacía, nunca como cero**
(FR-022). Un `0` en la columna del ancho es un dato falso que el usuario promediará sin enterarse,
y el promedio resultante será menor que el real justo en los caminos peor cubiertos.
"""

import csv
import io
import json

from django.utils.text import slugify

CSV_COLUMNS = [
    'index', 'station_start', 'station_end', 'length', 'elevation', 'grade_pct', 'grade_deg',
    'width', 'offset_left', 'offset_right', 'cross_slope_pct', 'status', 'left_reason',
    'right_reason',
]

# De qué campo del tramo sale cada columna, cuando el nombre no coincide.
CSV_SOURCE = {
    'grade_pct': 'grade',
    'cross_slope_pct': 'cross_slope',
}

DECIMALS = 3


def filename(task_name, analysis_name, extension):
    """`<tarea>-<análisis>-road.<ext>`, con ambas partes pasadas por `slugify`."""
    task_slug = slugify(task_name or '') or 'tarea'
    analysis_slug = slugify(analysis_name or '') or 'analisis'
    return '{}-{}-road.{}'.format(task_slug, analysis_slug, extension)


def _cell(value):
    if value is None:
        return ''
    if isinstance(value, float):
        return '{:.{}f}'.format(value, DECIMALS)
    return value


def _parameter_lines(analysis):
    """Bloque de comentarios con el contexto del cálculo (FR-033).

    Sin esto, un CSV suelto en el escritorio de alguien es una tabla de números sin unidad ni
    procedencia: no dice de qué camino es, sobre qué modelo se midió, ni con qué umbral de quiebre
    —que es justo el parámetro del que depende la columna del ancho.
    """
    axis = analysis.get('axis') or {}
    params = analysis.get('params') or {}
    lines = [
        '# analisis: {}'.format(analysis.get('name', '')),
        '# eje: {} ({}), longitud en planta {} m'.format(
            axis.get('ref', ''), axis.get('kind', ''), _cell(axis.get('plan_length'))),
        '# modelo: {} / {}'.format(analysis.get('model', ''), analysis.get('variant', '')),
    ]
    lines += ['# {}: {}'.format(key, params[key]) for key in sorted(params)]
    lines.append('# unidades: distancias en m, pendientes en %, grade_deg en grados')
    lines.append('# las celdas vacias son metricas que no se pudieron medir, no ceros')
    return lines


def to_csv(analysis, segments):
    """CSV con una fila por tramo y el bloque de parámetros **al final**.

    El bloque va detrás y no delante porque una hoja de cálculo interpreta la primera línea como
    cabecera: unos comentarios por delante convierten la columna A en basura al abrir el archivo.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerow(CSV_COLUMNS)

    for segment in segments:
        writer.writerow([_cell(segment.get(CSV_SOURCE.get(column, column)))
                         for column in CSV_COLUMNS])

    for line in _parameter_lines(analysis):
        buffer.write(line + '\n')

    return buffer.getvalue()


def _segment_feature(segment):
    properties = {'kind': 'segment'}
    properties.update({key: segment.get(key) for key in (
        'index', 'station_start', 'station_end', 'length', 'elevation', 'grade', 'grade_deg',
        'width', 'offset_left', 'offset_right', 'cross_slope', 'status', 'left_reason',
        'right_reason')})
    return {
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': segment['geometry']},
        'properties': properties,
    }


def _cross_section_feature(segment):
    return {
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': segment['cross_section']},
        'properties': {'kind': 'cross_section', 'index': segment['index']},
    }


def _edge_features(segment):
    features = []
    for side in ('left', 'right'):
        point = segment.get('edge_{}'.format(side))
        if point is None:
            continue
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': point},
            'properties': {'kind': 'edge', 'index': segment['index'], 'side': side},
        })
    return features


def to_geojson(analysis, segments):
    """`FeatureCollection` con tres familias de entidades, distinguibles por `kind`.

    Las tres viajan juntas para que QGIS abra un solo archivo y el usuario pueda filtrar por `kind`
    y estilar cada familia por su cuenta: el tramo dice dónde y cuánto, la transversal dice qué se
    recorrió para medirlo, y los puntos de borde dicen dónde acabó la calzada.
    """
    features = []
    for segment in segments:
        features.append(_segment_feature(segment))
        features.append(_cross_section_feature(segment))
        features.extend(_edge_features(segment))

    # El miembro `properties` en el objeto raíz es una extensión que RFC 7946 admite en un
    # `FeatureCollection`: es donde caben los parámetros del cálculo sin repetirlos por entidad.
    return json.dumps({
        'type': 'FeatureCollection',
        'properties': {
            'name': analysis.get('name'),
            'analysis_id': analysis.get('id'),
            'axis': analysis.get('axis', {}).get('ref'),
            'axis_kind': analysis.get('axis', {}).get('kind'),
            'model': analysis.get('model'),
            'variant': analysis.get('variant'),
            'params': analysis.get('params'),
            'summary': analysis.get('summary'),
        },
        'features': features,
    })
