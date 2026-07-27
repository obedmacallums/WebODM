"""Borrado en cascada del documento de polilíneas al eliminarse la tarea (FR-027, `research.md`
D8). Debe importarse desde `plugin.py` para que el `@receiver` se registre al cargar el plugin."""

from django.dispatch import receiver
from app.plugins import signals as plugin_signals

from . import store


@receiver(plugin_signals.task_removed, dispatch_uid="annotations_on_task_removed")
def on_task_removed(sender, task_id, **kwargs):
    store.del_document(task_id)
