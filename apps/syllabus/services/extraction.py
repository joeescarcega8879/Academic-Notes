"""Guardar un temario (archivo o texto pegado) y sacar el texto del archivo."""

from django.db import transaction

from ..models import Syllabus
from .text import ExtractionError, extract_text

MAX_PASTED_CHARS = 200_000


def get_or_create_syllabus(course):
    syllabus, _ = Syllabus.objects.get_or_create(course=course)
    return syllabus


def _drop_file(syllabus):
    if syllabus.file:
        syllabus.file.storage.delete(syllabus.file.name)
        syllabus.file = ''


@transaction.atomic
def save_uploaded_file(course, uploaded):
    """Guarda el archivo subido (reemplaza el anterior) y deja el temario pendiente de extracción.

    El archivo ya debe haber pasado ``validate_syllabus_file``. Devuelve el temario; quien llama encola la tarea.
    """
    syllabus = get_or_create_syllabus(course)
    _drop_file(syllabus)
    syllabus.original_name = uploaded.name[:255]
    syllabus.file.save(uploaded.name, uploaded, save=False)
    syllabus.status = Syllabus.Status.PENDING
    syllabus.text = ''
    syllabus.save()
    return syllabus


@transaction.atomic
def save_pasted_text(course, text):
    """Guarda el temario escrito o pegado por el docente (sin archivo)."""
    syllabus = get_or_create_syllabus(course)
    _drop_file(syllabus)
    syllabus.original_name = ''
    syllabus.text = text.strip()[:MAX_PASTED_CHARS]
    syllabus.status = Syllabus.Status.READY if syllabus.text else Syllabus.Status.EMPTY
    syllabus.save()
    return syllabus


def extract_syllabus(syllabus_id):
    """Lee el archivo del temario y guarda su texto y su estado. Devuelve el estado final (o ``None`` si ya no existe)."""
    syllabus = Syllabus.objects.filter(pk=syllabus_id).first()
    if syllabus is None or not syllabus.file:
        return None
    try:
        with syllabus.file.open('rb') as handle:
            text = extract_text(handle, syllabus.original_name or syllabus.file.name)
    except (ExtractionError, OSError):
        status, text = Syllabus.Status.FAILED, ''
    else:
        status = Syllabus.Status.READY if text else Syllabus.Status.EMPTY
    Syllabus.objects.filter(pk=syllabus.pk).update(text=text, status=status)
    return status
