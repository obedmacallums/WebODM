"""Persistencia del plugin (`research.md` D2, D3).

Dos almacenes, y la separación no es cosmética:

| Almacén | Qué guarda | Dónde |
|---|---|---|
| Índice | metadatos de cada dataset y sus exportaciones | `GlobalDataStore('training')`, claves `datasets` y `dataset_<id>` |
| Etiquetas | las etiquetas de un par (dataset, tarea) | `get_plugins_persistent_path('training', 'datasets', '<dataset_id>')/<task_id>.json` |

`PluginDatum` guarda el documento entero en una sola fila de texto, y un trazo de pincel largo tiene
miles de vértices: meterlos ahí convertiría cada arrastre en la reescritura de una fila enorme y
haría que listar datasets cargara todas las etiquetas. Separar las etiquetas **por tarea** es
además lo que permite que borrar una tarea no arrastre el resto del dataset.

El ciclo leer-modificar-guardar se serializa con un advisory lock de PostgreSQL, igual que en
`annotations.store` y `road.store` (FR-017).
"""

import json
import os
import shutil
import zlib
from contextlib import contextmanager

from django.db import connection, transaction

from app.plugins.data_store import GlobalDataStore
from app.plugins.functions import get_plugins_persistent_path

from . import models

NAMESPACE = 'training'
SCHEMA_VERSION = models.SCHEMA_VERSION
INDEX_KEY = 'datasets'

# Primera clave del advisory lock: identifica al plugin dentro del espacio de locks, que es global a
# la base de datos. `'trai'` en ASCII, ya dentro del rango de un int4 con signo. Debe diferir del
# 0x726F6164 de `road` y del 0x616E6E6F de `annotations`, o los tres plugins se bloquearían entre sí
# sin tener nada que compartir.
LOCK_NAMESPACE = 0x74726169


def _ds():
    return GlobalDataStore(NAMESPACE)


def _dataset_key(dataset_id):
    return 'dataset_{}'.format(dataset_id)


def _lock_keys(name):
    """Par de int4 para `pg_advisory_xact_lock`: el plugin y el documento."""
    checksum = zlib.crc32(name.encode('utf-8'))
    if checksum >= 2 ** 31:
        checksum -= 2 ** 32  # crc32 es sin signo; el lock toma int4 con signo
    return LOCK_NAMESPACE, checksum


@contextmanager
def document_lock(name):
    """Serializa el ciclo leer-modificar-guardar de un documento.

    Se usa un advisory lock y no `select_for_update` porque la fila puede no existir todavía
    (primera etiqueta del par dataset-tarea) y `PluginDatum` no tiene índice único por clave: no hay
    fila que bloquear ni restricción que arbitre la creación simultánea. El lock se libera solo al
    cerrarse la transacción.

    `name` identifica el documento: `'index'` para la lista de datasets, `dataset_<id>` para uno, y
    `labels_<dataset>_<task>` para las etiquetas de un par. Documentos distintos no se estorban.
    """
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", _lock_keys(name))
        yield


# --- Índice de datasets ------------------------------------------------------------------

def list_dataset_ids():
    ids = _ds().get_json(INDEX_KEY, None)
    return list(ids) if isinstance(ids, list) else []


def list_datasets():
    """Los datasets existentes, en orden de creación. Los identificadores huérfanos se ignoran."""
    datasets = []
    for dataset_id in list_dataset_ids():
        dataset = get_dataset(dataset_id)
        if dataset is not None:
            datasets.append(dataset)
    return datasets


def get_dataset(dataset_id):
    key = _dataset_key(dataset_id)
    ds = _ds()
    if not ds.has_key(key):
        return None
    dataset = ds.get_json(key, None)
    if not dataset:
        return None
    dataset.setdefault('schema_version', 1)
    dataset.setdefault('exports', [])
    # Los campos que el esquema 1 no tenía se completan al leer, no con una migración en disco
    # (`models.with_defaults`). El `schema_version` guardado se deja como está: es el dato que
    # dice con qué esquema se creó, y sobrescribirlo aquí borraría esa información.
    return models.with_defaults(dataset)


def create_dataset(dataset):
    """Guarda el dataset y lo añade al índice, ambas cosas bajo el mismo lock."""
    dataset.setdefault('exports', [])
    with document_lock('index'):
        _ds().set_json(_dataset_key(dataset['id']), dataset)
        ids = list_dataset_ids()
        if dataset['id'] not in ids:
            ids.append(dataset['id'])
            _ds().set_json(INDEX_KEY, ids)
    return dataset


def update_dataset(dataset_id, mutate):
    """Aplica `mutate(dataset)` **dentro del lock** y guarda el resultado.

    Es la vía correcta para cambios parciales: `get_dataset` + guardado desde fuera del lock
    reintroduce la carrera que el lock existe para evitar. Devuelve el dataset actualizado, o
    `None` si ya no existe.
    """
    with document_lock(_dataset_key(dataset_id)):
        dataset = get_dataset(dataset_id)
        if dataset is None:
            return None
        updated = mutate(dataset)
        if updated is None:
            updated = dataset
        _ds().set_json(_dataset_key(dataset_id), updated)
        return updated


def delete_dataset(dataset_id):
    """Borra el dataset, su entrada del índice y todas sus etiquetas y paquetes en disco.

    Los paquetes se van con él a propósito: sin dataset nadie puede volver a listarlos ni
    borrarlos, así que quedarían ocupando disco para siempre.
    """
    with document_lock('index'):
        _ds().del_key(_dataset_key(dataset_id))
        ids = [i for i in list_dataset_ids() if i != dataset_id]
        _ds().set_json(INDEX_KEY, ids)
    shutil.rmtree(dataset_dir(dataset_id), ignore_errors=True)
    shutil.rmtree(exports_dir(dataset_id), ignore_errors=True)
    return True


# --- Etiquetas en fichero ----------------------------------------------------------------

def dataset_dir(dataset_id):
    return get_plugins_persistent_path(NAMESPACE, 'datasets', str(dataset_id))


def exports_dir(dataset_id):
    """Directorio de los paquetes exportados.

    Vive aquí y no en `export.py` porque el store es el dueño de las rutas de persistencia y es
    quien tiene que borrarlas al borrar el dataset: si la ruta la definiera `export`, `store`
    tendría que importarlo y se cerraría un ciclo (`export` ya importa `store`).
    """
    return get_plugins_persistent_path(NAMESPACE, 'exports', str(dataset_id))


def labels_path(dataset_id, task_id):
    return os.path.join(dataset_dir(dataset_id), '{}.json'.format(task_id))


def _labels_lock_name(dataset_id, task_id):
    return 'labels_{}_{}'.format(dataset_id, task_id)


def read_labels(dataset_id, task_id):
    """Documento de etiquetas del par, o uno vacío si todavía no hay ninguna."""
    try:
        with open(labels_path(dataset_id, task_id)) as f:
            document = json.load(f)
    except (OSError, ValueError):
        return {'version': SCHEMA_VERSION, 'labels': [], 'next_order': 0}

    document.setdefault('version', SCHEMA_VERSION)
    document.setdefault('labels', [])
    document.setdefault('next_order', _highest_order(document['labels']) + 1)
    return document


def _highest_order(labels):
    orders = [int(label.get('order', 0)) for label in labels]
    return max(orders) if orders else -1


def write_labels(dataset_id, task_id, document):
    """Escribe el documento de forma atómica.

    Temporal en el mismo directorio y `os.replace`: un proceso interrumpido a media escritura
    dejaría un JSON truncado que la lectura no sabría distinguir de «todavía no hay etiquetas», y
    el usuario perdería el trabajo sin que nada lo avisara.
    """
    directory = dataset_dir(dataset_id)
    os.makedirs(directory, exist_ok=True)
    path = labels_path(dataset_id, task_id)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(document, f)
    os.replace(tmp, path)
    return path


def list_labels(dataset_id, task_id):
    """Etiquetas del par, en orden de composición ascendente (FR-012)."""
    labels = read_labels(dataset_id, task_id)['labels']
    return sorted(labels, key=lambda label: label.get('order', 0))


def add_label(dataset_id, task_id, build):
    """Añade una etiqueta. `build(order)` la construye con el `order` que le toca.

    El `order` se asigna dentro del lock y es monótono creciente: es lo que decide quién gana en
    las zonas solapadas (FR-012), así que dos usuarios dibujando a la vez no pueden recibir el
    mismo valor.
    """
    with document_lock(_labels_lock_name(dataset_id, task_id)):
        document = read_labels(dataset_id, task_id)
        order = document['next_order']
        label = build(order)
        document['labels'].append(label)
        document['next_order'] = order + 1
        write_labels(dataset_id, task_id, document)
        return label


def update_label(dataset_id, task_id, label_id, mutate):
    """Aplica `mutate(label)` dentro del lock. Devuelve la etiqueta, o `None` si no existe."""
    with document_lock(_labels_lock_name(dataset_id, task_id)):
        document = read_labels(dataset_id, task_id)
        for i, label in enumerate(document['labels']):
            if label.get('id') == label_id:
                updated = mutate(label)
                if updated is None:
                    updated = label
                document['labels'][i] = updated
                write_labels(dataset_id, task_id, document)
                return updated
        return None


def delete_label(dataset_id, task_id, label_id):
    with document_lock(_labels_lock_name(dataset_id, task_id)):
        document = read_labels(dataset_id, task_id)
        remaining = [label for label in document['labels'] if label.get('id') != label_id]
        if len(remaining) == len(document['labels']):
            return False
        document['labels'] = remaining
        write_labels(dataset_id, task_id, document)
        return True


def delete_task_labels(dataset_id, task_id):
    """Borra las etiquetas de un par. Se usa al quitar una tarea del dataset."""
    try:
        os.remove(labels_path(dataset_id, task_id))
        return True
    except OSError:
        return False


def count_labels_by_class(dataset_id):
    """`{class_index: cuántas}` sobre todas las tareas del dataset.

    Es lo que responde «cuántas etiquetas se perderán» antes de borrar una clase (FR-006). El
    borrador (`class_index` nulo) se cuenta aparte, bajo la clave `None`, porque no pertenece a
    ninguna clase y borrar una clase no debe llevárselo por delante.
    """
    counts = {}
    directory = dataset_dir(dataset_id)
    if not os.path.isdir(directory):
        return counts
    for filename in os.listdir(directory):
        if not filename.endswith('.json'):
            continue
        task_id = filename[:-len('.json')]
        for label in read_labels(dataset_id, task_id)['labels']:
            index = label.get('class_index')
            counts[index] = counts.get(index, 0) + 1
    return counts


def has_any_label(dataset_id):
    return any(count for count in count_labels_by_class(dataset_id).values())


# --- Exportaciones -----------------------------------------------------------------------
#
# Viven en el documento del dataset y no en un almacén propio: son unas pocas entradas de
# metadatos por dataset, el paquete pesado está en disco, y tenerlas ahí hace que el `GET` del
# dataset ya traiga su estado sin una segunda consulta.

def list_exports(dataset_id):
    dataset = get_dataset(dataset_id)
    return list(dataset.get('exports') or []) if dataset else []


def get_export(dataset_id, export_id):
    for entry in list_exports(dataset_id):
        if entry.get('id') == export_id:
            return entry
    return None


def upsert_export(dataset_id, export):
    """Inserta la exportación o la reemplaza entera si su `id` ya existe."""
    def mutate(dataset):
        exports = dataset.setdefault('exports', [])
        for i, entry in enumerate(exports):
            if entry.get('id') == export['id']:
                exports[i] = export
                break
        else:
            exports.append(export)
        return dataset

    update_dataset(dataset_id, mutate)
    return export


def update_export(dataset_id, export_id, mutate):
    """Aplica `mutate(export)` **dentro del lock** del dataset.

    Es la vía correcta para el progreso: el worker lo actualiza mientras el usuario puede estar
    renombrando el dataset desde la interfaz, y leer-modificar-guardar por fuera perdería uno de
    los dos cambios.
    """
    result = {}

    def mutate_dataset(dataset):
        for i, entry in enumerate(dataset.get('exports') or []):
            if entry.get('id') == export_id:
                updated = mutate(entry)
                if updated is None:
                    updated = entry
                dataset['exports'][i] = updated
                result['export'] = updated
                break
        return dataset

    update_dataset(dataset_id, mutate_dataset)
    return result.get('export')


def remove_export(dataset_id, export_id):
    def mutate(dataset):
        dataset['exports'] = [e for e in (dataset.get('exports') or [])
                              if e.get('id') != export_id]
        return dataset

    update_dataset(dataset_id, mutate)


# --- Estado derivado de las tareas -------------------------------------------------------

def describe_tasks(dataset):
    """Las tareas del dataset con su `available` **calculado**, nunca leído de disco.

    `available` es `false` si la tarea ya no existe o perdió la ortofoto. No se persiste
    deliberadamente (`data-model.md` §Tarea del dataset): un valor guardado quedaría obsoleto en
    cuanto el usuario borrase la tarea desde WebODM, y el dataset informaría de algo falso justo en
    el caso que este campo existe para cubrir.

    Cuando es `false` el dataset sigue abriéndose y la tarea se excluye de la exportación, en vez
    de fallar (US3-4, invariante 5 de `data-model.md`).
    """
    from app.models import Task  # diferido: `store` se importa desde `plugin.py`, que el registro
                                 # de plugins carga antes de que las apps de Django estén listas

    described = []
    referenced = [t['task_id'] for t in dataset.get('tasks') or []]
    found = {}
    if referenced:
        for task in Task.objects.filter(pk__in=referenced).select_related('project'):
            found[str(task.id)] = task

    for entry in dataset.get('tasks') or []:
        task = found.get(entry['task_id'])
        available = task is not None and task.orthophoto_extent is not None
        described.append({
            'task_id': entry['task_id'],
            'project_id': (task.project_id if task is not None else entry.get('project_id')),
            'added_at': entry.get('added_at'),
            'name': task.name if task is not None else None,
            'available': available,
        })
    return described


def available_tasks(dataset):
    return [t for t in describe_tasks(dataset) if t['available']]
