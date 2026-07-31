"""El plugin existe, carga, su manifiesto es válido y sus rutas están bien ancladas.

El test de anclaje no es cosmético: un `MountPoint` sin `$` final resuelve por prefijo, así que
`datasets` se tragaría `datasets/<id>/exports` y el usuario recibiría el listado de datasets al
pedir una descarga. Es un fallo silencioso —responde 200 con el cuerpo equivocado— y por eso se
comprueba mecánicamente en vez de confiar en la revisión.
"""

import json
import os

from django.test import TestCase

from app.plugins.functions import get_plugin_by_name

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class PluginLoadTest(TestCase):
    def test_plugin_is_registered(self):
        plugin = get_plugin_by_name('training')
        self.assertIsNotNone(plugin, 'El plugin training no aparece en el registro')

    def test_manifest_has_required_fields(self):
        with open(os.path.join(PLUGIN_DIR, 'manifest.json')) as f:
            manifest = json.load(f)
        for field in ('name', 'description', 'version', 'author', 'webodmMinVersion'):
            self.assertIn(field, manifest)
        self.assertEqual(manifest['name'], 'Training')

    def test_frontend_entrypoints_exist(self):
        plugin = get_plugin_by_name('training')
        for f in plugin.include_js_files() + plugin.build_jsx_components():
            self.assertTrue(os.path.isfile(os.path.join(PLUGIN_DIR, 'public', f)),
                            'Falta el asset declarado en plugin.py: {}'.format(f))

    def test_global_page_template_exists(self):
        """La página global se sirve con `render(self.template_path("index.html"))` (D1)."""
        self.assertTrue(os.path.isfile(os.path.join(PLUGIN_DIR, 'templates', 'index.html')))

    def test_api_routes_are_anchored(self):
        plugin = get_plugin_by_name('training')
        for mount_point in plugin.api_mount_points():
            self.assertTrue(mount_point.url.endswith('$'),
                            'Ruta sin anclar, resolvería por prefijo: {}'.format(mount_point.url))

    def test_literal_routes_precede_generic_patterns(self):
        """Las rutas literales van antes que el patrón que las podría capturar.

        `datasets/(?P<dataset_id>[^/.]+)$` casa con `datasets/loquesea`, así que cualquier ruta
        literal registrada después de él nunca se alcanzaría.
        """
        seen_generic = []
        for mount_point in plugin_mount_urls():
            for generic in seen_generic:
                self.assertFalse(_would_shadow(generic, mount_point),
                                 '{} nunca se alcanzará: {} la captura antes'.format(
                                     mount_point, generic))
            if '(?P<' in mount_point:
                seen_generic.append(mount_point)


def plugin_mount_urls():
    return [mp.url for mp in get_plugin_by_name('training').api_mount_points()]


def _would_shadow(generic, later):
    """¿El patrón `generic`, registrado antes, captura la ruta `later`?

    Se compara segmento a segmento: un grupo con nombre casa cualquier segmento sin `/` ni `.`, y
    ambos patrones deben tener el mismo número de segmentos para que el `$` final los enfrente.
    """
    import re

    a, b = generic.rstrip('$').split('/'), later.rstrip('$').split('/')
    if len(a) != len(b):
        return False
    for seg_a, seg_b in zip(a, b):
        if seg_a == seg_b:
            continue
        if seg_a.startswith('(?P<') and '.' not in seg_b and not re.search(r'[()\[\]|+*]', seg_b):
            continue
        return False
    return True
