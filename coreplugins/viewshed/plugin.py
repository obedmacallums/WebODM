from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import TaskViewshedGenerate
from .api import TaskViewshedResult


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Viewshed.jsx']

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/viewshed/generate', TaskViewshedGenerate.as_view()),
            MountPoint('task/[^/.]+/viewshed/result/(?P<celery_task_id>.+)', TaskViewshedResult.as_view()),
        ]
