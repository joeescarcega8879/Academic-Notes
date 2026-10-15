"""Importación de preguntas al banco desde un archivo CSV o Excel.

Formato (una pregunta por fila, encabezados en cualquier orden y con variantes en español):

    Pregunta | Tipo | Opción A … Opción H | Correcta | Puntos | Tema | Explicación

* ``Tipo`` es opcional: "opción múltiple" o "verdadero/falso". Si falta se deduce de las opciones y de la correcta.
* ``Correcta`` es la letra (A), el número (1) o el texto de la opción; en verdadero/falso, "Verdadero" o "Falso".
* Una pregunta que ya está en el banco, o repetida dentro del archivo, se omite: volver a subir el archivo no duplica.

Nada se escribe hasta ``apply_import``; ``analyze`` solo prevé qué pasaría con cada fila.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.courses.services.text import normalize_text
from apps.organizations import limits
from core.utils import parse_id

from ..models import Question
from .bank import save_question, validate_choices

ALIASES = {
    'text': {'pregunta', 'enunciado', 'texto', 'question', 'reactivo'},
    'kind': {'tipo', 'tipo de pregunta', 'type'},
    'correct': {'correcta', 'respuesta correcta', 'respuesta', 'answer', 'correct', 'clave'},
    'points': {'puntos', 'valor', 'points', 'puntaje'},
    'topic': {'tema', 'topic', 'categoria', 'unidad'},
    'explanation': {'explicacion', 'retroalimentacion', 'explanation', 'justificacion'},
}
OPTION_HEADER = re.compile(r'^(?:opcion|option|inciso|respuesta)?\s*([a-h]|[1-8])$')
LETTERS = 'abcdefgh'

TRUE_WORDS = {'verdadero', 'v', 'true', 't', 'cierto'}
FALSE_WORDS = {'falso', 'f', 'false'}
MAX_TEXT = 5000


@dataclass
class ParsedQuestion:
    line: int
    text: str = ''
    kind: str = ''
    points: Decimal = Decimal(1)
    topic: str = ''
    explanation: str = ''
    choices: list = field(default_factory=list)  # [(texto, es_correcta)]
    true_is_correct: bool | None = None
    errors: list = field(default_factory=list)
    duplicate: str = ''  # 'banco' o 'archivo'

    @property
    def status(self):
        if self.errors:
            return 'error'
        return 'duplicate' if self.duplicate else 'new'


@dataclass
class ImportPlan:
    items: list
    header_errors: list = field(default_factory=list)

    def count(self, status):
        return sum(1 for item in self.items if item.status == status)

    @property
    def count_new(self):
        return self.count('new')

    @property
    def count_duplicate(self):
        return self.count('duplicate')

    @property
    def count_error(self):
        return self.count('error')


# ── Encabezados ───────────────────────────────────────────────────────

def detect_columns(headers):
    """({campo: índice}, [índices de las opciones en orden A, B, C…]) según los encabezados reconocidos."""
    columns, options = {}, {}
    for index, header in enumerate(headers):
        normalized = normalize_text(header)
        field_name = next((name for name, aliases in ALIASES.items() if normalized in aliases), None)
        if field_name is not None:
            columns.setdefault(field_name, index)
            continue
        match = OPTION_HEADER.match(normalized)
        if match:
            token = match.group(1)
            position = LETTERS.index(token) if token in LETTERS else int(token) - 1
            options.setdefault(position, index)
    return columns, [options[p] for p in sorted(options)]


# ── Interpretación de una fila ────────────────────────────────────────

def _cell(row, index):
    return row[index].strip() if index is not None and index < len(row) else ''


def _kind_from(cell, has_options, correct_cell):
    word = normalize_text(cell)
    if word:
        if 'verdadero' in word or 'falso' in word or word in {'tf', 'vf', 'v f', 'true false'}:
            return Question.Kind.TRUE_FALSE
        if 'multiple' in word or 'opcion' in word:
            return Question.Kind.MULTIPLE_CHOICE
        return ''
    if has_options:
        return Question.Kind.MULTIPLE_CHOICE
    if normalize_text(correct_cell) in TRUE_WORDS | FALSE_WORDS:
        return Question.Kind.TRUE_FALSE
    return ''


def _correct_index(correct_cell, texts):
    """Posición (0-based) de la opción correcta según la celda ``Correcta``, o un mensaje de error."""
    value = normalize_text(correct_cell)
    if not value:
        return None, 'Falta la respuesta correcta.'
    if len(value) == 1 and value in LETTERS:
        index = LETTERS.index(value)
    elif parse_id(value) is not None:
        index = parse_id(value) - 1
    else:
        matches = [i for i, text in enumerate(texts) if normalize_text(text) == value]
        if len(matches) == 1:
            return matches[0], None
        # Varias letras ("A, C") u otro texto que no es una opción
        if re.fullmatch(r'[a-h](?: [a-h])+', value):
            return None, 'Solo puede haber una respuesta correcta.'
        return None, 'La respuesta correcta no coincide con ninguna opción.'
    if not 0 <= index < len(texts):
        return None, 'La respuesta correcta apunta a una opción que no existe.'
    return index, None


def _parse_points(cell):
    if not cell:
        return Decimal(1), None
    try:
        points = Decimal(cell.replace(',', '.'))
    except InvalidOperation:
        return None, 'Los puntos deben ser un número.'
    if not points.is_finite() or points <= 0 or points > 9999:
        return None, 'Los puntos deben ser mayores que 0.'
    return points.quantize(Decimal('0.01')), None


def parse_row(line, row, columns, option_columns):
    item = ParsedQuestion(line=line)
    item.text = _cell(row, columns.get('text'))
    item.topic = _cell(row, columns.get('topic'))
    item.explanation = _cell(row, columns.get('explanation'))
    correct_cell = _cell(row, columns.get('correct'))
    option_texts = [_cell(row, i) for i in option_columns]
    filled = [text for text in option_texts if text]

    if not item.text:
        item.errors.append('Falta la pregunta.')
    elif len(item.text) > MAX_TEXT:
        item.errors.append('La pregunta es demasiado larga.')
    if len(item.topic) > Question._meta.get_field('topic').max_length:
        item.errors.append('El tema es demasiado largo.')
    points, error = _parse_points(_cell(row, columns.get('points')))
    if error:
        item.errors.append(error)
    else:
        item.points = points

    item.kind = _kind_from(_cell(row, columns.get('kind')), bool(filled), correct_cell)
    if not item.kind:
        item.errors.append('No se pudo saber el tipo: escribe las opciones o "Verdadero"/"Falso" en la correcta.')
        return item

    if item.kind == Question.Kind.TRUE_FALSE:
        word = normalize_text(correct_cell)
        if word in TRUE_WORDS:
            item.true_is_correct = True
        elif word in FALSE_WORDS:
            item.true_is_correct = False
        else:
            item.errors.append('En verdadero o falso, la correcta debe ser "Verdadero" o "Falso".')
        return item

    # Opción múltiple: las posiciones se conservan aunque haya huecos (la letra apunta a la columna).
    texts = option_texts
    index, error = _correct_index(correct_cell, texts)
    if error:
        item.errors.append(error)
        return item
    if not texts[index].strip():
        item.errors.append('La respuesta correcta apunta a una opción vacía.')
        return item
    try:
        item.choices = validate_choices([(text, i == index) for i, text in enumerate(texts)])
    except ValidationError as exc:
        item.errors.extend(exc.messages)
    if any(len(text) > 500 for text in texts):
        item.errors.append('Una opción es demasiado larga.')
    return item


# ── Análisis y aplicación ─────────────────────────────────────────────

def _key(text, kind):
    return (normalize_text(text), kind)


def analyze(organization, headers, rows):
    """Prevé qué haría la importación con cada fila (sin escribir nada)."""
    columns, option_columns = detect_columns(headers)
    header_errors = []
    if 'text' not in columns:
        header_errors.append('No encontré la columna "Pregunta".')
    if 'correct' not in columns:
        header_errors.append('No encontré la columna "Correcta".')
    if header_errors:
        return ImportPlan(items=[], header_errors=header_errors)

    existing = {
        _key(text, kind)
        for text, kind in Question.objects.for_organization(organization).filter(is_archived=False).values_list('text', 'kind')
    }
    seen = {}
    items = []
    for index, row in enumerate(rows):
        item = parse_row(index + 2, row, columns, option_columns)  # la fila 1 son los encabezados
        items.append(item)
        if item.errors:
            continue
        key = _key(item.text, item.kind)
        if key in existing:
            item.duplicate = 'banco'
        elif key in seen:
            item.duplicate = 'archivo'
        else:
            seen[key] = item.line
    return ImportPlan(items=items)


@transaction.atomic
def apply_import(organization, author, plan):
    """Crea las preguntas nuevas del plan. Las filas con error y las repetidas se omiten. Devuelve un resumen.

    Si pasan el tope del banco del plan se rechaza la importación completa (``PlanLimitError``).
    """
    limits.check_limit(organization, 'questions', adding=plan.count_new)
    created = 0
    for item in plan.items:
        if item.status != 'new':
            continue
        save_question(
            organization=organization, author=author, kind=item.kind, text=item.text, points=item.points,
            explanation=item.explanation, topic=item.topic,
            choices=item.choices if item.kind == Question.Kind.MULTIPLE_CHOICE else None,
            true_is_correct=item.true_is_correct if item.kind == Question.Kind.TRUE_FALSE else None,
        )
        created += 1
    return {'created': created, 'duplicates': plan.count('duplicate'), 'errors': plan.count('error')}


TEMPLATE_HEADERS = ['Pregunta', 'Tipo', 'Opción A', 'Opción B', 'Opción C', 'Opción D', 'Correcta', 'Puntos', 'Tema', 'Explicación']
TEMPLATE_ROWS = [
    ['¿Cuál es la capital de México?', 'Opción múltiple', 'Guadalajara', 'Ciudad de México', 'Monterrey', 'Puebla', 'B', '1', 'Geografía', 'Es la sede de los poderes federales.'],
    ['El agua hierve a 100 °C al nivel del mar.', 'Verdadero/Falso', '', '', '', '', 'Verdadero', '1', 'Ciencias', ''],
]
