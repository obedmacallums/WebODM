"""`profile.detect_edges_segmentation()` — criterio de borde por segmentación (`007` FR-005..FR-007,
`research.md` D30).

Perfiles sintéticos de máscara binaria, en memoria: `mask_values` es `1.0` (calzada), `0.0`
(no-calzada) o `None` (sin cobertura de la ortofoto en ese punto). Sin ráster, sin `geodeep` y sin
Django, igual criterio que `test_surface.py` para el criterio de superficie de `006`.
"""

from .. import profile
from .base import RoadTestBase


def synthetic_mask_profile(half_width_left=4.0, half_width_right=4.0, search_half_width=10.0,
                           step=0.25, no_coverage_beyond_left=None, no_coverage_beyond_right=None):
    """`(distances, mask_values)`: calzada (`1.0`) dentro de los semianchos dados, no-calzada
    (`0.0`) fuera, con huecos de cobertura (`None`) opcionales más allá de una distancia."""
    n = int(round(search_half_width / step))
    distances = [k * step for k in range(-n, n + 1)]
    mask_values = []
    for d in distances:
        on_road = d <= half_width_left + 1e-9 if d >= 0 else -d <= half_width_right + 1e-9
        value = 1.0 if on_road else 0.0
        if no_coverage_beyond_left is not None and d > no_coverage_beyond_left:
            value = None
        if no_coverage_beyond_right is not None and -d > no_coverage_beyond_right:
            value = None
        mask_values.append(value)
    return distances, mask_values


class DetectEdgesSegmentationTest(RoadTestBase):
    def test_clean_edge_on_both_sides(self):
        distances, mask = synthetic_mask_profile(half_width_left=4.0, half_width_right=3.0)

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertAlmostEqual(edges['left']['offset'], 4.0, places=6)
        self.assertIsNone(edges['left']['reason'])
        self.assertAlmostEqual(edges['right']['offset'], 3.0, places=6)
        self.assertIsNone(edges['right']['reason'])

    def test_a_single_pixel_of_noise_does_not_trip_the_edge(self):
        # Un píxel aislado mal clasificado en plena calzada no debe leerse como el borde: la racha
        # sostenida (min_consecutive) lo filtra igual que filtra el ruido de un DEM fotogramétrico.
        distances, mask = synthetic_mask_profile(half_width_left=4.0, half_width_right=4.0)
        # Índice de d=1.0 dentro de la calzada (semiancho 4.0): lo volvemos "no-calzada" un instante.
        noisy_index = distances.index(1.0)
        mask[noisy_index] = 0.0

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertAlmostEqual(edges['left']['offset'], 4.0, places=6)
        self.assertIsNone(edges['left']['reason'])

    def test_road_all_the_way_to_the_search_half_width_is_no_break(self):
        distances, mask = synthetic_mask_profile(half_width_left=100.0, half_width_right=100.0)

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertIsNone(edges['left']['offset'])
        self.assertEqual(edges['left']['reason'], profile.NO_BREAK)
        self.assertIsNone(edges['right']['offset'])
        self.assertEqual(edges['right']['reason'], profile.NO_BREAK)

    def test_axis_already_off_the_roadway_is_break_at_axis(self):
        distances, mask = synthetic_mask_profile(half_width_left=0.0, half_width_right=0.0)

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertIsNone(edges['left']['offset'])
        self.assertEqual(edges['left']['reason'], profile.BREAK_AT_AXIS)
        self.assertIsNone(edges['right']['offset'])
        self.assertEqual(edges['right']['reason'], profile.BREAK_AT_AXIS)

    def test_no_coverage_at_the_axis_is_no_orthophoto(self):
        distances, mask = synthetic_mask_profile()
        center = profile._center_index(distances)
        mask[center] = None

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertEqual(edges['left']['reason'], profile.NO_ORTHOPHOTO)
        self.assertEqual(edges['right']['reason'], profile.NO_ORTHOPHOTO)

    def test_partial_coverage_reports_no_orthophoto_on_the_uncovered_side_only(self):
        # `research.md` D28 caso 2: cobertura parcial de un tramo, un solo lado sin ortofoto.
        distances, mask = synthetic_mask_profile(half_width_left=4.0, half_width_right=3.0,
                                                  no_coverage_beyond_left=2.0)

        edges = profile.detect_edges_segmentation(distances, mask, min_consecutive=3)

        self.assertEqual(edges['left']['reason'], profile.NO_ORTHOPHOTO)
        self.assertIsNone(edges['left']['offset'])
        self.assertAlmostEqual(edges['right']['offset'], 3.0, places=6)
        self.assertIsNone(edges['right']['reason'])

    def test_empty_profile_reports_no_orthophoto(self):
        edges = profile.detect_edges_segmentation([], [], min_consecutive=3)

        self.assertEqual(edges['left']['reason'], profile.NO_ORTHOPHOTO)
        self.assertEqual(edges['right']['reason'], profile.NO_ORTHOPHOTO)

    def test_mismatched_lengths_are_rejected(self):
        with self.assertRaises(ValueError):
            profile.detect_edges_segmentation([0.0, 0.25], [1.0], min_consecutive=3)
