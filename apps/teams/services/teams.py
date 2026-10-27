"""Equipos de un proyecto: formarlos, mover alumnos y darle al integrante nuevo la entrega que el equipo ya hizo."""

import random
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.courses.models import Enrollment
from apps.courses.services.text import sort_enrollments, student_sort_key
from apps.grades.models import Grade, Submission

from ..models import Team, TeamMember

MAX_TEAMS = 30
NAME_MAX = 80


def require_teamwork(activity):
    """El grupo debe poder editarse y el proyecto entregarse por equipos."""
    activity.course.ensure_editable()
    if not activity.by_teams:
        raise ValidationError('Este proyecto no se entrega por equipos.')


def team_of(activity, student):
    """El equipo del alumno en este proyecto, o None."""
    member = TeamMember.objects.filter(activity=activity, student=student).select_related('team').first()
    return member.team if member else None


def members_of(team):
    """Los alumnos del equipo que siguen inscritos en el grupo, en orden alfabético."""
    enrolled = set(Enrollment.objects.filter(course_id=team.activity.course_id).values_list('student_id', flat=True))
    students = [member.student for member in team.members.select_related('student__user') if member.student_id in enrolled]
    return sorted(students, key=student_sort_key)


def team_submission(team):
    """La entrega más reciente del equipo (todos los integrantes tienen la misma), o None."""
    return Submission.objects.filter(team=team).order_by('-submitted_at', '-pk').first()


def _next_name(taken):
    """«Equipo N» con el primer N libre; ``taken`` son los nombres en minúsculas."""
    number = 1
    while f'equipo {number}' in taken:
        number += 1
    return f'Equipo {number}'


def _clean_name(name):
    name = ' '.join((name or '').split())
    if len(name) > NAME_MAX:
        raise ValidationError(f'El nombre del equipo no puede pasar de {NAME_MAX} caracteres.')
    return name


def _names(activity, exclude=None):
    teams = activity.teams.all()
    if exclude is not None:
        teams = teams.exclude(pk=exclude.pk)
    return {team.name.lower(): team.name for team in teams}


@transaction.atomic
def create_team(activity, name=''):
    require_teamwork(activity)
    taken = _names(activity)
    if len(taken) >= MAX_TEAMS:
        raise ValidationError(f'Un proyecto no puede tener más de {MAX_TEAMS} equipos.')
    name = _clean_name(name) or _next_name(taken)
    if name.lower() in taken:
        raise ValidationError('Ya hay un equipo con ese nombre.')
    return Team.objects.create(activity=activity, name=name)


@transaction.atomic
def rename_team(team, name):
    require_teamwork(team.activity)
    name = _clean_name(name)
    if not name:
        raise ValidationError('El equipo necesita un nombre.')
    if name.lower() in _names(team.activity, exclude=team):
        raise ValidationError('Ya hay un equipo con ese nombre.')
    team.name = name
    team.save(update_fields=['name'])
    return team


def _give_submission(team, student):
    """Al integrante que llega a un equipo con entrega, se le da la misma entrega."""
    base = team_submission(team)
    if base is None:
        return
    copy = Submission(
        activity=team.activity, student=student, team=team, submitted_by=base.submitted_by, text=base.text,
        link=base.link, original_name=base.original_name, submitted_at=base.submitted_at, is_late=base.is_late,
    )
    if base.file:
        copy.file.name = base.file.name  # el mismo archivo en el almacenamiento: no se copia
    copy.save()


def drop_member(member):
    """Saca al integrante de su equipo y le quita su copia de la entrega (una calificación ya dada no se toca)."""
    Submission.objects.filter(team_id=member.team_id, student_id=member.student_id).delete()
    member.delete()


@transaction.atomic
def assign(activity, student, team):
    """Pone al alumno en ``team`` (o lo deja sin equipo si ``team`` es None). Un alumno con calificación no se mueve."""
    require_teamwork(activity)
    if not Enrollment.objects.filter(student=student, course=activity.course).exists():
        raise ValidationError(f'{student} no está inscrito en este grupo.')
    if team is not None and team.activity_id != activity.pk:
        raise ValidationError('Ese equipo no es de este proyecto.')
    current = TeamMember.objects.filter(activity=activity, student=student).select_related('team').first()
    if (current.team_id if current else None) == (team.pk if team else None):
        return
    if Grade.objects.filter(activity=activity, student=student).exists():
        raise ValidationError(
            f'{student} ya tiene calificación en este proyecto: elimínala antes de cambiarlo de equipo.'
        )
    if current is not None:
        drop_member(current)
    if team is not None:
        TeamMember.objects.create(team=team, student=student)
        _give_submission(team, student)


@transaction.atomic
def delete_team(team):
    """Borra el equipo y deja a sus integrantes sin equipo; si ya entregó o tiene calificaciones, no."""
    require_teamwork(team.activity)
    graded = Grade.objects.filter(activity=team.activity, student__team_memberships__team=team).exists()
    if graded or Submission.objects.filter(team=team).exists():
        raise ValidationError(f'«{team}» ya entregó o tiene calificaciones: no se puede borrar.')
    team.delete()


def unassigned_enrollments(activity):
    """Las inscripciones de los alumnos del grupo que aún no tienen equipo, en orden alfabético."""
    placed = TeamMember.objects.filter(activity=activity).values_list('student_id', flat=True)
    enrollments = activity.course.enrollments.exclude(student_id__in=placed).select_related('student__user')
    return sort_enrollments(enrollments)


@transaction.atomic
def split_randomly(activity, count, *, rng=random):
    """Reparte al azar a los alumnos sin equipo (y sin calificación) en ``count`` equipos nuevos."""
    require_teamwork(activity)
    graded = set(Grade.objects.filter(activity=activity).values_list('student_id', flat=True))
    students = [e.student for e in unassigned_enrollments(activity) if e.student_id not in graded]
    if not 2 <= count <= len(students):
        raise ValidationError(
            f'Hay {len(students)} alumnos sin equipo: elige entre 2 y {len(students)} equipos.'
            if len(students) >= 2 else 'Hacen falta al menos 2 alumnos sin equipo para repartirlos.'
        )
    taken = _names(activity)
    if len(taken) + count > MAX_TEAMS:
        raise ValidationError(f'Un proyecto no puede tener más de {MAX_TEAMS} equipos.')
    rng.shuffle(students)
    names = set(taken)
    teams = []
    for _ in range(count):
        name = _next_name(names)
        names.add(name.lower())
        teams.append(Team.objects.create(activity=activity, name=name))
    for index, student in enumerate(students):
        TeamMember.objects.create(team=teams[index % count], student=student)
    return teams


@transaction.atomic
def copy_teams(source, activity):
    """Copia los equipos (y quién está en cada uno) de otro proyecto por equipos del mismo grupo."""
    require_teamwork(activity)
    if source.pk == activity.pk or source.course_id != activity.course_id or not source.by_teams:
        raise ValidationError('Elige otro proyecto por equipos de este grupo.')
    if activity.teams.exists():
        raise ValidationError('Este proyecto ya tiene equipos: borra los actuales para copiar otros.')
    enrolled = set(activity.course.enrollments.values_list('student_id', flat=True))
    copied = 0
    for team in source.teams.prefetch_related('members'):
        new = Team.objects.create(activity=activity, name=team.name)
        for member in team.members.all():
            if member.student_id in enrolled:
                TeamMember.objects.create(team=new, student_id=member.student_id)
        copied += 1
    if not copied:
        raise ValidationError('Ese proyecto no tiene equipos que copiar.')
    return copied


def overview(activity):
    """Lo que muestra la pantalla de equipos: ``(filas, sin_equipo)``.

    Cada fila trae el equipo, sus integrantes, su entrega y cuántos tienen calificación; se puede borrar si no
    entregó ni tiene calificaciones.
    """
    members = defaultdict(list)
    for member in TeamMember.objects.filter(activity=activity).select_related('student__user'):
        members[member.team_id].append(member.student)
    submissions = {}
    for submission in Submission.objects.filter(activity=activity, team__isnull=False).select_related('submitted_by'):
        current = submissions.get(submission.team_id)
        if current is None or submission.submitted_at > current.submitted_at:
            submissions[submission.team_id] = submission
    graded = set(Grade.objects.filter(activity=activity).values_list('student_id', flat=True))
    rows = []
    for team in activity.teams.all():
        students = sorted(members.get(team.pk, []), key=student_sort_key)
        graded_count = sum(1 for student in students if student.pk in graded)
        rows.append({
            'team': team, 'members': students, 'submission': submissions.get(team.pk), 'graded': graded_count,
            'deletable': team.pk not in submissions and not graded_count,
            'locked': {student.pk for student in students if student.pk in graded},
        })
    return rows, unassigned_enrollments(activity)
