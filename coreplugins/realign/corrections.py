"""Pipeline de corrección de rásteres (D4 de research.md), ejecutado en el worker.

Para cada producto ráster 2D disponible se compone la nueva geotransformación afín
``GT_new = S ∘ GT_orig`` (bakea la similitud como geotransform rotado, sin remuestrear) y luego
se remuestrea con ``gdalwarp`` a un COG north-up estándar. Siempre se parte del asset
**original** de la tarea (FR-010) y los originales nunca se tocan (FR-009).

Cero dependencias nuevas: usa los bindings ``osgeo.gdal`` ya presentes en la imagen.
"""

import os
import datetime

# Remuestreo por tipo de producto: bilineal para la ortofoto, vecino más cercano para DEM.
RESAMPLING = {'orthophoto': 'bilinear', 'dsm': 'near', 'dtm': 'near'}


def compose_geotransform(gt, T):
    """Devuelve la geotransformación resultante de aplicar la similitud T sobre ``gt``.

    ``gt`` es la 6-tupla de GDAL (pixel→mundo). T = {scale, cos, sin, tx, ty} (mundo→mundo).
    Como ambas son afines, el resultado es la composición ``S ∘ GT``.
    """
    s, c, sn, tx, ty = T['scale'], T['cos'], T['sin'], T['tx'], T['ty']
    return (
        s * (c * gt[0] - sn * gt[3]) + tx,
        s * (c * gt[1] - sn * gt[4]),
        s * (c * gt[2] - sn * gt[5]),
        s * (sn * gt[0] + c * gt[3]) + ty,
        s * (sn * gt[1] + c * gt[4]),
        s * (sn * gt[2] + c * gt[5]),
    )


def apply_similarity_to_raster(src_path, out_path, T, resampling='bilinear'):
    """Aplica la similitud T al ráster ``src_path`` y escribe un COG north-up en ``out_path``."""
    from osgeo import gdal
    gdal.UseExceptions()

    src = gdal.Open(src_path)
    if src is None:
        raise RuntimeError("No se pudo abrir el ráster: {}".format(src_path))
    new_gt = compose_geotransform(src.GetGeoTransform(), T)

    # VRT liviano que referencia la fuente con el geotransform rotado (sin copiar píxeles).
    vrt_path = out_path + ".vrt"
    vrt = gdal.Translate(vrt_path, src, format='VRT')
    vrt.SetGeoTransform(new_gt)
    vrt.FlushCache()
    vrt = None
    src = None

    # gdalwarp remuestrea el geotransform rotado a un COG north-up estándar.
    gdal.Warp(out_path, vrt_path, options=gdal.WarpOptions(
        format='COG', resampleAlg=resampling,
        creationOptions=['COMPRESS=DEFLATE', 'BLOCKSIZE=512']))

    try:
        os.remove(vrt_path)
    except OSError:
        pass
    return out_path


def run_correction_pipeline(task_id, products, out_dir, T, applied_by=None):
    """Función de worker: genera los corregidos y marca el estado como ``applied``.

    ``products`` = [{'type': 'orthophoto', 'src': '/ruta/orthophoto.tif'}, ...].

    IMPORTANTE — debe ser **self-contained**: WebODM ejecuta esta función reejecutando su
    código fuente en un namespace vacío (``app/plugins/worker.py: eval_async`` hace
    ``eval(compile(source), ns, ns)`` con ``ns = {}``), sin los globals del módulo. Por eso
    todos los imports van **dentro** y son **absolutos**, y las funciones/constantes auxiliares
    se acceden a través del módulo importado (``corrections.*``) — nunca por nombre libre ni
    con imports relativos (``from . import ...``). Mismo patrón que ``coreplugins/viewshed``.
    """
    import os
    import datetime
    from coreplugins.realign import corrections, store

    os.makedirs(out_dir, exist_ok=True)

    corrected = {}
    for p in products:
        out_path = os.path.join(out_dir, p['type'] + '.tif')
        corrections.apply_similarity_to_raster(
            p['src'], out_path, T, corrections.RESAMPLING.get(p['type'], 'bilinear'))
        corrected[p['type']] = out_path

    state = store.get_state(task_id) or {}
    state['state'] = 'applied'
    state['corrected_paths'] = corrected
    state['applied_at'] = datetime.datetime.utcnow().isoformat() + 'Z'
    state['applied_by'] = applied_by
    store.set_state(task_id, state)

    return {'corrected': list(corrected.keys()), 'out_dir': out_dir}
