from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import TaskWatershedGenerate
from .api import TaskWatershedResult


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Watershed.jsx']

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/watershed/generate', TaskWatershedGenerate.as_view()),
            MountPoint('task/[^/.]+/watershed/result/(?P<celery_task_id>.+)', TaskWatershedResult.as_view()),
        ]
