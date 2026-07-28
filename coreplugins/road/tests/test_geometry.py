"""Tramificación y transversales (`research.md` D6, D7; invariantes de `data-model.md` §6).

Los invariantes de cobertura no son cosmética: si dos tramos se solapan, una parte del camino se
mide dos veces y el resumen miente; si queda un hueco, el usuario ve un camino roto sobre el mapa
sin ninguna indicación de por qué.
"""

import math

from django.test import SimpleTestCase
from rasterio.crs import CRS

from .. import geometry
from .base import DEM_EPSG, axis_vertices

UTM = CRS.from_epsg(DEM_EPSG)


def straight(length, start=(500000.0, 4984000.0)):
    """Eje recto de `length` unidades hacia el este."""
    return [start, (start[0] + length, start[1])]


class SegmentizeTest(SimpleTestCase):
    def test_covers_the_axis_without_gaps_or_overlaps(self):
        segments = geometry.segmentize(straight(103.0), 5.0)

        self.assertAlmostEqual(segments[0]['station_start'], 0.0, places=9)
        self.assertAlmostEqual(segments[-1]['station_end'], 103.0, places=9)
        for previous, current in zip(segments, segments[1:]):
            self.assertAlmostEqual(previous['station_end'], current['station_start'], places=9)

    def test_lengths_add_up_to_the_total(self):
        segments = geometry.segmentize(straight(103.0), 5.0)
        self.assertAlmostEqual(sum(s['length'] for s in segments), 103.0, places=9)

    def test_last_segment_keeps_its_real_length(self):
        segments = geometry.segmentize(straight(103.0), 5.0)

        self.assertEqual(len(segments), 21)
        self.assertAlmostEqual(segments[-1]['length'], 3.0, places=9)
        for s in segments[:-1]:
            self.assertAlmostEqual(s['length'], 5.0, places=9)

    def test_exact_multiple_does_not_produce_a_trailing_sliver(self):
        # Con una longitud múltiplo exacta del paso, el error de coma flotante de la división
        # generaba un tramo final de longitud ~0 que ensuciaba el resumen.
        segments = geometry.segmentize(straight(100.0), 5.0)

        self.assertEqual(len(segments), 20)
        self.assertAlmostEqual(segments[-1]['length'], 5.0, places=9)

    def test_axis_shorter_than_one_segment_yields_exactly_one(self):
        segments = geometry.segmentize(straight(3.2), 5.0)

        self.assertEqual(len(segments), 1)
        self.assertAlmostEqual(segments[0]['station_start'], 0.0, places=9)
        self.assertAlmostEqual(segments[0]['station_end'], 3.2, places=9)

    def test_indices_are_consecutive_from_zero(self):
        segments = geometry.segmentize(straight(37.0), 5.0)
        self.assertEqual([s['index'] for s in segments], list(range(len(segments))))

    def test_geometry_keeps_the_original_vertices_of_a_bend(self):
        # Un tramo que cruza un quiebre debe dibujarse con el quiebre, no como su cuerda.
        coords = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
        segments = geometry.segmentize(coords, 20.0)

        self.assertEqual(len(segments), 1)
        self.assertIn((10.0, 0.0), [tuple(p) for p in segments[0]['points']])

    def test_midpoint_sits_at_half_the_station(self):
        segments = geometry.segmentize(straight(20.0), 5.0)
        self.assertAlmostEqual(segments[0]['midpoint'][0], 500002.5, places=6)
        self.assertAlmostEqual(segments[2]['midpoint'][0], 500012.5, places=6)

    def test_zero_length_axis_is_rejected(self):
        with self.assertRaises(ValueError):
            geometry.segmentize([(0.0, 0.0), (0.0, 0.0)], 5.0)

    def test_non_positive_segment_length_is_rejected(self):
        with self.assertRaises(ValueError):
            geometry.segmentize(straight(10.0), 0.0)


class NormalTest(SimpleTestCase):
    def test_normal_is_unit_length_and_perpendicular(self):
        normal = geometry.left_normal((0.0, 0.0), (3.0, 4.0))

        self.assertAlmostEqual(math.hypot(*normal), 1.0, places=12)
        self.assertAlmostEqual(normal[0] * 3.0 + normal[1] * 4.0, 0.0, places=12)

    def test_left_of_eastward_travel_is_north(self):
        self.assertEqual(geometry.left_normal((0.0, 0.0), (1.0, 0.0)), (0.0, 1.0))

    def test_left_of_southward_travel_is_east(self):
        # Es el sentido con el que se traza el eje del DEM sintético: `offset_left` mide al este.
        normal = geometry.left_normal((0.0, 10.0), (0.0, 0.0))
        self.assertAlmostEqual(normal[0], 1.0, places=12)
        self.assertAlmostEqual(normal[1], 0.0, places=12)

    def test_reversing_the_axis_swaps_the_sides(self):
        forward = geometry.left_normal((0.0, 0.0), (1.0, 0.0))
        backward = geometry.left_normal((1.0, 0.0), (0.0, 0.0))
        self.assertAlmostEqual(forward[0], -backward[0], places=12)
        self.assertAlmostEqual(forward[1], -backward[1], places=12)

    def test_coincident_points_have_no_direction(self):
        self.assertIsNone(geometry.left_normal((1.0, 1.0), (1.0, 1.0)))


class CrossSectionTest(SimpleTestCase):
    def test_offsets_are_symmetric_and_contain_the_axis(self):
        offsets = geometry.cross_section_offsets(10.0, 0.25)

        self.assertEqual(len(offsets), 81)
        self.assertAlmostEqual(offsets[len(offsets) // 2], 0.0, places=12)
        self.assertAlmostEqual(offsets[0], -10.0, places=12)
        self.assertAlmostEqual(offsets[-1], 10.0, places=12)

    def test_offsets_never_exceed_the_half_width(self):
        offsets = geometry.cross_section_offsets(10.0, 0.3)
        self.assertLessEqual(max(offsets), 10.0)
        self.assertGreaterEqual(min(offsets), -10.0)

    def test_points_follow_the_normal_from_the_midpoint(self):
        points = geometry.cross_section_points((100.0, 200.0), (1.0, 0.0), [-2.0, 0.0, 2.0])
        self.assertEqual(points, [(98.0, 200.0), (100.0, 200.0), (102.0, 200.0)])

    def test_non_positive_step_is_rejected(self):
        with self.assertRaises(ValueError):
            geometry.cross_section_offsets(10.0, 0.0)


class ProjectionTest(SimpleTestCase):
    def test_round_trip_through_wgs84_is_stable(self):
        vertices = axis_vertices(vertices=3)
        projected = geometry.project_vertices(vertices, UTM)
        back = geometry.unproject_points(projected, UTM)

        for original, returned in zip(vertices, back):
            self.assertAlmostEqual(original[0], returned[0], places=9)
            self.assertAlmostEqual(original[1], returned[1], places=9)

    def test_axis_of_the_synthetic_dem_is_a_straight_north_south_line(self):
        projected = geometry.project_vertices(axis_vertices(vertices=3), UTM)
        xs = [p[0] for p in projected]

        self.assertAlmostEqual(max(xs) - min(xs), 0.0, places=6)
        self.assertGreater(projected[0][1], projected[-1][1])  # de norte a sur

    def test_plan_length_matches_the_projected_span(self):
        vertices = axis_vertices(row_start=40, row_end=440, vertices=2)
        # 400 celdas de 0,25 m entre los centros de la primera y la última.
        self.assertAlmostEqual(geometry.plan_length(vertices, UTM), 100.0, places=3)


class ValidateVerticesTest(SimpleTestCase):
    def test_accepts_a_plain_two_vertex_axis(self):
        ok, err = geometry.validate_vertices([[0.0, 0.0], [1.0, 1.0]])
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_rejects_fewer_than_two_vertices(self):
        ok, _err = geometry.validate_vertices([[0.0, 0.0]])
        self.assertFalse(ok)

    def test_rejects_two_identical_vertices(self):
        ok, _err = geometry.validate_vertices([[1.0, 1.0], [1.0, 1.0]])
        self.assertFalse(ok)

    def test_rejects_more_than_the_maximum(self):
        ok, _err = geometry.validate_vertices([[i * 0.001, 0.0]
                                               for i in range(geometry.MAX_VERTICES + 1)])
        self.assertFalse(ok)

    def test_rejects_out_of_range_and_non_numeric_coordinates(self):
        self.assertFalse(geometry.validate_vertices([[0.0, 0.0], [200.0, 0.0]])[0])
        self.assertFalse(geometry.validate_vertices([[0.0, 0.0], ['a', 0.0]])[0])
        self.assertFalse(geometry.validate_vertices([[0.0, 0.0], [1.0]])[0])
