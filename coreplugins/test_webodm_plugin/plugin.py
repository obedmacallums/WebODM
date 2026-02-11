from app.plugins import PluginBase, Menu, MountPoint
from django.shortcuts import render


class Plugin(PluginBase):

    def main_menu(self):
        return [Menu("Test Plugin", self.public_url(""), "fa fa-flask fa-fw")]

    def include_js_files(self):
        return ['main.js']

    def app_mount_points(self):
        def home(request):
            return render(request, self.template_path("home.html"), {
                'title': 'Test WebODM Plugin'
            })
        return [MountPoint('$', home)]
