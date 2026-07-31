"""Etiquetas -> máscara de una tesela (D5, D8, FR-012, FR-026).

El núcleo de la feature, y el sitio donde un error sería silencioso: una máscara mal compuesta no
rompe nada, solo entrena un modelo peor.

Cuatro reglas, todas verificables:

1. **La máscara empieza entera a 255.** Lo que nadie haya revisado se queda en «ignorar», nunca en
   clase 0 (FR-026). Es lo contrario de lo que haría un `zeros()`, y de ahí que se escriba
   explícitamente.
2. **El fondo lo crean las áreas revisadas, no la ausencia de etiquetas** (D18). Dentro de un área
   que el anotador declara revisada, lo que no lleve etiqueta es fondo de verdad —clase 0— y el
   modelo aprende de ello. Fuera, sigue siendo «no lo sé». La diferencia importa: un camino real
   sin etiquetar dentro de un área revisada enseña activamente «esto no es camino», y ese ruido
   hace más daño que tener menos datos.
3. **Se pinta en orden ascendente de `order` y gana el último** (FR-012). Rasterizar sobre el
   mismo array en ese orden produce la precedencia sin ninguna lógica adicional.
4. **El buffer de la línea central se hace en el CRS métrico de la ortofoto** (FR-012b, D4).
   Aplicarlo sobre grados lo interpretaría como grados y produciría un trazo cinco órdenes de
   magnitud mayor.

El motor geométrico es el GEOS de GeoDjango y no `shapely`, que **no está en la imagen** (D8): una
dependencia nueva está prohibida por FR-037. `rasterio.features.rasterize` acepta geometrías en
formato GeoJSON, que es justo lo que GEOS sabe entregar — el mismo camino que ya usa `road`.
"""

import collections
import json

import numpy as np
from django.contrib.gis.geos import LineString, LinearRing, Polygon
from rasterio.crs import CRS
from rasterio.features import rasterize as rio_rasterize
from rasterio.warp import transform as warp_transform

from .models import BACKGROUND_INDEX, IGNORE_INDEX, KIND_REVIEW

WGS84 = CRS.from_epsg(4326)

# Segmentos con que GEOS aproxima un cuarto de círculo al hacer `buffer`. Ocho da un error de área
# por debajo del 0,2 %, muy por debajo de la discretización a 10 cm/px, y mantiene acotado el
# número de vértices de un trazo largo.
BUFFER_QUAD_SEGS = 8


PreparedLabel = collections.namedtuple(
    'PreparedLabel', 'shape value extent kind hard_negative')
"""Una etiqueta ya reproyectada al CRS de la ortofoto y traducida a GeoJSON."""


def prepare_labels(labels, crs):
    """Reproyecta las etiquetas **una vez por tarea**, no una vez por tesela.

    La rejilla de la mina tiene 900 teselas y el dataset del usuario 53 etiquetas: reproyectar
    dentro del bucle serían 47 000 llamadas a PROJ para 53 geometrías distintas. Preparar antes es
    lo que hace que el exportador pueda recorrer la rejilla dos veces —planificar y escribir— sin
    que la segunda pasada cueste nada.

    Salen ordenadas por `order`, que es la precedencia con la que se pintan (FR-012).
    """
    prepared = []
    for label in sorted(labels, key=lambda l: l.get('order', 0)):
        geometry = label_geometry(label, crs)
        if geometry is None:
            continue

        kind = label.get('kind')
        if kind == KIND_REVIEW:
            value = BACKGROUND_INDEX
        else:
            # La etiqueta de ignorar devuelve a 255, que es el mismo valor con el que nace la
            # máscara: no es un caso especial del rasterizado, solo un valor distinto.
            raw = label.get('class_index')
            value = IGNORE_INDEX if raw is None else int(raw)

        prepared.append(PreparedLabel(
            shape=json.loads(geometry.geojson),
            value=value,
            extent=geometry.extent,
            kind=kind,
            hard_negative=bool(label.get('hard_negative')),
        ))
    return prepared


def rasterize_prepared(prepared, tile, tile_size_px):
    """Máscara `uint8` de una tesela a partir de etiquetas ya preparadas.

    Las áreas revisadas se pintan **antes** que todo lo demás y siempre a fondo (0), sin mirar su
    `order`. No compiten con las etiquetas de clase: establecen el lienzo sobre el que estas se
    pintan. Así una etiqueta de «ignorar» dibujada dentro de un área revisada sigue ganando —que es
    justo para lo que sirve: marcar un trozo dudoso dentro de una zona por lo demás revisada.
    """
    mask = np.full((tile_size_px, tile_size_px), IGNORE_INDEX, dtype=np.uint8)

    reviewed = []
    painted = []
    for label in prepared:
        if not _intersects(label.extent, tile.bounds):
            continue
        (reviewed if label.kind == KIND_REVIEW else painted).append((label.shape, label.value))

    for shapes in (reviewed, painted):
        if shapes:
            rio_rasterize(shapes, out=mask, transform=tile.transform, all_touched=False)

    return mask


def rasterize_tile(labels, tile, crs, tile_size_px):
    """Máscara de una tesela a partir de las etiquetas crudas.

    Atajo para quien solo va a rasterizar una tesela. El exportador usa `prepare_labels` +
    `rasterize_prepared`, que hacen lo mismo sin repetir la reproyección.
    """
    return rasterize_prepared(prepare_labels(labels, crs), tile, tile_size_px)


def touches_hard_negative(prepared, tile):
    """¿Cae la tesela dentro de un área revisada marcada como negativo difícil? (FR-043)"""
    return any(label.hard_negative and label.kind == KIND_REVIEW
               and _intersects(label.extent, tile.bounds)
               for label in prepared)


def project(points, crs):
    """Pasa `[[lon, lat], ...]` al CRS métrico de la ortofoto.

    Lo hace `rasterio.warp.transform` y **no** `GEOSGeometry.transform`, y la diferencia no es de
    gusto: con PROJ moderno, GeoDjango trata EPSG:4326 con el orden de ejes (lat, lon) declarado
    en la EPSG, así que interpreta como latitud la longitud que se le pasa. Medido sobre un punto
    de la ortofoto de prueba: la ida a WGS84 daba (-70,111, -36,140) y la vuelta con GEOS
    devolvía (1 694 024, 1 888 506) en lugar de (400 000, 6 000 000) — la geometría acababa fuera
    de la zona UTM y ninguna etiqueta llegaba a pintarse. `warp_transform` usa el orden (x, y) sin
    ambigüedad y es el mismo camino que ya recorre la lectura de la ortofoto.

    GEOS se sigue usando para el buffer, que es lo que sabe hacer sin depender del orden de ejes.
    """
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    projected_x, projected_y = warp_transform(WGS84, crs, xs, ys)
    return list(zip(projected_x, projected_y))


def label_geometry(label, crs):
    """La etiqueta como polígono en el CRS de la ortofoto, o `None` si no forma superficie.

    Las etiquetas se guardan en coordenadas geográficas (D4) y se reproyectan aquí, una sola vez
    por etiqueta y tesela.
    """
    points = label.get('geometry') or []
    kind = label.get('kind')

    try:
        projected = project(points, crs)

        if kind == 'stroke':
            if len(projected) < 2:
                return None
            radius = float(label.get('radius_m') or 0)
            if radius <= 0:
                return None
            # El buffer se hace **después** de reproyectar: el radio está en metros, y sobre
            # grados produciría un trazo cinco órdenes de magnitud mayor (FR-012b).
            return LineString(projected).buffer(radius, BUFFER_QUAD_SEGS)

        if len(projected) < 3:
            return None
        ring = list(projected)
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        return Polygon(LinearRing(ring))
    except Exception:
        # Una etiqueta con geometría degenerada no puede tumbar la exportación entera: se ignora
        # esa y siguen las demás.
        return None


def _intersects(extent, bounds):
    """¿Se solapan dos rectángulos `(izq, abajo, der, arriba)`?

    Comparar extensiones antes de rasterizar es lo que hace viable el enfoque tesela a tesela: sin
    esto, cada una de las 616 teselas de la mina recorrería todas las etiquetas del dataset.
    """
    return not (extent[2] < bounds[0] or extent[0] > bounds[2] or
                extent[3] < bounds[1] or extent[1] > bounds[3])


def class_pixel_counts(mask):
    """`{índice: píxeles}` de la máscara, **sin** el valor de ignorar.

    El manifiesto lo declara así a propósito (`contracts/dataset-package.md`): los ignorados se
    deducen restando del total, y no incluirlos evita que un lector distraído los trate como una
    clase más.
    """
    values, counts = np.unique(mask, return_counts=True)
    return {int(value): int(count)
            for value, count in zip(values, counts) if value != IGNORE_INDEX}


def reviewed_fraction(mask):
    """Fracción de la tesela que entra en el cálculo de la pérdida (FR-027, FR-041).

    Es decir, todo lo que no sea 255: tanto el camino como el fondo revisado. Es el número que
    decide si una tesela merece exportarse.
    """
    if mask.size == 0:
        return 0.0
    return float((mask != IGNORE_INDEX).sum()) / mask.size


def positive_fraction(mask):
    """Fracción de la tesela con alguna clase distinta del fondo.

    A cero en una tesela revisada significa negativo puro: terreno comprobado sin nada que detectar.
    Es lo que permite contar cuántos negativos lleva el dataset (FR-043).
    """
    if mask.size == 0:
        return 0.0
    return float(((mask != IGNORE_INDEX) & (mask != BACKGROUND_INDEX)).sum()) / mask.size


# Nombre anterior de `reviewed_fraction`. Se conserva porque la semántica es la misma —lo que no es
# 255— y quitarlo solo rompería a quien lo importe sin ganar nada.
labeled_fraction = reviewed_fraction
