"""Comparar texto sin que importen acentos, mayúsculas, signos ni espacios: lo que hace falta para verificar citas."""

import re
import unicodedata

MIN_CITATION_CHARS = 8  # una «cita» más corta que esto cabe en cualquier texto y no prueba nada


def normalize(text):
    """«  Ribosomas: síntesis… » -> «ribosomas sintesis»."""
    decomposed = unicodedata.normalize('NFKD', str(text).casefold())
    plain = ''.join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r'[\W_]+', ' ', plain).strip()


def quoted_in(fragment, normalized_text):
    """El fragmento aparece en el texto (ya normalizado con ``normalize``) y es lo bastante largo para valer como cita."""
    needle = normalize(fragment)
    return len(needle) >= MIN_CITATION_CHARS and needle in normalized_text


# Un modelo que escribe «\frac» sin duplicar la barra en el JSON entrega un salto de página + «rac»; «\times», un
# tabulador + «imes»… Dentro de una fórmula esos caracteres de control nunca son legítimos: se devuelven a su comando.
_MATH_SEGMENT = re.compile(r'\\\(.*?\\\)|\\\[.*?\\\]', re.DOTALL)
_CONTROL_COMMAND = {'\x08': r'\b', '\x0c': r'\f', '\t': r'\t', '\r': r'\r'}
# «\n» es el único que también se escribe a propósito (un salto de línea): solo se repara si sigue un comando conocido.
_NEWLINE_COMMAND = re.compile(
    r'\n(?=(?:eq|abla|u|ot|otin|i|ewline|leq|geq|less|gtr|parallel|mid|rightarrow|exists|sim|cong|subseteq)\b)',
)
_MATH_TOKEN = re.compile(r'\\[()\[\]]')


def repair_math(text):
    r"""Devuelve a su comando LaTeX lo que el JSON volvió carácter de control dentro de ``\( … \)`` y ``\[ … \]``."""

    def fix(segment):
        text = _NEWLINE_COMMAND.sub(lambda _: r'\n', segment.group())
        return re.sub(r'[\x08\x0c\t\r]', lambda char: _CONTROL_COMMAND[char.group()], text)

    return _MATH_SEGMENT.sub(fix, text)


def math_balanced(text):
    r"""Cada ``\(`` o ``\[`` se cierra con su pareja y no hay fórmulas anidadas ni delimitadores sueltos."""
    closing = {r'\(': r'\)', r'\[': r'\]'}
    expected = None
    for token in _MATH_TOKEN.findall(text):
        if expected is None:
            if token not in closing:
                return False
            expected = closing[token]
        elif token == expected:
            expected = None
        else:
            return False
    return expected is None


def line_norms(text):
    """El texto normalizado línea por línea: una cita debe caber en una sola línea del material."""
    return [line for line in (normalize(raw) for raw in text.splitlines()) if line]


def quoted_in_lines(fragment, lines):
    """El fragmento aparece dentro de **una** de las líneas (ya normalizadas con ``line_norms``) y es lo bastante largo.

    Exigir una sola línea evita que una «cita» junte varios temas del material y no pruebe nada.
    """
    needle = normalize(fragment)
    return len(needle) >= MIN_CITATION_CHARS and any(needle in line for line in lines)
