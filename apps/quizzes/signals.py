from django.core.exceptions import ValidationError
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.courses.signals import course_cloned
from apps.grades.hooks import activity_cloned, activity_publishing
from apps.grades.models import Activity
from apps.organizations.limits import PlanLimitError

from .models import QuizConfig
from .services.bank import copy_bank
from .services.builder import copy_quiz_content


@receiver(post_save, sender=Activity)
def ensure_quiz_config(sender, instance, raw=False, **kwargs):
    """Toda actividad de tipo quiz tiene su configuración (con los valores por defecto)."""
    if not raw and instance.type == Activity.Type.QUIZ:
        QuizConfig.objects.get_or_create(activity=instance)


@receiver(activity_publishing)
def require_questions_to_publish(sender, activity, **kwargs):
    """Un quiz sin preguntas no se puede publicar."""
    if activity.type != Activity.Type.QUIZ:
        return
    quiz = QuizConfig.objects.filter(activity_id=activity.pk).first() if activity.pk else None
    if quiz is None or not quiz.questions.exists():
        raise ValidationError('Agrega al menos una pregunta al quiz antes de publicarlo.')


@receiver(activity_cloned)
def copy_quiz_to_cloned_activity(sender, source, clone, **kwargs):
    """Al duplicar un grupo, sus quizzes llevan su configuración y sus preguntas (sin intentos)."""
    if source.type == Activity.Type.QUIZ:
        origin = QuizConfig.objects.filter(activity=source).first()
        if origin is not None:
            copy_quiz_content(origin, clone)


@receiver(course_cloned)
def copy_bank_to_cloned_course(sender, source, clone, **kwargs):
    """Al duplicar un grupo, su banco de preguntas viaja con él. Devuelve un aviso para mostrar al docente.

    Si las preguntas no caben en el plan no se copia ninguna, pero el grupo se duplica igual.
    """
    try:
        copied = copy_bank(source, clone)
    except PlanLimitError as error:
        return f'No se copió el banco de preguntas. {" ".join(error.messages)}'
    if copied:
        return 'Se copió 1 pregunta del banco.' if copied == 1 else f'Se copiaron {copied} preguntas del banco.'
    return None
