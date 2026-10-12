"""Código de invitación: un alumno de la lista enlaza su cuenta con su ficha de ``Student``.

El código solo no basta ni agrega a nadie a un grupo: hay que dar también la matrícula y los apellidos de
alguien que ya está en la lista y aún no tiene cuenta. Los fallos se limitan por usuario para que no se
puedan adivinar códigos o matrículas probando.
"""

from django.core.cache import cache
from django.db import IntegrityError, transaction

from ..models import Course, Student
from .text import normalize_text

MAX_FAILURES = 8
LOCK_SECONDS = 15 * 60

NOT_FOUND = 'No encontramos esa combinación de código, matrícula y apellidos. Revísala o pide ayuda a tu docente.'


class InvitationError(Exception):
    """El mensaje se muestra tal cual al alumno."""


def regenerate_invite_code(course):
    """Código nuevo: el anterior deja de funcionar."""
    course.invite_code = Course.new_invite_code()
    course.save(update_fields=['invite_code'])
    return course


def disable_invite_code(course):
    """Sin código, nadie puede enlazar su cuenta a este grupo."""
    course.invite_code = ''
    course.save(update_fields=['invite_code'])
    return course


def _failures_key(user):
    return f'invite_failures_{user.pk}'


def _find_student(code, student_number, last_name):
    code = ''.join((code or '').split()).replace('-', '').upper()
    number = (student_number or '').strip()
    if not code or not number:
        return None
    course = Course.objects.filter(invite_code=code, status=Course.Status.ACTIVE).first()
    if course is None:
        return None
    student = (
        Student.objects.for_organization(course.organization)
        .filter(student_number=number, enrollments__course=course)
        .first()
    )
    if student is None:
        return None
    # Si la lista no trae apellidos no hay nada que contrastar; si los trae, deben coincidir.
    if student.last_name.strip() and normalize_text(student.last_name) != normalize_text(last_name):
        return None
    return student


def redeem_invitation(user, code, student_number, last_name):
    """Enlaza ``user`` con su ficha de la lista. Devuelve el ``Student``; lanza ``InvitationError``."""
    key = _failures_key(user)
    failures = cache.get(key, 0)
    if failures >= MAX_FAILURES:
        raise InvitationError('Demasiados intentos fallidos. Espera unos minutos y vuelve a intentarlo.')

    student = _find_student(code, student_number, last_name)
    if student is None:
        cache.set(key, failures + 1, LOCK_SECONDS)
        raise InvitationError(NOT_FOUND)
    cache.delete(key)

    if student.user_id == user.pk:
        return student  # ya estaba enlazado: no es un error
    if student.user_id:
        raise InvitationError('Esa matrícula ya está vinculada a otra cuenta. Avisa a tu docente.')
    if Student.objects.filter(organization=student.organization, user=user).exists():
        raise InvitationError('Tu cuenta ya está vinculada a otro alumno de esta organización.')

    try:
        with transaction.atomic():
            student.user = user
            student.save()  # lo hace miembro de la organización y crea sus conversaciones
    except IntegrityError as error:  # otra petición lo enlazó primero
        raise InvitationError('No se pudo enlazar tu cuenta. Inténtalo de nuevo.') from error
    return student
