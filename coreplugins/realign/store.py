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
