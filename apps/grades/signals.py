from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.courses.models import Course
from apps.courses.signals import course_cloned

from .services.schemes import copy_scheme, create_default_scheme


@receiver(post_save, sender=Course)
def create_scheme_for_new_course(sender, instance, created, raw=False, **kwargs):
    """Todo grupo nuevo nace con el esquema de plantilla: nunca una pantalla vacía."""
    if created and not raw:
        create_default_scheme(instance)


@receiver(course_cloned)
def copy_course_content(sender, source, clone, **kwargs):
    """Al duplicar un grupo se copian su esquema y sus evaluaciones (sin fechas ni calificaciones)."""
    criteria = copy_scheme(source, clone)
    for evaluation in source.evaluations.all():
        clone.evaluations.create(
            title=evaluation.title, description=evaluation.description, type=evaluation.type,
            max_score=evaluation.max_score, weight=evaluation.weight, date=None,
            criterion=criteria[evaluation.criterion_id],
        )
