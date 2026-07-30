"""Persistencia de los análisis de una tarea (`data-model.md` §1, `research.md` D8, D10).

Dos almacenes, y la separación no es cosmética: `PluginDatum` guarda el documento entero en una
sola fila de texto, así que meter ahí los tramos convertiría cada actualización de progreso en una
reescritura de megabytes y haría que el `GET` del estado cargara todo el resultado.

| Almacén | Qué guarda | Dónde |
|---|---|---|
| Índice | metadatos de cada análisis y el candado de ejecución | `GlobalDataStore('road')`, clave `task_<pk>` |
| Tramos | la colección de tramos de un análisis terminado | `get_plugins_persistent_path('road', 'task_<pk>')/<analysis_id>.json` |

El documento es compartido por todos los usuarios con acceso a la tarea, así que el ciclo
leer-modificar-guardar se serializa con un advisory lock de PostgreSQL, igual que en
`annotations.store`.
"""

import json
import os
import zlib
from contextlib import contextmanager

from django.db import connection, transaction

from app.plugins.data_store import GlobalDataStore
from app.plugins.functions import get_plugins_persistent_path

NAMESPACE = 'road'
SCHEMA_VERSION = 1

# Primera clave del advisory lock: identifica al plugin dentro del espacio de locks, que es global
# a la base de datos. 'road' en ASCII, ya dentro del rango de un int4 con signo. Debe diferir del
# 0x616E6E6F de `annotations` o ambos plugins se bloquearían entre sí sin motivo.
LOCK_NAMESPACE = 0x726F6164


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

    Se usa un advisory lock y no `select_for_update` porque la fila puede no existir todavía
    (primer análisis de la tarea) y `PluginDatum` no tiene índice único por clave: no hay fila que
    bloquear ni restricción que arbitre la creación simultánea. El lock se libera solo al cerrarse
    la transacción.

    Aquí importa más que en `annotations`: el candado de ejecución (D10) se comprueba y se escribe
    dentro de este mismo lock, y sin eso dos peticiones simultáneas podrían ver ambas la tarea
    libre y lanzar dos análisis.
    """
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", _lock_keys(task_id))
        yield


# --- Documento de índice -----------------------------------------------------------------

def get_document(task_id):
    """Devuelve `{version, analyses, running?}`. La ausencia de documento equivale a una lista
    vacía de análisis (`data-model.md` §1)."""
    ds = _ds()
    key = _key(task_id)
    if not ds.has_key(key):
        return {'version': SCHEMA_VERSION, 'analyses': []}
    doc = ds.get_json(key, None)
    if not doc:
        return {'version': SCHEMA_VERSION, 'analyses': []}
    doc.setdefault('version', SCHEMA_VERSION)
    doc.setdefault('analyses', [])
    return doc


def set_document(task_id, document):
    document = dict(document)
    document.setdefault('version', SCHEMA_VERSION)
    document.setdefault('analyses', [])
    _ds().set_json(_key(task_id), document)
    return document


def del_document(task_id):
    """Elimina el documento entero de la tarea (borrado en cascada)."""
    return _ds().del_key(_key(task_id))


def list_analyses(task_id):
    return get_document(task_id)['analyses']


def get_thresholds(document):
    """Umbrales de color de la **tarea**, `{'color': [...] | None, 'width': [...] | None}`.

    Viven en el documento y no en cada análisis porque son una preferencia de lectura del usuario,
    no una propiedad de un camino: quien mueve el deslizador quiere ver todos sus caminos con el
    mismo criterio, y tener que repetir el ajuste en cada uno era trabajo inventado.

    Compatibilidad: un documento anterior a este cambio no tiene umbrales propios, así que se
    siembran con los del análisis más reciente que los llevara. Sin eso, el primer usuario que
    abriera el panel tras actualizar vería sus ajustes revertidos a los de fábrica.
    """
    stored = document.get('thresholds') or {}
    color = stored.get('color')
    if not color:
        color = _latest_analysis_value(document, 'color_thresholds')
    return {'color': color, 'width': stored.get('width')}


def _latest_analysis_value(document, key):
    """Valor de `key` en el análisis más reciente que lo tenga, por `updated_at`."""
    best, best_stamp = None, ''
    for analysis in document.get('analyses') or []:
        value = analysis.get(key)
        if not value:
            continue
        stamp = analysis.get('updated_at') or analysis.get('created_at') or ''
        if best is None or stamp >= best_stamp:
            best, best_stamp = value, stamp
    return best


def set_thresholds(task_id, changes):
    """Fija los umbrales de la tarea. `changes` es `{'color': [...]}`, `{'width': [...]}` o ambos."""
    with document_lock(task_id):
        doc = get_document(task_id)
        thresholds = dict(doc.get('thresholds') or {})
        thresholds.update(changes)
        doc['thresholds'] = thresholds
        set_document(task_id, doc)
    return thresholds


def get_analysis(task_id, analysis_id):
    for a in list_analyses(task_id):
        if a.get('id') == analysis_id:
            return a
    return None


def find_analysis_by_axis(task_id, kind, ref):
    """Localiza el análisis de un eje por su identidad `(kind, ref)` (`data-model.md` §3).

    Es la clave con la que "recalcular pisa": un eje tiene como mucho un análisis en la tarea.
    """
    for a in list_analyses(task_id):
        axis = a.get('axis') or {}
        if axis.get('kind') == kind and axis.get('ref') == ref:
            return a
    return None


def upsert_analysis(task_id, analysis):
    """Inserta el análisis si su `id` no existe todavía, o lo reemplaza entero si ya existe.

    El documento se relee dentro del lock, de modo que la escritura parte siempre de la última
    versión guardada — el worker actualiza progreso mientras el usuario puede estar renombrando.
    """
    with document_lock(task_id):
        doc = get_document(task_id)
        analyses = doc['analyses']
        for i, a in enumerate(analyses):
            if a.get('id') == analysis['id']:
                analyses[i] = analysis
                break
        else:
            analyses.append(analysis)
        set_document(task_id, doc)
    return analysis


def update_analysis(task_id, analysis_id, mutate):
    """Aplica `mutate(analysis)` sobre el análisis **dentro del lock** y guarda el resultado.

    Devuelve el análisis actualizado, o `None` si ya no existe. Es la vía correcta para cambios
    parciales (progreso, estado, umbrales): `get_analysis` + `upsert_analysis` desde fuera del
    lock reintroduce la carrera que el lock existe para evitar.
    """
    with document_lock(task_id):
        doc = get_document(task_id)
        for i, a in enumerate(doc['analyses']):
            if a.get('id') == analysis_id:
                updated = mutate(a)
                if updated is None:
                    updated = a
                doc['analyses'][i] = updated
                set_document(task_id, doc)
                return updated
    return None


def remove_analysis(task_id, analysis_id):
    """Quita el análisis del índice. El archivo de tramos lo borra el llamador."""
    with document_lock(task_id):
        doc = get_document(task_id)
        analyses = doc['analyses']
        remaining = [a for a in analyses if a.get('id') != analysis_id]
        if len(remaining) == len(analyses):
            return False
        doc['analyses'] = remaining
        set_document(task_id, doc)
    return True


# --- Candado de ejecución (D10) ----------------------------------------------------------

def _is_stale_running(running):
    """`True` si el candado quedó huérfano: su tarea de Celery ya terminó (o no se puede
    consultar) pero nadie limpió el bloque.

    Sin esto, un worker que muere sin liberar deja la tarea bloqueada para siempre y la única
    salida es borrar el estado a mano.
    """
    if not running:
        return True
    celery_task_id = running.get('celery_task_id')
    if not celery_task_id:
        # Ventana normal entre tomar el candado y conocer el id de Celery: no es obsoleto.
        return False
    try:
        from worker.tasks import TestSafeAsyncResult
        return bool(TestSafeAsyncResult(celery_task_id).ready())
    except Exception:
        # Sin backend de resultados (CELERY_TASK_ALWAYS_EAGER en tests) no se puede afirmar que
        # siga vivo: se trata como obsoleto para no dejar la tarea inutilizable.
        return True


def get_running(task_id):
    """Candado vigente, o `None` si no hay ninguno o el que hay está obsoleto."""
    running = get_document(task_id).get('running')
    if not running or _is_stale_running(running):
        return None
    return running


def acquire_running(task_id, analysis_id):
    """Toma el candado de ejecución de la tarea. Devuelve `(ok, running_vigente)`.

    Comprobación y escritura ocurren **dentro del mismo `document_lock`**: es lo único que impide
    que dos peticiones simultáneas vean ambas la tarea libre (FR-036, D10).
    """
    with document_lock(task_id):
        doc = get_document(task_id)
        running = doc.get('running')
        if running and not _is_stale_running(running):
            return False, running
        import datetime
        doc['running'] = {
            'analysis_id': analysis_id,
            'celery_task_id': None,
            'started_at': datetime.datetime.utcnow().isoformat() + 'Z',
        }
        set_document(task_id, doc)
        return True, doc['running']


def attach_celery_task(task_id, analysis_id, celery_task_id):
    """Anota el id de Celery en el candado, si sigue siendo el de este análisis.

    Bajo `CELERY_TASK_ALWAYS_EAGER` el trabajo ya terminó y liberó el candado cuando volvemos
    aquí: en ese caso no hay nada que anotar y no se debe resucitar el bloque.
    """
    with document_lock(task_id):
        doc = get_document(task_id)
        running = doc.get('running')
        if running and running.get('analysis_id') == analysis_id:
            running['celery_task_id'] = celery_task_id
            set_document(task_id, doc)
            return True
    return False


def release_running(task_id, analysis_id=None):
    """Libera el candado. Con `analysis_id` solo lo suelta si es el suyo, para que un worker
    tardío no borre el candado de un análisis posterior."""
    with document_lock(task_id):
        doc = get_document(task_id)
        running = doc.get('running')
        if not running:
            return False
        if analysis_id is not None and running.get('analysis_id') != analysis_id:
            return False
        doc.pop('running', None)
        set_document(task_id, doc)
    return True


# --- Almacén de tramos -------------------------------------------------------------------

def segments_dir(task_id):
    return get_plugins_persistent_path(NAMESPACE, 'task_{}'.format(task_id))


def segments_path(task_id, analysis_id):
    return os.path.join(segments_dir(task_id), '{}.json'.format(analysis_id))


def write_segments(task_id, analysis_id, payload):
    """Escribe el documento de tramos de forma atómica (`data-model.md` §6).

    Temporal en el mismo directorio y `os.replace`: un worker cancelado a media escritura dejaría
    un JSON truncado que el `GET` no sabría distinguir de un resultado válido.
    """
    directory = segments_dir(task_id)
    os.makedirs(directory, exist_ok=True)
    path = segments_path(task_id, analysis_id)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return path


def read_segments(task_id, analysis_id):
    """Documento de tramos, o `None` si el archivo no está o no es legible (`410 result_missing`)."""
    try:
        with open(segments_path(task_id, analysis_id)) as f:
            return _upgrade_segments(json.load(f))
    except (OSError, ValueError):
        return None


def _upgrade_segments(document):
    """Completa en memoria un documento escrito antes de `006-street-width` (FR-024).

    Los análisis antiguos no traen el origen por lado. Todo borde que exista se interpreta como
    medido —no hubo coherencia que pudiera inferirlo— y nada se escribe en disco: el archivo
    antiguo sigue siendo válido tal cual, sin migración ni cambio de `version`.
    """
    for segment in document.get('segments') or []:
        for side in ('left', 'right'):
            key = '{}_edge_source'.format(side)
            if key not in segment:
                segment[key] = ('measured'
                                if segment.get('offset_{}'.format(side)) is not None else None)
    return document


def delete_segments(task_id, analysis_id):
    for path in (segments_path(task_id, analysis_id), segments_path(task_id, analysis_id) + '.tmp'):
        try:
            os.remove(path)
        except OSError:
            pass


# --- Almacén de máscaras de segmentación (`008` FR-004) ----------------------------------
#
# Hermano del almacén de tramos: mismo directorio, mismo mecanismo del framework
# (`get_plugins_persistent_path`) y mismo ciclo de vida. La constitución exige que los datos
# persistentes de plugins vayan por ahí y **nunca** por rutas ad-hoc del contenedor; antes de `008`
# la máscara solo existía en un temporal de `MEDIA_TMP` que nadie limpiaba ni servía.
#
# Vive en un archivo aparte y no dentro del documento de tramos a propósito: ese documento lo leen
# `AnalysisDetail.get` y también las exportaciones, que no usan la máscara para nada y cargarían
# decenas de KB de polígonos en cada descarga CSV (`research.md` D35).

MASK_SCHEMA_VERSION = 1


def mask_path(task_id, analysis_id):
    return os.path.join(segments_dir(task_id), '{}.mask.json'.format(analysis_id))


def write_mask(task_id, analysis_id, payload):
    """Escribe la máscara de forma atómica, igual que `write_segments` y por la misma razón: un
    worker cancelado a media escritura dejaría un JSON truncado que el `GET` no sabría distinguir
    de un resultado válido."""
    directory = segments_dir(task_id)
    os.makedirs(directory, exist_ok=True)
    path = mask_path(task_id, analysis_id)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return path


def read_mask(task_id, analysis_id):
    """Documento de máscara, o `None` si no está o no es legible.

    `None` aquí **no es una anomalía**: es el estado esperado de los análisis anteriores a `008` y
    de los modos `break`/`surface`. Quien llama debe distinguirlo de una máscara con `features: []`,
    que sí es un resultado —el modelo corrió y no vio calzada— y explica por qué los tramos
    salieron sin borde (`FR-017`).
    """
    try:
        with open(mask_path(task_id, analysis_id)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def delete_mask(task_id, analysis_id):
    for path in (mask_path(task_id, analysis_id), mask_path(task_id, analysis_id) + '.tmp'):
        try:
            os.remove(path)
        except OSError:
            pass


def analysis_has_mask(analysis):
    """Si este análisis tiene máscara guardada, sin tocar el disco (`FR-015`, D37).

    Los análisis escritos antes de `008` no traen el campo. Su ausencia se interpreta como «no hay
    máscara», en memoria y sin reescribir nada — mismo criterio que `_upgrade_segments` aplica a los
    documentos de `005` (`006`/FR-024).
    """
    return bool((analysis or {}).get('has_mask'))


def delete_task_segments(task_id):
    """Borra el directorio de tramos entero (borrado en cascada al eliminarse la tarea)."""
    import shutil
    try:
        shutil.rmtree(segments_dir(task_id))
    except OSError:
        pass
