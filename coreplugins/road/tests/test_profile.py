"""Matemática de perfiles contra valores exactos (`research.md` D3, D4, D5).

Todos los perfiles se construyen en memoria: `profile.py` no hace entrada/salida, así que aquí no
hay ráster, ni base de datos, ni tarea. Es la parte que más puede equivocarse en silencio —un
ancho con medio metro de sesgo sigue pareciendo un ancho— y por eso se comprueba contra el número
exacto, no contra un rango plausible.
"""

import math

from django.test import SimpleTestCase

from .. import profile
from .base import synthetic_cross_profile, synthetic_long_profile

STEP = 0.25
SEARCH = 10.0
THRESHOLD = 15.0
MIN_CONSECUTIVE = 3


def build_profile(z_of_d, step=STEP, search=SEARCH):
    """Perfil `(distances, elevations)` a partir de una función `z(d)` que puede devolver `None`."""
    n = int(round(search / step))
    distances = [k * step for k in range(-n, n + 1)]
    return distances, [z_of_d(d) for d in distances]


class DetectEdgesTest(SimpleTestCase):
    def test_symmetric_taludes_give_exact_width(self):
        distances, elevations = synthetic_cross_profile(half_width_left=4.0, half_width_right=4.0)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertAlmostEqual(edges['left']['offset'], 4.0, places=9)
        self.assertAlmostEqual(edges['right']['offset'], 4.0, places=9)
        self.assertIsNone(edges['left']['reason'])
        self.assertIsNone(edges['right']['reason'])
        self.assertAlmostEqual(edges['left']['offset'] + edges['right']['offset'], 8.0, places=9)

    def test_asymmetric_taludes_give_each_side_its_own_offset(self):
        distances, elevations = synthetic_cross_profile(half_width_left=3.0, half_width_right=5.5)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertAlmostEqual(edges['left']['offset'], 3.0, places=9)
        self.assertAlmostEqual(edges['right']['offset'], 5.5, places=9)

    def test_edge_on_one_side_only_reports_no_break_on_the_other(self):
        # Talud solo al este; al oeste el camino se funde con el terreno, que es el caso real de
        # un camino a media ladera.
        def z(d):
            if d <= 3.0:
                return 100.0
            return 100.0 - 0.5 * (d - 3.0)

        distances, elevations = build_profile(z)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertAlmostEqual(edges['left']['offset'], 3.0, places=9)
        self.assertIsNone(edges['left']['reason'])
        self.assertIsNone(edges['right']['offset'])
        self.assertEqual(edges['right']['reason'], profile.NO_BREAK)

    def test_flat_profile_reports_no_break_on_both_sides(self):
        distances, elevations = synthetic_cross_profile(talud=0.0, cross_slope=0.0)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        for side in ('left', 'right'):
            self.assertIsNone(edges[side]['offset'])
            self.assertEqual(edges[side]['reason'], profile.NO_BREAK)

    def test_profile_truncated_by_nodata_reports_no_data(self):
        # Sin quiebre, y el dato se acaba al este antes de agotar el semiancho de búsqueda.
        distances, elevations = synthetic_cross_profile(talud=0.0, cross_slope=0.0,
                                                        nodata_beyond_left=6.0)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertEqual(edges['left']['reason'], profile.NO_DATA)
        self.assertEqual(edges['right']['reason'], profile.NO_BREAK)

    def test_no_data_at_the_axis_invalidates_both_sides(self):
        distances, elevations = synthetic_cross_profile()
        elevations[len(elevations) // 2] = None
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertEqual(edges['left']['reason'], profile.NO_DATA)
        self.assertEqual(edges['right']['reason'], profile.NO_DATA)

    def test_isolated_spike_below_min_consecutive_is_not_an_edge(self):
        # Un solo píxel ruidoso supera el umbral: sin el requisito de racha se leería como borde y
        # el ancho saldría absurdamente pequeño.
        def z(d):
            return 100.0 + (0.2 if abs(d - 1.0) < 1e-9 else 0.0)

        distances, elevations = build_profile(z)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertIsNone(edges['left']['offset'])
        self.assertEqual(edges['left']['reason'], profile.NO_BREAK)

    def test_edge_sits_at_the_start_of_the_break_not_at_its_steepest_point(self):
        # Talud que se va empinando: el borde de calzada es donde arranca, no donde más cae.
        def z(d):
            if d <= 2.0:
                return 100.0
            over = d - 2.0
            return 100.0 - (0.2 * over + 0.4 * over ** 2)

        distances, elevations = build_profile(z)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)

        self.assertAlmostEqual(edges['left']['offset'], 2.0, places=9)

    def test_mismatched_lengths_are_rejected(self):
        with self.assertRaises(ValueError):
            profile.detect_edges([0.0, 1.0], [100.0], THRESHOLD, MIN_CONSECUTIVE)


class FitGradeTest(SimpleTestCase):
    def test_exact_grade_on_a_known_ramp(self):
        stations, elevations = synthetic_long_profile(length=5.0, step=STEP, grade=0.05)
        fit = profile.fit_grade(stations, elevations)

        self.assertAlmostEqual(fit['grade'], 5.0, places=6)
        self.assertAlmostEqual(fit['grade_deg'], math.degrees(math.atan(0.05)), places=6)

    def test_negative_grade_keeps_its_sign(self):
        stations, elevations = synthetic_long_profile(length=5.0, step=STEP, grade=-0.08)
        self.assertAlmostEqual(profile.fit_grade(stations, elevations)['grade'], -8.0, places=6)

    def test_elevation_comes_from_the_fit_at_the_midpoint(self):
        stations, elevations = synthetic_long_profile(length=5.0, step=STEP, grade=0.05,
                                                      base=100.0)
        fit = profile.fit_grade(stations, elevations)
        self.assertAlmostEqual(profile.evaluate(fit, 2.5), 100.0 + 0.05 * 2.5, places=6)

    def test_least_squares_survives_dem_noise(self):
        # 2 cm de ruido, del orden del de un DEM fotogramétrico. La diferencia entre extremos
        # entrega la pendiente al ruido de dos muestras; el ajuste usa las 21.
        stations, elevations = synthetic_long_profile(length=5.0, step=STEP, grade=0.05,
                                                      noise=0.02)
        fit = profile.fit_grade(stations, elevations)
        self.assertLess(abs(fit['grade'] - 5.0), 0.5)

    def test_missing_samples_are_skipped_not_interpolated(self):
        stations, elevations = synthetic_long_profile(length=5.0, step=STEP, grade=0.05)
        elevations[3] = None
        elevations[7] = None
        self.assertAlmostEqual(profile.fit_grade(stations, elevations)['grade'], 5.0, places=6)

    def test_two_samples_degenerate_to_the_line_through_them(self):
        fit = profile.fit_grade([0.0, 4.0], [100.0, 100.4])
        self.assertAlmostEqual(fit['grade'], 10.0, places=9)

    def test_fewer_than_two_valid_samples_has_no_fit(self):
        self.assertIsNone(profile.fit_grade([0.0, 1.0], [100.0, None]))
        self.assertIsNone(profile.fit_grade([], []))

    def test_all_samples_at_the_same_station_has_no_fit(self):
        self.assertIsNone(profile.fit_grade([2.0, 2.0, 2.0], [100.0, 100.1, 100.2]))


class CrossSlopeTest(SimpleTestCase):
    def test_known_camber_between_edges(self):
        distances, elevations = synthetic_cross_profile(cross_slope=0.02)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)
        value = profile.cross_slope(distances, elevations,
                                    edges['left']['index'], edges['right']['index'])

        self.assertAlmostEqual(value, 2.0, places=6)

    def test_sign_follows_the_left_of_travel_convention(self):
        distances, elevations = synthetic_cross_profile(cross_slope=-0.03)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)
        value = profile.cross_slope(distances, elevations,
                                    edges['left']['index'], edges['right']['index'])

        self.assertAlmostEqual(value, -3.0, places=6)

    def test_no_cross_slope_without_both_edges(self):
        distances, elevations = synthetic_cross_profile()
        self.assertIsNone(profile.cross_slope(distances, elevations, 10, None))
        self.assertIsNone(profile.cross_slope(distances, elevations, None, 30))

    def test_taludes_do_not_leak_into_the_camber(self):
        # Calzada descentrada respecto del semiancho de búsqueda: al este quedan 7 m de talud y al
        # oeste solo 2, así que un ajuste sobre el perfil entero lo domina el talud largo y el
        # número deja de significar bombeo. Con taludes simétricos esto no se vería —el ajuste
        # global simplemente se diluye hacia cero—, que es justo por lo que el caso simétrico no
        # sirve para probar esto.
        distances, elevations = synthetic_cross_profile(half_width_left=3.0, half_width_right=8.0,
                                                        cross_slope=0.02, talud=0.5)
        edges = profile.detect_edges(distances, elevations, THRESHOLD, MIN_CONSECUTIVE)
        restricted = profile.cross_slope(distances, elevations,
                                         edges['left']['index'], edges['right']['index'])
        whole = profile.fit_grade(distances, elevations)['grade']

        self.assertAlmostEqual(restricted, 2.0, places=6)
        self.assertGreater(abs(whole - restricted), 5.0)
