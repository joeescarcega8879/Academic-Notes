"""Armado de un quiz: agregar, quitar, ordenar y ponderar sus preguntas."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from ..models import QuizChoice, QuizConfig, QuizQuestion


def ensure_editable(quiz):
    """Las preguntas de un quiz solo cambian en un grupo activo y mientras nadie lo haya intentado."""
    quiz.activity.course.ensure_editable()
    if quiz.is_locked:
        raise ValidationError(
            'Este quiz ya tiene intentos: sus preguntas no se pueden cambiar. Duplica el grupo para armar otra versión.'
        )


def totals(quiz):
    """(número de preguntas, total de puntos)."""
    data = quiz.questions.aggregate(total=Sum('points'))
    return quiz.questions.count(), data['total'] or Decimal(0)


def _copy_question(quiz, question, position, *, points=None):
    """Copia una pregunta (del banco o de otro quiz) con sus opciones dentro de ``quiz``."""
    copy = QuizQuestion.objects.create(
        quiz=quiz, source=question if hasattr(question, 'author') else getattr(question, 'source', None),
        kind=question.kind, text=question.text, points=question.points if points is None else points,
        explanation=question.explanation, position=position,
    )
    for index, choice in enumerate(question.choices.all()):
        QuizChoice.objects.create(question=copy, text=choice.text, is_correct=choice.is_correct, position=index)
    return copy


@transaction.atomic
def add_questions(quiz, questions):
    """Agrega copias de preguntas del banco al final del quiz. Las que ya están se omiten; devuelve las nuevas."""
    ensure_editable(quiz)
    already = set(quiz.questions.exclude(source=None).values_list('source_id', flat=True))
    position = quiz.questions.count()
    added = []
    for question in questions:
        if question.organization_id != quiz.organization_id:
            raise ValidationError('La pregunta es de otra organización.')
        if question.course_id is not None and question.course_id != quiz.activity.course_id:
            raise ValidationError('La pregunta es del banco de otro grupo. Duplícala en este grupo para usarla aquí.')
        if question.is_archived:
            raise ValidationError('No se pueden agregar preguntas archivadas.')
        if question.pk in already:
            continue
        added.append(_copy_question(quiz, question, position))
        already.add(question.pk)
        position += 1
    return added


def _renumber(quiz):
    for position, question in enumerate(quiz.questions.order_by('position', 'id')):
        if question.position != position:
            QuizQuestion.objects.filter(pk=question.pk).update(position=position)


@transaction.atomic
def remove_question(question):
    ensure_editable(question.quiz)
    quiz = question.quiz
    question.delete()
    _renumber(quiz)


@transaction.atomic
def move_question(question, direction):
    """Sube (``-1``) o baja (``1``) una pregunta."""
    ensure_editable(question.quiz)
    ordered = list(question.quiz.questions.order_by('position', 'id'))
    index = next(i for i, q in enumerate(ordered) if q.pk == question.pk)
    target = index + direction
    if 0 <= target < len(ordered):
        ordered[index], ordered[target] = ordered[target], ordered[index]
        for position, item in enumerate(ordered):
            QuizQuestion.objects.filter(pk=item.pk).update(position=position)


def set_points(question, points):
    ensure_editable(question.quiz)
    try:
        points = Decimal(str(points).replace(',', '.'))
    except Exception as error:  # noqa: BLE001 - cualquier texto no numérico
        raise ValidationError('Los puntos deben ser un número.') from error
    if not points.is_finite() or points <= 0 or points > 9999:
        raise ValidationError('Los puntos deben ser mayores que 0.')
    question.points = points.quantize(Decimal('0.01'))
    question.full_clean(exclude=['quiz', 'source'])
    question.save(update_fields=['points'])


def sync_activity_points(quiz):
    """Los puntos de la actividad pasan a ser el total de puntos de las preguntas."""
    quiz.activity.course.ensure_editable()
    count, total = totals(quiz)
    if not count:
        raise ValidationError('El quiz todavía no tiene preguntas.')
    quiz.activity.max_score = float(total)
    quiz.activity.save()


@transaction.atomic
def copy_quiz_content(source, target_activity):
    """Copia la configuración y las preguntas de ``source`` al quiz de ``target_activity`` (sin intentos)."""
    target, _ = QuizConfig.objects.get_or_create(activity=target_activity)
    for field in ('attempts_allowed', 'time_limit_minutes', 'shuffle_questions', 'shuffle_choices', 'feedback_mode', 'attempt_policy'):
        setattr(target, field, getattr(source, field))
    target.save()
    target.questions.all().delete()
    for position, question in enumerate(source.questions.prefetch_related('choices')):
        _copy_question(target, question, position)
    return target
