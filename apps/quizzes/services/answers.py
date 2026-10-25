"""Respuestas de los alumnos: cómo se leen, se comparan y se califican según el tipo de pregunta.

Opción múltiple y verdadero o falso guardan la opción elegida. La respuesta corta guarda el texto que escribió el
alumno y lo compara, ya normalizado, con las respuestas que el docente aceptó. La respuesta abierta guarda el texto y
queda por calificar: la puntúa el docente.
"""

import re
import unicodedata
from decimal import Decimal

from django.core.exceptions import ValidationError

from core.utils import parse_id

from ..models import Question

CHOICE_KINDS = (Question.Kind.MULTIPLE_CHOICE, Question.Kind.TRUE_FALSE)
TEXT_KINDS = (Question.Kind.SHORT_ANSWER, Question.Kind.OPEN)
MAX_TEXT_LENGTH = 500
MAX_OPEN_LENGTH = 5000

# «No hay nada que guardar»: un valor que no es un id válido se ignora (no borra la respuesta que ya había).
IGNORE = object()


def normalize(text):
    """Forma comparable de un texto: sin mayúsculas, acentos, signos ni espacios de sobra.

    Se conserva la «ñ» (año y ano no son lo mismo) y el punto decimal («3,5» y «3.5» valen igual).
    """
    text = (text or '').replace('ñ', '\x00').replace('Ñ', '\x00').casefold()
    text = ''.join(ch for ch in unicodedata.normalize('NFKD', text) if not unicodedata.combining(ch))
    text = text.replace('\x00', 'ñ')
    text = re.sub(r'(?<=\d),(?=\d)', '.', text)
    text = re.sub(r'[\W_]+', lambda m: '.' if m.group() == '.' else ' ', text)
    text = re.sub(r'(?<!\d)\.|\.(?!\d)', ' ', text)
    return ' '.join(text.split())


def accepted_answers(question):
    """Las respuestas que acepta una pregunta de respuesta corta, normalizadas."""
    return {normalize(choice.text) for choice in question.choices.all() if normalize(choice.text)}


def coerce(question, value, choice_ids):
    """Lo que se guarda de lo que llegó en la petición: ``{'choice_id': ...}`` o ``{'text': ...}``; ``IGNORE`` si no sirve.

    ``value`` es una opción (entero, o texto con un entero) para opción múltiple y verdadero o falso, y un texto para la
    respuesta corta. ``None`` o vacío borra la respuesta.
    """
    if question.kind in CHOICE_KINDS:
        if value is None or value == '':
            return {'choice_id': None}
        choice_id = value if isinstance(value, int) else parse_id(value)
        if choice_id is None:
            return IGNORE
        if choice_id not in choice_ids:
            raise ValidationError('Hay una opción que no es de esa pregunta.')
        return {'choice_id': choice_id}
    if question.kind in TEXT_KINDS:
        limit = MAX_OPEN_LENGTH if question.kind == Question.Kind.OPEN else MAX_TEXT_LENGTH
        text = '' if value is None else str(value).strip()
        if len(text) > limit:
            raise ValidationError(f'Una respuesta no puede pasar de {limit} caracteres.')
        return {'text': text}
    raise ValidationError('Tipo de pregunta desconocido.')


def has_answer(question, answer):
    """El alumno contestó esta pregunta (una respuesta en blanco cuenta como sin responder)."""
    if answer is None:
        return False
    if question.kind in TEXT_KINDS:
        return bool(answer.text.strip())
    return answer.choice_id is not None


def grade(question, answer):
    """``(es_correcta, puntos)`` de una respuesta. Las preguntas sin contestar valen 0.

    Una respuesta abierta con texto devuelve ``(None, None)``: queda por calificar y la puntúa el docente.
    """
    if question.kind == Question.Kind.OPEN:
        return (None, None) if answer.text.strip() else (False, Decimal(0))
    if question.kind in CHOICE_KINDS:
        correct = bool(answer.choice_id and answer.choice.is_correct)
    elif question.kind == Question.Kind.SHORT_ANSWER:
        correct = bool(normalize(answer.text)) and normalize(answer.text) in accepted_answers(question)
    else:
        correct = False
    return correct, (question.points if correct else Decimal(0))
