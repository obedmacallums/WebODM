"""Caché en disco de las particiones por celda, y el proveedor que las sirve (`010` D4, D5).

Partir una celda cuesta **0,951 s medidos** y su resultado no depende de nada que cambie: la misma
ortofoto, la misma resolución, el mismo paso y el mismo peso de elevación dan siempre el mismo mapa
de regiones. Es exactamente el perfil de algo que se calcula una vez y se guarda.

## La clave de caché incluye la versión del algoritmo

`(tarea, resolución, S, peso de elevación, ALGORITHM_VERSION)`. La versión no es decorativa: sin
ella, el día que cambie la partición —otro `compactness`, otro halo, otra normalización— los mapas
viejos convivirían con los nuevos y dos clics sobre el mismo punto darían regiones distintas según
qué celda estuviera cacheada. Sería una violación de FR-007 sin ningún síntoma: nada falla, solo
deja de ser cierto. Cambiar la partición **obliga** a subir `superpixels.ALGORITHM_VERSION`.

## Perder la caché no pierde nada

Es una caché de verdad, no un almacén: se puede borrar entera en cualquier momento y lo único que
ocurre es que el siguiente clic tarda un segundo. Por eso la expulsión por presupuesto puede ser
tan simple como borrar los ficheros menos usados, sin ninguna transacción ni bloqueo.
"""

import os
import shutil

import numpy as np
import rasterio

from app.plugins.functions import get_plugins_persistent_path

from . import elevation as elevation_module
from . import superpixels

# Celdas cacheadas por tarea y configuración. Cada fichero pesa unos 200 kB comprimidos (1,05 MB de
# `int32` en crudo), así que 64 celdas son ~13 MB y cubren 64 · 51,2² m² = 168 000 m² de terreno
# recorrido — mucho más que una sesión de etiquetado normal.
MAX_CACHED_CELLS = 64

# Coste medido de preparar una celda, en segundos. Alimenta la estimación de `regions/status`, que
# es una estimación declarada y no una promesa: sirve para que la interfaz pueda decir «esto va a
# tardar unos segundos» en vez de dejar el cursor colgado sin explicación (FR-024).
SECONDS_PER_CELL = 0.95

NAMESPACE = 'training'


def cache_dir(task_id):
    return get_plugins_persistent_path(NAMESPACE, 'regions', str(task_id))


def cache_key(resolution_cm_px, granularity, elevation_weight):
    """Prefijo de fichero que identifica una configuración de partición.

    Va en el **nombre** y no en un índice aparte para que la caché sea inspeccionable con `ls` y
    para que un cambio de configuración no necesite código de invalidación: la clave sencillamente
    deja de coincidir y los ficheros viejos se los lleva la expulsión por presupuesto.
    """
    return 'v{version}-r{res:.4f}-{granularity}-w{weight:.3f}'.format(
        version=superpixels.ALGORITHM_VERSION,
        res=float(resolution_cm_px),
        granularity=superpixels.spacing_px(granularity),
        weight=float(elevation_weight or 0.0))


def cell_path(task_id, key, row, col):
    return os.path.join(cache_dir(task_id), '{}-{}_{}.npz'.format(key, row, col))


def load_cell(task_id, key, row, col):
    """La partición cacheada de una celda, o `None`.

    Un fichero corrupto —una escritura interrumpida— se trata como ausencia y se borra: recalcular
    cuesta un segundo, y arrastrar un `.npz` roto costaría un error en cada clic sobre esa celda.
    """
    path = cell_path(task_id, key, row, col)
    if not os.path.isfile(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as data:
            partition = superpixels.CellPartition(
                labels=data['labels'],
                means=data['means'],
                adjacency=set(map(tuple, data['adjacency'].tolist())),
                continues={side: data['continues_' + side]
                           for side in ('top', 'bottom', 'left', 'right')},
                valid=data['valid'],
                band_count=int(data['band_count']),
                elevation_source=str(data['elevation_source']),
            )
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        return None

    _touch(path)
    return partition


def save_cell(task_id, key, row, col, partition):
    """Guarda la partición de una celda de forma atómica y aplica el presupuesto."""
    directory = cache_dir(task_id)
    os.makedirs(directory, exist_ok=True)
    path = cell_path(task_id, key, row, col)
    tmp = path + '.tmp'

    adjacency = (np.array(sorted(partition.adjacency), dtype='int32')
                 if partition.adjacency else np.zeros((0, 2), dtype='int32'))

    with open(tmp, 'wb') as f:
        np.savez_compressed(
            f,
            labels=partition.labels,
            means=partition.means,
            adjacency=adjacency,
            valid=partition.valid,
            band_count=np.int32(partition.band_count),
            elevation_source=np.array(partition.elevation_source or 'none'),
            **{'continues_' + side: value for side, value in partition.continues.items()})
    # Como en `store.write_labels`: un proceso interrumpido a media escritura dejaría un `.npz`
    # truncado, y aquí además lo leería otro proceso a la vez.
    os.replace(tmp, path)

    enforce_budget(task_id)
    return path


def _touch(path):
    """Marca el fichero como usado. La expulsión mira esta marca, no la fecha de creación."""
    try:
        os.utime(path, None)
    except OSError:
        pass


def enforce_budget(task_id, limit=MAX_CACHED_CELLS):
    """Deja como mucho `limit` celdas cacheadas por tarea, expulsando las menos usadas."""
    directory = cache_dir(task_id)
    try:
        entries = [os.path.join(directory, name) for name in os.listdir(directory)
                   if name.endswith('.npz')]
    except OSError:
        return 0

    if len(entries) <= limit:
        return 0

    entries.sort(key=lambda p: os.path.getmtime(p))
    evicted = 0
    for path in entries[:len(entries) - limit]:
        try:
            os.remove(path)
            evicted += 1
        except OSError:
            pass
    return evicted


def clear(task_id):
    shutil.rmtree(cache_dir(task_id), ignore_errors=True)


# --- Proveedor ---------------------------------------------------------------------------

class CellProvider:
    """Sirve particiones de celda de una tarea, tirando de caché y calculando lo que falte.

    Abre la ortofoto y el ráster de elevación **una vez** por petición: con un arrastre que toca
    varias celdas, abrir y cerrar por celda multiplicaría el coste de la lectura sin ganar nada.

    Se usa como contexto:

        with CellProvider(task_id, resolution_cm_px=10.0) as provider:
            partition = provider.get(row, col)

    `get` devuelve `None` para una celda fuera de la ortofoto, que **no es un error**: pinchar
    fuera de la huella del vuelo es algo que el usuario hace todo el rato (FR-025).
    """

    def __init__(self, task_id, resolution_cm_px, granularity=superpixels.DEFAULT_GRANULARITY,
                 elevation_weight=1.0, elevation_source=elevation_module.SOURCE_DTM,
                 orthophoto_path=None):
        self.task_id = str(task_id)
        self.resolution_cm_px = float(resolution_cm_px)
        self.granularity = granularity
        self.elevation_weight = float(elevation_weight or 0.0)
        self.requested_elevation = elevation_source
        self._orthophoto_path = orthophoto_path

        self.ortho = None
        self.dem = None
        self.grid = None
        self.elevation_source = elevation_module.SOURCE_NONE
        self.band_count = 3
        self.prepared_cells = 0
        self._memo = {}

    # -- Ciclo de vida --------------------------------------------------------------------

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def orthophoto_path(self):
        if self._orthophoto_path is not None:
            return self._orthophoto_path
        from app.models import Task
        try:
            task = Task.objects.get(pk=self.task_id)
        except Exception:
            return None
        path = task.get_asset_download_path('orthophoto.tif')
        return path if os.path.isfile(path) else None

    def open(self):
        path = self.orthophoto_path()
        if path is None:
            raise NoOrthophoto('La tarea {} no tiene ortofoto.'.format(self.task_id))

        self.ortho = rasterio.open(path)
        self.grid = superpixels.WorkGrid(self.ortho, self.resolution_cm_px, self.granularity)

        # Sin peso no se abre el DEM siquiera: `elevation_weight = 0` es «no quiero terreno», y
        # leerlo para multiplicarlo por cero sería pagar la parte más cara del cálculo para nada.
        if self.elevation_weight > 0:
            try:
                dem_path, source = elevation_module.resolve_source(
                    self.task_id, self.requested_elevation)
            except elevation_module.ElevationUnavailable:
                dem_path, source = None, elevation_module.SOURCE_NONE
            if dem_path:
                self.dem = rasterio.open(dem_path)
                self.elevation_source = source

        self.band_count = 5 if self.dem is not None else 3
        return self

    def close(self):
        for raster in (self.dem, self.ortho):
            if raster is not None:
                try:
                    raster.close()
                except Exception:
                    pass
        self.dem = None
        self.ortho = None

    # -- Particiones ----------------------------------------------------------------------

    @property
    def key(self):
        return cache_key(self.resolution_cm_px, self.granularity, self.elevation_weight)

    def is_ready(self, row, col):
        return os.path.isfile(cell_path(self.task_id, self.key, row, col))

    def get(self, row, col):
        """La partición de una celda: de memoria, de disco o calculada, en ese orden."""
        if (row, col) in self._memo:
            return self._memo[(row, col)]

        if not self.grid.contains_cell(row, col):
            self._memo[(row, col)] = None
            return None

        partition = load_cell(self.task_id, self.key, row, col)
        if partition is None:
            partition = superpixels.partition_cell(
                self.ortho, self.dem, self.grid, row, col, self.elevation_weight)
            partition = partition._replace(elevation_source=self.elevation_source)
            save_cell(self.task_id, self.key, row, col, partition)
            self.prepared_cells += 1

        self._memo[(row, col)] = partition
        return partition

    def region_at(self, lng, lat):
        """`(fila, columna, índice)` de la región bajo un punto geográfico, o `None`.

        `None` significa «ahí no hay nada que seleccionar»: fuera de la ortofoto, o dentro pero
        sobre píxeles sin datos de vuelo. Los dos casos son normales y ninguno es un error.
        """
        try:
            x, y = self.grid.lnglat_to_xy(lng, lat)
            row, col = self.grid.cell_of_xy(x, y)
        except superpixels.OutsideRaster:
            return None

        partition = self.get(row, col)
        if partition is None:
            return None

        offset_row, offset_col = self.grid.offset_in_cell(x, y)
        if not partition.valid[offset_row, offset_col]:
            return None
        return row, col, int(partition.labels[offset_row, offset_col])

    def select(self, points, tolerance=0.0, max_regions=None):
        """Selección a partir de una lista de puntos `(lng, lat)`.

        Un punto es un clic (US1); varios, un arrastre (US2). El camino es el mismo: la diferencia
        entre los dos gestos vive en el frontend, no aquí.

        El tope se lee del módulo **en cada llamada** y no como valor por defecto del argumento:
        así se puede bajar en un test para ejercitar FR-018 sin tener que fabricar una ortofoto de
        2000 regiones uniformes.
        """
        if max_regions is None:
            max_regions = superpixels.MAX_GROWTH_REGIONS

        seeds = []
        for lng, lat in points:
            seed = self.region_at(lng, lat)
            if seed is not None and seed not in seeds:
                seeds.append(seed)

        if not seeds:
            return superpixels.Selection(regions=set(), truncated=False)

        return superpixels.grow(seeds, tolerance, self.get, max_regions=max_regions)

    def geometry(self, regions):
        return superpixels.selection_geometry(
            self.grid, regions, {(r, c): self._memo.get((r, c)) for r, c, _ in regions})


class NoOrthophoto(Exception):
    """La tarea no tiene ortofoto, así que no hay nada sobre lo que segmentar."""
