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

    def test_segment_style_traffic_light(self):
        self._run_js('segmentStyle.test.js')

    def test_road_bridge_coexists_on_the_core_bus(self):
        self._run_js('roadBridge.test.js')

    def test_threshold_recolor_is_local_and_complete(self):
        self._run_js('thresholdRecolor.test.js')

    def test_bus_coexistence_with_annotations(self):
        """Carga los dos bridges reales a la vez: es la única forma de comprobar que ninguno se
        come los eventos del otro en el bus del core (T058)."""
        self._run_js('busCoexistence.test.js')
