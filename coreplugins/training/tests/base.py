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

# El DTM sintético es un plano inclinado hacia el este con esta pendiente, en metros por metro.
# 0,5 da una pendiente de atan(0,5) = 26,565°, dentro del techo de 45° y lejos de él, así que la
# normalización se puede comprobar sin saturar.
DTM_GRADIENT = 0.5
DTM_BASE_M = 4100.0                   # cota parecida a la de la mina real del usuario
DTM_RES = 0.10                        # m/px nativos: el DTM se escribe más grueso que la ortofoto


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


def make_dtm(path, size=ORTHO_SIZE, res=ORTHO_RES, origin=ORTHO_ORIGIN, epsg=ORTHO_EPSG,
             gradient=DTM_GRADIENT, base=DTM_BASE_M, native_res=DTM_RES, nodata_corner=False):
    """Escribe un DTM sintético: un plano inclinado hacia el este de pendiente conocida.

    Un plano y no ruido a propósito. Sus dos canales derivados tienen valor cerrado, así que los
    tests comprueban un número y no un rango:

    - **pendiente** = `atan(gradient)`, la misma en todo el ráster. Con 0,5 son 26,565°.
    - **rugosidad** = **cero exacto**, porque se mide como residuo respecto al plano local y un
      plano no se aparta de sí mismo. Es la comprobación que separa rugosidad de pendiente: con el
      TRI de Riley este mismo ráster daría 0,0375 m, o sea la pendiente disfrazada.

    Se escribe a `native_res` (10 cm/px), más grueso que la ortofoto (5 cm) y con **origen propio**,
    para que la alineación de D15 tenga de verdad algo que corregir. Un DTM ya alineado dejaría el
    `reproject` sin ejercitar y el test pasaría sin probar lo que importa.
    """
    span_m = size * res
    native_size = int(round(span_m / native_res))

    columns = np.arange(native_size, dtype=np.float64) * native_res
    elevation = (base + gradient * columns).astype(np.float32)
    elevation = np.broadcast_to(elevation, (native_size, native_size)).copy()

    nodata = -9999.0
    if nodata_corner:
        elevation[native_size // 2:, native_size // 2:] = nodata

    os.makedirs(os.path.dirname(path), exist_ok=True)
    profile = {
        'driver': 'GTiff', 'width': native_size, 'height': native_size, 'count': 1,
        'dtype': 'float32', 'crs': CRS.from_epsg(epsg), 'nodata': nodata,
        # Medio píxel de desfase en Y, que es lo que se midió entre la ortofoto y el DTM reales de
        # la mina (3,8 cm sobre 6,35 cm/px). Sin esto la rejilla saldría casualmente alineada.
        'transform': from_origin(origin[0], origin[1] - native_res / 2, native_res, native_res),
    }
    with rasterio.open(path, 'w', **profile) as dst:
        dst.write(elevation, 1)
    return path


def expected_slope_degrees(gradient=DTM_GRADIENT):
    return np.degrees(np.arctan(gradient))


def expected_tri_m(gradient=DTM_GRADIENT, step_m=0.10):
    """TRI de Riley sobre un plano: 6 vecinos a `±g*paso` y 2 a cero, entre 8.

    No es lo que calcula el plugin; se conserva para poder afirmar en los tests **cuánto** habría
    contaminado el canal de rugosidad si se hubiera usado el TRI.
    """
    return 6.0 * gradient * step_m / 8.0


def expected_checkerboard_roughness_m(amplitude):
    """Rugosidad de un damero de amplitud `A`, en metros.

    Sobre un damero el plano de mínimos cuadrados de la ventana 3x3 es horizontal y su término
    independiente es `±A/9`, así que el residuo cuadrático medio vale
    `A * sqrt((5*(8/9)^2 + 4*(10/9)^2) / 9) = A * sqrt(80/81)`.
    """
    return amplitude * np.sqrt(80.0 / 81.0)


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
                        available_assets=["orthophoto.tif", "dtm.tif"],
                        orthophoto_extent=ortho_extent(),
                        epsg=ORTHO_EPSG, name="Task with orthophoto")
        defaults.update(kwargs)
        return Task.objects.create(**defaults)

    def _task_with_orthophoto(self, project=None, with_dtm=True, nodata_corner=True,
                              **task_kwargs):
        """Tarea con la ortofoto —y por defecto el DTM— en la ruta de asset que WebODM espera.

        El DTM va por defecto porque sin él la tarea se salta entera: el paquete es de 5 bandas y
        una tarea sin elevación solo podría aportar 3 (FR-044). `with_dtm=False` es justamente el
        caso que hay que poder probar.
        """
        task = self._task(project, **task_kwargs)
        make_orthophoto(task.get_asset_download_path('orthophoto.tif'),
                        nodata_corner=nodata_corner)
        if with_dtm:
            make_dtm(task.get_asset_download_path('dtm.tif'))
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
            # Bloques de 2 teselas y no los 4 de producción. La ortofoto sintética mide 30 m, que a
            # teselas de 6,4 m con paso de 5,6 da una rejilla de 5x5 candidatas: con bloques de 4
            # salen solo 2x2 bloques, y si el sorteo manda a validación el bloque grande, el
            # pasillo se lleva las teselas de entrenamiento que quedan. Medido: pasa en el 24 % de
            # las semillas, y la semilla es el uuid del dataset — o sea, un test que falla uno de
            # cada cuatro días. Con bloques de 2 son 9 bloques y no ocurre nunca (0/500).
            'split_block_tiles': 2,
        }
        payload.update(overrides)
        return payload

    # Campos de configuración que `make_dataset` acepta por nombre. La lista está aquí para que
    # añadir un ajuste nuevo no obligue a tocar cada test que lo quiera usar.
    _DATASET_SETTINGS = ('resolution_cm_px', 'tile_size_px', 'tile_overlap_px', 'elevation_source',
                         'pixel_dtype', 'min_reviewed_fraction', 'min_valid_fraction',
                         'val_fraction', 'split_block_tiles', 'stroke_width_m')

    def _create_dataset(self, task, owner='testuser', **overrides):
        """Crea un dataset directamente por el store, sin pasar por la API.

        `owner` se registra como `created_by` porque es lo que hace la API real, y de ello depende
        que el dataset siga siendo accesible cuando su última tarea desaparece: sin dueño no
        quedaría nadie con derecho a abrirlo ni a borrarlo (invariante 5 de `data-model.md`).
        """
        from coreplugins.training import models, store
        payload = self._dataset_payload(task, **overrides)
        settings = {k: payload[k] for k in self._DATASET_SETTINGS if k in payload}
        # Con una tesela de 64 px el solape por defecto (1/8) son 8 px, que mantiene la rejilla de
        # los tests manejable y sigue ejercitando el solape de verdad.
        dataset = models.make_dataset(
            payload['name'], payload['classes'], payload['tasks'],
            created_by=User.objects.get(username=owner).id if owner else None,
            **settings)
        store.create_dataset(dataset)
        self.addCleanup(store.delete_dataset, dataset['id'])
        return dataset

    def _add_label(self, dataset, task, **payload):
        from coreplugins.training import models, store
        payload.setdefault('kind', models.KIND_POLYGON)
        return store.add_label(
            dataset['id'], str(task.id),
            lambda order: models.make_label(dataset, payload, order))

    def _review_all(self, dataset, task, margin_m=0.0, **payload):
        """Declara revisada la ortofoto entera.

        Sin un área revisada no se exporta nada, así que casi todos los tests de exportación
        necesitan esto. Es el equivalente de lo que hace el anotador cuando ha recorrido el vuelo
        completo: afirma que lo que no lleve etiqueta es fondo de verdad, no «no lo sé».
        """
        span = ORTHO_SIZE * ORTHO_RES
        corners = [(-margin_m, -margin_m), (span + margin_m, -margin_m),
                   (span + margin_m, span + margin_m), (-margin_m, span + margin_m)]
        return self._add_label(dataset, task, kind='review',
                               geometry=[list(offset_to_lnglat(dx, dy)) for dx, dy in corners],
                               **payload)

    def _review_box(self, dataset, task, x0, y0, x1, y1, **payload):
        """Área revisada rectangular, en metros desde la esquina superior izquierda."""
        corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return self._add_label(dataset, task, kind='review',
                               geometry=[list(offset_to_lnglat(dx, dy)) for dx, dy in corners],
                               **payload)

    def _api(self, *parts):
        return '/api/plugins/training/' + '/'.join(str(p) for p in parts)
