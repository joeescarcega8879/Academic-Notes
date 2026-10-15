"""Ciclo de vida de un grupo: archivar, desarchivar y duplicar para un nuevo ciclo."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.organizations import limits

from ..models import Course
from ..signals import course_cloned


def archive_course(course):
    """Archiva el grupo: sale de la vista principal y queda de solo lectura (sigue consultable y exportable)."""
    if course.is_archived:
        return course
    course.status = Course.Status.ARCHIVED
    course.archived_at = timezone.now()
    course.save(update_fields=['status', 'archived_at'])
    return course


def unarchive_course(course):
    """Devuelve un grupo archivado a la vista principal.

    Los grupos archivados no cuentan contra el plan, pero desarchivar sí lo verifica: el grupo y sus alumnos
    vuelven a contar. Lanza ``PlanLimitError`` (un ``ValidationError``) si el plan no lo permite.
    """
    if not course.is_archived:
        return course
    limits.check_limit(course.organization, 'groups')
    limits.check_students(course.organization, course.enrollments.values_list('student_id', flat=True))
    course.status = Course.Status.ACTIVE
    course.archived_at = None
    course.save(update_fields=['status', 'archived_at'])
    return course


@transaction.atomic
def clone_course(course, academic_year, *, code=None, name=None):
    """Duplica ``course`` en ``academic_year`` para un nuevo ciclo.

    Copia los datos del grupo y, mediante ``course_cloned``, su contenido (esquema de evaluación y evaluaciones
    sin fecha, listas para volver a programarse). No copia alumnos, inscripciones ni calificaciones: los
    ``Student`` persisten en la organización y en el nuevo ciclo solo se crean inscripciones nuevas.
    """
    if academic_year.organization_id != course.organization_id:
        raise ValidationError('El ciclo debe pertenecer a la misma organización que el grupo.')

    code = (code or course.code).strip()
    if Course.objects.filter(organization=course.organization, academic_year=academic_year, code=code).exists():
        raise ValidationError(f'Ya existe un grupo con el código "{code}" en el ciclo {academic_year}.')
    limits.check_limit(course.organization, 'groups')  # el duplicado cuenta como un grupo activo más

    clone = Course.objects.create(
        organization=course.organization,
        academic_year=academic_year,
        professor=course.professor,
        name=(name or course.name).strip(),
        code=code,
        description=course.description,
        schedule=course.schedule,
        color=course.color,
    )
    course_cloned.send(sender=Course, source=course, clone=clone)
    return clone
