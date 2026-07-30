"""Corredor del eje y segmentación semántica de la ortofoto (`007` FR-005, FR-008,
`research.md` D25, D26, D31).

Aísla la E/S y la dependencia externa de `geodeep`: recorta la ortofoto al corredor del eje con
`gdalwarp` (mismo patrón que `coreplugins/objdetect/api.py:detect()`) y clasifica el recorte en
calzada / no-calzada con el modelo `roads`. `profile.py` sigue sin conocer nada de esto: solo
recibe la máscara ya muestreada en los mismos offsets que la elevación (`compute.py`).

Import de `geodeep` diferido y defensivo (`research.md` D31): este módulo debe poder importarse sin
que la librería esté instalada, para que `build_corridor` y el resto del plugin sigan funcionando.
"""

import json
import os

import rasterio
import rasterio.features
import rasterio.warp
from django.contrib.gis.geos import GEOSGeometry, LineString

# Margen sobre `search_half_width` al recortar el corredor (`research.md` D26): el buffer se
# calcula antes de conocer los bordes, así que el margen absorbe el redondeo del propio buffer y
# el remuestreo del modelo (resolución nativa 21 cm/px) sin perder cobertura justo en el límite.
CORRIDOR_MARGIN = 2.0  # metros

# Modelo de segmentación de `geodeep` que clasifica calzada / no-calzada (`research.md` D25).
SEGMENTATION_MODEL = 'roads'

# Valor de la máscara que significa «calzada» (`save_mask_to_raster` escribe 1 / 0).
MASK_ROAD_VALUE = 1

# --- Vectorización de la máscara (`008`, `research.md` D34/D38) -----------------------------

# Tolerancia de simplificación, en metros. **No es un número de compromiso**: coincide con la
# resolución a la que el modelo devuelve la máscara (medido: recorte de ortofoto a 5 cm/px →
# máscara a 20 cm/px, porque `geodeep` remuestrea a la resolución nativa de entrenamiento). Por
# debajo de esa resolución la máscara no contiene información: los vértices más finos son el
# contorno de los píxeles, no forma medida. Simplificar hasta aquí es gratis en información y muy
# caro de evitar en bytes — medido sobre corredores reales, 115 KB → 19,5 KB (66 m) y
# 309,5 KB → 76,9 KB (293 m).
MASK_SIMPLIFY_TOLERANCE_M = 0.20

# Superficie mínima de un polígono para conservarlo. Red de seguridad contra ruido de
# clasificación, **no** la palanca que controla el tamaño: medido sobre los dos corredores reales
# no descarta ni un polígono, porque `geodeep.segment()` ya aplica internamente su propio
# `filter_small_segments` antes de devolver la matriz (`research.md` D38).
MASK_MIN_AREA_M2 = 1.0

# Longitud de un grado de latitud, para convertir la tolerancia y el área a grados. La tolerancia
# se aplica en el espacio de grados de EPSG:4326, donde un grado de longitud es más corto que uno
# de latitud fuera del ecuador: a latitud 33° la tolerancia efectiva en longitud es ~0,167 m en vez
# de 0,20 m. El sesgo va hacia **conservar más detalle**, nunca menos, y las cifras medidas ya lo
# incluyen. Simplificar en el CRS proyectado sería más exacto a cambio de dos reproyecciones más,
# por una diferencia que no cambia ninguna decisión (`research.md` D38).
_M_PER_DEG = 111320.0


def _geos_to_geojson_geometry(geometry):
    """GeoJSON (dict) de una geometría GEOS, construido desde `.coords`.

    **No usar `GEOSGeometry.geojson`**: serializa a través de OGR, que respeta el orden de ejes
    oficial de EPSG:4326 —latitud primero— y devuelve las coordenadas **invertidas**. Comprobado:
    una entrada `[-93.0, 45.0]` vuelve como `[45.0, -93.0]`, con y sin `srid`. Leaflet las
    interpreta como `[lon, lat]`, así que los polígonos aparecerían en otro punto del planeta.
    `.coords` no pasa por OGR y conserva el orden con el que se construyó la geometría.
    """
    if geometry.geom_type == 'Polygon':
        return {
            'type': 'Polygon',
            'coordinates': [[[float(x), float(y)] for x, y in ring] for ring in geometry.coords],
        }
    if geometry.geom_type == 'MultiPolygon':
        return {
            'type': 'MultiPolygon',
            'coordinates': [[[[float(x), float(y)] for x, y in ring] for ring in polygon]
                            for polygon in geometry.coords],
        }
    raise ValueError('geometría no soportada para la máscara: {}'.format(geometry.geom_type))


def build_corridor(vertices, half_width, crs):
    """GeoJSON (dict, EPSG:4326) del buffer del eje completo por `half_width + CORRIDOR_MARGIN`.

    `vertices` son `[[lng, lat], ...]` (EPSG:4326, mismo formato que el resto del plugin —
    `axis.py`). `crs` es el CRS nativo en el que se calcula el buffer (el de la ortofoto):
    construirlo en grados daría un buffer con la forma equivocada salvo en el ecuador.

    El resultado se escribe tal cual a un `.geojson` para `gdalwarp -cutline`, sin declarar `crs`
    en el documento: GDAL asume CRS84/WGS84 para GeoJSON sin ese miembro y reproyecta el cutline
    al CRS del ráster de entrada — mismo patrón, sin `-cutline_srs`, que ya usa `objdetect`.
    """
    xs = [float(v[0]) for v in vertices]
    ys = [float(v[1]) for v in vertices]
    px, py = rasterio.warp.transform('EPSG:4326', crs, xs, ys)

    line = LineString(list(zip(px, py)))
    corridor = line.buffer(half_width + CORRIDOR_MARGIN)

    ring = corridor.exterior_ring
    coords = list(ring.coords)
    lons, lats = rasterio.warp.transform(
        crs, 'EPSG:4326', [c[0] for c in coords], [c[1] for c in coords])

    return {
        'type': 'Polygon',
        'coordinates': [[[lon, lat] for lon, lat in zip(lons, lats)]],
    }


def run_segmentation(orthophoto_path, corridor, progress_callback=None):
    """Recorta `orthophoto_path` al `corridor` (GeoJSON de `build_corridor`) y segmenta el recorte
    con el modelo `roads` de `geodeep`. Devuelve la ruta de la máscara ráster georreferenciada
    (`road` = 1, `not_road` = 0).

    Cualquier fallo —librería ausente, `gdalwarp` ausente, recorte vacío, descarga del modelo sin
    red— se propaga como una excepción con un mensaje identificable. No se captura aquí: quien
    llama (`compute.run_analysis`, ya con su propio manejo de excepciones) es quien decide qué
    hacer con un fallo de esta etapa (`research.md` D28, caso 1).
    """
    import shutil
    import subprocess
    import tempfile

    from webodm import settings

    try:
        from geodeep import segment as gsegment, models
        from geodeep.segmentation import save_mask_to_raster
    except ImportError:
        raise RuntimeError('GeoDeep library is missing')

    # Mismo directorio de caché que `objdetect.api.detect()`: un modelo descargado por un plugin
    # sirve al otro, y no hay razón para duplicar la descarga.
    models.cache_dir = os.path.join(settings.MEDIA_CACHE, 'detection_models')

    gdalwarp_bin = shutil.which('gdalwarp')
    if gdalwarp_bin is None:
        raise RuntimeError('Cannot find gdalwarp')

    tmpdir = os.path.join(settings.MEDIA_TMP,
                          os.path.basename(tempfile.mkdtemp('_road_segmentation',
                                                            dir=settings.MEDIA_TMP)))
    corridor_path = os.path.join(tmpdir, 'corridor.geojson')
    # GTiff y no VRT, a diferencia de `objdetect.api.detect()`: `save_mask_to_raster` hereda el
    # `driver` del archivo que se le pasa para reconstruir la georreferenciación de la máscara
    # (`geodeep.segmentation.save_mask_to_raster`), y un VRT no admite escribirse a través de él
    # ("Writing through VRTSourcedRasterBand is not supported"). `objdetect` no lo sufre porque
    # solo *lee* el VRT recortado, nunca lo usa como plantilla de escritura.
    ortho_crop = os.path.join(tmpdir, 'orthophoto.tif')
    mask_path = os.path.join(tmpdir, 'mask.tif')

    with open(corridor_path, 'w', encoding='utf-8') as f:
        json.dump(corridor, f)

    p = subprocess.Popen([gdalwarp_bin, '-cutline', corridor_path,
                          '--config', 'GDALWARP_DENSIFY_CUTLINE', 'NO',
                          '-crop_to_cutline', '-of', 'GTiff',
                          orthophoto_path, ortho_crop],
                         cwd=tmpdir, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        raise RuntimeError('Error calling gdalwarp: {}'.format(err.decode('utf-8').strip()))

    # `output_type='default'` da la máscara como `np.ndarray`, no un GeoJSON de polígonos
    # (`research.md` D30: la detección de borde muestrea la máscara, no opera sobre polígonos).
    mask = gsegment(ortho_crop, SEGMENTATION_MODEL, output_type='default',
                    progress_callback=progress_callback)
    # El tamaño de `mask` puede ser menor que el del recorte (el modelo remuestrea a su resolución
    # nativa): `save_mask_to_raster` recalcula el transform a partir del tamaño real de `mask`, así
    # que la georreferenciación queda correcta aunque la resolución no coincida.
    save_mask_to_raster(ortho_crop, mask, mask_path)

    return mask_path


def vectorize_mask(mask_path, simplify_tolerance_m=None, min_area_m2=None):
    """Convierte la máscara ráster en polígonos EPSG:4326 dibujables (`008` FR-001, D34).

    Trabaja sobre el ráster que `run_segmentation` **ya dejó en disco**, en vez de pedirle el
    GeoJSON a `geodeep`. No es una preferencia de estilo: `compute._read_block` necesita la máscara
    ráster para muestrear los perfiles transversales, y `geodeep.segment()` devuelve *o* la matriz
    *o* los polígonos, nunca ambos. Pedirle el GeoJSON obligaría a una segunda inferencia completa
    —medido: 13,49 s en un corredor de 293 m— para un resultado idéntico byte a byte al que produce
    `rasterio.features.shapes` en 0,036 s (`research.md` D34).

    Devuelve `{'features': [...], 'resolution_m': float, 'simplify_tolerance_m': float}`.
    `features` **puede venir vacío**: significa que el modelo no reconoció calzada en el corredor,
    que es un resultado con valor informativo —explica por qué los tramos salieron sin borde— y no
    un error (`FR-017`).

    `resolution_m` se lee del propio ráster y no de una constante: es el número con el que la
    interfaz avisa de la precisión real (`FR-016`), y si se codificara a mano dejaría de ser cierto
    en cuanto el modelo cambiara de resolución.
    """
    tolerance_m = (MASK_SIMPLIFY_TOLERANCE_M if simplify_tolerance_m is None
                   else float(simplify_tolerance_m))
    min_area = MASK_MIN_AREA_M2 if min_area_m2 is None else float(min_area_m2)

    with rasterio.open(mask_path) as ds:
        band = ds.read(1)
        resolution_m = abs(ds.transform.a)
        # `mask=` restringe la vectorización a las celdas de calzada: sin él, `shapes` devolvería
        # también los polígonos de fondo y de nodata, que no son calzada y no deben dibujarse.
        raw = list(rasterio.features.shapes(band, mask=(band == MASK_ROAD_VALUE),
                                            transform=ds.transform))
        src_crs = ds.crs

    tolerance_deg = tolerance_m / _M_PER_DEG
    min_area_deg2 = min_area / (_M_PER_DEG ** 2)

    features = []
    for geom, _value in raw:
        geometry = GEOSGeometry(json.dumps(rasterio.warp.transform_geom(src_crs, 'EPSG:4326', geom)),
                                srid=4326)
        if geometry.area < min_area_deg2:
            continue
        if tolerance_deg > 0:
            # `preserve_topology=True` para no generar autointersecciones, que Leaflet dibuja mal.
            geometry = geometry.simplify(tolerance_deg, preserve_topology=True)
            if geometry.empty:
                continue
        features.append({
            'type': 'Feature',
            'properties': {'class': 'road'},
            'geometry': _geos_to_geojson_geometry(geometry),
        })

    return {
        'features': features,
        'resolution_m': resolution_m,
        'simplify_tolerance_m': tolerance_m,
    }
