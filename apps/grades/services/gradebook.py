"""Calificar a un alumno: valida, aplica la penalización por entrega tardía y deja constancia de quién lo hizo."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.courses.models import Enrollment

from ..models import Grade, Submission


def late_penalty_for(activity, student):
    """Penalización (en %) que corresponde a la entrega del alumno: 0 si no hay entrega o llegó a tiempo."""
    submission = Submission.objects.filter(activity=activity, student=student).first()
    if submission is not None and submission.is_late and activity.allow_late:
        return Decimal(str(activity.late_penalty))
    return Decimal(0)


@transaction.atomic
def grade_activity(activity, student, *, score, feedback='', by=None, waive_penalty=False):
    """Crea o actualiza la calificación de ``student`` en ``activity``.

    ``score`` es lo que escribe el docente (sobre ``activity.max_score``). Si la entrega fue tardía se le
    aplica la penalización de la actividad, salvo que se ``waive_penalty``. ``by`` es quien califica y queda
    en la bitácora. Lanza ``ValidationError`` con un mensaje para el docente.
    """
    activity.course.ensure_editable()
    if score is None or score < 0:
        raise ValidationError('La calificación no puede ser negativa.')
    if score > activity.max_score:
        raise ValidationError(f'La calificación no puede superar el máximo de {activity.max_score:g}.')
    if not Enrollment.objects.filter(student=student, course=activity.course).exists():
        raise ValidationError(f'{student} no está inscrito en este grupo.')

    penalty = Decimal(0) if waive_penalty else late_penalty_for(activity, student)
    grade = Grade.objects.filter(activity=activity, student=student).first() or Grade(activity=activity, student=student)
    grade.raw_score = score
    grade.late_penalty = penalty
    grade.feedback = feedback.strip()
    grade._changed_by = by
    grade.save()
    return grade


@transaction.atomic
def remove_grade(grade, *, by=None):
    """Elimina una calificación dejando constancia en la bitácora."""
    grade.activity.course.ensure_editable()
    grade._changed_by = by
    grade.delete()
