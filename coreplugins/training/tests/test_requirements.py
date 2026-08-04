"""El gate de dependencias del Principio IV.

Este módulo existe por un fallo concreto y silencioso, medido antes de escribirlo:

    ValueError: numpy.dtype size changed, may indicate binary incompatibility.
                Expected 96 from C header, got 88 from PyObject

`app/plugins/plugin_base.py:44` instala el `requirements.txt` del plugin con
`pip install -U --target <site-packages>` **sin `--no-deps`**, y `python_imports()` antepone ese
directorio a `sys.path`. `scikit-image` pide `numpy>=1.23`, así que sin pines `pip` deja ahí un
numpy 2.x que **tapa** al de la imagen — y `rasterio`, compilado contra el de la imagen, deja de
importarse. El síntoma aparece lejos de la causa: en una exportación, dentro del worker, sobre un
plugin «que no se ha tocado».

Lo que este módulo afirma, y por qué cada afirmación no se puede quitar:

1. `requirements.txt` **pinea** numpy y scipy. Sin pin no hay garantía ninguna.
2. Los pines **coinciden con las versiones de la imagen**. Es el gate de verdad: el día que un merge
   de upstream suba numpy, esto se pone rojo aquí, en un test de dos segundos, en vez de reventar en
   producción. No se salta nunca — solo lee ficheros.
3. Si el plugin ya tiene sus paquetes instalados, lo instalado coincide con lo pineado y
   `rasterio` + `skimage` se importan **con el directorio del plugin al frente**, que es el orden
   que impone `python_imports()`.

La comprobación (3) va en un **subproceso** a propósito. Dentro del proceso de test numpy ya está
importado, así que un `sys.path.insert` no cargaría el del plugin: el test pasaría sin probar nada.
"""

import json
import os
import re
import subprocess
import sys

from django.test import SimpleTestCase

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIREMENTS = os.path.join(PLUGIN_DIR, 'requirements.txt')

# Los paquetes cuya versión debe coincidir con la de la imagen. Son los que traen extensiones en C
# que `rasterio` comparte: si divergen, la ABI se rompe.
ABI_CRITICAL = ('numpy', 'scipy')

_PIN = re.compile(r'^([A-Za-z0-9_.\-]+)\s*==\s*([0-9][^\s#]*)')


def parse_pins(path):
    """`{paquete: versión}` de las líneas `nombre==versión` del requirements."""
    pins = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            match = _PIN.match(line)
            if match:
                pins[match.group(1).lower().replace('_', '-')] = match.group(2)
    return pins


def installed_version(site_packages, package):
    """Versión de `package` dentro de `site_packages`, leída del `.dist-info`, o `None`.

    Se lee del nombre del directorio en vez de importando: importar traería el módulo ya cargado
    del intérprete y devolvería la versión equivocada sin dar ningún síntoma.
    """
    if not os.path.isdir(site_packages):
        return None
    prefix = package.replace('-', '_').lower() + '-'
    for entry in os.listdir(site_packages):
        name = entry.lower()
        if name.startswith(prefix) and name.endswith('.dist-info'):
            return entry[len(prefix):-len('.dist-info')]
    return None


class RequirementsPinsTest(SimpleTestCase):
    """Lo que se puede afirmar leyendo ficheros. Nunca se salta."""

    def test_requirements_file_exists(self):
        self.assertTrue(os.path.isfile(REQUIREMENTS),
                        'El plugin declara `scikit-image`; su requirements.txt no puede faltar.')

    def test_the_file_has_no_comments(self):
        """`requirements.txt` **no admite comentarios**, por raro que suene.

        `app/plugins/pyutils.py:parse_requirements` no filtra las líneas que empiezan por `#`: toma
        toda línea no vacía como nombre de paquete. Con una sola línea de comentario,
        `requirements_installed()` devuelve `False` para siempre, y eso tiene dos consecuencias que
        no se parecen a un error:

        1. El framework escribe `WARNING Failed to install requirements.txt` **aunque pip haya
           terminado bien**, así que el aviso deja de significar nada.
        2. Nunca se escribe el `install_md5`, así que el plugin reinstala 246 MB en **cada
           arranque**: unos 8 s medidos, cada vez, para nada.

        Medido antes de quitar los comentarios de este fichero. La explicación de por qué numpy y
        scipy van pineados vive en `README.md`, donde sí se puede escribir.
        """
        with open(REQUIREMENTS) as f:
            offending = [line.rstrip('\n') for line in f
                         if line.strip() and not _PIN.match(line.strip())]
        self.assertEqual(
            offending, [],
            'requirements.txt solo admite líneas `paquete==versión`. Estas no lo son y hacen que '
            'el plugin reinstale sus dependencias en cada arranque: {}'.format(offending))

    def test_abi_critical_packages_are_pinned(self):
        pins = parse_pins(REQUIREMENTS)
        for package in ABI_CRITICAL:
            self.assertIn(
                package, pins,
                '{} debe ir pineado en requirements.txt. Sin pin, pip instala la última al lado '
                'de la de la imagen y rompe rasterio (ver la cabecera de este módulo).'.format(
                    package))

    def test_pins_match_the_image(self):
        """El gate. Rojo aquí = un merge de upstream movió numpy o scipy.

        Arreglo: poner en `requirements.txt` las versiones que reporta este mismo test.
        """
        import numpy
        import scipy

        image = {'numpy': numpy.__version__, 'scipy': scipy.__version__}
        pins = parse_pins(REQUIREMENTS)

        for package, version in image.items():
            self.assertEqual(
                pins.get(package), version,
                'requirements.txt pinea {package}=={pinned} pero la imagen trae {version}. '
                'Actualizar el pin a {version}: si no, pip instalará una copia distinta que '
                'tapará a la de la imagen y rasterio dejará de importarse.'.format(
                    package=package, pinned=pins.get(package), version=version))


class InstalledPackagesTest(SimpleTestCase):
    """Lo que solo se puede afirmar si los paquetes ya están instalados."""

    def setUp(self):
        super().setUp()
        from coreplugins.training import superpixels

        # Se resuelve con la misma función que usa el plugin en producción, no con
        # `get_plugins_persistent_path` a secas: bajo tests eso apunta a `app/media_test`, donde no
        # hay nada instalado, y el gate se saltaría siempre sin que nadie se enterara.
        self.site_packages = superpixels.resolve_site_packages()
        if self.site_packages is None:
            self.skipTest(
                'El plugin todavía no ha instalado su requirements.txt en ninguno de {}. Ocurre '
                'en un arranque limpio, antes de que `check_requirements()` corra.'.format(
                    superpixels.candidate_site_packages()))

    def test_installed_versions_match_the_pins(self):
        pins = parse_pins(REQUIREMENTS)
        for package in ABI_CRITICAL:
            found = installed_version(self.site_packages, package)
            if found is None:
                self.skipTest('{} no está instalado en el site-packages del plugin.'.format(
                    package))
            self.assertEqual(found, pins.get(package),
                             'Instalado {}=={} pero pineado {}. El site-packages del plugin quedó '
                             'obsoleto: borrarlo y dejar que el framework lo reinstale.'.format(
                                 package, found, pins.get(package)))

    def test_rasterio_survives_the_plugin_path(self):
        """`rasterio` y `skimage` conviven con el directorio del plugin al frente de `sys.path`.

        En subproceso: dentro de este proceso numpy ya está importado y un `insert` no cargaría el
        del plugin, así que el test pasaría sin ejercitar nada.
        """
        script = (
            'import sys, json\n'
            'sys.path.insert(0, {path!r})\n'
            'import numpy, rasterio, rasterio.features, rasterio.warp\n'
            'from skimage.segmentation import slic\n'
            'print(json.dumps({{"numpy": numpy.__version__, "numpy_file": numpy.__file__,\n'
            '                   "rasterio": rasterio.__version__}}))\n'
        ).format(path=self.site_packages)

        result = subprocess.run([sys.executable, '-c', script],
                                capture_output=True, text=True, timeout=120)

        self.assertEqual(
            result.returncode, 0,
            'Importar rasterio con el site-packages del plugin al frente falló. Es exactamente el '
            'fallo que los pines existen para evitar.\n--- stderr ---\n{}'.format(result.stderr))

        payload = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(payload['numpy'].startswith(parse_pins(REQUIREMENTS)['numpy']),
                        'El numpy que se cargó no es el pineado: {}'.format(payload))

    def test_superpixels_imports_skimage(self):
        """El plugin alcanza `skimage` por su cuenta, sin que nadie abra `python_imports()`."""
        from coreplugins.training import superpixels

        self.assertIsNotNone(superpixels.slic_function(),
                             'superpixels.slic_function() debe resolver `skimage.segmentation.slic` '
                             'añadiendo el site-packages del plugin a sys.path.')
