"""Saber de quién es un archivo buscando en su portada las matrículas exactas del grupo.

No se adivinan formatos: solo se buscan las matrículas que ya conocemos, así que lo único que puede salir mal es
que la portada no traiga ninguna (o traiga la de otro). Todo lo dudoso se manda a que el docente lo asigne a mano.
"""

import re

from apps.courses.services.text import normalize_text

# Una matrícula más corta (tras quitar los ceros a la izquierda) coincidiría con cualquier número de la portada
# («grupo 12», «hoja 3»): esos alumnos se identifican a mano.
MIN_ID_LENGTH = 4

# Entre dos caracteres de la matrícula la portada puede traer espacios, guiones, guiones bajos o puntos.
_SEPARATORS = r'[\s\-_.]*'


def _pattern(student_number):
    """Expresión que reconoce la matrícula ignorando mayúsculas, separadores y ceros a la izquierda, y solo completa.

    Completa significa que no puede estar pegada a otra letra o dígito: ``12345`` no coincide dentro de ``123456`` ni
    de ``A12345``. Devuelve ``None`` si la matrícula es demasiado corta para buscarla sin falsos positivos.
    """
    chars = re.sub(r'[^0-9a-z]', '', str(student_number).lower()).lstrip('0')
    if len(chars) < MIN_ID_LENGTH:
        return None
    body = _SEPARATORS.join(re.escape(c) for c in chars)
    return re.compile(rf'(?<![0-9a-z])0*{body}(?![0-9a-z])', re.IGNORECASE)


def match_students(cover_text, students):
    """Los alumnos de ``students`` cuya matrícula aparece en ``cover_text`` (una lista de cero, uno o varios).

    Si la matrícula de un alumno es la parte inicial de otra que también aparece (``12345 6`` contiene ``12345`` y
    ``123456``), solo cuenta la más larga.
    """
    spans = []  # (alumno, inicio, fin)
    for student in students:
        if not student.student_number:
            continue
        pattern = _pattern(student.student_number)
        if pattern is None:
            continue
        spans.extend((student, m.start(), m.end()) for m in pattern.finditer(cover_text))

    matched = {}
    for student, start, end in spans:
        dominated = any(
            other is not student and o_start <= start and end <= o_end and (o_start, o_end) != (start, end)
            for other, o_start, o_end in spans
        )
        if not dominated:
            matched[student.pk] = student
    return list(matched.values())


def name_matches(cover_text, student):
    """La portada nombra el apellido del alumno (para avisar si la matrícula parece ser de otro).

    Sin apellido que comparar se da por bueno: no hay con qué avisar.
    """
    words = set(normalize_text(cover_text).split())
    surnames = [w for w in normalize_text(student.last_name).split() if len(w) > 2]
    return not surnames or any(word in words for word in surnames)
