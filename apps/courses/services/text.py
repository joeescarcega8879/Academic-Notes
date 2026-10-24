"""Utilidades de texto compartidas por los servicios de alumnos."""

import re
import unicodedata


def normalize_text(text):
    """Minúsculas, sin acentos ni signos y con espacios colapsados: para comparar nombres y encabezados."""
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()


def student_sort_key(student):
    """Clave para ordenar alumnos como en una lista de clase: apellidos y nombres, sin acentos ni mayúsculas.

    Se ordena en Python porque el orden de la base depende de su configuración regional: SQLite y PostgreSQL
    sobre Alpine ponen «Álvarez» después de «Zapata».
    """
    return (normalize_text(student.last_name), normalize_text(student.first_name), student.pk)


def sort_enrollments(enrollments):
    """Las inscripciones (con su ``student`` ya cargado) en orden alfabético por alumno."""
    return sorted(enrollments, key=lambda enrollment: student_sort_key(enrollment.student))
