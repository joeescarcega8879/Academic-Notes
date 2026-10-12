"""Utilidades de texto compartidas por los servicios de alumnos."""

import re
import unicodedata


def normalize_text(text):
    """Minúsculas, sin acentos ni signos y con espacios colapsados: para comparar nombres y encabezados."""
    text = unicodedata.normalize('NFKD', str(text)).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', ' ', text.lower()).strip()
