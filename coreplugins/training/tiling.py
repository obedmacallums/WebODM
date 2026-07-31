"""Rejilla de teselas de una ortofoto a la resolución del dataset (D5, D6, D11, D20).

Tres decisiones gobiernan este módulo:

1. **La rejilla se define en el terreno, no en píxeles nativos.** Una tesela mide siempre
   `tile_size_px x resolution_cm_px` metros, venga de una ortofoto de 2,22 cm/px o de 6,35 — que
   es el rango real de las cinco tareas del usuario. Sin esto, cada tarea aportaría teselas de un
   tamaño de terreno distinto y el modelo aprendería escalas mezcladas (FR-023).

2. **La ventana nativa se lee directamente al tamaño de salida** (D6): `raster.read(..., window,
   out_shape)` remuestrea en la propia lectura, sin warp intermedio ni ficheros temporales. Este
   módulo solo calcula la ventana; leerla es cosa de `export.py`.

3. **Las teselas se solapan** (D20). Con el paso igual al tamaño, un camino que cruce justo por la
   junta aparece partido en dos mitades y en ninguna de las dos se ve entero. El solape hace que
   todo tramo del terreno esté completo en al menos una tesela. El precio es que las teselas
   vecinas comparten píxeles, y de ahí que el reparto train/val tenga que ser por zonas y no
   aleatorio (`split.py`).

La rejilla se ancla a la esquina superior izquierda de la ortofoto, así que es determinista: dos
exportaciones sin cambios producen exactamente las mismas teselas (FR-031).
"""

import collections
import math

from rasterio.transform import from_origin
from rasterio.warp import transform_bounds
from rasterio.windows import Window

Tile = collections.namedtuple('Tile', 'row col window transform bounds bounds_wgs84')
"""Una tesela.

- `window`: ventana en píxeles **nativos** del ráster, para `raster.read`.
- `transform`: transform de la tesela **de salida**, a la resolución del dataset. Es lo que alinea
  la máscara rasterizada con la imagen leída.
- `bounds`: extensión en el CRS de la ortofoto (métrico), donde se hace el buffer del pincel.
- `bounds_wgs84`: la misma extensión en coordenadas geográficas, que es lo que va al manifiesto.
"""


def tile_grid(raster, resolution_cm_px, tile_size_px, overlap_px=0):
    """Genera las teselas que cubren la ortofoto, por filas.

    La última fila y la última columna pueden sobresalir del ráster. No se recortan a propósito:
    las teselas deben ser todas del mismo tamaño en píxeles para poder entrenar con ellas, y lo
    que sobresale se lee como sin datos y lo descarta el umbral de píxeles válidos de FR-027. Un
    caso especial para los bordes habría sido más código y peor resultado.
    """
    resolution_m = float(resolution_cm_px) / 100.0
    tile_span_m = tile_size_px * resolution_m
    stride_px = stride(tile_size_px, overlap_px)
    stride_m = stride_px * resolution_m

    left, bottom, right, top = raster.bounds
    native_x = abs(raster.transform.a)
    native_y = abs(raster.transform.e)

    rows, columns = _grid_shape(right - left, top - bottom, tile_span_m, stride_m)

    # Cuántos píxeles nativos hay que leer para producir una tesela de `tile_size_px`. Con una
    # ortofoto de 5 cm/px y un dataset de 10, son el doble: 128 nativos -> 64 de salida.
    window_width = tile_span_m / native_x
    window_height = tile_span_m / native_y
    step_x = stride_m / native_x
    step_y = stride_m / native_y

    for row in range(rows):
        for col in range(columns):
            x0 = left + col * stride_m
            y1 = top - row * stride_m
            bounds = (x0, y1 - tile_span_m, x0 + tile_span_m, y1)

            yield Tile(
                row=row,
                col=col,
                window=Window(col * step_x, row * step_y, window_width, window_height),
                transform=from_origin(x0, y1, resolution_m, resolution_m),
                bounds=bounds,
                bounds_wgs84=transform_bounds(raster.crs, 'EPSG:4326', *bounds),
            )


def stride(tile_size_px, overlap_px):
    """Paso de la rejilla en píxeles de salida.

    El solape se recorta a `tile_size - 1` para que el paso nunca sea cero: un solape mayor o igual
    que la tesela generaría infinitas teselas sobre el mismo sitio.
    """
    overlap = max(0, min(int(overlap_px or 0), int(tile_size_px) - 1))
    return int(tile_size_px) - overlap


def _grid_shape(width_m, height_m, tile_span_m, stride_m):
    """Filas y columnas necesarias para cubrir el ráster con teselas de `tile_span_m`."""
    def count(extent):
        if extent <= tile_span_m:
            return 1
        return int(math.ceil((extent - tile_span_m) / stride_m)) + 1

    return max(1, count(height_m)), max(1, count(width_m))


def grid_size(raster, resolution_cm_px, tile_size_px, overlap_px=0):
    """`(filas, columnas)` sin construir las teselas. Para estimar antes de exportar."""
    resolution_m = float(resolution_cm_px) / 100.0
    tile_span_m = tile_size_px * resolution_m
    stride_m = stride(tile_size_px, overlap_px) * resolution_m
    left, bottom, right, top = raster.bounds
    return _grid_shape(right - left, top - bottom, tile_span_m, stride_m)
