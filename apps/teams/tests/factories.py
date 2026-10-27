from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.models import Activity
from apps.grades.tests.factories import ActivityFactory
from apps.teams.services import teams


def team_project(course, **kwargs):
    """Proyecto publicado del grupo que se entrega por equipos (ya trae su rúbrica)."""
    return ActivityFactory(course=course, type=Activity.Type.PROJECT, by_teams=True, **kwargs)


def enroll(course, count):
    """``count`` alumnos nuevos inscritos en el grupo."""
    return [EnrollmentFactory(course=course).student for _ in range(count)]


def make_team(activity, *students, name=''):
    """Un equipo del proyecto con esos alumnos."""
    team = teams.create_team(activity, name)
    for student in students:
        teams.assign(activity, student, team)
    return team
