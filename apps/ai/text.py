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


def line_norms(text):
    """El texto normalizado línea por línea: una cita debe caber en una sola línea del material."""
    return [line for line in (normalize(raw) for raw in text.splitlines()) if line]


def quoted_in_lines(fragment, lines):
    """El fragmento aparece dentro de **una** de las líneas (ya normalizadas con ``line_norms``) y es lo bastante largo.

    Exigir una sola línea evita que una «cita» junte varios temas del material y no pruebe nada.
    """
    needle = normalize(fragment)
    return len(needle) >= MIN_CITATION_CHARS and any(needle in line for line in lines)
