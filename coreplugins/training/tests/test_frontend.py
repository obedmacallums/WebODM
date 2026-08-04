"""Engancha los tests de `public/tests` a la suite de Django del plugin.

El `jest.config.js` del core solo cubre `app/static/app/js` y es un archivo de upstream que no se
toca (Principio I), así que el plugin trae sus propios casos y los lanza desde aquí para que corran
con la suite de siempre. Cargan los módulos reales de `public/`, no una copia: lo que se prueba es
el archivo que se despliega.

Se saltan —no fallan— si falta `node` o si `jsdom`/`leaflet` no están resueltos: en un entorno sin
el build del core montado, la ausencia del intérprete no es un fallo del plugin.
"""

import os
import shutil
import subprocess
import unittest

from django.test import SimpleTestCase

JS_TESTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            'public', 'tests')


def _node_available():
    return shutil.which('node') is not None and os.path.isdir(JS_TESTS_DIR)


@unittest.skipUnless(_node_available(), 'node no está disponible en este entorno')
class FrontendUnitTest(SimpleTestCase):
    def _run_js(self, script):
        proc = subprocess.run(['node', script], cwd=JS_TESTS_DIR,
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0:
            self.fail('{} falló:\n{}\n{}'.format(script, proc.stdout, proc.stderr))

    def test_brush_radius_is_measured_on_the_ground(self):
        self._run_js('brushRadius.test.js')

    def test_label_layer_respects_order_and_colors(self):
        self._run_js('labelLayer.test.js')

    def test_reviewed_areas_are_not_class_zero(self):
        self._run_js('reviewArea.test.js')

    def test_the_delete_key_only_fires_when_it_is_safe(self):
        self._run_js('deleteShortcut.test.js')

    def test_shift_click_selects_several_labels(self):
        self._run_js('selection.test.js')

    def test_label_editor_draws_polygons_strokes_and_erasures(self):
        self._run_js('labelEditor.test.js')

    def test_datasets_page_lists_tasks_with_an_orthophoto(self):
        self._run_js('datasetsPage.test.js')

    def test_panel_rebuilds_its_editor_when_reopened(self):
        self._run_js('panelLifecycle.test.js')

    def test_assisted_selection_does_not_disturb_the_other_modes(self):
        self._run_js('assistMode.test.js')
