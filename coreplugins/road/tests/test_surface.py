"""El criterio de superficie (`006` FR-005..FR-010, `research.md` D17, D18).

Cada caso de la primera mitad reproduce, en sintético, un fenómeno **medido** sobre la calle real
que motivó el modo (D17): el bordillo difuminado por la fotogrametría, el ruido más afilado que la
señal, el peralte y el eje descentrado. La segunda mitad fija el contrato: los tres motivos de
"sin borde" se reutilizan sin ampliar el enum (FR-010).

El helper local modela una **calle**: calzada con bombeo, bordillo como rampa de altura y anchura
configurables y acera plana detrás. El `synthetic_cross_profile` de `base` modela un camino rural
con talud hacia abajo, que es exactamente el perfil en el que este criterio no hace falta.
"""

from .. import profile
from .base import RoadTestBase

STEP = 0.05   # el paso del caso real: DTM de 5 cm


def street_profile(curb_left=3.5, curb_right=3.5, curb_height=0.15, curb_run=1.0,
                   camber=0.0, half_width=8.0, step=STEP, base=100.0,
                   spikes=None, nodata_beyond_left=None):
    """Perfil `(distances, elevations)` de una calle con bordillos.

    `curb_run` es la anchura en planta sobre la que el escalón aparece repartido: la fotogrametría
    convierte la cara vertical en una rampa (D17), y ese difuminado es el fenómeno que estos tests
    ejercitan. `spikes` es `{distancia: delta}` con picos de UNA muestra, como el ruido medido.
    Positivo = izquierda, como en todo `profile`.
    """
    n = int(round(half_width / step))
    distances = [k * step for k in range(-n, n + 1)]
    elevations = []
    for d in distances:
        for side, curb in ((1, curb_left), (-1, curb_right)):
            if d * side >= 0:
                inside = d * side
                curb_at = curb
                break
        if inside <= curb_at:
            z = base + camber * d                      # calzada: plano con bombeo
        elif inside <= curb_at + curb_run:
            ramp = (inside - curb_at) / curb_run       # la cara del bordillo, difuminada
            z = base + camber * (curb_at * side) + curb_height * ramp
        else:
            z = base + camber * (curb_at * side) + curb_height    # acera
        if spikes:
            for at, delta in spikes.items():
                if abs(d - at) < step / 2:
                    z += delta
        if nodata_beyond_left is not None and d > nodata_beyond_left:
            z = None
        elevations.append(z)
    return distances, elevations


class SurfaceCriterionTest(RoadTestBase):
    """Los cuatro fenómenos medidos que justifican el modo (D17, D18)."""

    def test_a_smeared_curb_is_found_by_surface_and_missed_by_break(self):
        # 15 cm repartidos en 1,5 m son un 10 % de pendiente local: por debajo del umbral por
        # defecto del criterio de quiebre. La separación respecto del plano sigue siendo 15 cm.
        distances, elevations = street_profile(curb_height=0.15, curb_run=1.5)

        broke = profile.detect_edges(distances, elevations, 15.0, 3)
        self.assertEqual(broke['left']['reason'], profile.NO_BREAK)
        self.assertEqual(broke['right']['reason'], profile.NO_BREAK)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)
        self.assertIsNone(surfaced['left']['reason'])
        self.assertIsNone(surfaced['right']['reason'])
        # El borde cae dentro de la rampa: entre el pie del bordillo y donde la separación ya
        # supera la tolerancia (0,06/0,15 del recorrido de la rampa).
        for side in ('left', 'right'):
            self.assertGreaterEqual(surfaced[side]['offset'], 3.5 - STEP)
            self.assertLessEqual(surfaced[side]['offset'], 3.5 + 1.5)

    def test_camber_does_not_count_as_separation(self):
        # La alternativa que D3 descartó comparaba contra la cota del eje y un peralte del 8 % le
        # parecía un borde. La referencia ajustada lo absorbe por construcción (FR-008).
        distances, elevations = street_profile(curb_height=0.12, curb_run=0.1, camber=0.08)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertIsNone(surfaced['left']['reason'])
        self.assertIsNone(surfaced['right']['reason'])
        for side in ('left', 'right'):
            self.assertAlmostEqual(surfaced[side]['offset'], 3.5, delta=0.2)

    def test_isolated_spikes_sharper_than_the_curb_are_ignored(self):
        # El fenómeno central de D17: picos de una sola muestra (aquí ±8 cm, un 160 % de pendiente
        # local) frente a un bordillo difuminado al 10 %. La racha mínima descarta los picos y la
        # tolerancia encuentra el bordillo, en la misma posición que sin ruido.
        clean = profile.detect_edges_surface(*street_profile(curb_height=0.15, curb_run=1.5),
                                             tolerance=0.06, min_consecutive=3)
        distances, elevations = street_profile(curb_height=0.15, curb_run=1.5,
                                               spikes={1.5: 0.08, -2.0: -0.08})

        noisy = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertIsNone(noisy['left']['reason'])
        self.assertIsNone(noisy['right']['reason'])
        self.assertAlmostEqual(noisy['left']['offset'], clean['left']['offset'], delta=STEP)
        self.assertAlmostEqual(noisy['right']['offset'], clean['right']['offset'], delta=STEP)

        # Y el criterio de quiebre, con los mismos datos, no saca nada útil: el pico no forma
        # racha y la rampa no supera el umbral. Es la inversión señal-ruido medida.
        broke = profile.detect_edges(distances, elevations, 15.0, 3)
        self.assertEqual(broke['left']['reason'], profile.NO_BREAK)

    def test_an_off_center_axis_still_finds_both_curbs(self):
        distances, elevations = street_profile(curb_left=1.0, curb_right=5.5,
                                               curb_height=0.15, curb_run=0.5)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertAlmostEqual(surfaced['left']['offset'], 1.0, delta=0.3)
        self.assertAlmostEqual(surfaced['right']['offset'], 5.5, delta=0.3)

    def test_a_curb_inside_the_seed_window_is_corrected_by_the_refit(self):
        # El caso que hace necesario el reajuste (D18): con el bordillo a 0,4 m del eje, la semilla
        # de ±0,5 m incluye muestras de acera y la primera pasada sale contaminada. La segunda
        # ajusta solo sobre la calzada acotada y recoloca el borde.
        distances, elevations = street_profile(curb_left=0.4, curb_right=5.5,
                                               curb_height=0.15, curb_run=0.3, camber=0.02)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertIsNone(surfaced['left']['reason'])
        self.assertAlmostEqual(surfaced['left']['offset'], 0.4, delta=0.35)
        self.assertAlmostEqual(surfaced['right']['offset'], 5.5, delta=0.3)

    def test_the_reference_slope_is_the_cross_slope(self):
        # D19: el bombeo del modo superficie es la pendiente de la propia referencia, ajustada
        # exactamente sobre las muestras que el criterio consideró calzada.
        distances, elevations = street_profile(curb_height=0.12, curb_run=0.1, camber=0.03)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertIsNotNone(surfaced['reference'])
        self.assertAlmostEqual(surfaced['reference']['cross_slope'], 3.0, delta=0.3)


class SurfaceContractTest(RoadTestBase):
    """Los tres motivos existentes bastan; el enum no crece (FR-010)."""

    def test_running_out_of_data_reports_no_data(self):
        distances, elevations = street_profile(curb_left=6.0, nodata_beyond_left=2.0)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertEqual(surfaced['left']['reason'], profile.NO_DATA)
        self.assertIsNone(surfaced['left']['offset'])
        self.assertIsNone(surfaced['right']['reason'])   # el otro lado no se contamina

    def test_a_street_without_curbs_reports_no_break(self):
        # Calzada que se funde con el terreno: nunca se aparta de su propia referencia. Es el
        # límite documentado del método y la razón de que `break` siga siendo el defecto.
        distances, elevations = street_profile(curb_height=0.0, camber=0.02)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertEqual(surfaced['left']['reason'], profile.NO_BREAK)
        self.assertEqual(surfaced['right']['reason'], profile.NO_BREAK)
        self.assertIsNone(surfaced['left']['offset'])

    def test_terrain_broken_at_the_axis_reports_break_at_axis(self):
        # El eje pasa por una arista (una cresta en V): ninguna recta representa el terreno junto
        # al eje y la separación arranca en la primera muestra de cada lado. No hay calzada que
        # medir, y el motivo es el mismo que en el modo de quiebre: el enum no crece (FR-010).
        n = int(round(8.0 / STEP))
        distances = [k * STEP for k in range(-n, n + 1)]
        elevations = [100.0 - 2.0 * abs(d) for d in distances]

        surfaced = profile.detect_edges_surface(distances, elevations, 0.15, 3)

        self.assertEqual(surfaced['left']['reason'], profile.BREAK_AT_AXIS)
        self.assertEqual(surfaced['right']['reason'], profile.BREAK_AT_AXIS)
        self.assertIsNone(surfaced['left']['offset'])

    def test_a_tolerance_above_the_curb_height_reports_no_break(self):
        # FR de los casos límite: con la tolerancia por encima del escalón, el comportamiento
        # correcto es "sin borde", no un borde arbitrario.
        distances, elevations = street_profile(curb_height=0.15, curb_run=0.5)

        surfaced = profile.detect_edges_surface(distances, elevations, 0.20, 3)

        self.assertEqual(surfaced['left']['reason'], profile.NO_BREAK)
        self.assertEqual(surfaced['right']['reason'], profile.NO_BREAK)

    def test_no_data_at_the_axis_voids_both_sides(self):
        distances, elevations = street_profile()
        center = len(distances) // 2
        elevations[center] = None
        for k in range(1, 12):                       # sin muestras válidas en toda la semilla
            elevations[center + k] = None
            elevations[center - k] = None

        surfaced = profile.detect_edges_surface(distances, elevations, 0.06, 3)

        self.assertEqual(surfaced['left']['reason'], profile.NO_DATA)
        self.assertEqual(surfaced['right']['reason'], profile.NO_DATA)
        self.assertIsNone(surfaced['reference'])

    def test_empty_profile_mirrors_detect_edges(self):
        surfaced = profile.detect_edges_surface([], [], 0.06, 3)
        self.assertEqual(surfaced['left']['reason'], profile.NO_DATA)
        self.assertEqual(surfaced['right']['reason'], profile.NO_DATA)

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            profile.detect_edges_surface([0.0], [], 0.06, 3)
