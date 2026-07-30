from app.plugins import PluginBase
from app.plugins import MountPoint

from .api import (AnalysisCancel, AnalysisDetail, AnalysisEstimate, AnalysisExport, AnalysisList, AnalysisMask,
                  Capabilities)
from . import signals  # noqa: F401 - registra el receptor de task_removed (borrado en cascada)


class Plugin(PluginBase):
    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Road.jsx']

    def api_mount_points(self):
        # Los MountPoint sin '$' final resuelven por prefijo (Django no exige match completo),
        # así que 'analyses' se "tragaría" rutas como 'analyses/estimate'. Toda ruta propia ancla
        # el final con '$'; las literales más específicas se registran antes que el patrón
        # genérico de '<analysis_id>' cuando coinciden en forma.
        return [
            MountPoint('task/(?P<pk>[^/.]+)/capabilities$', Capabilities.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/analyses$', AnalysisList.as_view()),
            # 'estimate' es literal y va **antes** del patrón de '<analysis_id>', que si no se la
            # tragaría como si fuera el id de un análisis.
            MountPoint('task/(?P<pk>[^/.]+)/analyses/estimate$', AnalysisEstimate.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/analyses/(?P<analysis_id>[^/.]+)/cancel$',
                       AnalysisCancel.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/analyses/(?P<analysis_id>[^/.]+)/export$',
                       AnalysisExport.as_view()),
            # La máscara del modelo (`008`). Como el resto de literales, va **antes** del patrón
            # genérico de `<analysis_id>`: sin `$` los MountPoint resuelven por prefijo y el
            # genérico se tragaría esta ruta.
            MountPoint('task/(?P<pk>[^/.]+)/analyses/(?P<analysis_id>[^/.]+)/mask$',
                       AnalysisMask.as_view()),
            MountPoint('task/(?P<pk>[^/.]+)/analyses/(?P<analysis_id>[^/.]+)$',
                       AnalysisDetail.as_view()),
        ]
