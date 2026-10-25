"""Respuestas de los alumnos: cómo se leen, se comparan y se califican según el tipo de pregunta.

Opción múltiple y verdadero o falso guardan la opción elegida. La respuesta corta guarda el texto que escribió el
alumno y lo compara, ya normalizado, con las respuestas que el docente aceptó. La respuesta abierta guarda el texto y
queda por calificar: la puntúa el docente.
"""

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError

from core.utils import parse_id

from ..models import Question

CHOICE_KINDS = (Question.Kind.MULTIPLE_CHOICE, Question.Kind.TRUE_FALSE)
TEXT_KINDS = (Question.Kind.SHORT_ANSWER, Question.Kind.OPEN)
# Preguntas cuya respuesta se guarda como datos (``Answer.response``) y no como opción o texto.
RESPONSE_KINDS = (Question.Kind.ORDERING,)
# Las que muestran su lista de «opciones» al alumno (revueltas en el orden del intento).
LISTED_KINDS = CHOICE_KINDS + RESPONSE_KINDS
TWO_PLACES = Decimal('0.01')
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
    if question.kind == Question.Kind.ORDERING:
        return _coerce_order(value, choice_ids)
    raise ValidationError('Tipo de pregunta desconocido.')


def _coerce_order(value, choice_ids):
    """El orden que dio el alumno: lista de ids de los elementos (o texto «3,1,2»). Vacío borra la respuesta."""
    if value is None or value == '' or value == []:
        return {'response': None}
    parts = list(value) if isinstance(value, (list, tuple)) else str(value).split(',')
    ids = [part if isinstance(part, int) else parse_id(part.strip()) for part in parts]
    if None in ids or len(set(ids)) != len(ids) or set(ids) != set(choice_ids):
        raise ValidationError('Ordena todos los elementos de la pregunta.')
    return {'response': ids}


def has_answer(question, answer):
    """El alumno contestó esta pregunta (una respuesta en blanco cuenta como sin responder)."""
    if answer is None:
        return False
    if question.kind in TEXT_KINDS:
        return bool(answer.text.strip())
    if question.kind in RESPONSE_KINDS:
        return bool(answer.response)
    return answer.choice_id is not None


def grade(question, answer):
    """``(es_correcta, puntos)`` de una respuesta. Las preguntas sin contestar valen 0.

    Una respuesta abierta con texto devuelve ``(None, None)``: queda por calificar y la puntúa el docente.
    """
    if question.kind == Question.Kind.OPEN:
        return (None, None) if answer.text.strip() else (False, Decimal(0))
    if question.kind == Question.Kind.ORDERING:
        return _grade_order(question, answer)
    if question.kind in CHOICE_KINDS:
        correct = bool(answer.choice_id and answer.choice.is_correct)
    elif question.kind == Question.Kind.SHORT_ANSWER:
        correct = bool(normalize(answer.text)) and normalize(answer.text) in accepted_answers(question)
    else:
        correct = False
    return correct, (question.points if correct else Decimal(0))


def partial_points(question, placed, total):
    """Puntos proporcionales: ``placed`` de ``total`` aciertos, redondeados a 2 decimales (mitad hacia arriba)."""
    if not total:
        return Decimal(0)
    return (question.points * placed / total).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def correct_order(question):
    """Los ids de los elementos de una pregunta de ordenar, en el orden correcto."""
    return [choice.pk for choice in sorted(question.choices.all(), key=lambda c: (c.position, c.pk))]


def _grade_order(question, answer):
    """Cada elemento en su lugar vale lo mismo; solo se marca correcta si acertó todos."""
    expected = correct_order(question)
    given = answer.response or []
    placed = sum(1 for want, got in zip(expected, given) if want == got)
    return bool(expected) and placed == len(expected), partial_points(question, placed, len(expected))
