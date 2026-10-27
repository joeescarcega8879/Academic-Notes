"""Calificar a un equipo con la rúbrica: la misma calificación para cada integrante."""

from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.grades.models import Grade
from apps.rubrics.services.grading import grade_with_rubric

from .teams import members_of, require_teamwork


@dataclass
class TeamGradeResult:
    graded: list = field(default_factory=list)
    kept: list = field(default_factory=list)  # integrantes con un ajuste a mano que no se tocó


def adjusted_members(activity, team):
    """Los integrantes cuya calificación el docente cambió a mano (``Grade.Source.MANUAL``)."""
    manual = set(
        Grade.objects.filter(activity=activity, source=Grade.Source.MANUAL, student__team_memberships__team=team)
        .values_list('student_id', flat=True)
    )
    return [student for student in members_of(team) if student.pk in manual]


@transaction.atomic
def grade_team(activity, team, *, choices, comments=None, feedback='', by=None, waive_penalty=False, replace_adjusted=False):
    """Califica a todo el equipo. Quien tiene un ajuste a mano lo conserva, salvo ``replace_adjusted``.

    Todo o nada: si falla la calificación de un integrante (un nivel sin elegir, por ejemplo) no se guarda ninguna.
    """
    require_teamwork(activity)
    members = members_of(team)
    if not members:
        raise ValidationError(f'«{team}» no tiene integrantes en el grupo.')
    keep = set() if replace_adjusted else {student.pk for student in adjusted_members(activity, team)}
    result = TeamGradeResult()
    for student in members:
        if student.pk in keep:
            result.kept.append(student)
            continue
        grade_with_rubric(
            activity, student, choices=choices, comments=comments, feedback=feedback, by=by, waive_penalty=waive_penalty,
        )
        result.graded.append(student)
    return result
