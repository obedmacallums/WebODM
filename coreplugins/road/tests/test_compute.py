"""Pipeline completo sobre el DEM sintético (`research.md` D2; invariantes de `data-model.md` §6).

El camino del DEM sintético tiene 8 m de ancho exactos, 5 % de pendiente longitudinal y 2 % de
peralte, así que aquí no se comprueba que el resultado sea plausible sino que sea **ese**. Los
invariantes de coherencia se verifican sobre todos los tramos de todos los casos: son la
definición de un resultado que el frontend puede dibujar sin adivinar.
"""

from django.test import SimpleTestCase

from .. import compute, sources
from .base import (AXIS_STATION_OFFSET, DEM_EPSG, DEM_ORIGIN, DEM_RES, DEM_SIZE, ROAD_COL,
                   RoadTestBase, axis_vertices, road_center_x)

PARAMS = {
    'segment_length': 5.0,
    'search_half_width': 10.0,
    'sample_step': DEM_RES,
    'break_threshold': 15.0,
    'min_consecutive_samples': 3,
}


def assert_segment_invariants(case, segment):
    """Coherencia obligatoria de `data-model.md` §6 de `006`, verificable en todos los tramos."""
    status = segment['status']
    measured = ('width', 'offset_left', 'offset_right', 'cross_slope')
    sources = (segment['left_edge_source'], segment['right_edge_source'])

    if status == 'measured':
        for field in measured:
            case.assertIsNotNone(segment[field], '{} vacío en un tramo measured'.format(field))
        case.assertIsNone(segment['left_reason'])
        case.assertIsNone(segment['right_reason'])
        case.assertEqual(sources, ('measured', 'measured'))
        case.assertAlmostEqual(segment['width'],
                               segment['offset_left'] + segment['offset_right'], places=9)
    elif status == 'inferred':
        # Hay ancho ⟺ hay dos bordes, sea cual sea su origen; el estado declara que al menos
        # uno es deducido (`006` FR-021, FR-022).
        for field in measured:
            case.assertIsNotNone(segment[field], '{} vacío en un tramo inferred'.format(field))
        case.assertIn('inferred', sources)
        case.assertAlmostEqual(segment['width'],
                               segment['offset_left'] + segment['offset_right'], places=9)
    elif status == 'no_edge':
        case.assertIsNone(segment['width'])
        case.assertIsNone(segment['cross_slope'])
        case.assertTrue(segment['left_reason'] or segment['right_reason'])
        case.assertIn(None, sources)
    elif status == 'no_coverage':
        case.assertIsNone(segment['elevation'])
        case.assertIsNone(segment['grade'])
        case.assertIsNone(segment['grade_deg'])
    else:
        case.fail('status desconocido: {}'.format(status))

    for side in ('left', 'right'):
        offset = segment['offset_{}'.format(side)]
        source = segment['{}_edge_source'.format(side)]
        # Origen nulo ⟺ distancia nula: no hay borde sin origen ni origen sin borde.
        case.assertEqual(offset is None, source is None,
                         'offset y edge_source inconsistentes en el lado {}'.format(side))
        # El lado sin motivo tiene borde (posiblemente sustituido); el motivo, en cambio, ya no
        # implica ausencia de distancia: puede convivir con un valor inferido (`006` FR-020).
        if segment['{}_reason'.format(side)] is None and status != 'no_coverage':
            case.assertIsNotNone(offset)

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

    def test_one_section_per_segment_is_still_the_default(self):
        # Sin `cross_section_spacing` no cambia nada: una transversal por tramo, en su punto medio.
        segments = self._analyze()['segments']

        for segment in segments:
            self.assertEqual(segment['width_sections'], 1)
            self.assertEqual(segment['width_measured_sections'], 1)
            self.assertAlmostEqual(segment['width_min'], segment['width'], places=9)
            self.assertAlmostEqual(segment['width_max'], segment['width'], places=9)

    def test_a_single_defect_at_the_midpoint_hijacks_the_whole_segment(self):
        """El fallo que esto viene a corregir, dejado por escrito: con una sola transversal, un
        estrechamiento de 1 m que caiga justo en el punto medio se lleva los 5 m del tramo."""
        # Camino de 8 m estrechado a 4 m entre las progresivas 2 y 3 del eje, que contienen el
        # punto medio del primer tramo (2,5) pero no el de ningún otro.
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 2.0, 2.0)
        segments = self._analyze(dem_kwargs={'pinch': pinch})['segments']

        self.assertAlmostEqual(segments[0]['width'], 4.0, places=6)
        self.assertAlmostEqual(segments[1]['width'], 8.0, places=6)

    def test_several_sections_report_the_representative_width(self):
        # El mismo DEM, midiendo cada metro: de las cinco transversales del primer tramo solo una
        # cae en el estrechamiento, así que la mediana devuelve el ancho real.
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 2.0, 2.0)
        segments = self._analyze(dem_kwargs={'pinch': pinch},
                                 params={'cross_section_spacing': 1.0})['segments']

        first = segments[0]
        self.assertEqual(first['width_sections'], 5)
        self.assertAlmostEqual(first['width'], 8.0, places=6)
        # Y el estrechamiento no se pierde: sigue declarado en la dispersión del tramo.
        self.assertAlmostEqual(first['width_min'], 4.0, places=6)
        self.assertAlmostEqual(first['width_max'], 8.0, places=6)

    def test_the_mean_averages_where_the_median_ignores(self):
        """El seleccionable de agregación, para comparar los dos criterios sobre el mismo DEM.
        Anchos [8, 8, 4, 8, 8]: la mediana devuelve 8 y la media 7,2 — el bache arrastra."""
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 2.0, 2.0)
        dem = {'pinch': pinch}

        median = self._analyze(dem_kwargs=dem,
                               params={'cross_section_spacing': 1.0})['segments'][0]
        mean = self._analyze(dem_kwargs=dem,
                             params={'cross_section_spacing': 1.0,
                                     'width_aggregation': 'mean'})['segments'][0]

        self.assertAlmostEqual(median['width'], 8.0, places=6)
        self.assertAlmostEqual(mean['width'], 7.2, places=6)
        # La dispersión no depende del criterio: describe lo medido, no cómo se resume.
        for segment in (median, mean):
            self.assertAlmostEqual(segment['width_min'], 4.0, places=6)
            self.assertAlmostEqual(segment['width_max'], 8.0, places=6)

    def test_the_median_is_the_default_aggregation(self):
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 2.0, 2.0)
        segments = self._analyze(dem_kwargs={'pinch': pinch},
                                 params={'cross_section_spacing': 1.0})['segments']

        self.assertAlmostEqual(segments[0]['width'], 8.0, places=6)

    def test_the_mean_keeps_width_equal_to_both_sides(self):
        """Aunque la media no corresponda a ninguna transversal real, el tramo sigue siendo
        internamente coherente: la regla que se dibuja mide lo que dice el popup."""
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 1.0, 3.0)
        segments = self._analyze(dem_kwargs={'pinch': pinch},
                                 params={'cross_section_spacing': 1.0,
                                         'width_aggregation': 'mean'})['segments']

        for segment in segments:
            if segment['width'] is None:
                continue
            self.assertAlmostEqual(segment['width'],
                                   segment['offset_left'] + segment['offset_right'], places=9)
            self.assertIsNotNone(segment['edge_left'])
            self.assertIsNotNone(segment['edge_right'])

    def test_the_reported_section_is_a_real_one(self):
        """Lo que compra elegir la sección mediana en vez de promediar: todo lo que se reporta
        —ancho, lados, bombeo y puntos de borde— sale de una misma transversal medida."""
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 1.0, 3.0)
        segments = self._analyze(dem_kwargs={'pinch': pinch},
                                 params={'cross_section_spacing': 1.0})['segments']

        for segment in segments:
            if segment['width'] is None:
                continue
            self.assertAlmostEqual(segment['width'],
                                   segment['offset_left'] + segment['offset_right'], places=9)
            self.assertIsNotNone(segment['edge_left'])
            self.assertIsNotNone(segment['edge_right'])

    def test_the_segment_carries_both_its_centre_and_where_it_was_measured(self):
        """`midpoint` es el centro del tramo —donde el cliente dibuja la regla, para que queden
        regularmente espaciadas— y `section_midpoint` dónde se midió de verdad. Con una sola
        transversal coinciden; con varias, no tienen por qué."""
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 2.0, 2.0)

        alone = self._analyze()['segments'][0]
        self.assertEqual(alone['midpoint'], alone['section_midpoint'])

        many = self._analyze(dem_kwargs={'pinch': pinch},
                             params={'cross_section_spacing': 1.0})['segments']
        # El centro del tramo no depende de dónde cayera la mediana: es el mismo con y sin
        # espaciado, y sigue repartiendo el tramo por la mitad.
        for segment, reference in zip(many, self._analyze()['segments']):
            self.assertEqual(segment['midpoint'], reference['midpoint'])
        self.assertNotEqual(many[0]['midpoint'], many[0]['section_midpoint'],
                            'la sección mediana del tramo del bache no es la central')

    def test_measuring_often_rescues_segments_whose_midpoint_has_no_edge(self):
        """La otra ganancia: hoy, si la única transversal falla, el tramo entero se queda sin
        ancho. Con varias basta que una mida."""
        # Sin talud en la franja del punto medio del primer tramo: ahí no hay borde que detectar.
        pinch = (AXIS_STATION_OFFSET + 2.0, AXIS_STATION_OFFSET + 3.0, 40.0, 40.0)

        alone = self._analyze(dem_kwargs={'pinch': pinch})['segments'][0]
        often = self._analyze(dem_kwargs={'pinch': pinch},
                              params={'cross_section_spacing': 1.0})['segments'][0]

        self.assertIsNone(alone['width'], 'la única transversal cae donde no hay borde')
        self.assertAlmostEqual(often['width'], 8.0, places=6)
        self.assertEqual(often['width_sections'], 5)
        self.assertEqual(often['width_measured_sections'], 4, 'la del hueco no mide, las otras sí')

    def test_smoothing_rescues_a_noisy_road_and_off_changes_nothing(self):
        # Ruido sigma=5 cm a paso 0,25 m: la pendiente aparente entre vecinas ronda el 28 % y el
        # umbral por defecto encuentra rachas falsas mucho antes del talud — el síntoma real del
        # camino minero: anchos pocos, pequeños e irregulares. El suavizado de mediana con ventana
        # de 1,25 m (5 muestras) las elimina sin mover el talud. Determinista: el ruido va con
        # semilla fija.
        noisy = {'noise': 0.05, 'cross_slope': 0.0}

        raw = self._analyze(dem_kwargs=noisy)['summary']
        smoothed = self._analyze(dem_kwargs=noisy,
                                 params={'smooth_window': 1.25})['summary']

        self.assertLess(raw['mean_width'] or 0.0, 6.0)
        self.assertAlmostEqual(smoothed['mean_width'], 8.0, delta=1.0)

        # Y apagado (el defecto) es EXACTAMENTE el comportamiento anterior: mismo resultado
        # que un análisis sin el parámetro, tramo a tramo.
        clean = {'cross_slope': 0.0}
        without = self._analyze(dem_kwargs=clean)['segments']
        with_zero = self._analyze(dem_kwargs=clean, params={'smooth_window': 0.0})['segments']
        for a, b in zip(without, with_zero):
            self.assertEqual(a['width'], b['width'])
            self.assertEqual(a['status'], b['status'])

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

    def test_surface_mode_measures_where_break_mode_cannot(self):
        # Un "talud" del 10 % es la rampa en que la fotogrametría convierte un bordillo (`006`
        # D17): por debajo del umbral de quiebre (15 %), pero acumulando separación respecto del
        # plano de calzada. El modo de quiebre no ve nada; el de superficie mide.
        street = {'talud': 0.10}

        broke = self._analyze(dem_kwargs=street)['segments']
        self.assertTrue(all(s['status'] == 'no_edge' for s in broke))

        surfaced = self._analyze(dem_kwargs=street,
                                 params={'edge_mode': 'surface',
                                         'surface_tolerance': 0.06})['segments']
        for segment in surfaced:
            self.assertEqual(segment['status'], 'measured')
            # El borde cae dentro de la rampa, donde la separación supera la tolerancia:
            # entre el pie del bordillo (8 m de calzada) y tolerancia/pendiente más la racha.
            self.assertGreaterEqual(segment['width'], 8.0 - 2 * DEM_RES)
            self.assertLessEqual(segment['width'], 8.0 + 2 * (0.06 / 0.10 + 2 * DEM_RES))
            # D19: el bombeo sale de la referencia ajustada y recupera el peralte conocido.
            self.assertAlmostEqual(segment['cross_slope'], 2.0, delta=0.15)
            assert_segment_invariants(self, segment)

    def test_surface_mode_matches_break_mode_on_the_rural_road(self):
        # Sobre el camino rural sintético (talud del 50 %) los dos criterios deben coincidir:
        # es la medición en pequeño de la pregunta que D24 deja abierta.
        surfaced = self._analyze(params={'edge_mode': 'surface',
                                         'surface_tolerance': 0.06})['segments']
        for segment in surfaced:
            self.assertEqual(segment['status'], 'measured')
            self.assertAlmostEqual(segment['width'], 8.0, delta=2 * DEM_RES + 0.06 / 0.50)

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

    def test_coherence_fills_a_short_gap_and_declares_it(self):
        # Parche de nodata SOLO sobre el lado izquierdo entre las progresivas 40 y 45: ese tramo
        # sale no_edge/no_data por la izquierda mientras sus vecinos miden 4,0 m. Con ventana 2 la
        # coherencia lo rellena, lo marca y conserva el motivo original (`006` FR-015, FR-020).
        patch = {'nodata_patch': (200, 220, 244, 270)}   # progresivas 40-45, este del eje (izquierda)

        plain = self._analyze(dem_kwargs=patch)['segments']
        holes = [s for s in plain if s['status'] == 'no_edge']
        self.assertEqual(len(holes), 1)
        self.assertEqual(holes[0]['left_reason'], 'no_data')
        hole_index = holes[0]['index']

        repaired = self._analyze(dem_kwargs=patch,
                                 params={'coherence_window': 2})['segments']
        fixed = repaired[hole_index]

        self.assertEqual(fixed['status'], 'inferred')
        self.assertEqual(fixed['left_edge_source'], 'inferred')
        self.assertEqual(fixed['right_edge_source'], 'measured')
        self.assertEqual(fixed['left_reason'], 'no_data')      # el motivo no se borra
        self.assertAlmostEqual(fixed['offset_left'], 4.0, delta=0.1)
        self.assertAlmostEqual(fixed['width'], 8.0, delta=0.15)
        self.assertIsNotNone(fixed['cross_slope'])
        self.assertIsNotNone(fixed['edge_left'], 'el punto de borde inferido también se emite')
        for segment in repaired:
            assert_segment_invariants(self, segment)
        # Y los demás tramos no se contagian: siguen medidos e intactos.
        untouched = [s for s in repaired if s['index'] != hole_index]
        self.assertTrue(all(s['status'] == 'measured' for s in untouched))

    def test_window_zero_changes_nothing_in_the_pipeline(self):
        # FR-012 de punta a punta: el mismo análisis con y sin el parámetro explícito.
        patch = {'nodata_patch': (200, 220, 244, 270)}
        plain = self._analyze(dem_kwargs=patch)['segments']
        explicit = self._analyze(dem_kwargs=patch, params={'coherence_window': 0})['segments']

        self.assertEqual(plain, explicit)

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


MASK_NODATA = 255


def make_road_mask(path, half_width_left, half_width_right, size=DEM_SIZE, res=DEM_RES,
                   origin=DEM_ORIGIN, epsg=DEM_EPSG, road_col=ROAD_COL, nodata_patch=None):
    """Máscara `road`/`not_road` sintética, en el mismo grid que `make_road_dem` (`base.py`), para
    los tests end-to-end del modo `segmentation` (`007` User Story 1). `nodata_patch` es
    `(row0, row1, col0, col1)` en celdas, igual convención que `make_road_dem`, para simular un
    hueco de cobertura de la ortofoto (`007` FR-007)."""
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    transform = from_origin(origin[0], origin[1], res, res)
    cols = np.arange(size)
    rows = np.arange(size)
    col_grid, _row_grid = np.meshgrid(cols, rows)
    x = origin[0] + (col_grid + 0.5) * res
    d = x - road_center_x(origin, res, road_col)

    on_road = np.where(d >= 0, d <= half_width_left, -d <= half_width_right)
    data = on_road.astype(np.uint8)

    if nodata_patch is not None:
        r0, r1, c0, c1 = nodata_patch
        data[r0:r1, c0:c1] = MASK_NODATA

    with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=1,
                       dtype='uint8', crs='EPSG:{}'.format(epsg), transform=transform,
                       nodata=MASK_NODATA) as dst:
        dst.write(data, 1)


class SegmentationModeTest(ComputeTestBase):
    """`007` User Story 1: el modo `segmentation` mide donde `break`/`surface` no pueden, porque el
    límite de la calzada es solo un cambio de clasificación en la ortofoto, sin ningún escalón de
    elevación asociado. `segmentation.run_segmentation` se sustituye por un doble que devuelve una
    máscara sintética ya escrita: estos tests no dependen de `geodeep` ni de `gdalwarp`
    (ya cubiertos por `test_segmentation.py`), solo del despacho dentro de `compute.py`.
    """

    def _analyze_segmentation(self, mask_half_width_left, mask_half_width_right, dem_kwargs=None,
                              params=None, mask_nodata_patch=None):
        import tempfile
        from unittest import mock

        task = self._task_with_dem(dem_kwargs=dict(dem_kwargs or {}, talud=0.0))
        dem_path = sources.original_path(task, 'dtm')

        mask_path = tempfile.mktemp(suffix='.tif')
        make_road_mask(mask_path, mask_half_width_left, mask_half_width_right,
                       nodata_patch=mask_nodata_patch)
        self.addCleanup(__import__('os').remove, mask_path)

        merged_params = dict(PARAMS, edge_mode=sources.EDGE_MODE_SEGMENTATION, **(params or {}))

        with mock.patch.object(compute.segmentation, 'run_segmentation', return_value=mask_path):
            return compute.analyze(dem_path, axis_vertices(), merged_params,
                                   orthophoto_path=dem_path)

    def test_segmentation_mode_measures_where_break_and_surface_find_nothing(self):
        # DEM plano (`talud=0.0`): `break` y `surface` dan `no_break` en los dos lados sobre este
        # mismo DEM (ver `SummaryTest.test_width_aggregates_are_null_without_any_measured_segment`).
        # La máscara sí tiene un límite claro, sin relieve asociado.
        result = self._analyze_segmentation(mask_half_width_left=3.5, mask_half_width_right=3.5)
        segments = result['segments']

        for segment in segments:
            self.assertEqual(segment['status'], 'measured', segment)
            self.assertAlmostEqual(segment['width'], 7.0, delta=0.3)
            self.assertAlmostEqual(segment['offset_left'], 3.5, delta=0.2)
            self.assertAlmostEqual(segment['offset_right'], 3.5, delta=0.2)
            assert_segment_invariants(self, segment)

    def test_break_mode_finds_nothing_on_the_same_flat_dem(self):
        # Control: el mismo DEM (sin máscara) en modo `break` no mide nada — confirma que la
        # medida del test anterior viene de la segmentación, no de una casualidad del DEM.
        task = self._task_with_dem(dem_kwargs={'talud': 0.0})
        result = compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(), dict(PARAMS))

        self.assertEqual(result['summary']['measured_count'], 0)

    def test_cross_slope_still_comes_from_elevation_between_the_edges(self):
        # `007/FR-010`: el bombeo en modo segmentación se deriva del DEM entre los bordes hallados
        # por la máscara, con el mismo criterio que el modo `break` — no de la máscara.
        result = self._analyze_segmentation(mask_half_width_left=3.5, mask_half_width_right=3.5,
                                            dem_kwargs={'cross_slope': 0.02})
        for segment in result['segments']:
            self.assertAlmostEqual(segment['cross_slope'], 2.0, delta=0.5)

    def test_partial_mask_coverage_reports_no_orthophoto(self):
        # `007/FR-007`, `research.md` D28 caso 2: la máscara no cubre el lado derecho del eje en
        # absoluto (todas las columnas al oeste de `ROAD_COL`, `nodata` real, no solo "muy ancho").
        result = self._analyze_segmentation(mask_half_width_left=3.5, mask_half_width_right=3.5,
                                            mask_nodata_patch=(0, DEM_SIZE, 0, ROAD_COL))
        segments = result['segments']

        for segment in segments:
            self.assertEqual(segment['status'], 'no_edge')
            self.assertIsNone(segment['left_reason'])
            self.assertEqual(segment['right_reason'], 'no_orthophoto')
            self.assertAlmostEqual(segment['offset_left'], 3.5, delta=0.2)
            self.assertIsNone(segment['offset_right'])
            assert_segment_invariants(self, segment)

    def test_break_threshold_and_surface_tolerance_are_ignored_in_segmentation_mode(self):
        # `007/FR-015`: no tienen efecto en este modo, aunque se envíen.
        result = self._analyze_segmentation(
            mask_half_width_left=3.5, mask_half_width_right=3.5,
            params={'break_threshold': 0.001, 'surface_tolerance': 0.001})

        for segment in result['segments']:
            self.assertEqual(segment['status'], 'measured')
            self.assertAlmostEqual(segment['width'], 7.0, delta=0.3)

    def test_missing_orthophoto_path_fails_clearly_instead_of_crashing(self):
        task = self._task_with_dem(dem_kwargs={'talud': 0.0})
        with self.assertRaises(RuntimeError) as ctx:
            compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(),
                            dict(PARAMS, edge_mode=sources.EDGE_MODE_SEGMENTATION))
        self.assertIn('orthophoto_path', str(ctx.exception))

    def test_coherence_can_infer_a_segmentation_edge_too(self):
        # `007` User Story 3 / FR-011, FR-012: la coherencia (`006`) no distingue de qué modo
        # salió un borde medido — un tramo sin cobertura de ortofoto en un lado, rodeado de tramos
        # con ese lado medido, recibe un valor inferido igual que en `break`/`surface`.
        # Filas 240-260 ~ tramo índice 10 (progresivas 50-55 m de un eje de 100 m en 20 tramos de
        # 5 m): sin cobertura de máscara en el lado derecho, solo ahí.
        result = self._analyze_segmentation(
            mask_half_width_left=3.5, mask_half_width_right=3.5,
            mask_nodata_patch=(240, 260, 0, ROAD_COL),
            params={'coherence_window': 2})
        segments = result['segments']

        target = segments[10]
        self.assertEqual(target['status'], 'inferred')
        self.assertEqual(target['right_edge_source'], 'inferred')
        self.assertEqual(target['right_reason'], 'no_orthophoto')  # el motivo original se conserva
        self.assertAlmostEqual(target['offset_right'], 3.5, delta=0.3)

        for i in (5, 15):   # vecinos lejos de la reparación: sin tocar
            self.assertEqual(segments[i]['status'], 'measured')
            self.assertEqual(segments[i]['right_edge_source'], 'measured')

    def test_a_params_dict_without_edge_mode_still_behaves_like_break(self):
        # `007` User Story 4: un análisis anterior a esta feature —o a `006`— tiene un documento de
        # `params` sin la clave `edge_mode` en absoluto (no solo `None`). Recalcularlo no puede
        # comportarse distinto de `break`: el despacho de `_section_result` cae en el `else` para
        # cualquier valor que no sea `'surface'` ni `'segmentation'`, así que una clave ausente ya
        # se comporta como `break` sin que haga falta ningún caso especial.
        task = self._task_with_dem()   # talud por defecto: break SÍ mide aquí
        params_without_edge_mode = {k: v for k, v in PARAMS.items() if k != 'edge_mode'}
        self.assertNotIn('edge_mode', params_without_edge_mode)

        result = compute.analyze(sources.original_path(task, 'dtm'), axis_vertices(),
                                 params_without_edge_mode)

        for segment in result['segments']:
            self.assertEqual(segment['status'], 'measured')
            self.assertAlmostEqual(segment['width'], 8.0, places=6)


class SegmentationFailureTest(RoadTestBase):
    """`007` User Story 2, `research.md` D28 caso 1: un fallo global de la etapa de segmentación
    —librería ausente, sin red para el modelo, `gdalwarp` ausente— hace fallar el análisis
    **completo**, con el mismo mecanismo que cualquier otra excepción de `run_analysis`. Ningún
    tramo se produce, y `break`/`surface` de la misma tarea no se ven afectados."""

    def test_run_analysis_marks_the_whole_analysis_as_failed_without_any_segment(self):
        from unittest import mock

        from .. import compute, sources, store

        task = self._task_with_dem(dem_kwargs={'talud': 0.0})
        dem_path = sources.original_path(task, 'dtm')
        analysis_id = 'analysis-segmentation-failure'
        params = dict(PARAMS, edge_mode=sources.EDGE_MODE_SEGMENTATION)
        store.upsert_analysis(str(task.id), {
            'id': analysis_id, 'name': 'Camino', 'status': 'running', 'progress': 0.0,
            'model': 'dtm', 'variant': 'original', 'params': params,
            'axis': {'kind': 'annotation', 'ref': 'a1', 'vertices': axis_vertices(),
                     'plan_length': 100.0},
        })
        store.acquire_running(str(task.id), analysis_id)

        with mock.patch.object(compute.segmentation, 'run_segmentation',
                               side_effect=RuntimeError('GeoDeep library is missing')):
            compute.run_analysis(str(task.id), analysis_id, dem_path, axis_vertices(), params,
                                 orthophoto_path=dem_path)

        analysis = store.get_analysis(str(task.id), analysis_id)
        self.assertEqual(analysis['status'], 'failed')
        self.assertIn('GeoDeep', analysis['error'])
        self.assertIsNone(store.get_running(str(task.id)))
        self.assertIsNone(store.read_segments(str(task.id), analysis_id))

    def test_break_mode_is_unaffected_by_geodeep_being_unavailable(self):
        # El resto de la tarea sigue funcionando: `break` nunca llama a `segmentation`.
        from .. import compute, sources, store

        task = self._task_with_dem(dem_kwargs={'talud': 0.5})
        analysis_id = 'analysis-break-control'
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
