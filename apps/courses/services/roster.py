"""Edición de la lista de un grupo: agregar, inscribir, quitar y desvincular alumnos."""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.organizations.models import Membership

from ..models import Enrollment, Student


@transaction.atomic
def add_student(course, **data):
    """Crea un alumno nuevo en la organización del grupo y lo inscribe."""
    student = Student.objects.create(organization=course.organization, **data)
    Enrollment.objects.create(student=student, course=course)
    return student


def enroll_existing(course, student):
    """Inscribe en el grupo a un alumno que ya está en la organización."""
    if student.organization_id != course.organization_id:
        raise ValidationError('El alumno debe pertenecer a la misma organización que el grupo.')
    enrollment, _ = Enrollment.objects.get_or_create(student=student, course=course)
    return enrollment


@transaction.atomic
def remove_from_course(course, student):
    """Quita al alumno del grupo. Si ya tiene calificaciones en él, no se quita: se perderían de vista."""
    from apps.grades.models import Grade

    if Grade.objects.filter(student=student, activity__course=course).exists():
        raise ValidationError(
            f'{student} ya tiene calificaciones en este grupo. Elimínalas primero si de verdad quieres quitarlo.'
        )
    course.ensure_editable()
    Enrollment.objects.filter(student=student, course=course).delete()


@transaction.atomic
def unlink_student(student):
    """Separa la cuenta del alumno (por ejemplo, si se enlazó a la persona equivocada).

    La cuenta pierde el acceso: se borran sus conversaciones de los grupos del alumno y su membresía de
    alumno en la organización. El alumno sigue en la lista, con sus calificaciones.
    """
    from apps.messaging.models import Conversation

    user = student.user
    if user is None:
        return student
    courses = student.enrollments.values_list('course_id', flat=True)
    Conversation.objects.filter(course_id__in=courses, student=user).delete()
    student.user = None
    student.save()
    # Solo se retira el rol de alumno; si la cuenta enseña en esa organización, se conserva.
    Membership.objects.filter(user=user, organization=student.organization, role=Membership.Role.STUDENT).delete()
    return student
