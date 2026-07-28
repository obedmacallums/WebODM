"""La pasada de coherencia (`006` FR-011..FR-018, `research.md` D20).

El orden de los tests refleja el orden de importancia: primero las **garantías de que no
inventa** —un hueco largo no se rellena, los inferidos no votan, ventana 0 es la identidad—, que
son las que hacen aceptable la inferencia frente a `005/FR-022`; después la precisión de lo que sí
repara.

Todo opera sobre listas de offsets en metros, sin ráster ni Django: `repair_edges` es pura.
"""

from django.test import SimpleTestCase

from .. import coherence


def sides(left, right=None):
    return coherence.repair_edges(left, right if right is not None else list(left), 2)


class CoherenceSafetyTest(SimpleTestCase):
    """Lo que la pasada se niega a hacer. Si alguno de estos falla, la feature miente."""

    def test_a_long_gap_is_never_filled(self):
        # Diez tramos sin borde: el descampado del caso de referencia (SC-006). La evidencia de
        # los extremos no puede viajar hacia el centro por muy corta que sea la distancia en
        # tramos, porque los rellenos no votan.
        offsets = [4.0, 4.1] + [None] * 10 + [4.0, 3.9]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        # Los dos tramos pegados a la evidencia real (2 y 11) sí pueden rellenarse: están a
        # distancia de ventana de dos bordes medidos. Todo el interior, jamás.
        for i in range(3, 11):
            self.assertIsNone(repaired[i][0], 'el tramo %d del hueco se rellenó' % i)
            self.assertIsNone(repaired[i][1])

    def test_inferred_edges_do_not_vote(self):
        # El tramo 2 es reparable (vecinos 0,1,3 medidos). Si su relleno votara, el 4 tendría
        # "dos vecinos" y la inferencia avanzaría en cadena por todo el hueco.
        offsets = [4.0, 4.1, None, 4.05] + [None] * 6

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        self.assertIsNotNone(repaired[2][0])
        self.assertEqual(repaired[2][1], 'inferred')
        # El 4 ve un solo medido (el 3): sin evidencia suficiente, intacto.
        self.assertIsNone(repaired[4][0])
        # Y del 5 en adelante, nada de nada.
        for i in range(5, 10):
            self.assertIsNone(repaired[i][0])

    def test_window_zero_is_the_identity(self):
        # FR-012: la garantía mecánica de que ningún análisis existente cambia de resultado.
        offsets = [4.0, None, 12.0, 3.9, None]

        repaired = coherence.repair_edges(offsets, list(offsets), 0)[0]

        for original, (offset, source) in zip(offsets, repaired):
            self.assertEqual(offset, original)
            self.assertEqual(source, 'measured' if original is not None else None)

    def test_fewer_than_two_measured_neighbors_changes_nothing(self):
        # FR-014. Con un solo vecino medido no hay dispersión que estimar ni mediana que valga.
        offsets = [None, 4.0, None]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        self.assertIsNone(repaired[0][0])
        self.assertEqual(repaired[1], (4.0, 'measured'))
        self.assertIsNone(repaired[2][0])

    def test_sides_are_independent(self):
        # FR-011: cada lado por separado. Un lado con evidencia no presta bordes al otro.
        left = [4.0, 4.1, None, 4.0, 4.05]
        right = [None] * 5

        repaired_left, repaired_right = coherence.repair_edges(left, right, 2)

        self.assertEqual(repaired_left[2][1], 'inferred')
        for offset, source in repaired_right:
            self.assertIsNone(offset)
            self.assertIsNone(source)


class CoherencePrecisionTest(SimpleTestCase):
    """Lo que sí repara, y con qué criterio."""

    def test_an_isolated_outlier_is_replaced_by_the_neighborhood_median(self):
        # El salto medido en el caso real: 1,25 -> 0,10 -> 1,50 sobre un bordillo recto. El 0,10
        # se aparta más de lo que la dispersión de su vecindad admite (FR-016).
        offsets = [1.25, 1.30, 0.10, 1.50, 1.20]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        self.assertEqual(repaired[2][1], 'inferred')
        self.assertAlmostEqual(repaired[2][0], 1.275, places=3)
        for i in (0, 1, 3, 4):
            self.assertEqual(repaired[i][1], 'measured')
            self.assertEqual(repaired[i][0], offsets[i])

    def test_a_short_gap_is_filled_and_marked(self):
        # FR-015: el paso de peatones o el acceso rebajado del caso de referencia.
        offsets = [5.8, 5.9, None, 5.85, 5.8]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        self.assertEqual(repaired[2][1], 'inferred')
        self.assertAlmostEqual(repaired[2][0], 5.825, places=3)   # mediana de 5.8/5.9/5.85/5.8

    def test_a_legitimate_gradual_widening_is_not_flattened(self):
        # FR-017: un ensanche que se abre de 1,0 a 2,0 m varía ~0,17 m entre vecinos, por debajo
        # del suelo de 0,30 m. Aplanarlo sería inventar una calle recta donde hay un ensanche.
        offsets = [1.0 + i / 6.0 for i in range(7)]   # 1,00 .. 2,00 en pasos de ~0,17

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        for original, (offset, source) in zip(offsets, repaired):
            self.assertEqual(source, 'measured')
            self.assertEqual(offset, original)

    def test_the_threshold_widens_with_the_neighborhood_dispersion(self):
        # El umbral sale del MAD, no de una constante: en una vecindad que ya varía medio metro
        # entre tramos, apartarse 0,8 m es normal y no debe corregirse.
        offsets = [3.0, 4.0, 4.8, 3.5, 4.4]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        for original, (offset, source) in zip(offsets, repaired):
            self.assertEqual(source, 'measured')
            self.assertEqual(offset, original)

    def test_a_perfectly_uniform_neighborhood_still_tolerates_the_floor(self):
        # Vecindad idéntica -> MAD 0 -> sin el suelo de 0,30 m cualquier desviación minúscula
        # sería "atípica". 0,25 m debe sobrevivir; 0,45 m no.
        survives = [4.0, 4.0, 4.25, 4.0, 4.0]
        repaired = coherence.repair_edges(survives, list(survives), 2)[0]
        self.assertEqual(repaired[2], (4.25, 'measured'))

        replaced = [4.0, 4.0, 4.45, 4.0, 4.0]
        repaired = coherence.repair_edges(replaced, list(replaced), 2)[0]
        self.assertEqual(repaired[2][1], 'inferred')
        self.assertAlmostEqual(repaired[2][0], 4.0, places=6)

    def test_the_edges_of_the_sequence_use_their_one_sided_neighborhood(self):
        # El primer tramo no tiene vecinos atrás: su ventana es la que hay, no una excusa para
        # dejarlo fuera de la reparación.
        offsets = [None, 4.0, 4.1, 4.05]

        repaired = coherence.repair_edges(offsets, list(offsets), 2)[0]

        self.assertEqual(repaired[0][1], 'inferred')
        self.assertAlmostEqual(repaired[0][0], 4.05, places=3)
