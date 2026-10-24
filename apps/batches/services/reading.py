"""Leer el contenido de un PDF del lote: la portada escaneada (para identificar al alumno) y el cuerpo del trabajo.

Una página con texto digital se lee tal cual; una que es imagen (un escaneo, una foto) pasa por OCR. Si el texto que sale
es muy poco o el OCR lo leyó con poca confianza (lo típico de la letra a mano), el trabajo queda «Legible a medias»: el
docente lo califica viendo el original.
"""

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader

from apps.grades.models import Submission

from . import ocr

ReadStatus = Submission.ReadStatus

MIN_PAGE_CHARS = 40  # una página con menos letras y números que esto se trata como imagen
MIN_BODY_CHARS = 80  # menos que esto en todo el trabajo es casi nada
MIN_CONFIDENCE = 60  # confianza media del OCR (0 a 100) por debajo de la cual el texto no es de fiar
MAX_BODY_CHARS = 200_000


@dataclass(frozen=True)
class Body:
    text: str
    status: str
    confidence: float | None = None
    note: str = ''


def _letters(text):
    return len(re.sub(r'[\W_]+', '', text))


def _page_text(page):
    try:
        return (page.extract_text() or '').strip()
    except Exception:  # pypdf lanza de todo ante una página dañada
        return ''


def _reader(data):
    reader = PdfReader(io.BytesIO(data), strict=False)
    if reader.is_encrypted:
        reader.decrypt('')
    return reader


def ocr_cover(data, cover_pages):
    """El texto de las primeras ``cover_pages`` páginas leídas con OCR (vacío si no hay OCR o no se pudo leer)."""
    if not cover_pages or not ocr.available():
        return ''
    texts = []
    with ocr.Scan(data) as scan:
        for index in range(cover_pages):
            try:
                texts.append(scan.read(index).text)
            except ocr.OcrError:
                continue
    return '\n'.join(texts).strip()


def read_body(data, cover_pages):
    """Lee las páginas después de la portada y dice qué tan bien se pudo."""
    reader = _reader(data)
    indexes = list(range(cover_pages, len(reader.pages)))
    if not indexes:
        return Body('', ReadStatus.EMPTY, note='El PDF solo tiene la portada.')

    texts = {index: _page_text(reader.pages[index]) for index in indexes}
    image_pages = [index for index in indexes if _letters(texts[index]) < MIN_PAGE_CHARS]

    ocr_pages = unread = 0
    weighted = words = 0.0
    if image_pages and ocr.available():
        with ocr.Scan(data) as scan:
            for index in image_pages:
                try:
                    page = scan.read(index)
                except ocr.OcrError:
                    unread += 1
                    continue
                ocr_pages += 1
                if page.confidence is not None:
                    weighted += page.confidence * page.words
                    words += page.words
                if _letters(page.text) > _letters(texts[index]):
                    texts[index] = page.text
    elif image_pages:
        unread = len(image_pages)

    text = '\n\n'.join(texts[index] for index in indexes if texts[index])[:MAX_BODY_CHARS]
    confidence = round(weighted / words, 1) if words else None
    notes = []
    if unread:
        notes.append(
            f'{unread} {"página" if unread == 1 else "páginas"} sin leer'
            + ('' if ocr.available() else ' (este servidor no tiene OCR)') + '.',
        )

    if _letters(text) < MIN_BODY_CHARS:
        notes.append('Casi no salió texto: puede ser letra a mano o una imagen.')
        return Body(text, ReadStatus.PARTIAL, confidence, ' '.join(notes))
    if confidence is not None and confidence < MIN_CONFIDENCE:
        notes.append(f'El OCR leyó con poca confianza ({confidence:.0f} %): puede ser letra a mano.')
        return Body(text, ReadStatus.PARTIAL, confidence, ' '.join(notes))
    return Body(text, ReadStatus.OCR if ocr_pages else ReadStatus.TEXT, confidence, ' '.join(notes))
