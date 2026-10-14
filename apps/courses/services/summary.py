"""Resumen académico de un alumno en su organización: lo que muestra su perfil."""

from apps.grades.models import Grade
from apps.grades.services.grading import results_by_course, student_average

from ..models import Course, Enrollment

RECENT_GRADES = 4


def student_summary(user, organization):
    """Promedio, grupos aprobados y calificaciones recientes de ``user`` en sus grupos activos.

    Solo cuenta lo publicado (el alumno nunca ve borradores) y los grupos archivados quedan fuera, igual
    que en su pantalla de inicio. Un grupo sin calificaciones es «sin calificar», no reprobado.
    """
    active = Course.Status.ACTIVE
    groups = Enrollment.objects.for_organization(organization).filter(student__user=user, course__status=active).count()
    grades = list(
        Grade.objects.for_organization(organization)
        .filter(student__user=user, activity__course__status=active, activity__published=True)
        .select_related('activity__course')
    )
    results = results_by_course(grades)
    graded = [result for result in results.values() if result.final is not None]
    passed = sum(1 for result in graded if result.passed)
    failed = len(graded) - passed
    pending = max(groups - len(graded), 0)

    def share(count):
        return round(count * 100 / groups) if groups else 0

    if not graded:
        tone = ''
    else:
        tone = 'bad' if failed else 'ok'
    return {
        'groups': groups,
        'average': student_average(results),
        'tone': tone,
        'passed': passed, 'failed': failed, 'pending': pending,
        'passed_share': share(passed), 'failed_share': share(failed), 'pending_share': share(pending),
        'recent': sorted(grades, key=lambda grade: grade.graded_at, reverse=True)[:RECENT_GRADES],
    }
