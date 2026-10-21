from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.courses.signals import course_cloned
from apps.grades.hooks import activity_cloned

from .models import Syllabus
from .services.cloning import clone_syllabus


@receiver(post_delete, sender=Syllabus)
def delete_syllabus_file(sender, instance, **kwargs):
    """Al borrar un temario (o su grupo) se borra su archivo del almacenamiento."""
    if instance.file:
        instance.file.storage.delete(instance.file.name)


@receiver(course_cloned)
def copy_syllabus(sender, source, clone, **kwargs):
    """Al duplicar un grupo se copia su temario con sus semanas (sin fecha de inicio)."""
    clone_syllabus(source, clone)


@receiver(activity_cloned)
def keep_week_link(sender, source, clone, **kwargs):
    """Una actividad copiada queda en la misma semana (por número) del temario copiado."""
    if source.syllabus_week_id is None:
        return
    syllabus = clone_syllabus(source.course, clone.course)
    week = syllabus.weeks.filter(position=source.syllabus_week.position).first() if syllabus is not None else None
    if week is not None:
        type(clone).objects.filter(pk=clone.pk).update(syllabus_week=week)
