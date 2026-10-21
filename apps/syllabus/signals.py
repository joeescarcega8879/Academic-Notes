from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Syllabus


@receiver(post_delete, sender=Syllabus)
def delete_syllabus_file(sender, instance, **kwargs):
    """Al borrar un temario (o su grupo) se borra su archivo del almacenamiento."""
    if instance.file:
        instance.file.storage.delete(instance.file.name)
