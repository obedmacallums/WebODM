"""Suite del plugin `training`, organizada en módulos por área.

Los tests viven en un paquete, lo que obliga a **reexportar las clases desde este `__init__.py`**:
el runner de Django prueba primero `loadTestsFromName('coreplugins.training.tests')` y solo si eso
devuelve 0 tests intenta `discover(start_dir=...)`. La discovery no es una opción aquí porque
`coreplugins/` no tiene `__init__.py` (es un namespace package) y `unittest` revienta con
`TypeError: expected str, bytes or os.PathLike object, not NoneType` al calcular el `top_level_dir`.
Con las clases importadas aquí, el primer camino ya encuentra los tests y el segundo nunca se
intenta.

**Un módulo de test que no se importe aquí sencillamente no se ejecuta, y la suite sigue en verde.**
Pasó en `008`.

Etiqueta de ejecución: `webodm.sh test backend coreplugins.training.tests`.
"""

from .test_plugin import *  # noqa: F401,F403
from .test_store import *   # noqa: F401,F403
from .test_api_datasets import *  # noqa: F401,F403
from .test_api_labels import *    # noqa: F401,F403
from .test_api_exports import *  # noqa: F401,F403
from .test_tiling import *       # noqa: F401,F403
from .test_rasterize import *    # noqa: F401,F403
from .test_export import *       # noqa: F401,F403
from .test_frontend import *      # noqa: F401,F403
