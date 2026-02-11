from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import TaskHillshadeGenerate
from .api import TaskHillshadeResult


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Hillshade.jsx']

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/hillshade/generate', TaskHillshadeGenerate.as_view()),
            MountPoint('task/[^/.]+/hillshade/result/(?P<celery_task_id>.+)', TaskHillshadeResult.as_view()),
        ]
