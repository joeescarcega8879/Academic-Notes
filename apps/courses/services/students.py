"""Reglas de negocio de alumnos e inscripciones."""

from ..models import Student


def student_for_user(user, organization):
    """Ficha de ``Student`` de ``user`` en ``organization``; si no existe, la crea con los datos de su cuenta."""
    student, _ = Student.objects.get_or_create(
        organization=organization,
        user=user,
        defaults={
            'first_name': user.first_name or user.username,
            'last_name': user.last_name,
            'email': user.email,
        },
    )
    return student
