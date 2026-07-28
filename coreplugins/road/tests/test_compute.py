"""Pipeline completo sobre el DEM sintético (`research.md` D2; invariantes de `data-model.md` §6).

El camino del DEM sintético tiene 8 m de ancho exactos, 5 % de pendiente longitudinal y 2 % de
peralte, así que aquí no se comprueba que el resultado sea plausible sino que sea **ese**. Los
invariantes de coherencia se verifican sobre todos los tramos de todos los casos: son la
definición de un resultado que el frontend puede dibujar sin adivinar.
"""

from django.test import SimpleTestCase

from .. import compute, sources
from .base import DEM_RES, RoadTestBase, axis_vertices

PARAMS = {
    'segment_length': 5.0,
    'search_half_width': 10.0,
    'sample_step': DEM_RES,
    'break_threshold': 15.0,
    'min_consecutive_samples': 3,
}


def assert_segment_invariants(case, segment):
    """Coherencia obligatoria de `data-model.md` §6, verificable en todos los tramos."""
    status = segment['status']
    measured = ('width', 'offset_left', 'offset_right', 'cross_slope')

    if status == 'measured':
        for field in measured:
            case.assertIsNotNone(segment[field], '{} vacío en un tramo measured'.format(field))
        case.assertIsNone(segment['left_reason'])
        case.assertIsNone(segment['right_reason'])
        case.assertAlmostEqual(segment['width'],
                               segment['offset_left'] + segment['offset_right'], places=9)
    elif status == 'no_edge':
        case.assertIsNone(segment['width'])
        case.assertIsNone(segment['cross_slope'])
        case.assertTrue(segment['left_reason'] or segment['right_reason'])
    elif status == 'no_coverage':
        case.assertIsNone(segment['elevation'])
        case.assertIsNone(segment['grade'])
        case.assertIsNone(segment['grade_deg'])
    else:
        case.fail('status desconocido: {}'.format(status))

    # El lado con borde conserva su distancia aunque el otro no lo tenga.
    for side in ('left', 'right'):
        if segment['{}_reason'.format(side)] is None and status != 'no_coverage':
            case.assertIsNotNone(segment['offset_{}'.format(side)])
        else:
            case.assertIsNone(segment['offset_{}'.format(side)])

    case.assertEqual(len(segment['cross_section']), 2)
    case.assertGreaterEqual(len(segment['geometry']), 2)


class ComputeTestBase(RoadTestBase):
    def _analyze(self, dem_kwargs=None, params=None, vertices=None, **task_kwargs):
        task = self._task_with_dem(dem_kwargs=dem_kwargs, **task_kwargs)
        path = sources.original_path(task, 'dtm')
        return compute.analyze(path, vertices or axis_vertices(), dict(PARAMS, **(params or {})))


class PipelineTest(ComputeTestBase):
    def test_segment_count_and_coverage_match_the_axis(self):
        result = self._analyze()
        segments = result['segments']

        self.assertEqual(len(segments), 20)   # 100 m de eje en tramos de 5 m
        self.assertAlmostEqual(segments[0]['station_start'], 0.0, places=6)
        self.assertAlmostEqual(segments[-1]['station_end'], 100.0, places=3)
        for previous, current in zip(segments, segments[1:]):
            self.assertAlmostEqual(previous['station_end'], current['station_start'], places=9)

    def test_width_is_exact_on_the_known_road(self):
        segments = self._analyze()['segments']

        for segment in segments:
            self.assertEqual(segment['status'], 'measured')
            self.assertAlmostEqual(segment['width'], 8.0, places=6)
            self.assertAlmostEqual(segment['offset_left'], 4.0, places=6)
            self.assertAlmostEqual(segment['offset_right'], 4.0, places=6)

    def test_longitudinal_grade_is_exact(self):
        segments = self._analyze()['segments']
        for segment in segments:
            self.assertAlmostEqual(segment['grade'], 5.0, places=4)

    def test_cross_slope_recovers_the_camber(self):
        segments = self._analyze()['segments']
        for segment in segments:
            self.assertAlmostEqual(segment['cross_slope'], 2.0, places=4)

    def test_asymmetric_road_reports_each_side(self):
        segments = self._analyze(dem_kwargs={'half_width_left': 3.0,
                                             'half_width_right': 5.5})['segments']
        for segment in segments:
            self.assertAlmostEqual(segment['offset_left'], 3.0, places=6)
            self.assertAlmostEqual(segment['offset_right'], 5.5, places=6)
            self.assertAlmostEqual(segment['width'], 8.5, places=6)

    def test_road_without_taludes_is_no_edge_with_a_reason_per_side(self):
        segments = self._analyze(dem_kwargs={'talud': 0.0, 'cross_slope': 0.0})['segments']

        for segment in segments:
            self.assertEqual(segment['status'], 'no_edge')
            self.assertIsNone(segment['width'])
            self.assertEqual(segment['left_reason'], 'no_break')
            self.assertEqual(segment['right_reason'], 'no_break')
            # La pendiente longitudinal sigue midiéndose: no tener bordes no impide tener rasante.
            self.assertIsNotNone(segment['grade'])

    def test_segment_without_dem_coverage_is_no_coverage(self):
        # Franja de `nodata` que cruza el eje entre las progresivas 40 y 44,75.
        segments = self._analyze(dem_kwargs={'nodata_patch': (200, 220, 0, 480)})['segments']
        no_coverage = [s for s in segments if s['status'] == 'no_coverage']

        self.assertEqual([s['index'] for s in no_coverage], [8])
        self.assertIsNone(no_coverage[0]['elevation'])
        self.assertIsNone(no_coverage[0]['grade'])

    def test_axis_off_the_roadway_is_no_edge_not_a_zero_width_road(self):
        # Calzada de ancho nulo: el terreno cae desde el propio eje. Es la forma que tiene el DEM
        # cuando el trazado no pasa por el camino, y lo que antes producía `width: 0.0` marcado
        # como `measured` con la pendiente transversal vacía.
        segments = self._analyze(dem_kwargs={'half_width_left': 0.0,
                                             'half_width_right': 0.0})['segments']

        for segment in segments:
            self.assertEqual(segment['status'], 'no_edge')
            self.assertIsNone(segment['width'])
            self.assertIsNone(segment['cross_slope'])
            self.assertEqual(segment['left_reason'], 'break_at_axis')
            self.assertEqual(segment['right_reason'], 'break_at_axis')

    def test_all_segments_satisfy_the_data_model_invariants(self):
        for dem_kwargs in ({}, {'talud': 0.0}, {'nodata_patch': (200, 220, 0, 480)},
                           {'half_width_left': 3.0, 'half_width_right': 5.5},
                           {'half_width_left': 0.0, 'half_width_right': 0.0},
                           {'noise': 0.05}):
            with self.subTest(dem=dem_kwargs):
                for segment in self._analyze(dem_kwargs=dem_kwargs)['segments']:
                    assert_segment_invariants(self, segment)

    def test_geometry_and_midpoint_come_back_in_wgs84(self):
        segment = self._analyze()['segments'][0]

        for lng, lat in segment['geometry'] + [segment['midpoint']]:
            self.assertTrue(-180.0 <= lng <= 180.0)
            self.assertTrue(-90.0 <= lat <= 90.0)

    def test_edges_are_reported_as_points_for_the_export(self):
        segment = self._analyze()['segments'][0]

        self.assertEqual(len(segment['edge_left']), 2)
        self.assertEqual(len(segment['edge_right']), 2)

    def test_noise_does_not_break_the_measurement(self):
        # 1 cm de ruido: el ancho se mantiene y la pendiente no se dispara, que es lo que compra
        # el ajuste por mínimos cuadrados frente a la diferencia entre extremos.
        segments = self._analyze(dem_kwargs={'noise': 0.01})['segments']
        measured = [s for s in segments if s['status'] == 'measured']

        self.assertGreaterEqual(len(measured), 18)
        for segment in measured:
            self.assertAlmostEqual(segment['width'], 8.0, delta=0.5)
            self.assertAlmostEqual(segment['grade'], 5.0, delta=1.0)


class SummaryTest(ComputeTestBase):
    def test_summary_counts_add_up(self):
        summary = self._analyze()['summary']

        self.assertEqual(summary['segment_count'], 20)
        self.assertEqual(summary['measured_count'], 20)
        self.assertEqual(summary['no_edge_count'], 0)
        self.assertEqual(summary['no_coverage_count'], 0)
        self.assertAlmostEqual(summary['length'], 100.0, places=3)
        self.assertGreater(summary['samples'], 0)

    def test_summary_aggregates_grade_and_width(self):
        summary = self._analyze()['summary']

        self.assertAlmostEqual(summary['mean_grade'], 5.0, places=4)
        self.assertAlmostEqual(summary['min_width'], 8.0, places=6)
        self.assertAlmostEqual(summary['max_width'], 8.0, places=6)

    def test_width_aggregates_are_null_without_any_measured_segment(self):
        summary = self._analyze(dem_kwargs={'talud': 0.0})['summary']

        self.assertEqual(summary['measured_count'], 0)
        self.assertIsNone(summary['mean_width'])
        self.assertIsNone(summary['min_width'])

    def test_no_coverage_segments_do_not_pollute_grade_statistics(self):
        summary = self._analyze(dem_kwargs={'nodata_patch': (200, 220, 0, 480)})['summary']

        self.assertEqual(summary['no_coverage_count'], 1)
        self.assertAlmostEqual(summary['mean_grade'], 5.0, places=3)


class ProgressAndCancelTest(ComputeTestBase):
    def test_progress_is_reported_and_monotonic(self):
        reported = []
        task = self._task_with_dem()
        compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(), dict(PARAMS),
                        progress_callback=lambda status, perc: reported.append(perc))

        self.assertTrue(reported)
        self.assertEqual(reported, sorted(reported))
        self.assertLessEqual(reported[-1], 100.0)

    def test_cancellation_stops_the_pipeline(self):
        task = self._task_with_dem()
        with self.assertRaises(compute.Canceled):
            compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(), dict(PARAMS),
                            should_cancel=lambda: True)

    def test_a_failing_cancel_check_does_not_abort_a_healthy_run(self):
        # Bajo CELERY_TASK_ALWAYS_EAGER no hay backend de resultados y `should_cancel` revienta.
        def boom():
            raise RuntimeError('sin backend de resultados')

        task = self._task_with_dem()
        result = compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(),
                                 dict(PARAMS), should_cancel=boom)
        self.assertEqual(len(result['segments']), 20)


class BlockingTest(SimpleTestCase):
    def test_block_size_shrinks_to_respect_the_memory_cap(self):
        # Una ventana enorme no debe leerse de una vez: el DEM de un vuelo grande no cabe
        # cómodamente en la memoria del worker.
        big = compute.block_size_for(segment_length=5.0, half_width=10.0, resolution=0.05,
                                     max_pixels=100000)
        small = compute.block_size_for(segment_length=5.0, half_width=10.0, resolution=1.0,
                                       max_pixels=100000)

        self.assertGreaterEqual(big, 1)
        self.assertGreater(small, big)


class RunAnalysisPersistenceTest(RoadTestBase):
    def test_run_analysis_writes_segments_and_finishes_the_index_entry(self):
        from .. import store

        task = self._task_with_dem()
        analysis_id = 'analysis-1'
        store.upsert_analysis(str(task.id), {
            'id': analysis_id, 'name': 'Camino', 'status': 'running', 'progress': 0.0,
            'model': 'dtm', 'variant': 'original', 'params': dict(PARAMS),
            'axis': {'kind': 'annotation', 'ref': 'a1', 'vertices': axis_vertices(),
                     'plan_length': 100.0},
        })
        store.acquire_running(str(task.id), analysis_id)

        compute.run_analysis(str(task.id), analysis_id, sources.original_path(task, 'dtm'),
                             axis_vertices(), dict(PARAMS))

        analysis = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(analysis['status'], 'completed')
        self.assertIsNone(analysis['progress'])
        self.assertEqual(analysis['summary']['segment_count'], 20)
        self.assertIsNone(store.get_running(str(task.id)))

        document = store.read_segments(str(task.id), analysis_id)
        self.assertEqual(len(document['segments']), 20)

    def test_failure_marks_the_analysis_and_releases_the_lock(self):
        from .. import store

        task = self._task_with_dem()
        analysis_id = 'analysis-2'
        store.upsert_analysis(str(task.id), {'id': analysis_id, 'status': 'running',
                                             'model': 'dtm', 'variant': 'original'})
        store.acquire_running(str(task.id), analysis_id)

        compute.run_analysis(str(task.id), analysis_id, '/no/existe.tif', axis_vertices(),
                             dict(PARAMS))

        analysis = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(analysis['status'], 'failed')
        self.assertTrue(analysis['error'])
        self.assertIsNone(store.get_running(str(task.id)))
        self.assertIsNone(store.read_segments(str(task.id), analysis_id))

    def test_cancellation_leaves_no_partial_result(self):
        from .. import store

        task = self._task_with_dem()
        analysis_id = 'analysis-3'
        store.upsert_analysis(str(task.id), {'id': analysis_id, 'status': 'running',
                                             'model': 'dtm', 'variant': 'original'})
        store.acquire_running(str(task.id), analysis_id)

        compute.run_analysis(str(task.id), analysis_id, sources.original_path(task, 'dtm'),
                             axis_vertices(), dict(PARAMS), should_cancel=lambda: True)

        analysis = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(analysis['status'], 'canceled')
        self.assertIsNone(store.read_segments(str(task.id), analysis_id))
        self.assertIsNone(store.get_running(str(task.id)))
