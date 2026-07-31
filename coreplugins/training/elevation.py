"""Canales derivados del modelo de terreno (D14, D15, D16).

El modelo no se entrena con RGB: entra un stack de 5 bandas `R, G, B, slope, roughness`. Este
módulo produce las dos últimas a partir del **DTM** de ODM, no del DSM: el DSM incluye camiones,
palas y estructuras, y esa señal no es topografía del camino sino lo que había encima el día del
vuelo.

**Nunca sale elevación absoluta.** Un canal con la cota en metros haría que el modelo aprendiese la
altitud de la mina en la que se entrenó; slope y roughness son invariantes a la cota y es lo único
que se exporta.

Tres decisiones que este módulo materializa:

1. **Alinear antes de derivar** (D15). El DTM se remuestrea a la rejilla exacta de salida de la
   tesela con `reproject` bilineal, y slope/roughness se calculan **sobre el DTM ya alineado**.
   Medido en la mina del usuario: orto y DTM tienen la misma resolución (0,0635 m) pero el origen
   del DTM está 3,8 cm más abajo — 0,6 px. Leer con `read(window=...)` sin reproyectar metería ese
   corrimiento en todas las teselas, y sería un fallo silencioso: los canales saldrían plausibles y
   sistemáticamente desplazados respecto al RGB.

2. **Halo en vez de stack global** (D14). Un GeoTIFF de 5 bandas de la ortofoto de la mina son
   3,05 GB (152 Mpx x 5 x float32) y el worker no los sostiene. `np.gradient` y la ventana 3x3 de
   la rugosidad son operadores locales, así que se lee la tesela con `HALO_PX` de margen, se deriva
   y se recorta: el resultado es idéntico al que daría el stack global, con un pico de memoria de
   una tesela.

3. **El techo de roughness se estima a la resolución del dataset** (D16). La rugosidad depende de
   la escala: la medida sobre un DTM decimado no se parece a la medida a 10 cm/px. Por eso el
   percentil no se calcula sobre una lectura reducida del ráster entero —que habría sido lo barato
   y lo incorrecto— sino sobre una muestra de teselas ya alineadas.

4. **La rugosidad no es el TRI** (D21). El TRI de Riley sobre terreno inclinado mide sobre todo la
   pendiente, y en el DTM real de la mina correlaba +0,907 con ella: una quinta banda que repite la
   cuarta. Ver `roughness()`.
"""

import math
import os

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import Affine
from rasterio.warp import reproject
from rasterio.windows import from_bounds

SOURCE_DTM = 'dtm'
SOURCE_DSM = 'dsm'
SOURCE_NONE = 'none'
SOURCES = (SOURCE_DTM, SOURCE_DSM, SOURCE_NONE)

ASSETS = {SOURCE_DTM: 'dtm.tif', SOURCE_DSM: 'dsm.tif'}

# Techo de la normalización de pendiente. 45° es la convención del texto de especificación: por
# encima de eso ya no es camino en ningún caso, y saturar ahí gasta el rango útil del canal en el
# tramo donde sí hay información.
SLOPE_CEILING_DEG = 45.0

# La rugosidad no tiene un techo natural, así que se mide. p98 y no el máximo porque un solo píxel
# de ruido del DTM —un artefacto de reconstrucción— aplastaría todo el resto del canal contra cero.
ROUGHNESS_PERCENTILE = 98.0
ROUGHNESS_WINDOW_PX = 3

# Margen que se lee de más alrededor de la tesela para que los operadores locales no vean el borde.
# `np.gradient` y la ventana 3x3 necesitan 1 px; 2 deja sitio también al núcleo del remuestreo
# bilineal.
HALO_PX = 2

# Teselas que se muestrean para estimar el techo de rugosidad. 24 sobre las 616 de la mina son un
# 4 % del terreno, suficiente para un percentil y despreciable en tiempo (~0,5 s).
SAMPLE_TILES = 24

# Suelo del techo de rugosidad, en metros. Un terreno perfectamente liso daría p98 = 0 y la
# normalización dividiría por cero; por debajo de 1 mm no hay rugosidad que un DTM fotogramétrico
# pueda medir de verdad.
MIN_ROUGHNESS_CEILING_M = 0.001


class ElevationUnavailable(Exception):
    """La tarea no tiene el ráster de elevación que el dataset pide."""


def resolve_source(task_id, requested=SOURCE_DTM):
    """`(ruta, fuente_efectiva)` del ráster de elevación de una tarea.

    La caída es solo DTM -> DSM y en ese sentido, como pide la especificación. Al revés no: quien
    elige DSM explícitamente está pidiendo la superficie con lo que haya encima, y servirle el
    terreno sería contestar otra pregunta.

    El import va dentro porque este módulo lo carga también el worker, donde `app.models` no puede
    importarse antes de que las apps de Django estén listas.
    """
    from app.models import Task

    if requested == SOURCE_NONE:
        return None, SOURCE_NONE

    candidates = [SOURCE_DTM, SOURCE_DSM] if requested == SOURCE_DTM else [requested]

    try:
        task = Task.objects.get(pk=task_id)
    except Exception:
        raise ElevationUnavailable('La tarea {} ya no existe.'.format(task_id))

    for source in candidates:
        path = task.get_asset_download_path(ASSETS[source])
        if os.path.isfile(path):
            return path, source

    raise ElevationUnavailable(
        'La tarea {} no tiene {}.'.format(task_id, ' ni '.join(ASSETS[s] for s in candidates)))


def read_aligned(dem, tile, tile_size_px, halo=HALO_PX):
    """El DTM remuestreado a la rejilla de salida de la tesela, con `halo` px de margen.

    Devuelve `(elevación relativa float32, máscara booleana de válidos, referencia en metros)`. Los
    dos arrays son de lado `tile_size_px + 2 * halo`; los píxeles sin dato salen como `nan` en el
    array y `False` en la máscara, y quien llama decide qué hacer con ellos, pero nunca debe
    dejarlos entrar en un canal. Sumar la referencia devuelve la cota absoluta, que es lo que
    permite comprobar el registro geográfico sin que ningún canal dependa de ella.

    **La elevación es relativa a la media de la ventana, no absoluta**, y eso es precisión, no
    estilo. Los DTM de ODM son `float32` y la mina del usuario está a 4 100 m: ahí el paso de
    representación es 4100 x 2^-23 = 0,49 mm, y el remuestreo bilineal acumula sobre eso. Medido en
    la suite, el ruido de fila a fila sobre un plano perfecto era de 2 mm, del orden de la propia
    rugosidad que este módulo tiene que medir. Restando la referencia antes de remuestrear, los valores
    quedan en unidades de metros alrededor de cero y el paso baja a las decenas de nanómetros.

    No se pierde nada: ningún canal usa la cota absoluta, precisamente para que el modelo no
    aprenda la altitud de la mina en la que se entrenó.

    La ventana de origen se recorta y se lee a mano en vez de pasarle el ráster entero a
    `reproject`, para que el pico de memoria sea demostrable: es la ventana nativa que cubre la
    tesela más un margen, unos 800 px de lado en la mina.
    """
    size = tile_size_px + 2 * halo
    resolution_m = abs(tile.transform.a)

    # El transform de destino es el de la tesela corrido `halo` píxeles hacia arriba y a la
    # izquierda, de modo que el recorte posterior devuelva exactamente la rejilla de la tesela.
    dst_transform = tile.transform * Affine.translation(-halo, -halo)

    left, top = dst_transform * (0, 0)
    right, bottom = dst_transform * (size, size)

    # Margen extra en la lectura de origen para el núcleo del remuestreo bilineal, que mira un
    # píxel nativo a cada lado.
    margin = 4 * max(abs(dem.transform.a), abs(dem.transform.e))
    window = from_bounds(left - margin, bottom - margin, right + margin, top + margin,
                         transform=dem.transform)

    nodata = dem.nodata
    fill = nodata if nodata is not None else -9999.0
    raw = dem.read(1, window=window, boundless=True, fill_value=fill)
    source_transform = dem.window_transform(window)

    # La resta va en float64 para que el propio centrado no introduzca el error que viene a quitar.
    known = raw != fill
    reference = float(raw[known].astype('float64').mean()) if known.any() else 0.0
    source = np.where(known, raw.astype('float64') - reference, fill).astype('float32')

    destination = np.full((size, size), np.nan, dtype='float32')
    reproject(
        source=source,
        destination=destination,
        src_transform=source_transform,
        src_crs=dem.crs,
        src_nodata=fill,
        dst_transform=dst_transform,
        dst_crs=dem.crs,
        dst_nodata=np.nan,
        resampling=Resampling.bilinear,
    )

    valid = np.isfinite(destination)
    return destination, valid, reference


def slope_degrees(dem, resolution_m):
    """Pendiente en grados, con la resolución real del ráster.

    Pasarle la resolución a `np.gradient` no es cosmética: sin ella el gradiente sale en metros por
    píxel, así que la misma ladera daría pendientes distintas según la resolución del dataset y el
    modelo no podría transferir entre vuelos.
    """
    dz_dy, dz_dx = np.gradient(dem.astype('float64'), resolution_m, resolution_m)
    return np.degrees(np.arctan(np.hypot(dz_dx, dz_dy))).astype('float32')


def roughness(dem):
    """Rugosidad en ventana 3x3: RMS del residuo respecto al plano local, en metros.

    **No es el TRI de Riley**, y la diferencia se midió antes de decidirla. El TRI —media de
    `|centro - vecino|`— sobre una superficie lisa pero inclinada no vale cero: vale
    `0,75 x pendiente x paso`. O sea que sobre terreno inclinado el TRI mide sobre todo la
    pendiente. Medido en el DTM real de la mina, a 10 cm/px sobre una ventana de 1 900 px de lado:

        canal            p50       p98       corr. con pendiente
        TRI            0,0416    0,2609            +0,907
        residuo        0,0132    0,0732            +0,750

    Con r = 0,907 el 82 % de la varianza del TRI ya la explica la banda de pendiente: sería una
    quinta banda que repite la cuarta, que es justo por lo que la especificación descarta el
    hillshade. Quitando el plano de la ventana antes de medir la dispersión, el canal pasa a decir
    lo que su nombre promete —cuánto se aparta el terreno de ser liso— y aporta un 44 % de
    información propia.

    El plano es el de mínimos cuadrados de los 9 puntos. Con `dx, dy` en `{-1, 0, 1}` la suma de
    `dx^2` sobre la ventana vale 6, así que la pendiente ajustada es `(columna derecha - columna
    izquierda) / 6` y el término independiente es la media: no hace falta resolver ningún sistema.

    Se calcula con desplazamientos de numpy en vez de con `scipy.ndimage` —que sí está en la
    imagen— porque son nueve restas sobre una tesela y no justifica arrastrar la dependencia hasta
    el worker (Principio IV).
    """
    center = dem.astype('float64')
    padded = np.pad(center, 1, mode='edge')
    rows, cols = center.shape

    window = {}
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            window[(dy, dx)] = padded[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]

    mean = sum(window.values()) / 9.0
    slope_x = sum(window[(dy, 1)] - window[(dy, -1)] for dy in (-1, 0, 1)) / 6.0
    slope_y = sum(window[(1, dx)] - window[(-1, dx)] for dx in (-1, 0, 1)) / 6.0

    total = np.zeros_like(center)
    for (dy, dx), values in window.items():
        total += (values - (mean + slope_x * dx + slope_y * dy)) ** 2

    return np.sqrt(total / 9.0).astype('float32')


def tile_channels(dem, tile, tile_size_px, halo=HALO_PX):
    """`(slope_deg, roughness_m, válidos)` de una tesela, ya recortados al tamaño de salida.

    Los píxeles sin dato del DTM se rellenan con la media de los válidos **antes** de derivar. No
    es para inventarse terreno: es para que el operador local no propague `nan` a los vecinos
    buenos. Esos píxeles salen marcados en `válidos` y quien llama los manda a «ignorar».
    """
    elevation, valid, _ = read_aligned(dem, tile, tile_size_px, halo)

    if valid.any():
        elevation = np.where(valid, elevation, float(elevation[valid].mean()))
    else:
        elevation = np.zeros_like(elevation)

    resolution_m = abs(tile.transform.a)
    slope = slope_degrees(elevation, resolution_m)
    rough = roughness(elevation)

    # Un píxel cuyo vecindario 3x3 toca relleno tiene un valor derivado del escalón artificial
    # entre el terreno y la media, no del terreno. Se marca inválido, que es lo único honesto: el
    # relleno existe para que el operador no propague `nan`, no para inventar terreno.
    #
    # Sin esto, la primera fila y la primera columna de toda tesela pegada al borde del DTM salían
    # con la rugosidad saturada. Se veía como una retícula de líneas brillantes en el canal 5, y
    # solo en las teselas del perímetro: el tipo de artefacto que se confunde con textura real.
    valid = _erode(valid)

    crop = slice(halo, halo + tile_size_px) if halo else slice(None)
    return slope[crop, crop], rough[crop, crop], valid[crop, crop]


def _erode(valid):
    """`valid` sin su borde: un píxel sobrevive solo si sus ocho vecinos también son válidos."""
    padded = np.pad(valid, 1, mode='constant', constant_values=False)
    rows, cols = valid.shape
    result = valid.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            result &= padded[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]
    return result


def estimate_roughness_ceiling(dem, tiles, tile_size_px,
                               percentile=ROUGHNESS_PERCENTILE, sample_tiles=SAMPLE_TILES):
    """Percentil `percentile` de la rugosidad, medido a la resolución del dataset (D16).

    Se muestrean teselas repartidas por toda la rejilla —no las primeras, que en una ortofoto son
    casi siempre borde sin datos— y se agrupan sus valores válidos.

    Devuelve el techo en metros, nunca por debajo de `MIN_ROUGHNESS_CEILING_M`.
    """
    if not tiles:
        return MIN_ROUGHNESS_CEILING_M

    step = max(1, len(tiles) // sample_tiles)
    samples = []

    for tile in tiles[::step][:sample_tiles]:
        _, rough, valid = tile_channels(dem, tile, tile_size_px)
        if valid.any():
            samples.append(rough[valid])

    if not samples:
        return MIN_ROUGHNESS_CEILING_M

    pooled = np.concatenate(samples)
    if pooled.size == 0:
        return MIN_ROUGHNESS_CEILING_M

    return max(float(np.percentile(pooled, percentile)), MIN_ROUGHNESS_CEILING_M)


def normalize_slope(slope_deg, ceiling_deg=SLOPE_CEILING_DEG):
    """Pendiente a [0, 1]."""
    return np.clip(slope_deg / float(ceiling_deg), 0.0, 1.0).astype('float32')


def normalize_roughness(roughness_m, ceiling_m):
    """Rugosidad a [0, 1] con el techo medido."""
    ceiling = max(float(ceiling_m), MIN_ROUGHNESS_CEILING_M)
    return np.clip(roughness_m / ceiling, 0.0, 1.0).astype('float32')


def normalization_metadata(roughness_ceiling_m, slope_ceiling_deg=SLOPE_CEILING_DEG):
    """El bloque `normalization` de `dataset.json`.

    Lo que la inferencia del plugin tendrá que reproducir **exactamente**. Va descrito banda a
    banda y con la fórmula escrita, para que quien escriba el cargador no tenga que deducirla de
    este código ni de la especificación.
    """
    return {
        'bands': [
            {'index': 1, 'name': 'red', 'source': 'orthophoto',
             'formula': 'value / 255', 'input_range': [0, 255]},
            {'index': 2, 'name': 'green', 'source': 'orthophoto',
             'formula': 'value / 255', 'input_range': [0, 255]},
            {'index': 3, 'name': 'blue', 'source': 'orthophoto',
             'formula': 'value / 255', 'input_range': [0, 255]},
            {'index': 4, 'name': 'slope', 'source': 'elevation',
             'formula': 'clip(slope_degrees / ceiling_deg, 0, 1)',
             'ceiling_deg': float(slope_ceiling_deg)},
            {'index': 5, 'name': 'roughness', 'source': 'elevation',
             'formula': 'clip(roughness_meters / ceiling_m, 0, 1)',
             'ceiling_m': round(float(roughness_ceiling_m), 6),
             'percentile': ROUGHNESS_PERCENTILE,
             'window_px': ROUGHNESS_WINDOW_PX,
             'definition': ('RMS del residuo respecto al plano de minimos cuadrados de la ventana '
                            '3x3, en metros. Vale cero sobre cualquier superficie plana, este o no '
                            'inclinada: mide falta de planitud, no pendiente.')},
        ],
        'output_range': [0.0, 1.0],
    }


BAND_NAMES = ('red', 'green', 'blue', 'slope', 'roughness')
BAND_COUNT = len(BAND_NAMES)
