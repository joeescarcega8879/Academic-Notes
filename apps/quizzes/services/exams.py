"""Examen en línea: el motor del quiz con reglas más estrictas, que el docente enciende examen por examen.

Un examen sigue siendo una actividad de tipo ``exam`` que se califica a mano en la libreta. Al aplicarlo en línea
se le crea una ``QuizConfig`` (la misma de los quizzes): ventana de apertura y cierre, tiempo medido por el servidor,
intentos y orden aleatorio. Sin esa configuración el examen es el de siempre, así que los que ya existen no cambian.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.grades.models import Activity

from ..models import QuizConfig

# Un examen nace más cerrado que un quiz: un intento, orden distinto para cada alumno y respuestas hasta que cierre.
EXAM_DEFAULTS = {
    'attempts_allowed': 1,
    'shuffle_questions': True,
    'shuffle_choices': True,
    'feedback_mode': QuizConfig.Feedback.AFTER_CLOSE,
}


def uses_quiz_engine(activity):
    """El quiz siempre; el examen solo si el docente lo aplica en línea."""
    if activity.type == Activity.Type.QUIZ:
        return True
    return activity.type == Activity.Type.EXAM and QuizConfig.objects.filter(activity_id=activity.pk).exists()


def noun(activity):
    """«quiz» o «examen», para los mensajes que comparten ambos."""
    return activity.get_type_display().lower()


@transaction.atomic
def enable_online(activity):
    """Aplica el examen en línea creando su configuración. Si ya lo estaba, no hace nada."""
    if activity.type != Activity.Type.EXAM:
        raise ValidationError('Solo un examen se puede aplicar en línea.')
    activity.course.ensure_editable()
    existing = QuizConfig.objects.filter(activity=activity).first()
    if existing is not None:
        return existing
    if activity.published:
        # Publicado y sin preguntas, los alumnos verían un examen vacío y la libreta dejaría de coincidir.
        raise ValidationError('Pasa el examen a borrador antes de aplicarlo en línea; lo publicas cuando tenga sus preguntas.')
    return QuizConfig.objects.create(activity=activity, **EXAM_DEFAULTS)


@transaction.atomic
def disable_online(activity):
    """Vuelve el examen a calificarse a mano, borrando sus preguntas. No se puede si alguien ya lo presentó."""
    activity.course.ensure_editable()
    config = QuizConfig.objects.filter(activity=activity, activity__type=Activity.Type.EXAM).first()
    if config is None:
        return
    if config.is_locked:
        raise ValidationError('Este examen ya tiene intentos de alumnos: no se puede quitar lo que aplicaron en línea.')
    if activity.published:
        raise ValidationError('Pasa el examen a borrador antes de dejar de aplicarlo en línea.')
    config.delete()
