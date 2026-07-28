"""Borrado en cascada al eliminarse la tarea (`data-model.md` §7).

Hay dos almacenes que limpiar, no uno: el documento de índice en el DataStore y el directorio de
tramos en disco. Debe importarse desde `plugin.py` para que el `@receiver` se registre al cargar
el plugin.
"""

from django.dispatch import receiver
from app.plugins import signals as plugin_signals

from . import store


@receiver(plugin_signals.task_removed, dispatch_uid="road_on_task_removed")
def on_task_removed(sender, task_id, **kwargs):
    store.del_document(task_id)
    store.delete_task_segments(task_id)
