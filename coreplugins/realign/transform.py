"""Ajuste de la transformación de similitud (autoritativo, backend).

Espejo en Python de ``public/similarity.js`` (mismo algoritmo cerrado tipo Umeyama para el
caso 2D con escala). El diseño es **independiente del tipo de dato** (FR-017): recibe pares de
puntos en un plano métrico y devuelve los parámetros de la similitud; la reproyección de
lat/lng al CRS de la tarea se hace aparte con ``reproject_points``.
"""

import math

EPS = 1e-12


def apply_similarity(T, x, y):
    """Aplica la similitud T a (x, y)."""
    return (T['scale'] * (T['cos'] * x - T['sin'] * y) + T['tx'],
            T['scale'] * (T['sin'] * x + T['cos'] * y) + T['ty'])


def fit_similarity(pairs, use_scale=True):
    """Ajusta una transformación a ``pairs`` = [(sx, sy, tx, ty), ...] en un plano métrico.

    Con ``use_scale=True`` (default): similitud completa (traslación + rotación + escala
    uniforme). Con ``use_scale=False``: transformación rígida (traslación + rotación, ``scale``
    fijo en 1.0) — ver D9 en research.md. La rotación (``cos``/``sin``) es idéntica en ambos
    modos: sale de normalizar el mismo numerador de covarianza cruzada (``a``, ``b``) por
    ``hypot(a, b)`` en vez de por ``sxx``; solo cambian ``scale`` y, por lo tanto, la traslación.

    Devuelve un dict con: ok, degenerate, n, scale, rotation, rotation_deg, tx, ty, cos, sin,
    residuals (por punto) y rmse. Misma semántica que ``fitSimilarity`` en el frontend.
    """
    n = len(pairs)
    base = dict(ok=False, degenerate=False, n=n, scale=1.0, rotation=0.0, rotation_deg=0.0,
                tx=0.0, ty=0.0, cos=1.0, sin=0.0, residuals=[], rmse=None)

    if n == 0:
        base['degenerate'] = True
        return base

    musx = sum(p[0] for p in pairs) / n
    musy = sum(p[1] for p in pairs) / n
    mutx = sum(p[2] for p in pairs) / n
    muty = sum(p[3] for p in pairs) / n

    if n == 1:
        T = dict(scale=1.0, cos=1.0, sin=0.0, tx=pairs[0][2] - pairs[0][0], ty=pairs[0][3] - pairs[0][1])
    else:
        sxx = 0.0  # Σ |s − μs|²
        a = 0.0    # Re: Σ (dsx·dtx + dsy·dty)
        b = 0.0    # Im: Σ (dsx·dty − dsy·dtx)
        for sx, sy, tx, ty in pairs:
            dsx, dsy = sx - musx, sy - musy
            dtx, dty = tx - mutx, ty - muty
            sxx += dsx * dsx + dsy * dsy
            a += dsx * dtx + dsy * dty
            b += dsx * dty - dsy * dtx

        if sxx < EPS:
            base['degenerate'] = True
            return base

        if use_scale:
            wx = a / sxx
            wy = b / sxx
            scale = math.hypot(wx, wy)
            if scale < EPS:
                base['degenerate'] = True
                return base
            cos = wx / scale
            sin = wy / scale
        else:
            norm = math.hypot(a, b)
            if norm < EPS:
                base['degenerate'] = True
                return base
            scale = 1.0
            cos = a / norm
            sin = b / norm

        tx = mutx - (scale * cos * musx - scale * sin * musy)
        ty = muty - (scale * sin * musx + scale * cos * musy)
        T = dict(scale=scale, cos=cos, sin=sin, tx=tx, ty=ty)

    residuals = []
    sum_sq = 0.0
    for sx, sy, tx, ty in pairs:
        qx, qy = apply_similarity(T, sx, sy)
        dx, dy = qx - tx, qy - ty
        d = math.hypot(dx, dy)
        residuals.append(d)
        sum_sq += dx * dx + dy * dy

    rmse = math.sqrt(sum_sq / n)
    rotation = math.atan2(T['sin'], T['cos'])
    return dict(ok=True, degenerate=False, n=n, scale=T['scale'], rotation=rotation,
                rotation_deg=math.degrees(rotation), tx=T['tx'], ty=T['ty'],
                cos=T['cos'], sin=T['sin'], residuals=residuals, rmse=rmse)


def reproject_points(points, dst_epsg, src_epsg=4326):
    """Reproyecta pares de puntos lat/lng al CRS destino (métrico) de la tarea.

    ``points`` = [{'source': {'lat','lng'}, 'target': {'lat','lng'}}, ...].
    Devuelve [(sx, sy, tx, ty), ...] en unidades del CRS destino.
    """
    from osgeo import osr

    src = osr.SpatialReference()
    src.ImportFromEPSG(int(src_epsg))
    src.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    dst = osr.SpatialReference()
    dst.ImportFromEPSG(int(dst_epsg))
    dst.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    ct = osr.CoordinateTransformation(src, dst)

    pairs = []
    for p in points:
        sx, sy, _ = ct.TransformPoint(p['source']['lng'], p['source']['lat'])
        tx, ty, _ = ct.TransformPoint(p['target']['lng'], p['target']['lat'])
        pairs.append((sx, sy, tx, ty))
    return pairs


def similarity_from_latlng(points, dst_epsg, use_scale=True):
    """Reproyecta ``points`` (lat/lng) al CRS de la tarea y ajusta ahí (ver ``fit_similarity``)."""
    pairs = reproject_points(points, dst_epsg)
    return fit_similarity(pairs, use_scale=use_scale)
