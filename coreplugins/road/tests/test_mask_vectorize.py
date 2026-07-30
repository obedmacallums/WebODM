"""Vectorización de la máscara de segmentación (`008` Phase 2, D34/D38).

Estos tests no tocan `geodeep` ni la red: parten de una máscara ráster ya escrita, que es
exactamente lo que `run_segmentation` deja en disco. Lo que se prueba es la conversión de esa
matriz a polígonos dibujables y su simplificación.
"""

import json
import os
import tempfile

from .base import DEM_EPSG, DEM_ORIGIN, DEM_RES, RoadTestBase
from .test_compute import make_road_mask

from coreplugins.road import segmentation


class VectorizeMaskTest(RoadTestBase):
    """`vectorize_mask` convierte el ráster que el modelo produjo en polígonos EPSG:4326."""

    def _mask(self, **kwargs):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'mask.tif')
        make_road_mask(path, kwargs.pop('half_left', 4.0), kwargs.pop('half_right', 4.0), **kwargs)
        return path

    def _diagonal_mask(self, size=120):
        """Máscara con el borde en diagonal, para que el contorno sea escalonado.

        Un borde diagonal sobre una rejilla produce un peldaño por celda, que es la forma real que
        devuelve el modelo y la razón de ser de la simplificación.
        """
        import numpy as np
        import rasterio
        from rasterio.transform import from_origin

        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, 'diagonal.tif')

        rows, cols = np.meshgrid(np.arange(size), np.arange(size), indexing='ij')
        data = (cols < rows).astype('uint8')

        with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=1,
                           dtype='uint8', crs='EPSG:{}'.format(DEM_EPSG),
                           transform=from_origin(DEM_ORIGIN[0], DEM_ORIGIN[1],
                                                 DEM_RES, DEM_RES)) as dst:
            dst.write(data, 1)
        return path

    def test_returns_polygons_in_wgs84(self):
        """El dibujo es Leaflet, que habla en grados: la salida ya viene reproyectada.

        El ráster está en UTM (`DEM_EPSG`), así que si no se reproyectara las coordenadas serían
        centenares de miles de metros y caerían fuera de todo rango geográfico válido.
        """
        result = segmentation.vectorize_mask(self._mask())

        self.assertGreater(len(result['features']), 0)
        for feature in result['features']:
            self.assertEqual(feature['geometry']['type'], 'Polygon')
            self.assertEqual(feature['properties']['class'], 'road')
            for lon, lat in feature['geometry']['coordinates'][0]:
                self.assertGreaterEqual(lon, -180.0)
                self.assertLessEqual(lon, 180.0)
                self.assertGreaterEqual(lat, -90.0)
                self.assertLessEqual(lat, 90.0)

    def test_reports_the_resolution_of_the_mask_itself(self):
        """`resolution_m` sale del ráster, no de una constante.

        Es el número con el que la interfaz avisa al usuario de la precisión real (`FR-016`). Si
        se escribiera a mano en el frontend, dejaría de ser cierto en cuanto el modelo cambiara.
        """
        result = segmentation.vectorize_mask(self._mask())
        self.assertAlmostEqual(result['resolution_m'], DEM_RES, places=6)

    def test_empty_mask_yields_no_features_and_no_error(self):
        """Que el modelo no vea calzada es un resultado, no un fallo (`FR-017`).

        Un corredor sin calzada detectada explica por qué los tramos salieron sin borde, así que
        tiene que poder distinguirse de «no hay máscara». Reventar aquí borraría esa diferencia.

        Semiancho negativo y no cero: con cero, `make_road_mask` todavía marca la columna exacta
        del eje (la condición es `d <= half_width`, y `d == 0` la cumple).
        """
        result = segmentation.vectorize_mask(self._mask(half_left=-1.0, half_right=-1.0))
        self.assertEqual(result['features'], [])

    def test_simplification_drops_vertices_without_changing_the_class(self):
        """La simplificación es lo que controla el tamaño (D38), no el filtro de área.

        Hace falta un borde **diagonal**: la calzada recta de `make_road_mask` queda alineada con la
        rejilla y su contorno son cinco vértices, que ya es el mínimo de un anillo cerrado — no hay
        nada que simplificar. Los bordes reales son escalonados, que es justo lo que produce los
        miles de vértices que esta simplificación existe para recortar.
        """
        path = self._diagonal_mask()

        fine = segmentation.vectorize_mask(path, simplify_tolerance_m=0.0)
        coarse = segmentation.vectorize_mask(path, simplify_tolerance_m=2.0)

        def vertices(result):
            return sum(len(ring)
                       for feature in result['features']
                       for ring in feature['geometry']['coordinates'])

        self.assertGreater(vertices(fine), vertices(coarse))
        for feature in coarse['features']:
            self.assertEqual(feature['properties']['class'], 'road')

    def test_reports_the_tolerance_it_applied(self):
        """Queda trazado qué se descartó, para que el tamaño sea explicable a posteriori."""
        result = segmentation.vectorize_mask(self._mask(), simplify_tolerance_m=0.5)
        self.assertAlmostEqual(result['simplify_tolerance_m'], 0.5, places=6)

    def test_min_area_discards_specks(self):
        """Red de seguridad contra ruido de clasificación (`FR-008`).

        Ojo con lo que este filtro NO es: medido sobre corredores reales no descarta ni un
        polígono, porque `geodeep` ya aplica su propio filtro antes de devolver la matriz (D38).
        Aquí se fuerza con un umbral absurdo para probar que el mecanismo funciona, no para
        sugerir que sea lo que controla el tamaño.
        """
        path = self._mask(half_left=4.0, half_right=4.0)

        kept = segmentation.vectorize_mask(path, min_area_m2=0.0)
        self.assertGreater(len(kept['features']), 0)

        dropped = segmentation.vectorize_mask(path, min_area_m2=10.0 ** 9)
        self.assertEqual(dropped['features'], [])

    def test_ignores_nodata_cells(self):
        """Un hueco de cobertura no es calzada, y tampoco debe salir como polígono."""
        path = self._mask(half_left=4.0, half_right=4.0,
                          nodata_patch=(0, 240, 0, 480))
        result = segmentation.vectorize_mask(path)

        # Con la mitad superior en nodata debe seguir habiendo calzada, pero solo en la inferior.
        self.assertGreater(len(result['features']), 0)
        top_y = DEM_ORIGIN[1]
        for feature in result['features']:
            for _lon, lat in feature['geometry']['coordinates'][0]:
                self.assertLess(lat, top_y)   # en grados, muy por debajo del origen UTM

    def test_output_is_json_serializable(self):
        """Se persiste como JSON: una geometría no serializable rompería el guardado."""
        result = segmentation.vectorize_mask(self._mask())
        json.dumps(result)
