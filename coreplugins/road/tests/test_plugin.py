"""El plugin existe, carga y su manifiesto es válido (Principio III de la constitución)."""

import json
import os

from django.test import TestCase

from app.plugins.functions import get_plugin_by_name

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PluginLoadTest(TestCase):
    def test_plugin_is_registered(self):
        plugin = get_plugin_by_name('road')
        self.assertIsNotNone(plugin, 'El plugin road no aparece en el registro')

    def test_manifest_has_required_fields(self):
        with open(os.path.join(PLUGIN_DIR, 'manifest.json')) as f:
            manifest = json.load(f)
        for field in ('name', 'description', 'version', 'author', 'webodmMinVersion'):
            self.assertIn(field, manifest)
        self.assertEqual(manifest['name'], 'Road')

    def test_frontend_entrypoints_exist(self):
        plugin = get_plugin_by_name('road')
        for f in plugin.include_js_files() + plugin.build_jsx_components():
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN_DIR, 'public', f)),
                            'Falta el asset declarado en plugin.py: {}'.format(f))
