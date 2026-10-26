from django.core.exceptions import ValidationError
from django.dispatch import receiver

from apps.grades.hooks import activity_cloned, activity_publishing
from apps.grades.models import Activity


@receiver(activity_publishing)
def require_rubric_to_publish(sender, activity, **kwargs):
    """Un proyecto no se publica sin su rúbrica: es lo que se le muestra al alumno para saber cómo se le calificará."""
    if not activity.requires_rubric or activity.rubric_version_id is not None:
        return
    if activity.pk and Activity.objects.filter(pk=activity.pk, published=True).exists():
        return  # ya estaba publicado antes de que existieran las rúbricas: guardarlo no se veta, solo publicarlo
    raise ValidationError('Un proyecto necesita una rúbrica antes de publicarse. Elige una al editarlo.')


@receiver(activity_cloned)
def copy_rubric_to_cloned_activity(sender, source, clone, **kwargs):
    """Al duplicar un grupo, sus actividades siguen calificándose con la misma rúbrica."""
    if source.rubric_version_id:
        Activity.objects.filter(pk=clone.pk).update(rubric_version_id=source.rubric_version_id)
        clone.rubric_version_id = source.rubric_version_id
