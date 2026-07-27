from app.plugins import PluginBase
from app.plugins import MountPoint

from .api import (
    PolylineList, PolylineDetail, ElevationCapabilities, PolylineExport,
    PolylineSingleExport, PolylineDensified,
)
from . import contract
from .contract import IncompleteCoverage, LimitExceeded  # noqa: F401 - reexport del contrato
from . import signals  # noqa: F401 - registra el receptor de task_removed (FR-027)


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Annotations.jsx']

    def api_mount_points(self):
        # Los MountPoint sin '$' final resuelven por prefijo (Django no exige match completo),
        # así que 'polylines' se "tragaría" rutas como 'polylines/export' o 'polylines/<id>/export'
        # si esas llegaran a registrarse después. Toda ruta propia ancla el final con '$'; las
        # rutas literales más específicas deben registrarse antes que el patrón genérico de
        # '<polyline_id>' cuando coincidan en forma (p. ej. 'polylines/export').
        return [
            MountPoint('task/(?P<pk>[^/.]+)/elevation$', ElevationCapabilities.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/polylines$', PolylineList.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/polylines/export$', PolylineExport.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/polylines/(?P<polyline_id>[^/.]+)/export$', PolylineSingleExport.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/polylines/(?P<polyline_id>[^/.]+)/densified$', PolylineDensified.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/polylines/(?P<polyline_id>[^/.]+)$', PolylineDetail.as_view()),
        ]

    # --- Contrato para otros plugins (`contracts/plugin-contract.md` §1.1, FR-036 a FR-040) ---
    # Delegan enteramente en `contract.py`: ningún otro atributo de esta clase forma parte del
    # contrato.

    def contract_version(self):
        return contract.CONTRACT_VERSION

    def get_polylines(self, task_id):
        return contract.get_polylines(task_id)

    def get_polyline(self, task_id, polyline_id):
        return contract.get_polyline(task_id, polyline_id)

    def get_densified(self, task_id, polyline_id, step=None):
        return contract.get_densified(task_id, polyline_id, step)
