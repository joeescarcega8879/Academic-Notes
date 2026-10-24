"""Leer un PDF subido: cuántas páginas tiene y el texto de su portada (texto digital, sin OCR)."""

from dataclasses import dataclass

from pypdf import PdfReader

MAX_PAGES = 100
MAX_COVER_CHARS = 4000


class UnreadablePdf(Exception):
    """El archivo no sirve; el mensaje es para el docente."""


@dataclass(frozen=True)
class PdfInfo:
    pages: int
    cover_text: str


def read_pdf(file, cover_pages):
    """Abre ``file`` y devuelve su número de páginas y el texto de las primeras ``cover_pages``.

    Lanza ``UnreadablePdf`` si no es un PDF, está dañado, tiene contraseña o excede ``MAX_PAGES``. El texto de una
    portada que es imagen sale vacío: eso no es un error, solo no se podrá identificar sola.
    """
    file.seek(0)
    if not file.read(1024).lstrip().startswith(b'%PDF-'):
        raise UnreadablePdf('No es un PDF válido.')
    file.seek(0)
    try:
        reader = PdfReader(file, strict=False)
        if reader.is_encrypted and not reader.decrypt(''):
            raise UnreadablePdf('Está protegido con contraseña.')
        pages = len(reader.pages)
        if pages == 0:
            raise UnreadablePdf('No tiene páginas.')
        if pages > MAX_PAGES:
            raise UnreadablePdf(f'Tiene {pages} páginas y el máximo es {MAX_PAGES}.')
        text = '\n'.join((reader.pages[i].extract_text() or '') for i in range(min(cover_pages, pages)))
    except UnreadablePdf:
        raise
    except Exception:  # pypdf lanza de todo ante un archivo dañado (PdfReadError, ValueError, RecursionError…)
        raise UnreadablePdf('Está dañado o no se pudo abrir.') from None
    finally:
        file.seek(0)
    return PdfInfo(pages=pages, cover_text=text.strip()[:MAX_COVER_CHARS])
