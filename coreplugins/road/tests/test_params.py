"""Validación de parámetros y estimación previa (`data-model.md` §4, `research.md` D11).

Dos exigencias que se prueban aquí y que no son intercambiables:

- Un parámetro fuera de rango **no inicia el cálculo** y dice el rango admitido (FR-042). Un
  "parámetro inválido" a secas obliga al usuario a adivinar cuál y por qué.
- La estimación previa tiene que **coincidir con lo que el análisis produce de verdad**. Una
  estimación que no acierta es peor que no tenerla: el usuario decide lanzar o no en función de
  ella.
"""

from rest_framework import status

from .. import compute, sources, store
from .base import DEM_RES, RoadTestBase
from .test_api_analyses import AnalysesApiTestBase


class ValidateParamsTest(RoadTestBase):
    def test_defaults_fill_in_what_is_omitted(self):
        params, err = sources.validate_params({}, DEM_RES)

        self.assertIsNone(err)
        self.assertEqual(params['segment_length'], 5.0)
        self.assertEqual(params['search_half_width'], 10.0)
        self.assertEqual(params['sample_step'], DEM_RES)
        self.assertEqual(params['break_threshold'], 15.0)
        self.assertEqual(params['min_consecutive_samples'], 3)

    def test_partial_params_keep_the_rest_at_their_defaults(self):
        params, err = sources.validate_params({'break_threshold': 22.0}, DEM_RES)

        self.assertIsNone(err)
        self.assertEqual(params['break_threshold'], 22.0)
        self.assertEqual(params['segment_length'], 5.0)

    def test_the_new_edge_parameters_default_to_the_previous_behavior(self):
        # `break` con coherencia apagada ES el comportamiento anterior: los defectos de los tres
        # parámetros nuevos no pueden cambiar ningún resultado existente (`006` FR-002, FR-012).
        params, err = sources.validate_params({}, DEM_RES)

        self.assertIsNone(err)
        self.assertEqual(params['edge_mode'], 'break')
        self.assertEqual(params['surface_tolerance'], 0.06)
        self.assertEqual(params['coherence_window'], 0)

    def test_an_unknown_edge_mode_lists_the_valid_ones(self):
        # Enum, no rango: el mensaje enumera los valores admitidos (`006` FR-004).
        params, err = sources.validate_params({'edge_mode': 'laser'}, DEM_RES)

        self.assertIsNone(params)
        self.assertIn('edge_mode', str(err))
        self.assertIn('break', str(err))
        self.assertIn('surface', str(err))

    def test_surface_mode_is_accepted_and_persists_its_tolerance(self):
        params, err = sources.validate_params(
            {'edge_mode': 'surface', 'surface_tolerance': 0.10, 'coherence_window': 2}, DEM_RES)

        self.assertIsNone(err)
        self.assertEqual(params['edge_mode'], 'surface')
        self.assertEqual(params['surface_tolerance'], 0.10)
        self.assertEqual(params['coherence_window'], 2)

    def test_smoothing_defaults_off(self):
        # `smooth_window=0` ES el comportamiento anterior: el defecto no puede cambiar el
        # resultado de ningún análisis existente, igual que los parámetros nuevos de `006`.
        params, err = sources.validate_params({}, DEM_RES)

        self.assertIsNone(err)
        self.assertEqual(params['smooth_window'], 0.0)

    def test_smoothing_accepts_its_range_and_rejects_outside(self):
        params, err = sources.validate_params({'smooth_window': 0.9}, DEM_RES)
        self.assertIsNone(err)
        self.assertEqual(params['smooth_window'], 0.9)

        params, err = sources.validate_params({'smooth_window': -0.1}, DEM_RES)
        self.assertIsNone(params)
        self.assertIn('smooth_window', str(err))

        params, err = sources.validate_params({'smooth_window': 5.1}, DEM_RES)
        self.assertIsNone(params)
        self.assertIn('smooth_window', str(err))

    def test_a_fractional_window_truncates_like_the_other_integer_params(self):
        # Mismo trato que min_consecutive_samples: int() trunca, no rechaza. Documentarlo aquí
        # evita que alguien lo "arregle" en un solo sitio y deje a los dos enteros inconsistentes.
        params, err = sources.validate_params({'coherence_window': 1.5}, DEM_RES)
        self.assertIsNone(err)
        self.assertEqual(params['coherence_window'], 1)

    def test_each_parameter_reports_its_own_range(self):
        cases = {
            'segment_length': (0.1, '0.5', '100'),
            'search_half_width': (0.5, '1', '50'),
            'break_threshold': (1.0, '2', '200'),
            'min_consecutive_samples': (99, '1', '20'),
            'surface_tolerance': (1.0, '0.02', '0.5'),
            'coherence_window': (9, '0', '5'),
        }
        for key, (bad, low, high) in cases.items():
            with self.subTest(param=key):
                params, err = sources.validate_params({key: bad}, DEM_RES)
                self.assertIsNone(params)
                self.assertIn(key, str(err))
                self.assertIn(low, str(err))
                self.assertIn(high, str(err))

    def test_sample_step_cannot_go_below_the_dem_resolution(self):
        # Muestrear más fino que el píxel inventa detalle que no existe.
        params, err = sources.validate_params({'sample_step': DEM_RES / 2}, DEM_RES)

        self.assertIsNone(params)
        self.assertIn('sample_step', str(err))

    def test_sample_step_at_the_resolution_is_accepted(self):
        params, err = sources.validate_params({'sample_step': DEM_RES}, DEM_RES)
        self.assertIsNone(err)
        self.assertEqual(params['sample_step'], DEM_RES)

    def test_segment_shorter_than_the_sample_step_is_rejected(self):
        # Un tramo más corto que el paso puede quedarse sin ninguna muestra que ajustar.
        params, err = sources.validate_params({'segment_length': 0.5, 'sample_step': 2.0}, DEM_RES)

        self.assertIsNone(params)
        self.assertIn('segment_length', str(err))
        self.assertIn('sample_step', str(err))

    def test_non_numeric_values_are_rejected(self):
        params, err = sources.validate_params({'segment_length': 'ancho'}, DEM_RES)
        self.assertIsNone(params)
        self.assertIn('segment_length', str(err))

    def test_color_thresholds_must_be_ordered_and_positive(self):
        for bad in ([12.0, 8.0], [0.0, 12.0], [8.0, 120.0], [8.0], 'x', [8.0, 8.0]):
            with self.subTest(value=bad):
                value, err = sources.validate_color_thresholds(bad)
                self.assertIsNone(value)
                self.assertTrue(err)

        value, err = sources.validate_color_thresholds([6.0, 10.0])
        self.assertIsNone(err)
        self.assertEqual(value, [6.0, 10.0])

    def test_width_aggregation_is_an_enum_with_a_named_error(self):
        params, err = sources.validate_params({'width_aggregation': 'moda'}, DEM_RES)
        self.assertIsNone(params)
        self.assertIn('width_aggregation', str(err))
        self.assertIn('median', str(err))

        for mode in sources.WIDTH_AGGREGATIONS:
            with self.subTest(mode=mode):
                params, err = sources.validate_params({'width_aggregation': mode}, DEM_RES)
                self.assertIsNone(err)
                self.assertEqual(params['width_aggregation'], mode)

    def test_width_thresholds_must_be_ordered_and_positive(self):
        # `[mínimo, holgado]` ascendente, como el par de pendiente. Lo que cambia es la lectura
        # —por debajo del mínimo es rojo, no verde—, no la forma del dato.
        for bad in ([20.0, 15.0], [0.0, 20.0], [-1.0, 5.0], [15.0], 'x', [15.0, 15.0]):
            with self.subTest(value=bad):
                value, err = sources.validate_width_thresholds(bad)
                self.assertIsNone(value)
                self.assertTrue(err)

        value, err = sources.validate_width_thresholds([15.0, 20.0])
        self.assertIsNone(err)
        self.assertEqual(value, [15.0, 20.0])

    def test_width_thresholds_are_derived_from_the_measured_mean(self):
        """Sin umbrales guardados se deducen del propio análisis: una calle de 6 m y una rampa de
        25 m necesitan escalas distintas, y una constante solo puede acertar en una de las dos."""
        self.assertEqual(sources.derive_width_thresholds(25.0), [20.0, 25.0])
        self.assertEqual(sources.derive_width_thresholds(6.0), [4.8, 6.0])

    def test_derived_thresholds_stay_ordered_however_narrow_the_road(self):
        # El derivado se va a validar como cualquier otro: si empatara, el propio backend
        # rechazaría lo que él mismo produjo.
        # 100 m es el techo real: nadie puede medir más de `2 * search_half_width` (2 x 50).
        for mean in (0.5, 1.0, 3.33, 100.0):
            with self.subTest(mean=mean):
                derived = sources.derive_width_thresholds(mean)
                self.assertLess(derived[0], derived[1])
                self.assertIsNone(sources.validate_width_thresholds(derived)[1])

    def test_without_a_measured_mean_there_is_nothing_to_derive(self):
        # Ningún tramo con ancho: no hay regla que colorear, así que tampoco hay umbrales que
        # inventar.
        for empty in (None, 0.0):
            with self.subTest(mean=empty):
                self.assertIsNone(sources.derive_width_thresholds(empty))


class ParamsApiTest(AnalysesApiTestBase):
    def test_out_of_range_parameter_does_not_start_a_calculation(self):
        task = self._task_with_dem()
        self._login()

        res = self._create(task, params={'segment_length': 500.0})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_parameter')
        self.assertIn('100', res.data['error'])
        self.assertEqual(store.list_analyses(str(task.id)), [])
        self.assertIsNone(store.get_running(str(task.id)))

    def test_custom_parameters_change_the_result(self):
        task = self._task_with_dem()
        self._login()

        analysis_id = self._create(task, params={'segment_length': 10.0}).data['analysis_id']
        analysis = store.get_analysis(str(task.id), analysis_id)

        self.assertEqual(analysis['params']['segment_length'], 10.0)
        self.assertEqual(analysis['summary']['segment_count'], 10)

    def test_break_threshold_changes_how_many_segments_find_an_edge(self):
        # El talud del DEM sintético es del 50 %. Con el umbral por defecto (15 %) todos los tramos
        # encuentran sus dos bordes; subiéndolo por encima del talud, ninguno.
        task = self._task_with_dem()
        self._login()

        default = self._create(task).data['analysis_id']
        self.assertEqual(store.get_analysis(str(task.id), default)['summary']['measured_count'], 20)

        lax = self._create(task, params={'break_threshold': 60.0},
                           confirm=True).data['analysis_id']
        summary = store.get_analysis(str(task.id), lax)['summary']

        self.assertEqual(summary['measured_count'], 0)
        self.assertEqual(summary['no_edge_count'], 20)

    def test_a_threshold_below_the_camber_finds_the_break_on_the_roadway_itself(self):
        # Peralte del 5 % y umbral del 2 %: el "quiebre" cae dentro de la calzada, sobre el eje.
        task = self._task_with_dem(dem_kwargs={'cross_slope': 0.05})
        self._login()

        analysis_id = self._create(task, params={'break_threshold': 2.0}).data['analysis_id']
        summary = store.get_analysis(str(task.id), analysis_id)['summary']

        self.assertEqual(summary['measured_count'], 0)
        self.assertIsNone(summary['mean_width'])


class EstimateTest(AnalysesApiTestBase):
    def test_estimate_matches_what_the_analysis_really_produces(self):
        task = self._task_with_dem()
        self._login()

        estimated = self.client.post(self._url(task, 'analyses/estimate'),
                                     {'axis': {'kind': 'annotation', 'ref': 'a1b2'}},
                                     format='json')
        analysis_id = self._create(task).data['analysis_id']
        summary = store.get_analysis(str(task.id), analysis_id)['summary']

        self.assertEqual(estimated.status_code, status.HTTP_200_OK)
        self.assertEqual(estimated.data['segments'], summary['segment_count'])
        self.assertEqual(estimated.data['samples'], summary['samples'])

    def test_estimate_does_not_launch_anything(self):
        task = self._task_with_dem()
        self._login()

        self.client.post(self._url(task, 'analyses/estimate'),
                         {'axis': {'kind': 'annotation', 'ref': 'a1b2'}}, format='json')

        self.assertEqual(store.list_analyses(str(task.id)), [])
        self.assertIsNone(store.get_running(str(task.id)))

    def test_estimate_reports_the_warning_flag(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.post(self._url(task, 'analyses/estimate'),
                               {'axis': {'kind': 'annotation', 'ref': 'a1b2'}}, format='json')

        self.assertIn('warn', res.data)
        self.assertIn('cross_sections', res.data)
        self.assertIn('estimated_seconds', res.data)
        self.assertFalse(res.data['warn'])   # 100 m con los valores por defecto no avisa

    def test_estimate_validates_parameters_too(self):
        task = self._task_with_dem()
        self._login()

        res = self.client.post(self._url(task, 'analyses/estimate'),
                               {'axis': {'kind': 'annotation', 'ref': 'a1b2'},
                                'params': {'segment_length': 500.0}}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data['code'], 'invalid_parameter')

    def test_a_costly_analysis_requires_confirmation(self):
        task = self._task_with_dem()
        self._login()

        # Sin tope duro (FR-043): se avisa y, con `confirm`, se lanza igual.
        with self.settings():
            original = compute.WARN_SAMPLES
            compute.WARN_SAMPLES = 100
            try:
                refused = self._create(task)
                self.assertEqual(refused.status_code, status.HTTP_409_CONFLICT)
                self.assertEqual(refused.data['code'], 'confirmation_required')
                self.assertIn('estimate', refused.data)
                self.assertEqual(store.list_analyses(str(task.id)), [])
                self.assertIsNone(store.get_running(str(task.id)))

                accepted = self._create(task, confirm=True)
                self.assertEqual(accepted.status_code, status.HTTP_202_ACCEPTED)
            finally:
                compute.WARN_SAMPLES = original
