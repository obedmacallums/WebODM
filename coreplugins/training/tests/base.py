"""Andamiaje común de la suite: tarea con ortofoto sintética de georreferenciación conocida.

La ortofoto no es ruido con forma de imagen: está construida para que cada comprobación tenga un
valor **exacto** esperado de antemano.

- **CRS métrico** (EPSG:32719, el de las cinco ortofotos reales del usuario según `research.md`
  D4), para que el buffer del pincel se pueda verificar en metros.
- **Cuatro bandas con la cuarta en alfa** y `nodata` sin declarar, que es exactamente lo que
  midió D7. La mitad derecha de la última fila de teselas lleva alfa 0, de modo que el filtro de
  píxeles válidos de FR-027 tenga algo real que descartar.
- **Resolución nativa más fina que la del dataset** (5 cm/px frente a 10), porque el remuestreo de
  la lectura (D6) es justo lo que hay que probar; si coincidieran, el test pasaría sin ejercitarlo.

Las etiquetas se guardan en coordenadas geográficas (D4), así que los helpers convierten de UTM a
lon/lat: los tests razonan en metros y el almacenamiento ve grados, que es el reparto real.
"""

import os
import shutil

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin
from rasterio.warp import transform as warp_transform

from django.contrib.auth.models import User
from django.contrib.gis.geos import Polygon
from guardian.shortcuts import assign_perm
from rest_framework.test import APIClient

from app.models import Project, Task
from app.tests.classes import BootTestCase
from nodeodm import status_codes

ORTHO_EPSG = 32719                    # UTM 19S, el de las ortofotos reales del usuario
ORTHO_ORIGIN = (400000.0, 6000000.0)  # (x, y) de la esquina superior izquierda, en metros
ORTHO_RES = 0.05                      # m/px nativos
ORTHO_SIZE = 600                      # px por lado -> 30 m x 30 m


def xy_to_lnglat(x, y, epsg=ORTHO_EPSG):
    lng, lat = warp_transform(CRS.from_epsg(epsg), CRS.from_epsg(4326), [x], [y])
    return lng[0], lat[0]


def offset_to_lnglat(dx, dy, epsg=ORTHO_EPSG):
    """Punto a `dx` metros al este y `dy` metros al sur de la esquina superior izquierda."""
    return xy_to_lnglat(ORTHO_ORIGIN[0] + dx, ORTHO_ORIGIN[1] - dy, epsg)


def ortho_extent(size=ORTHO_SIZE, res=ORTHO_RES, origin=ORTHO_ORIGIN, epsg=ORTHO_EPSG):
    """Extensión de la ortofoto en EPSG:4326, para la columna `orthophoto_extent` de la tarea."""
    x0, y0 = origin
    x1, y1 = x0 + size * res, y0 - size * res
    lng0, lat0 = xy_to_lnglat(x0, y1, epsg)
    lng1, lat1 = xy_to_lnglat(x1, y0, epsg)
    return Polygon.from_bbox([min(lng0, lng1), min(lat0, lat1), max(lng0, lng1), max(lat0, lat1)])


def make_orthophoto(path, size=ORTHO_SIZE, res=ORTHO_RES, origin=ORTHO_ORIGIN, epsg=ORTHO_EPSG,
                    nodata_corner=True):
    """Escribe una ortofoto RGBA de contenido conocido.

    El rojo crece con la columna y el verde con la fila, de modo que una tesela remuestreada se
    puede identificar por su contenido: si la ventana leída fuera la equivocada, los valores no
    cuadrarían y el test lo vería.
    """
    columns = np.arange(size, dtype=np.float64) / max(size - 1, 1)
    rows = np.arange(size, dtype=np.float64).reshape(-1, 1) / max(size - 1, 1)

    red = np.broadcast_to(columns * 255, (size, size)).astype(np.uint8)
    green = np.broadcast_to(rows * 255, (size, size)).astype(np.uint8)
    blue = np.full((size, size), 64, dtype=np.uint8)
    alpha = np.full((size, size), 255, dtype=np.uint8)
    if nodata_corner:
        # Cuadrante inferior derecho sin datos: es el perímetro de vuelo que FR-027 debe descartar.
        alpha[size // 2:, size // 2:] = 0

    os.makedirs(os.path.dirname(path), exist_ok=True)
    profile = {
        'driver': 'GTiff', 'width': size, 'height': size, 'count': 4, 'dtype': 'uint8',
        'crs': CRS.from_epsg(epsg), 'transform': from_origin(origin[0], origin[1], res, res),
        'tiled': True, 'blockxsize': 256, 'blockysize': 256,
    }
    with rasterio.open(path, 'w', **profile) as dst:
        dst.write(red, 1)
        dst.write(green, 2)
        dst.write(blue, 3)
        dst.write(alpha, 4)
        dst.colorinterp = [rasterio.enums.ColorInterp.red, rasterio.enums.ColorInterp.green,
                           rasterio.enums.ColorInterp.blue, rasterio.enums.ColorInterp.alpha]
    return path


class TrainingTestBase(BootTestCase):
    """Andamiaje común de la suite (patrón de `road` y `annotations`)."""

    def setUp(self):
        super().setUp()
        self.client = APIClient()

    def _project(self, name="Training test project", owner="testuser"):
        return Project.objects.create(owner=User.objects.get(username=owner), name=name)

    def _task(self, project=None, **kwargs):
        if project is None:
            project = self._project()
        defaults = dict(project=project, status=status_codes.COMPLETED,
                        available_assets=["orthophoto.tif"], orthophoto_extent=ortho_extent(),
                        epsg=ORTHO_EPSG, name="Task with orthophoto")
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _task_with_orthophoto(self, project=None, **task_kwargs):
        """Tarea con la ortofoto sintética escrita en la ruta de asset que WebODM espera."""
        task = self._task(project, **task_kwargs)
        make_orthophoto(task.get_asset_download_path('orthophoto.tif'))
        self.addCleanup(shutil.rmtree, task.task_path(), ignore_errors=True)
        return task

    def _login(self, username="testuser"):
        self.client.login(username=username, password="test1234")

    def _grant_read_only(self, username, project):
        user = User.objects.get(username=username)
        assign_perm('view_project', user, project)
        return user

    def _dataset_payload(self, task, **overrides):
        payload = {
            'name': 'Pistas mineras',
            'classes': [{'index': 0, 'name': 'background'}, {'index': 1, 'name': 'road'}],
            'tasks': [{'task_id': str(task.id), 'project_id': task.project_id}],
            'resolution_cm_px': 10.0,
            'tile_size_px': 64,
        }
        payload.update(overrides)
        return payload

    def _create_dataset(self, task, owner='testuser', **overrides):
        """Crea un dataset directamente por el store, sin pasar por la API.

        `owner` se registra como `created_by` porque es lo que hace la API real, y de ello depende
        que el dataset siga siendo accesible cuando su última tarea desaparece: sin dueño no
        quedaría nadie con derecho a abrirlo ni a borrarlo (invariante 5 de `data-model.md`).
        """
        from coreplugins.training import models, store
        payload = self._dataset_payload(task, **overrides)
        dataset = models.make_dataset(
            payload['name'], payload['classes'], payload['tasks'],
            resolution_cm_px=payload.get('resolution_cm_px'),
            tile_size_px=payload.get('tile_size_px'),
            created_by=User.objects.get(username=owner).id if owner else None)
        store.create_dataset(dataset)
        self.addCleanup(store.delete_dataset, dataset['id'])
        return dataset

    def _add_label(self, dataset, task, **payload):
        from coreplugins.training import models, store
        payload.setdefault('kind', models.KIND_POLYGON)
        return store.add_label(
            dataset['id'], str(task.id),
            lambda order: models.make_label(dataset, payload, order))

    def _api(self, *parts):
        return '/api/plugins/training/' + '/'.join(str(p) for p in parts)
