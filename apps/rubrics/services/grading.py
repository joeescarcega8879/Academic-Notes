"""Calificar con rúbrica: el docente elige un nivel por criterio y la calificación sale de sumar sus puntos."""

from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.grades.models import Grade
from apps.grades.services.gradebook import grade_activity

from ..models import RubricScore

COMMENT_MAX = 500


def scaled_score(version, points, max_score):
    """Los puntos de la rúbrica llevados a la escala de la actividad (17 de 20 sobre 10 son 8.5), a 2 decimales."""
    if not version.max_points:
        return 0.0
    value = Decimal(points) / version.max_points * Decimal(str(max_score))
    return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def criteria_of(version):
    return list(version.criteria.prefetch_related('levels'))


@transaction.atomic
def grade_with_rubric(activity, student, *, choices, comments=None, feedback='', by=None, waive_penalty=False):
    """Califica a ``student`` con la rúbrica de ``activity``.

    ``choices`` es ``{id del criterio: id del nivel}`` y debe cubrir todos los criterios; ``comments`` es
    ``{id del criterio: texto}`` (opcional). Devuelve la ``Grade``. Lanza ``ValidationError`` con un mensaje claro.
    """
    version = activity.rubric_version
    if version is None:
        raise ValidationError('Esta actividad no se califica con rúbrica.')
    comments = comments or {}
    criteria = criteria_of(version)

    picked, total = [], Decimal(0)
    for criterion in criteria:
        level_id = choices.get(criterion.pk)
        level = next((lvl for lvl in criterion.levels.all() if lvl.pk == level_id), None)
        if level is None:
            raise ValidationError(f'Elige un nivel en «{criterion.name}».')
        comment = comments.get(criterion.pk, '').strip()
        if len(comment) > COMMENT_MAX:
            raise ValidationError(f'El comentario de «{criterion.name}» no puede pasar de {COMMENT_MAX} caracteres.')
        picked.append((criterion, level, comment))
        total += level.points

    grade = grade_activity(
        activity, student, score=scaled_score(version, total, activity.max_score), feedback=feedback, by=by,
        waive_penalty=waive_penalty, source=Grade.Source.RUBRIC,
    )
    grade.rubric_scores.all().delete()
    RubricScore.objects.bulk_create([
        RubricScore(
            organization_id=grade.organization_id, grade=grade, criterion=criterion, level=level, points=level.points,
            comment=comment,
        )
        for criterion, level, comment in picked
    ])
    return grade


def rubric_points(grade):
    """Lo que sumó la rúbrica de una calificación (None si no se calificó con ella)."""
    scores = list(grade.rubric_scores.all())
    return sum((score.points for score in scores), Decimal(0)) if scores else None


def adjusted_by_hand(grade):
    """¿El docente cambió a mano una calificación que salió de la rúbrica? Entonces el detalle ya no explica la nota."""
    return grade.source == Grade.Source.MANUAL and grade.rubric_scores.exists()


def panel_rows(version, grade=None):
    """Filas para mostrar la rúbrica: cada criterio con sus niveles; si hay calificación, marca el elegido y su comentario."""
    scores = {score.criterion_id: score for score in grade.rubric_scores.all()} if grade is not None else {}
    rows = []
    for criterion in criteria_of(version):
        score = scores.get(criterion.pk)
        rows.append({
            'criterion': criterion, 'comment': score.comment if score else '',
            'levels': [{'level': level, 'selected': score is not None and score.level_id == level.pk} for level in criterion.levels.all()],
        })
    return rows
