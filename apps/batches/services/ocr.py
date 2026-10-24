"""OCR local con Tesseract: páginas de un PDF escaneado a texto, con la confianza con que se leyó.

Todo corre en nuestro servidor y ninguna imagen sale a un tercero. Si el programa no está instalado (``available()`` es
falso) el resto de la app sigue funcionando: solo se lee el texto digital de los PDF.
"""

import io
import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings

DPI = 200  # con menos, la letra chica sale mal; con más, tarda sin ganar mucho
MAX_SIDE_PX = 3000  # tope para que una página enorme (un plano, un cartel) no llene la memoria
PAGE_TIMEOUT = 60  # segundos por página


class OcrError(Exception):
    """Una página no se pudo leer (el programa falló o tardó demasiado)."""


@dataclass(frozen=True)
class OcrPage:
    text: str
    confidence: float | None  # media de las palabras leídas (0 a 100); ``None`` si no salió ninguna
    words: int


def _command():
    return settings.OCR_TESSERACT_CMD or shutil.which('tesseract') or ''


def _env():
    env = os.environ.copy()
    if settings.OCR_TESSDATA_DIR:
        env['TESSDATA_PREFIX'] = str(settings.OCR_TESSDATA_DIR)
    return env


def _run(args, **kwargs):
    # Sin ventana de consola en Windows; sin intérprete de comandos en ningún sistema.
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    return subprocess.run([_command(), *args], env=_env(), capture_output=True, creationflags=flags, **kwargs)


@lru_cache(maxsize=8)
def _has_language(command, tessdata_dir, language):
    """Si el programa existe y tiene el idioma pedido (se pregunta una vez por combinación)."""
    try:
        result = _run(['--list-langs'], timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and language in result.stdout.decode('utf-8', 'replace').split()


def available():
    """¿Este servidor puede leer imágenes con OCR?"""
    if not settings.OCR_ENABLED or not _command():
        return False
    return _has_language(_command(), str(settings.OCR_TESSDATA_DIR), settings.OCR_LANGUAGE)


def recognize(image):
    """Lee una imagen (``PIL.Image``) y devuelve su texto y la confianza con que Tesseract lo leyó."""
    buffer = io.BytesIO()
    image.convert('L').save(buffer, 'PNG')
    # ``-c tessedit_create_tsv=1`` y no la configuración «tsv»: esa vive en una carpeta que no siempre existe.
    args = ['stdin', 'stdout', '--dpi', str(DPI), '-l', settings.OCR_LANGUAGE, '-c', 'tessedit_create_tsv=1']
    try:
        result = _run(args, input=buffer.getvalue(), timeout=PAGE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise OcrError('Tesseract tardó demasiado en una página.') from None
    except (OSError, subprocess.SubprocessError) as error:
        raise OcrError(f'No se pudo ejecutar Tesseract: {error}') from None
    if result.returncode != 0:
        raise OcrError(result.stderr.decode('utf-8', 'replace').strip()[:300] or 'Tesseract falló.')
    return _parse_tsv(result.stdout.decode('utf-8', 'replace'))


def _parse_tsv(tsv):
    lines, confidences = {}, []
    for row in tsv.splitlines()[1:]:  # la primera fila son los nombres de las columnas
        cells = row.split('\t', 11)
        if len(cells) < 12 or cells[0] != '5':  # el nivel 5 son las palabras
            continue
        word = cells[11].strip()
        try:
            confidence = float(cells[10])
        except ValueError:
            continue
        if not word or confidence < 0:
            continue
        lines.setdefault(tuple(cells[2:5]), []).append(word)  # (bloque, párrafo, línea)
        confidences.append(confidence)
    text = '\n'.join(' '.join(words) for words in lines.values())
    return OcrPage(text, sum(confidences) / len(confidences) if confidences else None, len(confidences))


class Scan:
    """Un PDF escaneado abierto para leer sus páginas una por una (``with Scan(bytes) as scan: scan.read(0)``)."""

    def __init__(self, data):
        import pypdfium2

        self._pdf = pypdfium2.PdfDocument(data)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._pdf.close()

    def read(self, index):
        """El OCR de la página ``index`` (desde 0). Lanza ``OcrError`` si no se pudo."""
        try:
            page = self._pdf[index]
            try:
                width, height = page.get_size()
                scale = min(DPI / 72, MAX_SIDE_PX / max(width, height, 1))
                image = page.render(scale=scale).to_pil()
            finally:
                page.close()
        except Exception as error:  # pdfium lanza errores propios y genéricos según el daño
            raise OcrError(f'No se pudo abrir la página {index + 1}: {error}') from None
        return recognize(image)
