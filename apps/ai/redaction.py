"""Depurar el texto de un trabajo antes de mandarlo a la IA: quitar lo que identifica a una persona.

Se cambian por marcadores (``[NOMBRE]``, ``[MATRÍCULA]``, ``[CORREO]``, ``[TELÉFONO]``, ``[CURP]``; no se borran, para no
romper las frases) los nombres del alumno, de **todos** sus compañeros de grupo y del docente, sus matrículas y
cualquier correo, teléfono o CURP que tenga forma de tal. Se cuenta cuántas sustituciones hubo: si hubo, el alumno se
identificó en el cuerpo del trabajo y se le avisa al docente.

Reduce los datos personales que se envían, no los elimina: un apodo, un dato que no está en la lista o un nombre que el
OCR leyó mal pueden pasar. Por eso la IA solo se usa con el nivel de pago del proveedor y con el interruptor de la
organización encendido.
"""

import re
import unicodedata
from dataclasses import dataclass

NAME, NUMBER, EMAIL, PHONE, CURP = '[NOMBRE]', '[MATRÍCULA]', '[CORREO]', '[TELÉFONO]', '[CURP]'

MIN_NAME_CHARS = 3  # «de», «la»… no identifican a nadie; un nombre de tres letras (Ana, Luz) sí
MIN_NUMBER_CHARS = 4  # igual que al identificar la portada: «40» o «7» aparecen en cualquier texto
PARTICLES = frozenset({'de', 'del', 'la', 'las', 'los', 'el', 'y', 'e', 'da', 'das', 'do', 'dos', 'van', 'von', 'san', 'santa'})

_COMBINING = '[̀-ͯ]*'
_SEPARATORS = r'[\s.\-_]*'
_EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+', re.IGNORECASE)
_CURP = re.compile(r'(?<![A-Za-z0-9])[A-Z]{4}\d{6}[HM][A-Z]{5}[A-Z0-9]\d(?![A-Za-z0-9])', re.IGNORECASE)
_PHONE = re.compile(  # diez dígitos (con lada de 2 o 3 cifras y, si lo trae, el +52): nada más corto, para no tocar cifras sueltas
    r'(?<!\d)(?:\+?52[\s.-]?)?(?:\(?\d{2}\)?[\s.-]?\d{4}[\s.-]?\d{4}|\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)',
)
_ADJACENT_NAMES = re.compile(rf'{re.escape(NAME)}(?:[ \t]+{re.escape(NAME)})+')


def _base(char):
    return ''.join(c for c in unicodedata.normalize('NFD', char) if not unicodedata.combining(c))


def _letter_pattern(char):
    """Una letra que casa con o sin acento, en mayúscula o minúscula, y con la tilde suelta (NFD) o pegada."""
    base = _base(char).lower()
    if not base.isalpha():
        return re.escape(char)
    variants = {base}
    for code in range(0xC0, 0x180):  # latín con acentos
        candidate = chr(code)
        if _base(candidate).lower() == base:
            variants.add(candidate.lower())
    return f'[{"".join(sorted(variants))}]{_COMBINING}'


def _word_pattern(word):
    return r'(?<!\w)' + ''.join(_letter_pattern(char) for char in word) + r'(?!\w)'


def _number_pattern(number):
    """La matrícula con o sin separadores y, si es numérica, con o sin ceros a la izquierda."""
    compact = re.sub(r'[^0-9A-Za-z]', '', number)
    if len(compact) < MIN_NUMBER_CHARS:
        return None
    significant = compact.lstrip('0') if compact.isdigit() else compact
    significant = significant if len(significant) >= MIN_NUMBER_CHARS else compact
    body = _SEPARATORS.join(re.escape(char) for char in significant)
    zeros = r'(?:0+' + _SEPARATORS + ')?' if compact.isdigit() else ''
    return rf'(?<![0-9A-Za-z]){zeros}{body}(?![0-9A-Za-z])'


def name_tokens(*names):
    """Las palabras de unos nombres que identifican a alguien (sin partículas ni palabras de una o dos letras)."""
    tokens = set()
    for name in names:
        for word in re.split(r'[\s,.;:()\-]+', unicodedata.normalize('NFC', name or '')):
            if len(word) >= MIN_NAME_CHARS and _base(word).lower() not in PARTICLES:
                tokens.add(word)
    return tokens


@dataclass(frozen=True)
class Redaction:
    text: str
    replacements: int


class Redactor:
    """Las reglas de depuración de un trabajo: se arma una vez por entrega y se aplica a todo lo que se envíe."""

    def __init__(self, *, names=(), numbers=(), emails=()):
        self.name_patterns = [re.compile(_word_pattern(token), re.IGNORECASE) for token in sorted(name_tokens(*names), key=len, reverse=True)]
        self.number_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in (_number_pattern(number) for number in set(numbers)) if pattern
        ]
        self.email_patterns = [re.compile(re.escape(email), re.IGNORECASE) for email in set(emails) if email]

    def apply(self, text):
        text = unicodedata.normalize('NFC', text or '')
        count = 0

        def sub(pattern, marker, source):
            nonlocal count
            result, n = pattern.subn(marker, source)
            count += n
            return result

        for pattern in self.email_patterns:
            text = sub(pattern, EMAIL, text)
        text = sub(_EMAIL, EMAIL, text)
        text = sub(_CURP, CURP, text)
        for pattern in self.number_patterns:
            text = sub(pattern, NUMBER, text)
        text = sub(_PHONE, PHONE, text)
        for pattern in self.name_patterns:
            text = sub(pattern, NAME, text)

        def merge(match):  # «Ana Torres Ruiz» deja tres marcadores seguidos: es una sola mención
            nonlocal count
            count -= match.group().count(NAME) - 1
            return NAME

        return Redaction(_ADJACENT_NAMES.sub(merge, text), count)


def redactor_for(student, classmates, teacher):
    """El ``Redactor`` de un alumno: sus datos, los de sus compañeros de grupo y los del docente."""
    people = [student, *classmates]
    return Redactor(
        names=[name for person in people for name in (person.first_name, person.last_name)]
        + [teacher.first_name, teacher.last_name],
        numbers=[person.student_number for person in people if person.student_number],
        emails=[person.email for person in people] + [teacher.email],
    )
