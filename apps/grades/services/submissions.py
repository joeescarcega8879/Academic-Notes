"""Entregas de los alumnos: reglas de cuándo y cómo se puede entregar."""

import os
import re

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.courses.models import Enrollment

from ..models import Grade, Submission


def clean_filename(name):
    """Nombre del archivo tal como se mostrará: sin ruta ni caracteres de control, de largo acotado."""
    base = os.path.basename((name or '').replace('\\', '/'))
    return re.sub(r'[\x00-\x1f\x7f]', '', base)[:255]


def submission_state(activity, now=None):
    """Estado de la ventana de entrega: ``open``, ``late`` (abierta pero con penalización), ``not_open`` o ``closed``."""
    now = now or timezone.now()
    if activity.opens_at and now < activity.opens_at:
        return 'not_open'
    if activity.due_at and now > activity.due_at:
        return 'late' if activity.allow_late else 'closed'
    return 'open'


def submit(activity, student, *, text='', link='', file=None, now=None):
    """Registra o actualiza la entrega de ``student``. Lanza ``ValidationError`` con un mensaje para el alumno."""
    now = now or timezone.now()
    activity.course.ensure_editable()
    if not activity.published or not activity.accepts_submissions:
        raise ValidationError('Esta actividad no recibe entregas.')
    if not Enrollment.objects.filter(student=student, course=activity.course).exists():
        raise ValidationError('No estás inscrito en este grupo.')

    state = submission_state(activity, now)
    if state == 'not_open':
        raise ValidationError('La actividad todavía no abre.')
    if state == 'closed':
        raise ValidationError('La fecha límite ya pasó y esta actividad no acepta entregas tardías.')

    existing = Submission.objects.filter(activity=activity, student=student).first()
    if existing is not None and Grade.objects.filter(activity=activity, student=student).exists():
        raise ValidationError('Tu entrega ya fue calificada y no se puede cambiar.')

    with transaction.atomic():
        submission = existing or Submission(activity=activity, student=student)
        old_file = submission.file.name if existing and submission.file else ''
        submission.text = text.strip()
        submission.link = link.strip()
        if file is not None:
            submission.file = file
            submission.original_name = clean_filename(file.name)
        submission.submitted_at = now
        submission.is_late = state == 'late'
        submission.full_clean()
        submission.save()

    if old_file and file is not None:
        submission.file.storage.delete(old_file)  # el archivo anterior ya no hace falta
    return submission
