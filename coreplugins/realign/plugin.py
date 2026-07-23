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
)


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
        ]
