"""El lote de PDFs de una actividad: subir, identificar, asignar a mano, descartar y guardar como entregas."""

import os
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.courses.models import Student
from apps.grades.models import MAX_SUBMISSION_BYTES, Grade, Submission
from apps.grades.services.submissions import clean_filename

from ..models import BatchFile
from . import identify
from .pdfs import UnreadablePdf, read_pdf

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
    """Sube los PDFs, lee sus portadas y deja cada uno con su estado. No toca ninguna entrega todavía."""
    activity.course.ensure_editable()
    if not activity.accepts_submissions:
        raise ValidationError('Esta actividad no recibe entregas.')
    check_batch(activity, files)

    result = UploadResult()
    students = course_students(activity)
    touched = set()
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
        _identify(batch_file, students)
        batch_file.save()
        if batch_file.student_id:
            touched.add(batch_file.student_id)
        result.created.append(batch_file)

    for student in Student.objects.filter(pk__in=touched):
        settle_student(activity, student)
    for batch_file in result.created:
        batch_file.refresh_from_db()
    return result


def _identify(batch_file, students):
    """Pone el estado inicial según lo que diga la portada (el duplicado y el conflicto los decide ``settle_student``)."""
    if not batch_file.cover_pages:
        batch_file.status, batch_file.problem = BatchFile.Status.UNIDENTIFIED, 'La actividad no tiene páginas de portada.'
        return
    if not batch_file.cover_text:
        batch_file.status = BatchFile.Status.UNIDENTIFIED
        batch_file.problem = 'La portada no tiene texto (¿es una imagen?).'
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
    submission.save()
    # El archivo ahora es de la entrega: la fila del lote se va sin que su señal lo borre del almacenamiento.
    BatchFile.objects.filter(pk=batch_file.pk).update(file='')
    BatchFile.objects.filter(pk=batch_file.pk).delete()
    return old_name if old_name != submission.file.name else ''
