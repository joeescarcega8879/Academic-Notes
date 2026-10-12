"""Esquemas de evaluación: plantilla por defecto, asignación de criterios y copia entre grupos."""

from django.core.exceptions import ValidationError
from django.db import transaction

from ..models import Evaluation, EvaluationCriterion, EvaluationPeriod, EvaluationScheme

DEFAULT_PERIOD_NAME = 'Periodo único'

# (nombre, peso, tipo de evaluación que se le asigna solo). Suma 100: nunca una pantalla vacía.
DEFAULT_CRITERIA = [
    ('Exámenes', 40, Evaluation.Type.EXAM),
    ('Tareas', 30, Evaluation.Type.HOMEWORK),
    ('Proyecto', 20, Evaluation.Type.PROJECT),
    ('Quizzes', 10, Evaluation.Type.QUIZ),
]


@transaction.atomic
def create_default_scheme(course):
    """Esquema inicial del grupo: escala 0–10, aprobatorio 6, un periodo y cuatro criterios editables."""
    scheme = EvaluationScheme.objects.create(course=course)
    period = EvaluationPeriod.objects.create(scheme=scheme, name=DEFAULT_PERIOD_NAME, weight=100, position=0)
    for position, (name, weight, evaluation_type) in enumerate(DEFAULT_CRITERIA):
        EvaluationCriterion.objects.create(
            period=period, name=name, weight=weight, default_type=evaluation_type, position=position,
        )
    return scheme


def ensure_scheme(course):
    """El esquema del grupo; si por alguna razón no tiene, se le crea el de plantilla."""
    try:
        return course.scheme
    except EvaluationScheme.DoesNotExist:
        return create_default_scheme(course)


def default_criterion(course, evaluation_type):
    """Criterio al que va una evaluación nueva: el del mismo tipo o, si no hay, el primero del esquema."""
    criteria = list(ensure_scheme(course).criteria())
    if not criteria:
        raise ValidationError('El esquema de evaluación del grupo no tiene criterios.')
    return next((c for c in criteria if c.default_type == evaluation_type), criteria[0])


@transaction.atomic
def copy_scheme(source, target):
    """Reemplaza el esquema de ``target`` por una copia del de ``source``.

    Devuelve ``{id del criterio origen: criterio nuevo}`` para reasignar las evaluaciones copiadas.
    """
    origin = ensure_scheme(source)
    EvaluationScheme.objects.filter(course=target).delete()
    scheme = EvaluationScheme.objects.create(
        course=target, scale_max=origin.scale_max, pass_mark=origin.pass_mark, rounding_decimals=origin.rounding_decimals,
    )
    mapping = {}
    for period in origin.periods.all():
        new_period = EvaluationPeriod.objects.create(
            scheme=scheme, name=period.name, weight=period.weight, position=period.position,
        )
        for criterion in period.criteria.all():
            mapping[criterion.pk] = EvaluationCriterion.objects.create(
                period=new_period, name=criterion.name, weight=criterion.weight,
                default_type=criterion.default_type, position=criterion.position,
            )
    return mapping
