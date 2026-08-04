"""Partición del terreno en regiones para la selección asistida (`010`, research.md D1–D9).

La herramienta no clasifica nada: parte la ortofoto en regiones que siguen los bordes visibles y
deja que el usuario diga qué es cada una. Todo lo que hay aquí sirve a tres propiedades, y ninguna
de las tres es negociable:

1. **Determinismo** (FR-007). El mismo punto con los mismos ajustes da siempre la misma región,
   esté la caché fría o caliente, sea la primera vez o la centésima.
2. **Independencia del encuadre** (FR-008). El resultado no depende del zoom, del tamaño de la
   ventana del navegador ni del orden de los clics.
3. **Sin juntas** (FR-009). Una región que cruza el borde de una celda de trabajo sale entera, sin
   ningún corte recto artificial.

Las tres salen de una misma decisión: **la rejilla de trabajo se ancla al terreno, no a la vista.**

## Por qué el anclaje, por qué el halo mide `8·S`, y por qué además hay costura

SLIC coloca sus semillas en una rejilla regular de paso `S = sqrt(N_px / n_segments)` que empieza
en `S/2` **relativo a la ventana que se le pasa**. Dos ventanas cuyos orígenes no difieran en un
múltiplo de `S` reciben rejillas desfasadas y parten el mismo terreno de formas distintas. Medido
sobre la ortofoto real del usuario: **11,343 %** de pares de píxeles vecinos en desacuerdo con la
ventana desalineada 7 px, frente a **0,960 %** con la ventana alineada. De ahí las dos invariantes
que impone `WorkGrid`: `S` divide a `CELL`, y el origen de cada ventana es múltiplo de `S` en
coordenadas globales de la ortofoto.

**El desacuerdo no llega a cero, y eso no es un defecto que quede por arreglar.** La fase 0 midió
0,000 % de desacuerdo con halo `8·S`, pero lo midió con la `compactness` por defecto de skimage
(10), que a estas escalas degenera en una rejilla de cuadrados perfectos: convergen exactamente
porque no siguen ningún borde. Medido, con `compactness=10` la región mayor del núcleo mide 256 px,
o sea exactamente el tamaño nominal — ninguna se ha deformado para seguir nada. Con la
`compactness` que sí sigue los bordes (ver `COMPACTNESS`), el desacuerdo baja monótonamente con el
halo pero se queda en torno al 1 %:

    halo:       0S      1S      2S      4S      8S     12S     16S
    desacuerdo: 2,344 % 1,725 % 1,446 % 1,194 % 0,960 % 0,860 % 0,678 %

Cambiar la `compactness` para recuperar la convergencia exacta habría sido cumplir FR-009 a costa
de que la feature dejara de servir para lo que existe. Así que la junta se resuelve donde de verdad
se ve: **cosiendo**. Cuando una región toca el borde del núcleo y `continues` dice que sigue hacia
fuera, se le añade entera la región de la celda vecina que ocupa el píxel de enfrente
(`cross_cell_links`). Medido sobre las 33 regiones que cruzan una junta real, comparando contra la
partición de referencia de una ventana que abarca las dos celdas:

    halo:                        0S     1S     2S     4S     8S    16S
    IoU de la unión cosida     0,735  0,811  0,858  0,953  0,981  0,976
    IoU sin coser (solo A)     0,735  0,777  0,785  0,786  0,795  0,801

Las dos columnas dicen cada una su cosa. **Sin coser**, la región se queda en 0,79 haga lo que haga
el halo: le falta el trozo del otro lado, que es exactamente el corte recto que FR-009 prohíbe.
**Cosiendo**, sube a 0,981 y ahí se estanca — `16·S` no mejora a `8·S`. Ese estancamiento es lo que
fija el halo en `8·S`: por debajo la partición del borde está deformada por no ver el terreno de
fuera, y por encima solo se paga tiempo.

`tests/test_superpixels.py::SeamTest` es lo único que sostiene todo esto: es invisible en revisión
de código y romperlo no da ningún síntoma, solo regiones que terminan en una línea recta.

## El techo de rugosidad es constante a propósito

`elevation.estimate_roughness_ceiling` mide el percentil 98 sobre una muestra, que es lo correcto
al exportar. Aquí sería un fallo: un techo calculado por ventana normalizaría el mismo píxel del
terreno con divisores distintos según qué celda lo calculó, y la coincidencia exacta del solape
—o sea FR-009— se perdería. Se usa una constante medida (`ROUGHNESS_CEILING_M`).

## Las dependencias

`scikit-image` no está en la imagen: lo instala el framework en el `site-packages` del plugin.
`slic_function()` resuelve ese directorio y lo añade al **final** de `sys.path`, de modo que numpy
y scipy se sigan resolviendo contra los de la imagen aunque el plugin tenga copias. Ver
`requirements.txt` y `tests/test_requirements.py`.
"""

import collections
import os
import sys

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform
from rasterio.windows import Window

from . import elevation, tiling

# Versión del algoritmo de partición. **Subirla es obligatorio** en cuanto cambie cualquier cosa que
# altere el resultado: paso de la rejilla, halo, compactness, orden o normalización de las bandas.
# Forma parte de la clave de caché (`regions.py`), y sin subirla un mapa viejo convive con uno nuevo
# y rompe el determinismo de FR-007 en silencio, que es el peor fallo posible en esta feature.
ALGORITHM_VERSION = 1

# Lado del núcleo de una celda de trabajo, en píxeles a la resolución del dataset. 512 px son 51,2 m
# a 10 cm/px. **No es la rejilla de teselas de exportación** (`tiling.py`), que se solapa por diseño
# y por eso no serviría: aquí las celdas deben ser disjuntas para que cada píxel del terreno
# pertenezca a una y solo una.
CELL_PX = 512

# Halo en múltiplos de `S`. 8 es donde la fidelidad de una región cosida a través de una junta se
# estanca: 0,953 con `4·S`, 0,981 con `8·S`, 0,976 con `16·S` (ver la cabecera). Bajarlo deforma las
# regiones del borde; subirlo solo cuesta tiempo, y el coste va con el cuadrado de la ventana.
HALO_FACTOR = 8

# Paso de la rejilla de semillas por granularidad, en píxeles. Una región mide del orden de `S²`.
GRANULARITIES = collections.OrderedDict((
    ('fine', 8),
    ('medium', 16),
    ('coarse', 32),
))
DEFAULT_GRANULARITY = 'medium'

# Peso de la distancia espacial frente a la de color en SLIC. El valor por defecto de skimage (10)
# está pensado para Lab, cuyo canal L llega a 100; aquí las bandas van en [0, 1], así que con 10 la
# distancia de color no pesa nada y sale una rejilla de cuadrados perfectos.
#
# 0,5 no es una estimación: es el mínimo medido de la desviación típica **dentro** de cada región
# sobre la ortofoto real del usuario, que es la forma directa de medir si las regiones respetan los
# bordes o los atraviesan. Ventana de 768 px, 5 bandas, desviación típica global 0,2100:
#
#     compactness   regiones   mediana   mayor región   desv. típica intra-región
#        0,1           733       298 px     3524 px            0,0790
#        0,3          1035       261 px     1097 px            0,0641
#        0,5          1095       256 px      488 px            0,0620   <- mínimo
#        0,8          1098       256 px      339 px            0,0652
#       10,0          1089       256 px      256 px            0,0776   <- rejilla perfecta
#
# Por debajo las regiones se desparraman y una sola se come varios objetos; por encima convergen a
# cuadrados de S² px que ignoran el terreno. El caso de 10,0 es revelador: **mayor región = 256 px**
# es exactamente el tamaño nominal, o sea que ninguna región se ha deformado para seguir un borde.
COMPACTNESS = 0.5

# Iteraciones de SLIC. Fijo y explícito: es parte de la definición del resultado, no un ajuste.
MAX_ITER = 10

# Techo de normalización de la rugosidad, en metros. Constante a propósito — ver la cabecera. El
# valor es el p98 medido en el DTM real del usuario a 10 cm/px (0,0732 m), redondeado hacia arriba.
ROUGHNESS_CEILING_M = 0.10

# Tope de regiones que puede alcanzar el crecimiento por tolerancia (FR-018). A `medium` sobre un
# dataset de 10 cm/px, una región mide 2,56 m², así que 2000 regiones son unos 5100 m². Pasado el
# tope el crecimiento **se detiene y lo declara**, en vez de seguir hasta comerse el vuelo entero.
MAX_GROWTH_REGIONS = 2000


class OutsideRaster(Exception):
    """El punto pedido cae fuera de la ortofoto."""


# --- Resolución de `scikit-image` --------------------------------------------------------

_slic = None


def plugin_site_packages():
    """Directorio donde el framework instala el `requirements.txt` del plugin."""
    from app.plugins.functions import get_plugins_persistent_path
    return get_plugins_persistent_path('training', 'site-packages')


def candidate_site_packages():
    """Dónde buscar los paquetes del plugin, en orden.

    El segundo candidato existe por un detalle del entorno de tests que si no deja la feature entera
    sin cobertura: bajo `manage.py test`, `MEDIA_ROOT` apunta a `app/media_test`, y ahí no hay nada
    instalado porque `check_requirements()` corre al **registrar** los plugins y el proceso de test
    no los registra. Los paquetes reales están en el `MEDIA_ROOT` de producción y se leen tal cual —
    solo se leen, el test no escribe ahí.

    Sin esto, `test_superpixels` se saltaría o fallaría entero en un entorno donde el plugin
    funciona perfectamente, que es la peor clase de test: el que enseña un problema que no existe.
    """
    from django.conf import settings

    paths = [plugin_site_packages()]
    if getattr(settings, 'TESTING', False):
        paths.append(os.path.join(settings.BASE_DIR, 'app', 'media', 'plugins', 'training',
                                  'site-packages'))
    return paths


def resolve_site_packages():
    """El primer candidato que exista, o `None` si el plugin todavía no ha instalado nada."""
    for path in candidate_site_packages():
        if os.path.isdir(path):
            return path
    return None


def slic_function():
    """`skimage.segmentation.slic`, resolviendo el `site-packages` del plugin si hace falta.

    El directorio se añade al **final** de `sys.path`, no al principio. `python_imports()` del
    framework lo antepone, y eso hace que las copias de numpy y scipy del plugin tapen a las de la
    imagen; funciona porque `requirements.txt` las pinea a la misma versión, pero depender de ello
    en cada import sería apostar a que nadie toque los pines. Al final, la imagen siempre gana y lo
    único que se toma del plugin es lo que la imagen no tiene.
    """
    global _slic
    if _slic is not None:
        return _slic

    path = resolve_site_packages()
    if path is not None and path not in sys.path:
        sys.path.append(path)

    from skimage.segmentation import slic as _skimage_slic
    _slic = _skimage_slic
    return _slic


# --- Rejilla de trabajo ------------------------------------------------------------------

def spacing_px(granularity):
    """Paso `S` de la rejilla de semillas. Lanza `ValueError` si la granularidad no existe."""
    try:
        return GRANULARITIES[str(granularity or DEFAULT_GRANULARITY)]
    except KeyError:
        raise ValueError('Granularidad desconocida: {!r}. Las válidas son {}.'.format(
            granularity, ', '.join(GRANULARITIES)))


def halo_px(granularity):
    return HALO_FACTOR * spacing_px(granularity)


def window_size_px(granularity):
    return CELL_PX + 2 * halo_px(granularity)


class WorkGrid:
    """Rejilla de celdas disjuntas sobre una ortofoto, a la resolución de un dataset.

    Se ancla a la esquina superior izquierda de la ortofoto, igual criterio que `tiling.py`. La
    identidad de una celda es `(fila, columna)` y es **función únicamente del punto del terreno**:
    ni el zoom, ni el encuadre, ni el orden de los clics entran en el cálculo. De ahí salen FR-007
    y FR-008 sin ningún esfuerzo adicional.
    """

    def __init__(self, raster, resolution_cm_px, granularity=DEFAULT_GRANULARITY):
        self.crs = raster.crs
        self.left, self.bottom, self.right, self.top = raster.bounds
        self.native_x = abs(raster.transform.a)
        self.native_y = abs(raster.transform.e)
        self.resolution_m = float(resolution_cm_px) / 100.0
        self.granularity = str(granularity or DEFAULT_GRANULARITY)
        self.spacing = spacing_px(self.granularity)
        self.halo = halo_px(self.granularity)
        self.window_size = window_size_px(self.granularity)

        if CELL_PX % self.spacing:
            raise ValueError(
                'El paso S={} no divide al lado de celda CELL={}: las ventanas dejarían de estar '
                'alineadas y la partición perdería el determinismo.'.format(self.spacing, CELL_PX))

        span_x = self.right - self.left
        span_y = self.top - self.bottom
        cell_span_m = CELL_PX * self.resolution_m
        self.rows = max(1, int(np.ceil(span_y / cell_span_m)))
        self.cols = max(1, int(np.ceil(span_x / cell_span_m)))

    # -- Coordenadas ----------------------------------------------------------------------

    def xy_to_pixel(self, x, y):
        """Punto del CRS de la ortofoto a píxel global de salida (float, sin redondear)."""
        return ((x - self.left) / self.resolution_m, (self.top - y) / self.resolution_m)

    def lnglat_to_xy(self, lng, lat):
        """EPSG:4326 al CRS de la ortofoto.

        Con `rasterio.warp.transform` y nunca con `GEOSGeometry.transform`: este último invierte el
        orden de ejes al tocar el 4326 y produce coordenadas corruptas sin lanzar ningún error.
        """
        xs, ys = warp_transform('EPSG:4326', self.crs, [float(lng)], [float(lat)])
        return xs[0], ys[0]

    def cell_of_xy(self, x, y):
        """Celda `(fila, columna)` que contiene un punto. `OutsideRaster` si cae fuera."""
        px, py = self.xy_to_pixel(x, y)
        if not (0 <= px < self.cols * CELL_PX and 0 <= py < self.rows * CELL_PX):
            raise OutsideRaster('El punto cae fuera de la ortofoto.')
        return int(py // CELL_PX), int(px // CELL_PX)

    def cell_of_lnglat(self, lng, lat):
        x, y = self.lnglat_to_xy(lng, lat)
        return self.cell_of_xy(x, y)

    def offset_in_cell(self, x, y):
        """`(fila, columna)` del píxel dentro del núcleo de su celda."""
        px, py = self.xy_to_pixel(x, y)
        return int(py) % CELL_PX, int(px) % CELL_PX

    def contains_cell(self, row, col):
        return 0 <= row < self.rows and 0 <= col < self.cols

    # -- Geometría de una celda -----------------------------------------------------------

    def cell_origin_px(self, row, col):
        """Píxel global de salida de la esquina superior izquierda del **núcleo**."""
        return col * CELL_PX, row * CELL_PX

    def window_origin_px(self, row, col):
        """Píxel global de la ventana de cálculo, halo incluido.

        **Invariante**: es múltiplo de `S`. `CELL_PX` lo es (512 = 64·8 = 32·16 = 16·32) y el halo
        es `8·S`, así que `col·CELL - 8·S` también. Es la propiedad de la que depende que dos
        celdas vecinas reciban la misma rejilla de semillas.
        """
        x0, y0 = self.cell_origin_px(row, col)
        return x0 - self.halo, y0 - self.halo

    def cell_transform(self, row, col):
        x0, y0 = self.cell_origin_px(row, col)
        return from_origin(self.left + x0 * self.resolution_m,
                           self.top - y0 * self.resolution_m,
                           self.resolution_m, self.resolution_m)

    def window_tile(self, row, col):
        """Una `tiling.Tile` que describe la ventana de cálculo con halo de una celda.

        Se devuelve una `Tile` y no una tupla suelta porque es lo que `elevation.tile_channels`
        consume: así los canales de terreno se leen exactamente con la misma corrección de
        alineación (D15) que usa la exportación, sin duplicar esa lógica ni tocar `elevation.py`.
        """
        px, py = self.window_origin_px(row, col)
        size = self.window_size
        x0 = self.left + px * self.resolution_m
        y1 = self.top - py * self.resolution_m
        span = size * self.resolution_m
        bounds = (x0, y1 - span, x0 + span, y1)

        return tiling.Tile(
            row=row, col=col,
            window=Window((x0 - self.left) / self.native_x,
                          (self.top - y1) / self.native_y,
                          span / self.native_x,
                          span / self.native_y),
            transform=from_origin(x0, y1, self.resolution_m, self.resolution_m),
            bounds=bounds,
            bounds_wgs84=None,   # no se usa aquí; calcularlo por celda sería gasto puro
        )

    def cells_for_bounds(self, minx, miny, maxx, maxy):
        """Celdas que intersecan una extensión del CRS de la ortofoto."""
        px0, py0 = self.xy_to_pixel(minx, maxy)
        px1, py1 = self.xy_to_pixel(maxx, miny)
        col0 = max(0, int(px0 // CELL_PX))
        col1 = min(self.cols - 1, int(px1 // CELL_PX))
        row0 = max(0, int(py0 // CELL_PX))
        row1 = min(self.rows - 1, int(py1 // CELL_PX))
        return [(r, c) for r in range(row0, row1 + 1) for c in range(col0, col1 + 1)]


# --- Stack de bandas ---------------------------------------------------------------------

def band_stack(ortho, dem, tile, size_px, elevation_weight=1.0):
    """`(stack float32 (size, size, bandas), máscara de válidos)` de una ventana.

    RGB normalizado a [0, 1] más, si hay ráster de elevación y peso, pendiente y rugosidad
    normalizadas y escaladas por el peso. Con peso 0 o sin DTM/DSM salen 3 bandas y **no falla**
    (FR-011): trabajar sin terreno es un modo de uso, no un error.

    El RGB se remuestrea en la propia lectura, igual que en la exportación (D6). Los canales de
    terreno los produce `elevation.tile_channels`, que ya corrige el desalineo de 0,6 px entre la
    ortofoto y el DTM de ODM (D15); replicar eso aquí habría sido duplicar el fallo más caro de
    detectar del plugin.
    """
    rgb = ortho.read((1, 2, 3), window=tile.window, out_shape=(3, size_px, size_px),
                     boundless=True, fill_value=0)

    if ortho.count >= 4:
        # El alfa dice sin ambigüedad qué píxeles tienen datos de vuelo (D7). Las ortofotos reales
        # llegan con `nodata: None`, así que cualquier heurística sobre el valor —¿un negro es
        # sombra o ausencia de datos?— sería una fuente de fallos silenciosos.
        alpha = ortho.read(4, window=tile.window, out_shape=(size_px, size_px),
                           boundless=True, fill_value=0)
        valid = alpha > 0
    else:
        valid = np.ones((size_px, size_px), dtype=bool)

    channels = [rgb[i].astype('float32') / 255.0 for i in range(3)]

    weight = float(elevation_weight or 0.0)
    if dem is not None and weight > 0:
        slope, rough, dem_valid = elevation.tile_channels(dem, tile, size_px)
        channels.append(elevation.normalize_slope(slope) * weight)
        channels.append(elevation.normalize_roughness(rough, ROUGHNESS_CEILING_M) * weight)
        valid = valid & dem_valid

    return np.stack(channels, axis=-1).astype('float32'), valid


# --- Partición ---------------------------------------------------------------------------

def partition_window(bands, spacing):
    """Etiqueta cada píxel de la ventana con su región. Devuelve `int32` de la forma de `bands`.

    `n_segments` se elige para que el paso efectivo de la rejilla de semillas de SLIC sea
    exactamente `spacing`: con una ventana de `W × H` y semillas cada `S`, hacen falta
    `(W/S)·(H/S)`. Es lo que ancla las semillas a múltiplos de `S` y, con el origen de la ventana
    alineado, hace que dos celdas vecinas partan el solape de forma idéntica.

    `convert2lab=False` es deliberado y no un descuido. skimage lo activa solo cuando la imagen
    tiene exactamente 3 canales, así que dejarlo por defecto haría que el camino sin terreno
    (3 bandas) segmentara en un espacio de color distinto al del camino con terreno (5 bandas):
    cambiar el peso de elevación a cero cambiaría el resultado por dos motivos a la vez.
    """
    height, width = bands.shape[:2]
    if height % spacing or width % spacing:
        raise ValueError(
            'La ventana {}×{} no es múltiplo del paso S={}: la rejilla de semillas quedaría '
            'desalineada y la partición dejaría de ser determinista.'.format(
                height, width, spacing))

    n_segments = (height // spacing) * (width // spacing)
    slic = slic_function()
    return slic(bands, n_segments=n_segments, compactness=COMPACTNESS,
                channel_axis=-1, convert2lab=False, enforce_connectivity=True,
                start_label=0, max_num_iter=MAX_ITER, sigma=0).astype('int32')


CellPartition = collections.namedtuple(
    'CellPartition', 'labels means adjacency continues valid band_count elevation_source')
"""Partición del núcleo de una celda.

- `labels`: `int32 (CELL, CELL)`, índice de región compacto desde 0.
- `means`: `float32 (n_regiones, bandas)`, vector medio de cada región. Alimenta la tolerancia.
- `adjacency`: `set` de pares `(i, j)` con `i < j`, regiones vecinas dentro del núcleo.
- `continues`: `{'top'|'bottom'|'left'|'right': bool[CELL]}`, si el píxel del borde del núcleo
  pertenece a la **misma** región que su vecino de fuera. Es lo que permite coser una región que
  cruza a la celda de al lado sin volver a segmentar (ver `cross_cell_neighbours`).
- `valid`: `bool (CELL, CELL)`, píxeles con datos de vuelo.
"""


def partition_cell(ortho, dem, grid, row, col, elevation_weight=1.0):
    """Calcula la partición del núcleo de una celda. Es la operación cara: ~0,95 s medidos."""
    tile = grid.window_tile(row, col)
    bands, valid = band_stack(ortho, dem, tile, grid.window_size, elevation_weight)
    window_labels = partition_window(bands, grid.spacing)

    halo = grid.halo
    # Se recorta el núcleo **más un anillo de un píxel**. Ese anillo no se guarda: solo sirve para
    # saber si la región del borde continúa hacia fuera, que es lo que hace posible devolver entera
    # una región que cruza la junta (FR-009).
    ext = window_labels[halo - 1:halo + CELL_PX + 1, halo - 1:halo + CELL_PX + 1]
    core = ext[1:-1, 1:-1]

    continues = {
        'top': ext[0, 1:-1] == core[0, :],
        'bottom': ext[-1, 1:-1] == core[-1, :],
        'left': ext[1:-1, 0] == core[:, 0],
        'right': ext[1:-1, -1] == core[:, -1],
    }

    labels, means = _compact(core, bands[halo:halo + CELL_PX, halo:halo + CELL_PX])
    return CellPartition(
        labels=labels,
        means=means,
        adjacency=_adjacency(labels),
        continues={k: np.ascontiguousarray(v) for k, v in continues.items()},
        valid=np.ascontiguousarray(valid[halo:halo + CELL_PX, halo:halo + CELL_PX]),
        band_count=bands.shape[-1],
        elevation_source=None,   # lo rellena quien sabe de dónde salió el DEM
    )


def _compact(core, bands):
    """Renumera las regiones del núcleo desde 0 y calcula su vector medio.

    El recorte deja huecos en la numeración —hay regiones que solo existían en el halo—, y una
    numeración con huecos convertiría `means` en una tabla llena de filas muertas indexada por
    números que no significan nada.
    """
    unique, flat = np.unique(core, return_inverse=True)
    labels = flat.reshape(core.shape).astype('int32')

    count = unique.size
    band_count = bands.shape[-1]
    sums = np.zeros((count, band_count), dtype='float64')
    for band in range(band_count):
        sums[:, band] = np.bincount(labels.ravel(), weights=bands[:, :, band].ravel(),
                                    minlength=count)
    sizes = np.bincount(labels.ravel(), minlength=count).astype('float64')
    means = (sums / np.maximum(sizes, 1)[:, None]).astype('float32')
    return labels, means


def _adjacency(labels):
    """Pares de regiones vecinas en 4-conectividad, como `set` de `(menor, mayor)`."""
    pairs = set()
    for a, b in ((labels[:-1, :], labels[1:, :]), (labels[:, :-1], labels[:, 1:])):
        different = a != b
        if not different.any():
            continue
        left = a[different].astype('int64')
        right = b[different].astype('int64')
        low = np.minimum(left, right)
        high = np.maximum(left, right)
        pairs.update(zip(low.tolist(), high.tolist()))
    return pairs


# --- Costura entre celdas ----------------------------------------------------------------

_OPPOSITE = {'top': 'bottom', 'bottom': 'top', 'left': 'right', 'right': 'left'}
_STEP = {'top': (-1, 0), 'bottom': (1, 0), 'left': (0, -1), 'right': (0, 1)}


def _edge(labels, side):
    if side == 'top':
        return labels[0, :]
    if side == 'bottom':
        return labels[-1, :]
    if side == 'left':
        return labels[:, 0]
    return labels[:, -1]


def cross_cell_links(partition, region, cell, load_cell):
    """`(fragmentos, vecinas)` de `region` al otro lado de las juntas de su celda.

    - **fragmentos**: trozos de **la misma** región guardados en la celda de al lado. Una región que
      cruza la junta vive partida en dos núcleos; como las dos celdas parten el solape de forma
      idéntica (halo `8·S`, 0,000 % de desacuerdo medido), basta mirar qué región de la vecina ocupa
      el píxel de enfrente. Entran en la selección **siempre**: son la misma región, y de eso
      depende FR-009.
    - **vecinas**: regiones distintas que solo se tocan a través de la junta. Entran únicamente si
      pasan el umbral de tolerancia, igual que cualquier vecina de dentro de la celda. Sin ellas, el
      crecimiento de US3 se pararía en seco en los bordes de celda: exactamente la junta artificial
      que la feature existe para no tener.

    `continues` es lo que separa los dos casos. Sin ese dato habría que elegir entre coserlo todo
    —tragándose el terreno vecino— o no coser nada —y dejar la junta a la vista—.

    `load_cell(fila, columna)` se llama **solo** para los lados que la región toca de verdad.
    Preparar una celda cuesta ~0,95 s, así que cargar las cuatro vecinas en cada clic multiplicaría
    por cinco el coste del caso normal, que es un clic en mitad de una celda ya preparada.
    """
    row, col = cell
    fragments = set()
    adjacent = set()

    for side, (drow, dcol) in _STEP.items():
        edge = _edge(partition.labels, side)
        on_edge = edge == region
        if not on_edge.any():
            continue

        neighbour = load_cell(row + drow, col + dcol)
        if neighbour is None:
            continue

        opposite = _edge(neighbour.labels, _OPPOSITE[side])
        same = partition.continues[side]

        for index in np.unique(opposite[on_edge & same]):
            fragments.add((row + drow, col + dcol, int(index)))
        for index in np.unique(opposite[on_edge & ~same]):
            adjacent.add((row + drow, col + dcol, int(index)))

    return fragments, adjacent


# --- Selección y crecimiento -------------------------------------------------------------

Selection = collections.namedtuple('Selection', 'regions truncated')


def grow(seeds, tolerance, load_cell, max_regions=MAX_GROWTH_REGIONS):
    """Regiones seleccionadas a partir de unas semillas `(fila, columna, índice)`.

    `load_cell(row, col)` devuelve la `CellPartition` de una celda, o `None` si está fuera de la
    ortofoto. Se le pide bajo demanda: el crecimiento prepara celdas nuevas solo si de verdad las
    alcanza.

    Dos cosas ocurren aquí, y conviene no confundirlas:

    1. **La costura** (siempre). Los fragmentos de una misma región repartidos entre celdas se unen.
       No es opcional ni depende de la tolerancia: es lo que hace cumplir FR-009.
    2. **El crecimiento** (si `tolerance > 0`). Se admiten regiones vecinas cuyo vector medio diste
       de la **semilla** menos que el umbral.

    Medir contra la semilla y no contra la vecina inmediata es lo que garantiza la monotonía de
    FR-017: la admisión de cada región es una condición sobre un valor fijo, así que una tolerancia
    mayor admite un superconjunto y la selección de A queda contenida en la de B.

    El tope se comprueba **antes** de expandir (D7): así la selección devuelta nunca lo supera, y
    `truncated` dice que había más y se paró, en vez de dejar al usuario creyendo que ahí se
    acababa el terreno parecido.
    """
    selected = set()
    truncated = False
    queue = collections.deque()
    partitions = {}
    neighbour_maps = {}

    def partition_at(row, col):
        if (row, col) not in partitions:
            partitions[(row, col)] = load_cell(row, col)
        return partitions[(row, col)]

    def neighbours_within(cell, part):
        """`{región: [vecinas]}` de una celda, construido una sola vez.

        Recorrer el `set` de adyacencia entero por cada región convertiría el crecimiento en
        cuadrático sobre las ~1000 regiones de una celda.
        """
        if cell not in neighbour_maps:
            mapping = collections.defaultdict(list)
            for a, b in part.adjacency:
                mapping[a].append(b)
                mapping[b].append(a)
            neighbour_maps[cell] = mapping
        return neighbour_maps[cell]

    reference = None
    for row, col, index in seeds:
        part = partition_at(row, col)
        if part is None or index < 0 or index >= part.means.shape[0]:
            continue
        if reference is None:
            reference = part.means[index]
        if (row, col, index) not in selected:
            selected.add((row, col, index))
            queue.append((row, col, index))

    if reference is None:
        return Selection(regions=set(), truncated=False)

    growing = bool(tolerance) and float(tolerance) > 0
    threshold = float(tolerance or 0.0) * np.sqrt(float(reference.size))

    def close_enough(part, index):
        return float(np.linalg.norm(part.means[index] - reference)) <= threshold

    while queue and not truncated:
        row, col, index = queue.popleft()
        part = partition_at(row, col)
        if part is None:
            continue

        # (1) Costura: los fragmentos de esta misma región en las celdas de al lado entran siempre,
        # sin pasar por el umbral. No son terreno parecido: son la misma región.
        fragments, across = cross_cell_links(part, index, (row, col), partition_at)
        candidates = set(fragments)

        # (2) Crecimiento por parecido, dentro y a través de la junta con el mismo criterio: que la
        # junta esté ahí no debe cambiar qué se selecciona.
        if growing:
            for other in neighbours_within((row, col), part)[index]:
                if close_enough(part, other):
                    candidates.add((row, col, other))
            for candidate in across:
                other_part = partition_at(candidate[0], candidate[1])
                if other_part is not None and close_enough(other_part, candidate[2]):
                    candidates.add(candidate)

        for candidate in candidates:
            if candidate in selected:
                continue
            # El tope se comprueba antes de añadir, no después: así lo devuelto nunca lo supera.
            if len(selected) >= max_regions:
                truncated = True
                break
            selected.add(candidate)
            queue.append(candidate)

    return Selection(regions=selected, truncated=truncated)


# --- Vectorización -----------------------------------------------------------------------

def selection_geometry(grid, regions, partitions):
    """`MultiPolygon` en EPSG:4326 de las regiones seleccionadas, o `None` si no hay ninguna.

    Se rasteriza la selección sobre la caja de las celdas implicadas, se vectoriza con
    `rasterio.features.shapes` y se reproyecta con `rasterio.warp.transform`.

    **Nunca `GEOSGeometry.transform`**: al pasar a EPSG:4326 invierte el orden de los ejes y
    devuelve coordenadas `(lat, lon)` sin lanzar ningún error. Una geometría así se guarda tan
    contenta y aparece en el otro hemisferio (research.md D6).
    """
    from rasterio.features import shapes

    if not regions:
        return None

    rows = [r for r, _, _ in regions]
    cols = [c for _, c, _ in regions]
    row0, row1 = min(rows), max(rows)
    col0, col1 = min(cols), max(cols)

    height = (row1 - row0 + 1) * CELL_PX
    width = (col1 - col0 + 1) * CELL_PX
    mask = np.zeros((height, width), dtype='uint8')

    by_cell = collections.defaultdict(list)
    for row, col, index in regions:
        by_cell[(row, col)].append(index)

    for (row, col), indexes in by_cell.items():
        part = partitions.get((row, col))
        if part is None:
            continue
        top = (row - row0) * CELL_PX
        left = (col - col0) * CELL_PX
        mask[top:top + CELL_PX, left:left + CELL_PX] |= np.isin(
            part.labels, indexes).astype('uint8')

    if not mask.any():
        return None

    x0, y0 = grid.cell_origin_px(row0, col0)
    transform = from_origin(grid.left + x0 * grid.resolution_m,
                            grid.top - y0 * grid.resolution_m,
                            grid.resolution_m, grid.resolution_m)

    polygons = []
    for geometry, value in shapes(mask, mask=mask.astype(bool), transform=transform):
        if not value:
            continue
        polygons.append([_to_wgs84(grid.crs, ring) for ring in geometry['coordinates']])

    if not polygons:
        return None

    return {'type': 'MultiPolygon', 'coordinates': polygons}


def _to_wgs84(crs, ring):
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    lngs, lats = warp_transform(crs, 'EPSG:4326', xs, ys)
    return [[round(lng, 9), round(lat, 9)] for lng, lat in zip(lngs, lats)]
