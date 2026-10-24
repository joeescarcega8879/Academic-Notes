from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import BatchFile


@receiver(post_delete, sender=BatchFile)
def delete_batch_file(sender, instance, **kwargs):
    """Al quitar un archivo del lote (o su actividad o grupo) se borra del almacenamiento."""
    if instance.file:
        instance.file.storage.delete(instance.file.name)
