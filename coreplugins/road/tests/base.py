"""Fixtures compartidas: tarea de prueba y DEM sintético de un camino de geometría conocida.

El DEM que genera `make_road_dem` no es ruido con forma de terreno: es una superficie construida
para que el ancho, la pendiente longitudinal y la transversal tengan un valor **exacto** conocido
de antemano. Eso es lo que permite afirmar que la detección de bordes acierta, en vez de comprobar
que devuelve algo con la unidad correcta.

Forma de la superficie, con el camino corriendo de norte a sur (x constante):

```
    z
    │        ┌─────────────┐          calzada plana (o con peralte conocido)
    │       ╱               ╲         taludes de pendiente `talud`
    │      ╱                 ╲
    └──────┴────┴───────┴────┴──────  d (distancia con signo al eje; + = este = izquierda)
        -hw_right         +hw_left
```

Sobre eso se superpone una rampa longitudinal de pendiente `grade`. Como el camino corre de norte
a sur y las transversales van de este a oeste, la rampa **no** contamina el perfil transversal: la
pendiente longitudinal y la transversal se pueden verificar por separado.

Convenio de lados: el eje se traza de norte a sur, así que el sentido de avance es `(0, -1)` y su
izquierda —`geometry.left_normal`— es el este (`+x`). `offset_left` mide hacia el este.
"""

import os
import shutil

import numpy as np
import rasterio
import rasterio.warp
from rasterio.crs import CRS
from rasterio.transform import from_origin

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from guardian.shortcuts import assign_perm
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

DEM_EPSG = 32615                      # UTM 15N
DEM_ORIGIN = (500000.0, 4984000.0)    # (x, y) de la esquina superior izquierda, en metros
DEM_SIZE = 480                        # celdas por lado
DEM_RES = 0.25                        # m/celda -> 120 m x 120 m
DEM_NODATA = -9999.0

# Columna del pixel por cuyo **centro** pasa el eje. Que caiga en un centro de celda y que el paso
# de muestreo sea múltiplo de la resolución es lo que hace que los bordes salgan en valores
# redondos: con muestreo por vecino más próximo, una transversal desalineada mide el ancho con
# medio píxel de sesgo y los asertos exactos dejarían de ser posibles.
ROAD_COL = 240

# El eje sintético arranca en la fila 40, así que su progresiva 0 cae en esta progresiva del DEM.
# Sumarlo es lo que traduce "el metro 2,5 del camino" a la franja que hay que tocar en el ráster.
AXIS_STATION_OFFSET = (40 + 0.5) * DEM_RES

DEFAULT_HALF_WIDTH = 4.0    # -> 8 m de ancho de calzada
DEFAULT_GRADE = 0.05        # 5 % longitudinal
DEFAULT_CROSS_SLOPE = 0.02  # 2 % de peralte hacia el este
DEFAULT_TALUD = 0.50        # 50 %: muy por encima del umbral de quiebre por defecto (15 %)
DEFAULT_BASE = 100.0


def road_center_x(origin=DEM_ORIGIN, res=DEM_RES, col=ROAD_COL):
    return origin[0] + (col + 0.5) * res


def make_road_dem(path, size=DEM_SIZE, res=DEM_RES, origin=DEM_ORIGIN, epsg=DEM_EPSG,
                  nodata=DEM_NODATA, half_width_left=DEFAULT_HALF_WIDTH,
                  half_width_right=DEFAULT_HALF_WIDTH, grade=DEFAULT_GRADE,
                  cross_slope=DEFAULT_CROSS_SLOPE, talud=DEFAULT_TALUD, base=DEFAULT_BASE,
                  road_col=ROAD_COL, nodata_patch=None, noise=0.0, seed=7, pinch=None):
    """Escribe el GeoTIFF del camino sintético.

    `talud=0.0` produce una superficie sin quiebre a los lados (el caso `no_break`).
    `nodata_patch` es `(row0, row1, col0, col1)` en celdas y sirve para el caso `no_data`.
    `pinch` es `(station0, station1, semiancho_izq, semiancho_der)` en progresivas **del DEM**
    (usa `AXIS_STATION_OFFSET` para pasar de progresiva del eje): estrecha o ensancha el camino
    en esa franja, que es como se construye un camino no uniforme a lo largo.
    `noise` superpone ruido gaussiano reproducible, para comprobar que los ajustes por mínimos
    cuadrados aguantan lo que las diferencias entre extremos no aguantarían.
    """
    transform = from_origin(origin[0], origin[1], res, res)
    cols = np.arange(size)
    rows = np.arange(size)
    col_grid, row_grid = np.meshgrid(cols, rows)

    x = origin[0] + (col_grid + 0.5) * res
    y = origin[1] - (row_grid + 0.5) * res

    d = x - road_center_x(origin, res, road_col)   # + = este = izquierda del avance
    station = origin[1] - y                        # progresiva desde el borde norte

    # El semiancho es un array, no un escalar, para que `pinch` pueda estrecharlo en una franja
    # de progresiva: es lo que permite construir un camino que NO es uniforme a lo largo, y sin
    # eso no hay forma de distinguir medir el ancho una vez por tramo de medirlo varias.
    hw_left = np.full(station.shape, float(half_width_left))
    hw_right = np.full(station.shape, float(half_width_right))
    if pinch is not None:
        s0, s1, p_left, p_right = pinch
        inside = (station >= s0) & (station < s1)
        hw_left = np.where(inside, p_left, hw_left)
        hw_right = np.where(inside, p_right, hw_right)

    on_road = np.where(d >= 0, d <= hw_left, -d <= hw_right)
    edge_z = np.where(d >= 0, cross_slope * hw_left, -cross_slope * hw_right)
    overshoot = np.where(d >= 0, d - hw_left, -d - hw_right)

    cross = np.where(on_road, cross_slope * d, edge_z - talud * np.maximum(overshoot, 0.0))
    data = (base + grade * station + cross).astype(np.float32)

    if noise:
        rng = np.random.default_rng(seed)
        data = (data + rng.normal(0.0, noise, data.shape)).astype(np.float32)

    if nodata_patch is not None:
        r0, r1, c0, c1 = nodata_patch
        data[r0:r1, c0:c1] = nodata

    with rasterio.open(path, 'w', driver='GTiff', height=size, width=size, count=1,
                       dtype='float32', crs='EPSG:{}'.format(epsg), transform=transform,
                       nodata=nodata) as dst:
        dst.write(data, 1)


def xy_to_lnglat(x, y, epsg=DEM_EPSG):
    lng, lat = rasterio.warp.transform(CRS.from_epsg(epsg), CRS.from_epsg(4326), [x], [y])
    return [lng[0], lat[0]]


def pixel_to_lnglat(row, col, origin=DEM_ORIGIN, res=DEM_RES, epsg=DEM_EPSG):
    return xy_to_lnglat(origin[0] + (col + 0.5) * res, origin[1] - (row + 0.5) * res, epsg)


def dem_extent(size=DEM_SIZE, res=DEM_RES, origin=DEM_ORIGIN, epsg=DEM_EPSG):
    """Extensión del DEM sintético en EPSG:4326, para las columnas `*_extent` de la tarea."""
    x0, y0 = origin
    x1, y1 = x0 + size * res, y0 - size * res
    lng0, lat0 = xy_to_lnglat(x0, y1, epsg)
    lng1, lat1 = xy_to_lnglat(x1, y0, epsg)
    return Polygon.from_bbox([min(lng0, lng1), min(lat0, lat1), max(lng0, lng1), max(lat0, lat1)])


def axis_vertices(row_start=40, row_end=440, road_col=ROAD_COL, vertices=2, **kwargs):
    """Eje recto sobre el centro del camino, de norte a sur, en EPSG:4326.

    De norte a sur porque el convenio de lados del módulo depende del sentido de trazado: con este
    sentido la izquierda es el este, que es como está construido el DEM.
    """
    return [pixel_to_lnglat(row_start + (row_end - row_start) * i / (vertices - 1), road_col,
                            **kwargs)
            for i in range(vertices)]


class RoadTestBase(BootTestCase):
    """Andamiaje común de la suite (patrón de `annotations` y `realign`)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Road test project", owner="testuser"):
        return Project.objects.create(owner=User.objects.get(username=owner), name=name)

    def _task(self, project, **kwargs):
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif"], orthophoto_extent=dem_extent(),
                        epsg=DEM_EPSG)
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _task_with_dem(self, project=None, asset='dtm.tif', dem_kwargs=None, **task_kwargs):
        """Tarea con el DEM sintético ya escrito en la ruta de asset que WebODM espera."""
        if project is None:
            project = self._project()
        extent_field = 'dsm_extent' if asset == 'dsm.tif' else 'dtm_extent'
        task_kwargs.setdefault('available_assets', ['orthophoto.tif', asset])
        task_kwargs.setdefault(extent_field, dem_extent())
        task = self._task(project, **task_kwargs)

        path = task.get_asset_download_path(asset)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        make_road_dem(path, **(dem_kwargs or {}))
        self.addCleanup(shutil.rmtree, task.task_path(), ignore_errors=True)
        return task

    def _login(self, username="testuser"):
        self.client.login(username=username, password="test1234")

    def _grant_read_only(self, username, project):
        """Usuario con acceso de lectura al proyecto pero sin `change_project`."""
        user = User.objects.get(username=username)
        assign_perm('view_project', user, project)
        return user

    def _url(self, task, suffix="capabilities"):
        return "/api/plugins/road/task/{}/{}".format(task.id, suffix)


# --- Perfiles sintéticos en memoria (para los tests de `profile.py`, sin ráster) ----------

def synthetic_cross_profile(half_width_left=DEFAULT_HALF_WIDTH,
                            half_width_right=DEFAULT_HALF_WIDTH, search_half_width=10.0,
                            step=0.25, cross_slope=DEFAULT_CROSS_SLOPE, talud=DEFAULT_TALUD,
                            base=DEFAULT_BASE, nodata_beyond_left=None,
                            nodata_beyond_right=None, noise=0.0, seed=11):
    """Perfil transversal `(distances, elevations)` con la misma forma que el DEM sintético.

    `nodata_beyond_*` corta el perfil con `None` a partir de esa distancia, que es lo que hace un
    DEM cuando el vuelo no llegó hasta allí.
    """
    n = int(round(search_half_width / step))
    distances = [k * step for k in range(-n, n + 1)]
    rng = np.random.default_rng(seed)

    elevations = []
    for d in distances:
        if d >= 0:
            on_road = d <= half_width_left + 1e-9
            edge_z = cross_slope * half_width_left
            overshoot = d - half_width_left
        else:
            on_road = -d <= half_width_right + 1e-9
            edge_z = -cross_slope * half_width_right
            overshoot = -d - half_width_right
        z = base + (cross_slope * d if on_road else edge_z - talud * max(overshoot, 0.0))
        if noise:
            z += float(rng.normal(0.0, noise))
        if nodata_beyond_left is not None and d > nodata_beyond_left:
            z = None
        if nodata_beyond_right is not None and -d > nodata_beyond_right:
            z = None
        elevations.append(z)
    return distances, elevations


def synthetic_long_profile(length=5.0, step=0.25, grade=DEFAULT_GRADE, base=DEFAULT_BASE,
                           noise=0.0, seed=13):
    """Perfil longitudinal `(stations, elevations)` de pendiente exacta `grade`."""
    n = int(round(length / step))
    rng = np.random.default_rng(seed)
    stations = [k * step for k in range(n + 1)]
    elevations = [base + grade * s + (float(rng.normal(0.0, noise)) if noise else 0.0)
                  for s in stations]
    return stations, elevations
