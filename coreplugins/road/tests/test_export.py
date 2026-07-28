"""Exportación a CSV y GeoJSON (`contracts/rest-api.md`).

Dos formatos con dos destinos distintos: el CSV va a una hoja de cálculo y el GeoJSON a QGIS. Lo
que ambos comparten, y es lo que más se comprueba aquí, es que **una métrica que no se pudo medir
viaja vacía y nunca como cero** (FR-022): un 0 en la columna del ancho es un dato falso que el
usuario promediará sin enterarse.
"""

import csv
import io
import json

from rest_framework import status

from .. import export, store
from .base import RoadTestBase
from .test_api_analyses import AnalysesApiTestBase

ANALYSIS = {
    'id': 'an-1',
    'name': 'Camino norte',
    'axis': {'kind': 'annotation', 'ref': 'a1b2', 'vertices': [[-93.87, 45.0], [-93.86, 45.0]],
             'plan_length': 100.0},
    'model': 'dtm',
    'variant': 'original',
    'params': {'segment_length': 5.0, 'search_half_width': 10.0, 'sample_step': 0.25,
               'break_threshold': 15.0, 'min_consecutive_samples': 3},
    'color_thresholds': [8.0, 12.0],
    'status': 'completed',
}


def segment(index=0, **overrides):
    base = {
        'index': index,
        'station_start': index * 5.0, 'station_end': (index + 1) * 5.0, 'length': 5.0,
        'geometry': [[-93.87, 45.0], [-93.869, 45.0]],
        'midpoint': [-93.8695, 45.0],
        'elevation': 100.5, 'grade': 5.0, 'grade_deg': 2.86,
        'width': 8.0, 'offset_left': 4.0, 'offset_right': 4.0, 'cross_slope': 2.0,
        'status': 'measured', 'left_reason': None, 'right_reason': None,
        'cross_section': [[-93.8697, 45.0], [-93.8693, 45.0]],
        'edge_left': [-93.8696, 45.0], 'edge_right': [-93.8694, 45.0],
    }
    base.update(overrides)
    return base


UNMEASURED = segment(1, status='no_edge', width=None, cross_slope=None, offset_left=None,
                     offset_right=None, left_reason='no_break', right_reason='no_data',
                     edge_left=None, edge_right=None)
NO_COVERAGE = segment(2, status='no_coverage', elevation=None, grade=None, grade_deg=None,
                      width=None, cross_slope=None, offset_left=None, offset_right=None,
                      left_reason='no_data', right_reason='no_data',
                      edge_left=None, edge_right=None)

# Un tramo reparado por la coherencia: la derecha viene de los vecinos, con su motivo original
# conservado (`006` data-model §6, tercera fila de la tabla de combinaciones).
INFERRED = segment(3, status='inferred', width=9.8, offset_left=4.0, offset_right=5.8,
                   left_edge_source='measured', right_edge_source='inferred',
                   right_reason='no_break')


class CsvTest(RoadTestBase):
    def _rows(self, segments):
        text = export.to_csv(ANALYSIS, segments)
        body = [line for line in text.splitlines() if not line.startswith('#')]
        return text, list(csv.reader(io.StringIO('\n'.join(body))))

    def test_header_matches_the_contract(self):
        # Las dos columnas de origen van AL FINAL (`006` FR-033): quien lea por posición de
        # columna no se rompe con la ampliación.
        _text, rows = self._rows([segment(0)])
        self.assertEqual(rows[0], [
            'index', 'station_start', 'station_end', 'length', 'elevation', 'grade_pct',
            'grade_deg', 'width', 'offset_left', 'offset_right', 'cross_slope_pct', 'status',
            'left_reason', 'right_reason', 'left_edge_source', 'right_edge_source'])

    def test_one_row_per_segment(self):
        _text, rows = self._rows([segment(0), UNMEASURED, NO_COVERAGE])
        self.assertEqual(len(rows), 4)   # cabecera + 3 tramos

    def test_missing_cells_are_empty_never_zero(self):
        _text, rows = self._rows([UNMEASURED])
        row = dict(zip(self._rows([segment(0)])[1][0], rows[1]))

        for field in ('width', 'offset_left', 'offset_right', 'cross_slope_pct'):
            self.assertEqual(row[field], '', '{} debería ir vacío, no a cero'.format(field))
        self.assertNotEqual(row['grade_pct'], '')   # la rasante sí se midió

    def test_no_coverage_leaves_elevation_and_grade_empty(self):
        _text, rows = self._rows([NO_COVERAGE])
        header = self._rows([segment(0)])[1][0]
        row = dict(zip(header, rows[1]))

        for field in ('elevation', 'grade_pct', 'grade_deg'):
            self.assertEqual(row[field], '')

    def test_reasons_travel_per_side(self):
        _text, rows = self._rows([UNMEASURED])
        header = self._rows([segment(0)])[1][0]
        row = dict(zip(header, rows[1]))

        self.assertEqual(row['left_reason'], 'no_break')
        self.assertEqual(row['right_reason'], 'no_data')

    def test_parameters_travel_in_a_comment_block(self):
        text, _rows = self._rows([segment(0)])
        comments = '\n'.join(l for l in text.splitlines() if l.startswith('#'))

        self.assertIn('segment_length', comments)
        self.assertIn('break_threshold', comments)
        self.assertIn('dtm', comments)
        self.assertIn('original', comments)
        self.assertIn('Camino norte', comments)

    def test_comment_block_comes_after_the_rows(self):
        # Una hoja de cálculo lee la primera línea como cabecera: un bloque de comentarios delante
        # convierte la columna A en basura al abrir el archivo.
        text = export.to_csv(ANALYSIS, [segment(0)])
        lines = [l for l in text.splitlines() if l.strip()]

        self.assertFalse(lines[0].startswith('#'))
        self.assertTrue(lines[-1].startswith('#'))


class CsvEdgeSourceTest(RoadTestBase):
    """El origen de cada borde viaja como dato (`006` FR-033, SC-005)."""

    def _row(self, seg):
        text = export.to_csv(ANALYSIS, [seg])
        body = [l for l in text.splitlines() if not l.startswith('#')]
        rows = list(csv.reader(io.StringIO('\n'.join(body))))
        return dict(zip(rows[0], rows[1]))

    def test_an_inferred_side_says_so_and_keeps_its_reason(self):
        row = self._row(INFERRED)

        self.assertEqual(row['left_edge_source'], 'measured')
        self.assertEqual(row['right_edge_source'], 'inferred')
        self.assertEqual(row['right_reason'], 'no_break')     # el motivo no se borra
        self.assertEqual(row['offset_right'], '5.800')        # y la distancia existe
        self.assertEqual(row['status'], 'inferred')

    def test_a_segment_without_edges_has_empty_sources(self):
        row = self._row(UNMEASURED)
        self.assertEqual(row['left_edge_source'], '')
        self.assertEqual(row['right_edge_source'], '')

    def test_a_pre_feature_document_exports_without_the_fields_crashing(self):
        # Un documento guardado antes de esta feature no trae las claves de origen: el export las
        # deja vacías en vez de reventar (FR-024).
        old = segment(0)
        row = self._row(old)
        self.assertEqual(row['left_edge_source'], '')

    def test_the_new_params_travel_in_the_comment_block(self):
        analysis = dict(ANALYSIS)
        analysis['params'] = dict(ANALYSIS['params'], edge_mode='surface',
                                  surface_tolerance=0.06, coherence_window=2)
        text = export.to_csv(analysis, [segment(0)])
        comments = '\n'.join(l for l in text.splitlines() if l.startswith('#'))

        self.assertIn('edge_mode: surface', comments)
        self.assertIn('surface_tolerance', comments)
        self.assertIn('coherence_window', comments)


class GeoJsonTest(RoadTestBase):
    def _doc(self, segments):
        return json.loads(export.to_geojson(ANALYSIS, segments))

    def test_is_a_valid_feature_collection(self):
        doc = self._doc([segment(0)])
        self.assertEqual(doc['type'], 'FeatureCollection')
        self.assertIsInstance(doc['features'], list)

    def test_three_families_of_features(self):
        doc = self._doc([segment(0)])
        kinds = sorted({f['properties']['kind'] for f in doc['features']})
        self.assertEqual(kinds, ['cross_section', 'edge', 'segment'])

    def test_segment_feature_carries_every_metric(self):
        doc = self._doc([segment(0)])
        feature = next(f for f in doc['features'] if f['properties']['kind'] == 'segment')

        self.assertEqual(feature['geometry']['type'], 'LineString')
        for field in ('grade', 'width', 'cross_slope', 'status', 'elevation', 'station_start'):
            self.assertIn(field, feature['properties'])

    def test_cross_section_is_a_two_point_line_referring_to_its_segment(self):
        doc = self._doc([segment(3)])
        feature = next(f for f in doc['features'] if f['properties']['kind'] == 'cross_section')

        self.assertEqual(feature['geometry']['type'], 'LineString')
        self.assertEqual(len(feature['geometry']['coordinates']), 2)
        self.assertEqual(feature['properties']['index'], 3)

    def test_edges_are_points_with_their_side(self):
        doc = self._doc([segment(0)])
        edges = [f for f in doc['features'] if f['properties']['kind'] == 'edge']

        self.assertEqual(len(edges), 2)
        self.assertEqual(sorted(f['properties']['side'] for f in edges), ['left', 'right'])
        for f in edges:
            self.assertEqual(f['geometry']['type'], 'Point')

    def test_absent_edges_produce_no_point(self):
        doc = self._doc([UNMEASURED])
        self.assertEqual([f for f in doc['features'] if f['properties']['kind'] == 'edge'], [])

    def test_missing_metrics_are_null_never_zero(self):
        doc = self._doc([UNMEASURED])
        feature = next(f for f in doc['features'] if f['properties']['kind'] == 'segment')

        self.assertIsNone(feature['properties']['width'])
        self.assertIsNone(feature['properties']['cross_slope'])

    def test_segment_features_carry_the_edge_sources(self):
        doc = self._doc([INFERRED])
        feature = next(f for f in doc['features'] if f['properties']['kind'] == 'segment')

        self.assertEqual(feature['properties']['left_edge_source'], 'measured')
        self.assertEqual(feature['properties']['right_edge_source'], 'inferred')
        self.assertEqual(feature['properties']['status'], 'inferred')

    def test_edge_points_declare_their_source(self):
        # Sin `source` en el punto, en QGIS un borde inferido sería indistinguible de uno medido
        # y se daría por medido lo que no lo está (`006` FR-033).
        doc = self._doc([INFERRED])
        edges = {f['properties']['side']: f for f in doc['features']
                 if f['properties']['kind'] == 'edge'}

        self.assertEqual(edges['left']['properties']['source'], 'measured')
        self.assertEqual(edges['right']['properties']['source'], 'inferred')

    def test_parameters_travel_in_the_collection_properties(self):
        doc = self._doc([segment(0)])
        props = doc['properties']

        self.assertEqual(props['model'], 'dtm')
        self.assertEqual(props['variant'], 'original')
        self.assertEqual(props['params']['segment_length'], 5.0)
        self.assertEqual(props['name'], 'Camino norte')


class FilenameTest(RoadTestBase):
    def test_filename_carries_task_and_analysis_slugified(self):
        name = export.filename('Camino Ñandú / km 0-1', 'Análisis 2!', 'csv')

        self.assertTrue(name.endswith('-road.csv'))
        self.assertNotIn(' ', name)
        self.assertNotIn('/', name)
        self.assertIn('camino', name)

    def test_empty_names_still_produce_a_usable_filename(self):
        self.assertTrue(export.filename('', '', 'geojson').endswith('-road.geojson'))


class ExportEndpointTest(AnalysesApiTestBase):
    def _completed(self, task):
        return self._create(task).data['analysis_id']

    def test_csv_download_has_attachment_disposition(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._completed(task)

        res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                              {'format': 'csv'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('attachment', res['Content-Disposition'])
        self.assertIn('-road.csv', res['Content-Disposition'])
        # 14 columnas de `005` + las dos de origen que `006` añade al final (FR-033).
        self.assertEqual(len(res.content.decode().splitlines()[0].split(',')), 16)

    def test_geojson_download_parses(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._completed(task)

        res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                              {'format': 'geojson'})

        doc = json.loads(res.content.decode())
        self.assertEqual(doc['type'], 'FeatureCollection')
        self.assertEqual(len([f for f in doc['features']
                              if f['properties']['kind'] == 'segment']), 20)

    def test_unknown_format_is_rejected(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._completed(task)

        res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                              {'format': 'shp'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_parameter')

    def test_missing_segments_file_reports_result_missing(self):
        task = self._task_with_dem()
        self._login()
        analysis_id = self._completed(task)
        store.delete_segments(str(task.id), analysis_id)

        res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                              {'format': 'csv'})

        self.assertEqual(res.status_code, status.HTTP_410_GONE)
        self.assertEqual(res.data['code'], 'result_missing')

    def test_unknown_analysis_is_not_found(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.get(self._url(task, 'analyses/nope/export'), {'format': 'csv'})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_export_only_needs_read_access(self):
        # Descargar no modifica nada: un usuario con solo lectura debe poder llevarse el resultado.
        task = self._task_with_dem()
        self._login()
        analysis_id = self._completed(task)

        self._grant_read_only('testuser2', task.project)
        self.client.logout()
        self._login('testuser2')
        res = self.client.get(self._url(task, 'analyses/{}/export'.format(analysis_id)),
                              {'format': 'csv'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
