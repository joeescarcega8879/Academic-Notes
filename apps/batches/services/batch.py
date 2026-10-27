"""El lote de PDFs de una actividad: subir, leer, identificar, asignar a mano, descartar y guardar como entregas."""

import logging
import os
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.grades.models import MAX_SUBMISSION_BYTES, Activity, Grade, Submission
from apps.grades.services.submissions import clean_filename

from ..models import BatchFile
from . import identify, ocr, reading
from .pdfs import MAX_COVER_CHARS, UnreadablePdf, read_pdf

logger = logging.getLogger(__name__)

MAX_BATCH_BYTES = 50 * 1024 * 1024  # lo que se puede subir de una vez
MAX_BATCH_FILES = 80  # archivos por subida
MAX_PENDING_FILES = 200  # archivos esperando confirmación en una actividad

LIVE = (BatchFile.Status.READY, BatchFile.Status.DUPLICATE, BatchFile.Status.CONFLICT)


@dataclass
class UploadResult:
    created: list = field(default_factory=list)
    rejected: list = field(default_factory=list)  # (nombre, motivo): ni siquiera entran a la lista


def check_batch(activity, files):
    """Revisa los topes de una subida completa; lanza ``ValidationError`` con el motivo."""
    if not files:
        raise ValidationError('Elige al menos un archivo PDF.')
    if len(files) > MAX_BATCH_FILES:
        raise ValidationError(f'Sube hasta {MAX_BATCH_FILES} archivos a la vez.')
    if sum(f.size for f in files) > MAX_BATCH_BYTES:
        raise ValidationError(f'La subida pesa más de {MAX_BATCH_BYTES // (1024 * 1024)} MB. Divídela en lotes más chicos.')
    if BatchFile.objects.filter(activity=activity).count() + len(files) > MAX_PENDING_FILES:
        raise ValidationError(
            f'Ya hay muchos archivos esperando (máximo {MAX_PENDING_FILES} por actividad). Guarda o descarta algunos primero.',
        )


def course_students(activity):
    return [e.student for e in activity.course.enrollments.select_related('student')]


def upload(activity, files, *, cover_pages, user=None):
    """Sube los PDFs y deja cada uno «Leyendo»; ``process_file`` (en Celery) los lee y les da su estado.

    No toca ninguna entrega todavía.
    """
    activity.course.ensure_editable()
    if not activity.accepts_submissions or activity.by_teams:
        raise ValidationError('Esta actividad no recibe entregas.')
    check_batch(activity, files)

    result = UploadResult()
    new_ids = []
    for uploaded in files:
        name = clean_filename(uploaded.name) or 'archivo.pdf'
        if os.path.splitext(name)[1].lower() != '.pdf':
            result.rejected.append((name, 'Solo se aceptan archivos PDF.'))
            continue
        if uploaded.size > MAX_SUBMISSION_BYTES:
            result.rejected.append((name, f'Pesa más de {MAX_SUBMISSION_BYTES // (1024 * 1024)} MB.'))
            continue
        batch_file = BatchFile(
            activity=activity, uploaded_by=user, original_name=name, size=uploaded.size, cover_pages=cover_pages,
        )
        try:
            info = read_pdf(uploaded, cover_pages)
        except UnreadablePdf as error:
            batch_file.status = BatchFile.Status.UNREADABLE
            batch_file.problem = str(error)
            batch_file.save()
            result.created.append(batch_file)
            continue

        batch_file.pages, batch_file.cover_text = info.pages, info.cover_text
        batch_file.file = uploaded
        batch_file.status = BatchFile.Status.READING
        batch_file.save()
        new_ids.append(batch_file.pk)
        result.created.append(batch_file)

    for pk in new_ids:
        _enqueue(pk)
    for batch_file in result.created:
        batch_file.refresh_from_db()
    return result


def _enqueue(pk):
    from .. import tasks

    try:
        tasks.read_batch_file.delay(pk)
    except Exception:  # sin broker no se puede encolar: se lee ahora, en lugar de dejar el archivo «Leyendo» para siempre
        logger.exception('No se pudo encolar la lectura del archivo %s del lote', pk)
        process_file(pk)


def process_file(pk):
    """Lee un archivo recién subido (la portada escaneada y el cuerpo, con OCR si hace falta) y le da su estado."""
    batch_file = BatchFile.objects.filter(pk=pk, status=BatchFile.Status.READING).first()
    if batch_file is None:  # lo descartaron mientras esperaba, o ya se leyó
        return
    try:
        with batch_file.file.open('rb') as handle:
            data = handle.read()
        cover_text = batch_file.cover_text
        ocr_tried = bool(batch_file.cover_pages and not cover_text and ocr.available())
        if ocr_tried:
            cover_text = reading.ocr_cover(data, batch_file.cover_pages)
        body = reading.read_body(data, batch_file.cover_pages)
    except Exception:
        logger.exception('No se pudo leer el archivo %s del lote', pk)
        BatchFile.objects.filter(pk=pk, status=BatchFile.Status.READING).update(
            status=BatchFile.Status.UNREADABLE, problem='No se pudo leer el contenido del archivo.',
        )
        return

    with transaction.atomic():
        # Un archivo a la vez por actividad decide de quién es: así dos del mismo alumno se ven como duplicados.
        activity = Activity.objects.select_for_update(of=('self',)).select_related('course').get(pk=batch_file.activity_id)
        batch_file = BatchFile.objects.select_for_update().filter(pk=pk, status=BatchFile.Status.READING).first()
        if batch_file is None:
            return
        batch_file.cover_text = cover_text[:MAX_COVER_CHARS]
        batch_file.body_text, batch_file.body_status = body.text, body.status
        batch_file.ocr_confidence, batch_file.body_note = body.confidence, body.note
        _identify(batch_file, course_students(activity), ocr_tried=ocr_tried)
        batch_file.save()
        if batch_file.student_id:
            settle_student(activity, batch_file.student)


def _identify(batch_file, students, *, ocr_tried=False):
    """Pone el estado inicial según lo que diga la portada (el duplicado y el conflicto los decide ``settle_student``)."""
    if not batch_file.cover_pages:
        batch_file.status, batch_file.problem = BatchFile.Status.UNIDENTIFIED, 'La actividad no tiene páginas de portada.'
        return
    if not batch_file.cover_text:
        batch_file.status = BatchFile.Status.UNIDENTIFIED
        if ocr_tried:
            batch_file.problem = 'No se pudo leer texto en la portada, ni con OCR.'
        elif ocr.available():
            batch_file.problem = 'La portada no tiene texto (¿es una imagen?).'
        else:
            batch_file.problem = 'La portada no tiene texto (¿es una imagen?) y este servidor no tiene OCR para leerla.'
        return
    matches = identify.match_students(batch_file.cover_text, students)
    if len(matches) == 1:
        student = matches[0]
        batch_file.status, batch_file.student = BatchFile.Status.READY, student
        batch_file.identified_by = BatchFile.IdentifiedBy.COVER
        batch_file.name_mismatch = not identify.name_matches(batch_file.cover_text, student)
    elif matches:
        batch_file.status = BatchFile.Status.UNIDENTIFIED
        batch_file.problem = 'La portada trae la matrícula de varios alumnos del grupo.'
    else:
        batch_file.status = BatchFile.Status.UNIDENTIFIED
        batch_file.problem = 'No se encontró la matrícula de ningún alumno del grupo.'


def settle_student(activity, student):
    """Recalcula el estado de los archivos pendientes de un alumno: listo, duplicado o con una entrega ya hecha."""
    files = list(BatchFile.objects.filter(activity=activity, student=student, status__in=LIVE))
    if not files:
        return
    if len(files) > 1:
        for batch_file in files:
            batch_file.status, batch_file.replace = BatchFile.Status.DUPLICATE, False
            batch_file.problem = 'Hay más de un archivo de este alumno. Descarta o reasigna los que sobren.'
            batch_file.save(update_fields=['status', 'replace', 'problem'])
        return

    batch_file = files[0]
    existing = Submission.objects.filter(activity=activity, student=student).first()
    if existing is None:
        status, problem, replace = BatchFile.Status.READY, '', False
    elif Grade.objects.filter(activity=activity, student=student).exists():
        status, replace = BatchFile.Status.CONFLICT, False
        problem = 'Ya entregó y su entrega está calificada: no se puede reemplazar.'
    elif batch_file.replace:
        status, problem, replace = BatchFile.Status.READY, '', True
    else:
        status, replace = BatchFile.Status.CONFLICT, False
        problem = 'Ya entregó por el portal. Puedes reemplazar su archivo o descartar este.'
    batch_file.status, batch_file.problem, batch_file.replace = status, problem, replace
    batch_file.save(update_fields=['status', 'problem', 'replace'])


def assign(batch_file, student, *, replace=False):
    """El docente dice de quién es el archivo (o, con ``replace``, que sustituya la entrega que el alumno ya hizo)."""
    activity = batch_file.activity
    activity.course.ensure_editable()
    if batch_file.status == BatchFile.Status.UNREADABLE:
        raise ValidationError('Este archivo no se pudo leer: quítalo y súbelo de nuevo.')
    if batch_file.status == BatchFile.Status.READING:
        raise ValidationError('Este archivo todavía se está leyendo: espera a que termine.')
    if not activity.course.enrollments.filter(student=student).exists():
        raise ValidationError('Ese alumno no está en el grupo.')
    previous = batch_file.student
    batch_file.student, batch_file.identified_by = student, BatchFile.IdentifiedBy.MANUAL
    batch_file.name_mismatch, batch_file.replace = False, replace
    batch_file.status = BatchFile.Status.READY  # provisional: ``settle_student`` decide
    batch_file.save(update_fields=['student', 'identified_by', 'name_mismatch', 'replace', 'status'])
    settle_student(activity, student)
    if previous is not None and previous.pk != student.pk:
        settle_student(activity, previous)
    batch_file.refresh_from_db()
    return batch_file


def discard(batch_file):
    """Quita el archivo del lote (y de disco); a los demás del mismo alumno se les recalcula el estado."""
    activity, student = batch_file.activity, batch_file.student
    activity.course.ensure_editable()
    batch_file.delete()  # la señal post_delete borra el archivo
    if student is not None:
        settle_student(activity, student)


@dataclass
class ApplyResult:
    saved: int = 0
    skipped: list = field(default_factory=list)  # (nombre del archivo, motivo)


def apply(activity, *, now=None):
    """Convierte en entregas los archivos identificados. Lo que ya no se pueda guardar se queda en la lista con su motivo."""
    activity.course.ensure_editable()
    now = now or timezone.now()
    result = ApplyResult()
    for batch_file in BatchFile.objects.filter(activity=activity, status=BatchFile.Status.READY).select_related('student'):
        try:
            with transaction.atomic():
                replaced_file = _save_submission(batch_file, now)
        except ValidationError as error:
            result.skipped.append((batch_file.original_name, ' '.join(error.messages)))
            settle_student(activity, batch_file.student)
        else:
            result.saved += 1
            if replaced_file:  # ya con la entrega confirmada en la base: el archivo anterior no hace falta
                Submission._meta.get_field('file').storage.delete(replaced_file)
    return result


def _save_submission(batch_file, now):
    """Guarda la entrega del archivo. Devuelve el nombre del archivo que reemplazó (si lo hubo) para borrarlo después."""
    activity, student = batch_file.activity, batch_file.student
    existing = Submission.objects.select_for_update().filter(activity=activity, student=student).first()
    old_name = ''
    if existing is None:
        submission = Submission(activity=activity, student=student, submitted_at=now, is_late=False)
    elif not batch_file.replace:
        raise ValidationError('El alumno entregó mientras tanto: revisa este archivo.')
    elif Grade.objects.filter(activity=activity, student=student).exists():
        raise ValidationError('La entrega del alumno ya está calificada.')
    else:
        submission = existing
        old_name = existing.file.name if existing.file else ''

    submission.file.name = batch_file.file.name  # el mismo archivo en disco: no se copia
    submission.original_name = batch_file.original_name
    submission.body_text, submission.read_status = batch_file.body_text, batch_file.body_status
    submission.ocr_confidence = batch_file.ocr_confidence
    submission.save()
    # El archivo ahora es de la entrega: la fila del lote se va sin que su señal lo borre del almacenamiento.
    BatchFile.objects.filter(pk=batch_file.pk).update(file='')
    BatchFile.objects.filter(pk=batch_file.pk).delete()
    return old_name if old_name != submission.file.name else ''
