"""Suite del plugin `road`, organizada en módulos por área.

A diferencia de `annotations` y `realign`, que usan un `tests.py` plano, aquí los tests viven en un
paquete. Eso obliga a **reexportar las clases desde este `__init__.py`**: el runner de Django
prueba primero `loadTestsFromName('coreplugins.road.tests')` y solo si eso devuelve 0 tests intenta
`discover(start_dir=...)`. La discovery no es una opción aquí porque `coreplugins/` no tiene
`__init__.py` (es un namespace package) y `unittest` revienta con `TypeError: expected str, bytes
or os.PathLike object, not NoneType` al calcular el `top_level_dir`. Con las clases importadas
aquí, el primer camino ya encuentra los tests y el segundo nunca se intenta.

**Un módulo de test que no se importe aquí sencillamente no se ejecuta.**

Etiqueta de ejecución: `webodm.sh test backend coreplugins.road.tests`.
"""

from .test_plugin import *            # noqa: F401,F403
from .test_geometry import *          # noqa: F401,F403
from .test_profile import *           # noqa: F401,F403
from .test_surface import *           # noqa: F401,F403
from .test_coherence import *         # noqa: F401,F403
from .test_api_capabilities import *  # noqa: F401,F403
from .test_axis import *              # noqa: F401,F403
from .test_compute import *           # noqa: F401,F403
from .test_api_analyses import *      # noqa: F401,F403
from .test_params import *            # noqa: F401,F403
from .test_lifecycle import *         # noqa: F401,F403
from .test_upload import *            # noqa: F401,F403
from .test_variants import *          # noqa: F401,F403
from .test_export import *            # noqa: F401,F403
from .test_frontend import *          # noqa: F401,F403
from .test_segmentation_edges import *  # noqa: F401,F403
from .test_segmentation import *      # noqa: F401,F403
from .test_mask_vectorize import *    # noqa: F401,F403
from .test_mask_store import *       # noqa: F401,F403
from .test_api_mask import *         # noqa: F401,F403
