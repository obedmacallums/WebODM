"""Persistencia del estado de realineación por tarea (D6 de research.md).

Se usa el ``GlobalDataStore`` del framework (modelo ``PluginDatum``) con ``user=None`` para que
el estado sea compartido por todos los usuarios con acceso a la tarea (FR-012). La clave es
``task_<pk>`` y el valor es el documento JSON descrito en data-model.md (entidad TaskRealignment).
"""

from app.plugins.data_store import GlobalDataStore

NAMESPACE = 'realign'
SCHEMA_VERSION = 1


def _ds():
    return GlobalDataStore(NAMESPACE)


def _key(task_id):
    return "task_{}".format(task_id)


def get_state(task_id):
    """Devuelve el TaskRealignment persistido o ``None`` si no existe."""
    ds = _ds()
    key = _key(task_id)
    if not ds.has_key(key):
        return None
    return ds.get_json(key, None)


def set_state(task_id, state):
    """Guarda (crea/actualiza) el TaskRealignment de la tarea."""
    state = dict(state)
    state.setdefault('version', SCHEMA_VERSION)
    _ds().set_json(_key(task_id), state)
    return state


def del_state(task_id):
    """Elimina el TaskRealignment de la tarea. Devuelve True si existía."""
    return _ds().del_key(_key(task_id))


def get_pointcloud_state(task_id):
    """Devuelve el subdocumento ``pointcloud`` del TaskRealignment, o ``None`` si no existe
    (data-model.md: ausencia de la clave equivale a ``status: "absent"``, retrocompatible con
    documentos persistidos antes de esta capacidad).
    """
    state = get_state(task_id)
    if state is None:
        return None
    return state.get('pointcloud')


def set_pointcloud_state(task_id, pointcloud_state):
    """Actualiza (crea/reemplaza) el subdocumento ``pointcloud`` del TaskRealignment.

    Lee y reescribe el documento completo (mismo patrón de lectura-modificación-escritura que
    ``corrections.py: run_correction_pipeline`` usa para ``corrected_paths`` — una edición
    concurrente de puntos entre la lectura y la escritura podría perderse; es el mismo riesgo ya
    aceptado en el resto del plugin, no una limitación nueva de esta feature).
    """
    state = get_state(task_id) or {}
    state['pointcloud'] = pointcloud_state
    return set_state(task_id, state)


def del_pointcloud_state(task_id):
    """Elimina el subdocumento ``pointcloud`` del TaskRealignment. Devuelve True si existía."""
    state = get_state(task_id)
    if state is None or 'pointcloud' not in state:
        return False
    del state['pointcloud']
    set_state(task_id, state)
    return True
