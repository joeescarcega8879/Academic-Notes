"""Banco de preguntas: validar y guardar preguntas con sus opciones."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.organizations.models import Membership

from ..models import Choice, Question

MIN_CHOICES = 2
MAX_CHOICES = 8
TRUE_FALSE_LABELS = ('Verdadero', 'Falso')


def validate_choices(choices):
    """Opciones de una pregunta de opción múltiple: ``[(texto, es_correcta), ...]`` -> lista limpia.

    Exige entre 2 y 8 opciones con texto, sin repetidas, y exactamente una correcta. Las opciones en blanco se
    ignoran (los formularios traen filas vacías de sobra).
    """
    cleaned = [(text.strip(), bool(correct)) for text, correct in choices if text and text.strip()]
    if len(cleaned) < MIN_CHOICES:
        raise ValidationError(f'Escribe al menos {MIN_CHOICES} opciones.')
    if len(cleaned) > MAX_CHOICES:
        raise ValidationError(f'Máximo {MAX_CHOICES} opciones.')
    texts = [text.casefold() for text, _ in cleaned]
    if len(set(texts)) != len(texts):
        raise ValidationError('Hay opciones repetidas.')
    if sum(1 for _, correct in cleaned if correct) != 1:
        raise ValidationError('Marca exactamente una respuesta correcta.')
    return cleaned


def can_edit_question(user, membership, question):
    """Edita la autora o el autor, o quien es propietario de la organización."""
    if question.author_id == user.pk:
        return True
    return membership is not None and membership.role == Membership.Role.OWNER


@transaction.atomic
def save_question(
    *, organization, author, kind, text, points, explanation='', topic='',
    choices=None, true_is_correct=None, question=None,
):
    """Crea o actualiza una pregunta con sus opciones.

    Opción múltiple: ``choices`` es ``[(texto, es_correcta), ...]``. Verdadero o falso: ``true_is_correct`` dice si
    la respuesta correcta es "Verdadero". El tipo de una pregunta existente no cambia.
    """
    if question is not None and question.kind != kind:
        raise ValidationError('El tipo de una pregunta no se puede cambiar.')
    if question is not None and question.organization_id != organization.pk:
        raise ValidationError('La pregunta es de otra organización.')

    if kind == Question.Kind.TRUE_FALSE:
        if true_is_correct is None:
            raise ValidationError('Indica si la respuesta correcta es verdadero o falso.')
        rows = [(TRUE_FALSE_LABELS[0], bool(true_is_correct)), (TRUE_FALSE_LABELS[1], not true_is_correct)]
    elif kind == Question.Kind.MULTIPLE_CHOICE:
        rows = validate_choices(choices or [])
    else:
        raise ValidationError('Tipo de pregunta desconocido.')

    if question is None:
        question = Question(organization=organization, author=author, kind=kind)
    question.text = text.strip()
    question.points = points
    question.explanation = explanation.strip()
    question.topic = topic.strip()
    question.full_clean(exclude=['author'])
    question.save()

    question.choices.all().delete()
    for position, (choice_text, correct) in enumerate(rows):
        Choice.objects.create(question=question, text=choice_text, is_correct=correct, position=position)
    return question


@transaction.atomic
def duplicate_question(question, *, by):
    """Copia una pregunta (con sus opciones) a nombre de ``by``, lista para editar."""
    copy = save_question(
        organization=question.organization, author=by, kind=question.kind, text=f'{question.text} (copia)',
        points=question.points, explanation=question.explanation, topic=question.topic,
        choices=[(c.text, c.is_correct) for c in question.choices.all()] if question.kind == Question.Kind.MULTIPLE_CHOICE else None,
        true_is_correct=(
            next(c.is_correct for c in question.choices.all() if c.text == TRUE_FALSE_LABELS[0])
            if question.kind == Question.Kind.TRUE_FALSE else None
        ),
    )
    return copy
