from app.plugins import PluginBase
from app.plugins import MountPoint

from .api import (
    RealignState,
    RealignApply,
    RealignRevert,
    RealignStatus,
    RealignTiles,
    RealignTileJson,
    RealignDownload,
    RealignPointCloud,
    RealignPointCloudDownload,
)
from . import contract


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Realign.jsx']

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/realign/state', RealignState.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/apply', RealignApply.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/revert', RealignRevert.as_view()),
            MountPoint('task/[^/.]+/realign/status/(?P<celery_task_id>.+)', RealignStatus.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/tiles/(?P<type>orthophoto|dsm|dtm)/(?P<z>\\d+)/(?P<x>\\d+)/(?P<y>\\d+)(?P<ext>\\.png)?', RealignTiles.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/tilejson/(?P<type>orthophoto|dsm|dtm)', RealignTileJson.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/download/(?P<type>orthophoto|dsm|dtm)', RealignDownload.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/pointcloud/download$', RealignPointCloudDownload.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/realign/pointcloud$', RealignPointCloud.as_view()),
        ]

    # --- Contrato para otros plugins (`005-road-metrics/contracts/consumed-contracts.md` §2) ---
    # Delegan enteramente en `contract.py`: ningún otro atributo de esta clase forma parte del
    # contrato. Un consumidor obtiene este plugin por `get_plugin_by_name` y nunca importando
    # `coreplugins.realign`, que es lo que le permite degradar si está ausente o deshabilitado.

    def contract_version(self):
        return contract.CONTRACT_VERSION

    def corrected_rasters(self, task_id):
        return contract.corrected_rasters(task_id)
