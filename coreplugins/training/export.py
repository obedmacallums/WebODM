"""Construcción del paquete de entrenamiento (`contracts/dataset-package.md`, D5, D6, D9, D14).

El paquete se escribe **tesela a tesela directamente al `.zip` en disco**, y eso no es una
preferencia de estilo sino aritmética (D5, D14): la ortofoto de la mina a 10 cm/px son 10 876 x
14 023 px, o sea 152 Mpx. Un stack global de 5 bandas en `float32` serían 3,05 GB por tarea y por
exportación. FR-030 prohíbe construir el paquete en memoria; hacerlo por teselas lo cumple por
construcción, y el pico de memoria queda en una tesela.

Que el stack no se materialice entero **no** relaja la alineación píxel a píxel que exige la
especificación: la tesela deriva su `transform` de la misma rejilla global, la máscara se rasteriza
con ese `transform` y el DTM se reproyecta a él. Rasterizar globalmente y recortar daría exactamente
los mismos píxeles.

El recorrido es de dos pasadas:

1. **Planificar** — recorre la rejilla calculando solo la máscara, que no toca disco, y se queda con
   las teselas suficientemente revisadas. Sobre esas candidatas se reparte train/val, para que la
   fracción de validación se calcule sobre lo que de verdad se exporta y no sobre una rejilla llena
   de teselas vacías.
2. **Escribir** — lee RGB y elevación solo de las teselas que sobrevivieron.

Los imports pesados —`rasterio`, `numpy`— viven **aquí**, en el módulo. La función que se despacha
al worker (`api.run_export_async`) los alcanza importando este módulo dentro de su cuerpo:
`run_function_async` la recompila por código fuente en un espacio de nombres vacío, así que no
puede depender de los globals de su propio módulo (D9, Principio IV paso 3).
"""

import datetime
import json
import os
import shutil
import zipfile

import numpy as np
import rasterio

from app.plugins.functions import get_plugins_persistent_path

from . import elevation, models, rasterize, split, store, tiling

SCHEMA_VERSION = 2

# Compresión de los GeoTIFF. El predictor importa mucho más que el nivel: sobre bandas continuas
# como pendiente y rugosidad, el de coma flotante (3) baja el paquete a menos de la mitad frente a
# escribir sin él.
COMPRESSION = {'compress': 'deflate', 'zlevel': 6}
PREDICTOR = {'float32': 3, 'uint16': 2}

# Escala de la cuantización a entero. Los canales salen en [0, 1]; con 16 bits el paso es 1/65535,
# tres órdenes de magnitud por debajo de lo que un DTM fotogramétrico resuelve.
UINT16_SCALE = 65535.0


class Cancelled(Exception):
    """La exportación se abortó desde fuera. No es un error: el usuario pulsó cancelar."""


class ExportError(Exception):
    """La exportación no puede completarse y hay que decir por qué."""

    def __init__(self, message, code):
        super().__init__(message)
        self.message = message
        self.code = code


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
    """Construye el `.zip` del dataset y devuelve un resumen de lo exportado.

    Solo entran las tareas disponibles: una tarea borrada de WebODM se salta en vez de hacer
    fallar la exportación entera (invariante 5 de `data-model.md`).
    """
    should_cancel = _cancel_guard(should_cancel)
    export_id = export_id or models.now_iso().replace(':', '').replace('.', '')[:20]
    dataset = models.with_defaults(dict(dataset))

    tasks = store.available_tasks(dataset)
    tile_size = int(dataset['tile_size_px'])
    overlap = int(dataset['tile_overlap_px'])
    elevation_source = dataset['elevation_source']

    plans = []
    for entry in tasks:
        if should_cancel():
            raise Cancelled()
        plan = _plan_task(dataset, entry, tile_size, overlap, elevation_source)
        if plan is not None:
            plans.append(plan)

    candidates = [(plan['task_id'], tile.row, tile.col)
                  for plan in plans for tile in plan['candidates']]
    if not candidates:
        raise ExportError(
            'Ninguna tesela llega al {:.0%} de superficie revisada. Dibuja áreas revisadas sobre '
            'el terreno que hayas comprobado antes de exportar.'.format(
                dataset['min_reviewed_fraction']),
            'no_reviewed_tiles')

    block_tiles = int(dataset['split_block_tiles'])
    assignments = split.assign_tiles(
        candidates,
        block_tiles=block_tiles,
        val_fraction=float(dataset['val_fraction']),
        # La semilla es el identificador del dataset: el mismo dataset da siempre el mismo split,
        # y dos datasets distintos no heredan el reparto uno del otro (FR-031).
        seed=dataset['id'],
        reach=split.neighbour_reach(tile_size, tiling.stride(tile_size, overlap)),
    )

    # Dos desenlaces distintos, y confundirlos sería un error:
    #
    # - **Sin train no hay paquete.** Si el pasillo se lleva todas las teselas de entrenamiento
    #   —pasa cuando la zona revisada da para pocos bloques y todos son vecinos del de val— lo que
    #   saldría es un `.zip` con el que no se puede entrenar. Se falla y se dice cómo arreglarlo.
    # - **Sin val sí hay paquete.** Con una sola zona revisada no hay dónde sacar validación, y eso
    #   no invalida las teselas: el paquete se entrega con el aviso escrito en `dataset.json`, que
    #   es donde lo verá quien vaya a entrenar.
    counts = split.summarize(assignments)
    if counts['train'] == 0:
        raise ExportError(
            'El reparto train/val no deja ninguna tesela de entrenamiento: los bloques de {} '
            'teselas son demasiado grandes para la zona revisada. Baja «teselas por bloque» o '
            'revisa más terreno.'.format(block_tiles),
            'bad_split')

    split_warning = None
    if counts['val'] == 0 and float(dataset['val_fraction']) > 0:
        split_warning = ('La zona revisada solo da para un bloque, así que no hay teselas de '
                         'validación. Revisa terreno en otra zona o baja «teselas por bloque».')

    directory = exports_dir(dataset['id'])
    os.makedirs(directory, exist_ok=True)
    path = package_path(dataset['id'], export_id)

    tile_entries = []
    source_tasks = []
    written = 0
    total = sum(1 for value in assignments.values() if value is not None)

    try:
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED) as archive:
            for plan in plans:
                if should_cancel():
                    raise Cancelled()
                entries, summary = _write_task_tiles(
                    archive, dataset, plan, assignments, tile_size,
                    progress_callback=progress_callback, should_cancel=should_cancel,
                    written_before=written, total=total)
                tile_entries.extend(entries)
                source_tasks.append(summary)
                written += len(entries)

            # El reparto se decidió sobre las **candidatas**, pero entre medias el umbral de
            # píxeles válidos ha podido tumbar teselas — y no las tumba al azar, sino allí donde no
            # hay datos de vuelo, que es una zona concreta del terreno. Así que el lado de
            # entrenamiento puede quedar vacío después de haber sobrevivido al guard de arriba.
            # Volver a comprobarlo aquí, sobre lo que de verdad se ha escrito, es lo único que
            # cierra el hueco: si no, el paquete saldría sin teselas de train y sin decirlo.
            split_warning = _check_written_split(tile_entries, dataset, block_tiles, split_warning)

            archive.writestr('dataset.json', json.dumps(
                _dataset_json(dataset, source_tasks, tile_entries, assignments, plans,
                              split_warning),
                indent=2, ensure_ascii=False))
    except BaseException:
        # Un `.zip` a medias es peor que ninguno: parece un paquete válido y le falta la mitad.
        _remove_quietly(path)
        raise

    if progress_callback:
        progress_callback(100)

    return {
        'export_id': export_id,
        'path': path,
        'tile_count': len(tile_entries),
        'size_bytes': os.path.getsize(path),
        'train_tiles': sum(1 for t in tile_entries if t['split'] == split.TRAIN),
        'val_tiles': sum(1 for t in tile_entries if t['split'] == split.VAL),
        'dropped_by_gutter': counts['dropped_by_gutter'],
        'warning': split_warning,
    }


def _check_written_split(tile_entries, dataset, block_tiles, warning):
    """Revalida el reparto sobre las teselas escritas. Devuelve el aviso, o falla si no hay train.

    Un paquete sin teselas es otro problema —lo traduce la API a «todo descartado por los
    umbrales»— y se deja pasar tal cual.
    """
    if not tile_entries:
        return warning

    train = sum(1 for t in tile_entries if t['split'] == split.TRAIN)
    val = sum(1 for t in tile_entries if t['split'] == split.VAL)

    if train == 0:
        raise ExportError(
            'Todas las teselas de entrenamiento se quedaron sin datos de vuelo suficientes y solo '
            'sobreviven {} de validación. Revisa terreno en otra zona o baja «teselas por bloque» '
            '(ahora {}).'.format(val, block_tiles),
            'bad_split')

    if val == 0 and float(dataset['val_fraction']) > 0:
        return ('No queda ninguna tesela de validación: la zona revisada da para muy pocos '
                'bloques. Revisa terreno en otra zona o baja «teselas por bloque».')

    return warning


def _plan_task(dataset, entry, tile_size, overlap, elevation_source):
    """Decide qué teselas de una tarea son candidatas, sin leer un solo píxel de imagen.

    La máscara se calcula aquí porque es lo barato —geometría contra una rejilla— y es lo que
    descarta la mayoría de las teselas: en un dataset donde solo una parte está revisada, esta
    pasada elimina el grueso antes de que nadie toque el disco.
    """
    orthophoto = _orthophoto_path(entry['task_id'])
    if orthophoto is None:
        return None

    elevation_path, effective_source = (None, elevation.SOURCE_NONE)
    if elevation_source != elevation.SOURCE_NONE:
        try:
            elevation_path, effective_source = elevation.resolve_source(
                entry['task_id'], elevation_source)
        except elevation.ElevationUnavailable as error:
            # Sin elevación la tesela tendría 3 bandas en vez de 5, y un dataset con teselas de
            # distinto número de bandas no lo carga nadie. Se salta la tarea entera y se dice por
            # qué en `dataset.json`, en vez de emitir un paquete incoherente.
            return {'task_id': entry['task_id'], 'name': entry.get('name'), 'skipped': str(error),
                    'candidates': [], 'orthophoto': orthophoto, 'elevation_path': None,
                    'elevation_source': elevation.SOURCE_NONE, 'prepared': [], 'crs': None,
                    'native_resolution_cm_px': None}

    minimum = float(dataset['min_reviewed_fraction'])

    with rasterio.open(orthophoto) as raster:
        prepared = rasterize.prepare_labels(
            store.list_labels(dataset['id'], entry['task_id']), raster.crs)
        tiles = list(tiling.tile_grid(raster, dataset['resolution_cm_px'], tile_size, overlap))

        # Se guarda la tesela, no su máscara. Una máscara son 256 KB y las candidatas de la mina
        # pueden ser 900: 230 MB por retener lo que cuesta milisegundos rehacer, ahora que las
        # geometrías ya están reproyectadas.
        candidates = [tile for tile in tiles
                      if rasterize.reviewed_fraction(
                          rasterize.rasterize_prepared(prepared, tile, tile_size)) >= minimum]

        return {
            'task_id': entry['task_id'],
            'name': entry.get('name'),
            'skipped': None,
            'orthophoto': orthophoto,
            'elevation_path': elevation_path,
            'elevation_source': effective_source,
            'prepared': prepared,
            'candidates': candidates,
            'crs': str(raster.crs),
            'native_resolution_cm_px': round(abs(raster.transform.a) * 100, 4),
            'grid': tiling.grid_size(raster, dataset['resolution_cm_px'], tile_size, overlap),
        }


def _write_task_tiles(archive, dataset, plan, assignments, tile_size,
                      progress_callback, should_cancel, written_before, total):
    """Escribe al zip las teselas candidatas de una tarea que el split no descartó."""
    entries = []
    summary = {
        'task_id': plan['task_id'],
        'name': plan.get('name'),
        'crs': plan.get('crs'),
        'native_resolution_cm_px': plan.get('native_resolution_cm_px'),
        'elevation_source': plan['elevation_source'],
        'skipped': plan['skipped'],
    }
    if plan['skipped'] or not plan['candidates']:
        return entries, summary

    min_valid = float(dataset['min_valid_fraction'])
    dtype = dataset['pixel_dtype']
    done = 0

    with rasterio.open(plan['orthophoto']) as raster:
        dem = rasterio.open(plan['elevation_path']) if plan['elevation_path'] else None
        try:
            ceiling = (elevation.estimate_roughness_ceiling(dem, plan['candidates'], tile_size)
                       if dem is not None else elevation.MIN_ROUGHNESS_CEILING_M)
            summary['roughness_ceiling_m'] = round(float(ceiling), 6)

            has_alpha = raster.count >= 4

            for tile in plan['candidates']:
                if should_cancel():
                    raise Cancelled()

                assigned = assignments.get((plan['task_id'], tile.row, tile.col))
                if assigned is None:
                    continue

                mask = rasterize.rasterize_prepared(plan['prepared'], tile, tile_size)
                stack, valid = _tile_stack(raster, dem, tile, tile_size, has_alpha, ceiling, dtype)
                valid_fraction = float(valid.sum()) / valid.size
                if valid_fraction < min_valid:
                    continue

                # Un píxel sin imagen no puede estar etiquetado: da igual lo que dijese el área
                # revisada, ahí no hay nada que mirar. Devolverlo a 255 es lo que impide que el
                # modelo aprenda del relleno del borde de la ortofoto.
                mask[~valid] = models.IGNORE_INDEX
                reviewed = rasterize.reviewed_fraction(mask)
                if reviewed < float(dataset['min_reviewed_fraction']):
                    continue

                name = '{}_{:04d}_{:04d}'.format(plan['task_id'], tile.row, tile.col)
                archive.writestr('images/{}.tif'.format(name), _geotiff_bytes(
                    stack, tile.transform, raster.crs, dtype, elevation.BAND_NAMES))
                archive.writestr('masks/{}.tif'.format(name), _geotiff_bytes(
                    mask[np.newaxis, :, :], tile.transform, raster.crs, 'uint8', ('mask',),
                    nodata=models.IGNORE_INDEX))

                entries.append({
                    'tile_id': name,
                    'image': 'images/{}.tif'.format(name),
                    'mask': 'masks/{}.tif'.format(name),
                    'task_id': plan['task_id'],
                    'row': tile.row,
                    'column': tile.col,
                    'split': assigned,
                    'block': list(split.block_of(tile.row, tile.col,
                                                 int(dataset['split_block_tiles']))),
                    'origin': [round(tile.bounds[0], 4), round(tile.bounds[3], 4)],
                    'bounds': [round(v, 4) for v in tile.bounds],
                    'bounds_wgs84': [round(v, 8) for v in tile.bounds_wgs84],
                    'reviewed_fraction': round(reviewed, 6),
                    'valid_fraction': round(valid_fraction, 6),
                    'positive_fraction': round(rasterize.positive_fraction(mask), 6),
                    'hard_negative': rasterize.touches_hard_negative(plan['prepared'], tile),
                    'class_pixels': {str(k): v
                                     for k, v in rasterize.class_pixel_counts(mask).items()},
                })

                done += 1
                if progress_callback and total:
                    progress_callback(min(99, int((written_before + done) / total * 100)))
        finally:
            if dem is not None:
                dem.close()

    return entries, summary


def _tile_stack(raster, dem, tile, tile_size, has_alpha, roughness_ceiling, dtype):
    """`(stack de 5 bandas, máscara de píxeles válidos)` de una tesela.

    El remuestreo del RGB lo hace la propia lectura (D6): una ventana de 128 px nativos se pide
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
        valid = alpha > 0
    else:
        valid = np.ones((tile_size, tile_size), dtype=bool)

    channels = [rgb[i].astype('float32') / 255.0 for i in range(3)]

    if dem is not None:
        slope, rough, dem_valid = elevation.tile_channels(dem, tile, tile_size)
        channels.append(elevation.normalize_slope(slope))
        channels.append(elevation.normalize_roughness(rough, roughness_ceiling))
        # Un píxel sin DTM no tiene pendiente ni rugosidad, solo el relleno que puso
        # `tile_channels` para que el operador local no propagase `nan`. Cuenta como inválido.
        valid = valid & dem_valid
    else:
        zeros = np.zeros((tile_size, tile_size), dtype='float32')
        channels.append(zeros)
        channels.append(zeros.copy())

    stack = np.stack(channels)
    # Donde no hay dato no sale valor: el píxel va a cero en las cinco bandas. La máscara ya manda
    # esos píxeles a «ignorar», así que no entran en la pérdida, pero **sí entran en la
    # convolución** — un borde de ortofoto o un relleno del DTM alimentando el receptive field es
    # textura inventada que el modelo puede aprender igual.
    stack[:, ~valid] = 0

    if dtype == 'uint16':
        stack = np.clip(stack * UINT16_SCALE, 0, UINT16_SCALE).astype('uint16')

    return stack, valid


def _geotiff_bytes(array, transform, crs, dtype, band_names, nodata=None):
    """GeoTIFF en memoria, con su CRS y su `transform`.

    No es PNG a propósito: la especificación exige conservar la georreferencia, y con PNG la
    trazabilidad de la tesela dependería de que nadie perdiera el manifiesto. Cada tesela sabe
    dónde está.
    """
    profile = dict(
        driver='GTiff',
        height=array.shape[1],
        width=array.shape[2],
        count=array.shape[0],
        dtype=dtype,
        crs=crs,
        transform=transform,
        predictor=PREDICTOR.get(dtype, 2),
        **COMPRESSION
    )
    if nodata is not None:
        profile['nodata'] = nodata

    with rasterio.io.MemoryFile() as memfile:
        with memfile.open(**profile) as dst:
            dst.write(array)
            dst.descriptions = tuple(band_names)
        return memfile.read()


def _dataset_json(dataset, source_tasks, tiles, assignments, plans, split_warning=None):
    """El `dataset.json` de `contracts/dataset-package.md`.

    Tiene que bastarse solo (FR-029): quien reciba el paquete escribe su cargador leyendo esto y
    nada más, sin acceso a WebODM ni a la especificación. Por eso el bloque `normalization` lleva
    la fórmula escrita y no solo los números: la inferencia tiene que aplicar exactamente la misma
    transformación, y deducirla de un puñado de constantes sueltas es como se introducen los
    desajustes que luego nadie encuentra.
    """
    ceilings = [t['roughness_ceiling_m'] for t in source_tasks if 'roughness_ceiling_m' in t]
    counts = split.summarize({k: v for k, v in assignments.items() if v is not None})
    hard_negatives = sum(1 for t in tiles if t['hard_negative'])
    negatives = sum(1 for t in tiles if t['positive_fraction'] == 0)

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
        'tile_overlap_px': int(dataset['tile_overlap_px']),
        'stride_px': tiling.stride(int(dataset['tile_size_px']),
                                   int(dataset['tile_overlap_px'])),
        'ignore_index': models.IGNORE_INDEX,
        'background_index': models.BACKGROUND_INDEX,
        'pixel_dtype': dataset['pixel_dtype'],
        'uint16_scale': UINT16_SCALE if dataset['pixel_dtype'] == 'uint16' else None,
        'bands': list(elevation.BAND_NAMES),
        'elevation_source': dataset['elevation_source'],
        'normalization': elevation.normalization_metadata(
            max(ceilings) if ceilings else elevation.MIN_ROUGHNESS_CEILING_M),
        'classes': [{'index': c['index'], 'name': c['name']} for c in dataset['classes']],
        'split': {
            'strategy': 'geographic_blocks',
            'block_tiles': int(dataset['split_block_tiles']),
            'requested_val_fraction': float(dataset['val_fraction']),
            'seed': dataset['id'],
            'train_tiles': sum(1 for t in tiles if t['split'] == split.TRAIN),
            'val_tiles': sum(1 for t in tiles if t['split'] == split.VAL),
            'dropped_by_gutter': counts['dropped_by_gutter'],
            'warning': split_warning,
            'note': ('Los bloques se reparten enteros y las teselas de train que solapan con un '
                     'bloque de val se descartan, así que ningún píxel de validación aparece en '
                     'el entrenamiento.'),
        },
        'curation': {
            'min_reviewed_fraction': float(dataset['min_reviewed_fraction']),
            'min_valid_fraction': float(dataset['min_valid_fraction']),
            'negative_tiles': negatives,
            'hard_negative_tiles': hard_negatives,
            'hard_negative_fraction': round(float(hard_negatives) / len(tiles), 4) if tiles else 0,
            'note': ('Solo entran teselas cuya superficie revisada llega al umbral. Lo no '
                     'revisado sale como {} y se excluye de la pérdida.'.format(
                         models.IGNORE_INDEX)),
        },
        'source_tasks': source_tasks,
        'skipped_tasks': [{'task_id': p['task_id'], 'reason': p['skipped']}
                          for p in plans if p['skipped']],
        'tiles': tiles,
    }


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


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
