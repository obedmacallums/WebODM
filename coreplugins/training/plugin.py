from app.plugins import PluginBase, Menu, MountPoint
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils.translation import gettext as _

from .api import (DatasetDetail, DatasetList, ExportDetail, ExportDownload, ExportList,
                  LabelDetail, LabelList)


class Plugin(PluginBase):
    def main_menu(self):
        # Un dataset referencia varias tareas (FR-002), así que no puede colgar de ninguna: la
        # gestión vive en una página global. Precedente: `coreplugins/task-manager/plugin.py`.
        return [Menu(_("Training"), self.public_url(""), "fa fa-vector-square fa-fw")]

    def app_mount_points(self):
        @login_required
        def index_view(request):
            return render(request, self.template_path("index.html"), {
                'title': _("Training datasets")
            })

        return [
            MountPoint('$', index_view),
        ]

    def include_js_files(self):
        return ['main.js']

    def build_jsx_components(self):
        return ['Training.jsx']

    def api_mount_points(self):
        # Los MountPoint sin '$' final resuelven por prefijo (Django no exige match completo), así
        # que 'datasets' se "tragaría" rutas como 'datasets/export'. Toda ruta propia ancla el final
        # con '$'; las literales más específicas se registran antes que el patrón genérico de
        # '<dataset_id>' cuando coinciden en forma. Convención heredada de `annotations` y `road`.
        return [
            MountPoint('datasets$', DatasetList.as_view()),
            MountPoint('datasets/(?P<dataset_id>[^/.]+)/tasks/(?P<pk>[^/.]+)/labels$',
                       LabelList.as_view()),
            MountPoint('datasets/(?P<dataset_id>[^/.]+)/tasks/(?P<pk>[^/.]+)/labels/'
                       '(?P<label_id>[^/.]+)$', LabelDetail.as_view()),
            MountPoint('datasets/(?P<dataset_id>[^/.]+)/exports$', ExportList.as_view()),
            # 'download' es literal y va **antes** del patrón de '<export_id>': aunque el '$' final
            # ya los distingue por longitud, el orden mantiene la regla que evita el fallo
            # silencioso de responder 200 con el cuerpo equivocado.
            MountPoint('datasets/(?P<dataset_id>[^/.]+)/exports/(?P<export_id>[^/.]+)/download$',
                       ExportDownload.as_view()),
            MountPoint('datasets/(?P<dataset_id>[^/.]+)/exports/(?P<export_id>[^/.]+)$',
                       ExportDetail.as_view()),
            MountPoint('datasets/(?P<dataset_id>[^/.]+)$', DatasetDetail.as_view()),
        ]
