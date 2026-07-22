from app.plugins import PluginBase
from app.plugins import MountPoint
from .api import TaskViewshedGenerate
from .api import TaskViewshedDownload


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Viewshed.jsx']

    def api_mount_points(self):
        return [
            MountPoint('task/(?P<pk>[^/.]+)/viewshed/generate', TaskViewshedGenerate.as_view()),
            MountPoint('task/[^/.]+/viewshed/download/(?P<celery_task_id>.+)', TaskViewshedDownload.as_view()),
        ]
