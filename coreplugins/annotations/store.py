"""Persistencia de polilíneas por tarea (`data-model.md`).

Un único documento JSON por tarea en el ``GlobalDataStore`` del framework (modelo
``PluginDatum``), con ``user=None`` para que el documento sea compartido por todos los
usuarios con acceso a la tarea (FR-025). La clave es ``task_<pk>``.
"""

import zlib
from contextlib import contextmanager

from django.db import connection, transaction

from app.plugins.data_store import GlobalDataStore

NAMESPACE = 'annotations'
SCHEMA_VERSION = 1

# Primera clave del advisory lock: identifica al plugin dentro del espacio de locks, que es
# global a la base de datos. 'anno' en ASCII, ya dentro del rango de un int4 con signo.
LOCK_NAMESPACE = 0x616E6E6F


def _ds():
    return GlobalDataStore(NAMESPACE)


def _key(task_id):
    return "task_{}".format(task_id)


def _lock_keys(task_id):
    """Par de int4 para `pg_advisory_xact_lock`: el plugin y el documento de esta tarea."""
    checksum = zlib.crc32(_key(task_id).encode('utf-8'))
    if checksum >= 2 ** 31:
        checksum -= 2 ** 32  # crc32 es sin signo; el lock toma int4 con signo
    return LOCK_NAMESPACE, checksum


@contextmanager
def document_lock(task_id):
    """Serializa el ciclo leer-modificar-guardar del documento de una tarea.

    ``PluginDatum`` guarda el documento entero en una sola fila y ``GlobalDataStore`` no ofrece
    ningún bloqueo, así que dos peticiones simultáneas sobre la misma tarea leían la misma
    versión y la última en guardar borraba el trabajo de la otra (una polilínea creada por otro
    usuario, o el PATCH que dispara cada arrastre de vértice). El documento es compartido por
    todos los usuarios con acceso a la tarea (FR-025), así que la carrera es el caso normal, no
    el excepcional.

    Se usa un advisory lock y no ``select_for_update`` porque la fila puede no existir todavía
    (primera polilínea de la tarea) y ``PluginDatum`` no tiene índice único por clave: no hay
    fila que bloquear ni restricción que arbitre la creación simultánea. El lock se libera solo
    al cerrarse la transacción.
    """
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", _lock_keys(task_id))
        yield


def get_document(task_id):
    """Devuelve el documento ``{version, polylines}`` de la tarea. La ausencia de documento
    equivale a una lista vacía de polilíneas (`data-model.md`)."""
    ds = _ds()
    key = _key(task_id)
    if not ds.has_key(key):
        return {'version': SCHEMA_VERSION, 'polylines': []}
    doc = ds.get_json(key, None)
    if not doc:
        return {'version': SCHEMA_VERSION, 'polylines': []}
    doc.setdefault('version', SCHEMA_VERSION)
    doc.setdefault('polylines', [])
    return doc


def set_document(task_id, document):
    document = dict(document)
    document.setdefault('version', SCHEMA_VERSION)
    document.setdefault('polylines', [])
    _ds().set_json(_key(task_id), document)
    return document


def del_document(task_id):
    """Elimina el documento entero de la tarea (borrado en cascada, FR-027)."""
    return _ds().del_key(_key(task_id))


def list_polylines(task_id):
    return get_document(task_id)['polylines']


def get_polyline(task_id, polyline_id):
    for p in list_polylines(task_id):
        if p.get('id') == polyline_id:
            return p
    return None


def upsert_polyline(task_id, polyline):
    """Inserta la polilínea si su ``id`` no existe todavía en la tarea, o la reemplaza
    entera si ya existe. El documento se relee dentro del lock, de modo que la escritura parte
    siempre de la última versión guardada."""
    with document_lock(task_id):
        doc = get_document(task_id)
        polylines = doc['polylines']
        for i, p in enumerate(polylines):
            if p.get('id') == polyline['id']:
                polylines[i] = polyline
                break
        else:
            polylines.append(polyline)
        set_document(task_id, doc)
    return polyline


def remove_polyline(task_id, polyline_id):
    with document_lock(task_id):
        doc = get_document(task_id)
        polylines = doc['polylines']
        new_polylines = [p for p in polylines if p.get('id') != polyline_id]
        if len(new_polylines) == len(polylines):
            return False
        doc['polylines'] = new_polylines
        set_document(task_id, doc)
    return True
