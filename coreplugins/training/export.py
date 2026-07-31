"""Construcción del paquete de entrenamiento (`contracts/dataset-package.md`, D5, D6, D9).

El paquete se escribe **tesela a tesela directamente al `.zip` en disco**, y eso no es una
preferencia de estilo sino aritmética (D5): la ortofoto de la mina a 10 cm/px son 10 876 x 14 023
px, o sea 152 Mpx. Una máscara global en `uint8` serían 152 MB y la imagen RGB 457 MB, por dataset
y por exportación. FR-030 prohíbe construir el paquete en memoria; hacerlo por teselas lo cumple
por construcción, y el pico de memoria queda en una tesela: 64 KB de máscara y 192 KB de imagen a
512 px.

Los imports pesados —`rasterio`, `numpy`, `PIL`— viven **aquí**, en el módulo. La función que se
despacha al worker (`api.run_export_async`) los alcanza importando este módulo dentro de su
cuerpo: `run_function_async` la recompila por código fuente en un espacio de nombres vacío, así
que no puede depender de los globals de su propio módulo (D9, Principio IV paso 3).
"""

import datetime
import json
import os
import shutil
import zipfile

import numpy as np
import rasterio
from PIL import Image

from app.plugins.functions import get_plugins_persistent_path

from . import models, rasterize, store, tiling

SCHEMA_VERSION = 1


class Cancelled(Exception):
    """La exportación se abortó desde fuera. No es un error: el usuario pulsó cancelar."""


def exports_dir(dataset_id):
    # La ruta la define `store`, que es quien la borra al borrar el dataset.
    return store.exports_dir(dataset_id)


def package_path(dataset_id, export_id):
    return os.path.join(exports_dir(dataset_id), '{}.zip'.format(export_id))


def delete_package(dataset_id, export_id):
    try:
        os.remove(package_path(dataset_id, export_id))
        return True
    except OSError:
        return False


def delete_all_packages(dataset_id):
    shutil.rmtree(exports_dir(dataset_id), ignore_errors=True)


def _cancel_guard(should_cancel):
    """Envuelve el chequeo de cancelación para que un fallo suyo no tumbe la exportación.

    El `should_cancel` que inyecta `eval_async` consulta el backend de resultados de Celery, y bajo
    `CELERY_TASK_ALWAYS_EAGER` —como corre la suite— eso lanza «Cannot retrieve result with
    task_always_eager enabled». Preguntar si hay que cancelar no puede ser motivo para abortar un
    trabajo por lo demás sano. Mismo guard que `coreplugins/road/compute.py:374-382`.
    """
    def canceled():
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False
    return canceled


def build_package(dataset, export_id=None, progress_callback=None, should_cancel=None):
    """Construye el `.zip` del dataset y devuelve `{export_id, path, tile_count, size_bytes}`.

    Solo entran las tareas disponibles: una tarea borrada de WebODM se salta en vez de hacer
    fallar la exportación entera (invariante 5 de `data-model.md`).
    """
    should_cancel = _cancel_guard(should_cancel)
    export_id = export_id or models.now_iso().replace(':', '').replace('.', '')[:20]
    tasks = store.available_tasks(dataset)

    directory = exports_dir(dataset['id'])
    os.makedirs(directory, exist_ok=True)
    path = package_path(dataset['id'], export_id)

    tile_entries = []
    source_tasks = []
    tile_size = int(dataset['tile_size_px'])
    total_units = max(1, len(tasks))

    # `ZIP_DEFLATED` sobre PNG no comprime casi nada —ya vienen comprimidos— pero mantiene el
    # paquete en un formato que cualquier lector abre sin preguntar.
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for index, entry in enumerate(tasks):
            orthophoto = _orthophoto_path(entry['task_id'])
            if orthophoto is None:
                continue

            with rasterio.open(orthophoto) as raster:
                source_tasks.append({
                    'task_id': entry['task_id'],
                    'name': entry.get('name'),
                    'native_resolution_cm_px': round(abs(raster.transform.a) * 100, 4),
                    'crs': str(raster.crs),
                })

                labels = store.list_labels(dataset['id'], entry['task_id'])
                tile_entries.extend(_export_task_tiles(
                    archive, raster, dataset, entry, labels, tile_size,
                    progress_callback=progress_callback, should_cancel=should_cancel,
                    task_index=index, task_total=total_units))

        archive.writestr('manifest.json', json.dumps(
            _manifest(dataset, source_tasks, tile_entries), indent=2, ensure_ascii=False))

    if progress_callback:
        progress_callback(100)

    return {
        'export_id': export_id,
        'path': path,
        'tile_count': len(tile_entries),
        'size_bytes': os.path.getsize(path),
    }


def _export_task_tiles(archive, raster, dataset, task_entry, labels, tile_size,
                       progress_callback, should_cancel, task_index, task_total):
    """Recorre la rejilla de una tarea y añade al zip las teselas que pasan los filtros."""
    entries = []
    tiles = list(tiling.tile_grid(raster, dataset['resolution_cm_px'], tile_size))
    min_labeled = float(dataset.get('min_labeled_fraction', models.DEFAULT_MIN_LABELED_FRACTION))
    min_valid = float(dataset.get('min_valid_fraction', models.DEFAULT_MIN_VALID_FRACTION))
    has_alpha = raster.count >= 4

    for position, tile in enumerate(tiles):
        if should_cancel and should_cancel():
            raise Cancelled()

        # La máscara se calcula **antes** de leer la imagen: descartar por etiquetas es mucho más
        # barato que leer y remuestrear 512x512 px de ortofoto para tirarlos después. En un dataset
        # donde solo una parte está etiquetada —el caso normal— esto se ahorra la mayoría de las
        # lecturas.
        mask = rasterize.rasterize_tile(labels, tile, raster.crs, tile_size)
        labeled = rasterize.labeled_fraction(mask)
        if labeled < min_labeled:
            continue

        rgb, valid = _read_tile(raster, tile, tile_size, has_alpha)
        if valid < min_valid:
            continue

        name = '{}_{:03d}_{:03d}.png'.format(task_entry['task_id'], tile.row, tile.col)
        archive.writestr('images/' + name, _png_bytes(rgb, 'RGB'))
        archive.writestr('labels/' + name, _png_bytes(mask, 'L'))

        entries.append({
            'image': 'images/' + name,
            'label': 'labels/' + name,
            'task_id': task_entry['task_id'],
            'row': tile.row,
            'column': tile.col,
            'bounds': [round(v, 8) for v in tile.bounds_wgs84],
            'labeled_fraction': round(labeled, 6),
            'valid_fraction': round(valid, 6),
            'class_pixels': {str(k): v for k, v in rasterize.class_pixel_counts(mask).items()},
        })

        if progress_callback and tiles:
            done = (task_index + (position + 1) / len(tiles)) / task_total
            progress_callback(min(99, int(done * 100)))

    return entries


def _read_tile(raster, tile, tile_size, has_alpha):
    """`(rgb, fracción de píxeles válidos)` de una tesela.

    El remuestreo lo hace la propia lectura (D6): una ventana de 128 px nativos se pide
    directamente como 64 px de salida, sin paso de warp intermedio. `boundless` cubre las teselas
    del borde que sobresalen del ráster: se rellenan con ceros, que al ser alfa 0 las descarta el
    umbral de píxeles válidos sin ningún caso especial.
    """
    rgb = raster.read((1, 2, 3), window=tile.window, out_shape=(3, tile_size, tile_size),
                      boundless=True, fill_value=0)

    if has_alpha:
        # El alfa dice sin ambigüedad qué píxeles tienen datos de vuelo (D7). Con `nodata: None`
        # en las ortofotos reales, cualquier heurística sobre el valor de los píxeles —¿un negro
        # es sombra o ausencia de datos?— habría sido una fuente de fallos silenciosos.
        alpha = raster.read(4, window=tile.window, out_shape=(tile_size, tile_size),
                            boundless=True, fill_value=0)
        valid = float((alpha > 0).sum()) / alpha.size
    else:
        valid = 1.0

    return rgb, valid


def _png_bytes(array, mode):
    """PNG en memoria. Es una tesela, no la ortofoto: el pico es de 192 KB a 512 px."""
    import io
    if mode == 'RGB':
        image = Image.fromarray(np.transpose(array, (1, 2, 0)), mode='RGB')
    else:
        image = Image.fromarray(array, mode='L')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def _manifest(dataset, source_tasks, tiles):
    """El manifiesto de `contracts/dataset-package.md`.

    Tiene que bastarse solo (FR-029): quien reciba el paquete escribe su cargador leyendo esto y
    nada más, sin acceso a WebODM ni a la spec.
    """
    return {
        'schema_version': SCHEMA_VERSION,
        'dataset': {
            'id': dataset['id'],
            'name': dataset['name'],
            'created_at': dataset.get('created_at'),
            'exported_at': datetime.datetime.utcnow().isoformat() + 'Z',
        },
        'resolution_cm_px': dataset['resolution_cm_px'],
        'tile_size_px': int(dataset['tile_size_px']),
        'ignore_index': models.IGNORE_INDEX,
        'classes': [{'index': c['index'], 'name': c['name']} for c in dataset['classes']],
        'source_tasks': source_tasks,
        'tiles': tiles,
    }


def _orthophoto_path(task_id):
    """Ruta de la ortofoto de una tarea, o `None` si ya no está.

    El import va dentro porque este módulo lo carga también el worker, y `app.models` no puede
    importarse antes de que las apps de Django estén listas.
    """
    from app.models import Task
    try:
        task = Task.objects.get(pk=task_id)
    except Exception:
        return None
    path = task.get_asset_download_path('orthophoto.tif')
    return path if os.path.isfile(path) else None
