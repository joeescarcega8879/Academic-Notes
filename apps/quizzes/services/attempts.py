"""Intentos de un quiz: empezar, guardar respuestas, enviar y cerrar por tiempo.

El plazo de un intento lo fija el servidor al empezar y se guarda; el navegador solo lo muestra. Todo lo que
llegue después se rechaza y el intento se cierra con lo que ya estaba guardado. Un intento vencido se cierra
solo la próxima vez que alguien lo toca (o con la tarea periódica de cierre).
"""

import logging
import random
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.courses.models import Enrollment

from ..models import Answer, Question, QuizAttempt
from . import answers as answer_service
from . import results
from .exams import noun

logger = logging.getLogger(__name__)

# Margen por latencia de red: un envío que llega unos segundos tarde se acepta; más allá, no.
GRACE_SECONDS = 5


class AttemptExpired(Exception):
    """El intento ya terminó (o se acabó el tiempo). ``attempt`` es el intento ya cerrado."""

    def __init__(self, attempt):
        super().__init__('El intento ya terminó.')
        self.attempt = attempt


# ── Ventana de disponibilidad ─────────────────────────────────────────

def window_state(activity, now=None):
    """``open``, ``not_open`` o ``closed``. Un quiz o examen no admite intentos nuevos después de su fecha límite."""
    now = now or timezone.now()
    if activity.opens_at and now < activity.opens_at:
        return 'not_open'
    if activity.due_at and now > activity.due_at:
        return 'closed'
    return 'open'


def compute_deadline(quiz, started_at):
    """El plazo del intento: el tiempo límite desde que empieza o la fecha de cierre, lo que ocurra antes."""
    candidates = []
    if quiz.time_limit_minutes:
        candidates.append(started_at + timedelta(minutes=quiz.time_limit_minutes))
    if quiz.activity.due_at:
        candidates.append(quiz.activity.due_at)
    return min(candidates) if candidates else None


def remaining_seconds(attempt, now=None):
    """Segundos que le quedan al intento (0 si ya pasó el plazo, None si no tiene límite)."""
    if attempt.deadline is None:
        return None
    now = now or timezone.now()
    return max(0, int((attempt.deadline - now).total_seconds()))


def build_layout(quiz, rng=None):
    """Orden de las preguntas y de las opciones de cada una, fijado al empezar el intento."""
    rng = rng or random.SystemRandom()
    questions = list(quiz.questions.prefetch_related('choices'))
    if quiz.shuffle_questions:
        rng.shuffle(questions)
    choices = {}
    for question in questions:
        if question.kind not in answer_service.CHOICE_KINDS:
            continue  # lo que hay en sus «opciones» (las respuestas aceptadas, por ejemplo) no se le muestra al alumno
        ids = [c.pk for c in question.choices.all()]
        # Verdadero/Falso conserva su orden natural: barajarlo solo confunde.
        if quiz.shuffle_choices and question.kind == Question.Kind.MULTIPLE_CHOICE:
            rng.shuffle(ids)
        choices[str(question.pk)] = ids
    return {'questions': [q.pk for q in questions], 'choices': choices}


# ── Cierre y calificación de un intento ───────────────────────────────

def score_attempt(attempt):
    """Marca cada respuesta como correcta o no y suma los puntos del intento (sin tocar la libreta)."""
    answers = {a.question_id: a for a in attempt.answers.select_related('choice')}
    total, earned = Decimal(0), Decimal(0)
    for question in attempt.quiz.questions.all():
        total += question.points
        answer = answers.get(question.pk)
        if answer is None:
            answer = Answer(attempt=attempt, question=question)
        correct, points = answer_service.grade(question, answer)
        answer.is_correct = correct
        answer.points_awarded = points
        answer.save()
        earned += points
    attempt.score, attempt.max_points = earned, total


@transaction.atomic
def finalize_attempt(attempt, *, expired=False, now=None):
    """Cierra un intento en curso y lo califica. Si ya estaba cerrado, no hace nada (enviar dos veces es inofensivo)."""
    attempt = QuizAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != QuizAttempt.Status.IN_PROGRESS:
        return attempt
    now = now or timezone.now()
    score_attempt(attempt)
    attempt.status = QuizAttempt.Status.EXPIRED if expired else QuizAttempt.Status.SUBMITTED
    # Un intento cerrado por tiempo termina en su plazo, no en el momento en que alguien lo descubre.
    attempt.submitted_at = attempt.deadline if expired and attempt.deadline else now
    attempt.save()
    try:
        results.sync_grade(attempt.quiz, attempt.student)
    except ValidationError:
        pass  # p. ej. el grupo se archivó mientras respondía: el intento queda calificado, la libreta no cambia
    return attempt


def expire_if_overdue(attempt, now=None):
    """Cierra por tiempo un intento en curso cuyo plazo ya pasó; devuelve el intento (actualizado)."""
    now = now or timezone.now()
    if attempt.status == QuizAttempt.Status.IN_PROGRESS and attempt.deadline and now > attempt.deadline:
        return finalize_attempt(attempt, expired=True, now=now)
    return attempt


def close_overdue_attempts(now=None):
    """Cierra y califica todos los intentos en curso cuyo plazo ya pasó. Devuelve cuántos cerró por tiempo.

    Es una tarea de mantenimiento que recorre todas las organizaciones a propósito. Espera el margen de red
    antes de cerrar, para no adelantarse a un envío legítimo que viene en camino. Un intento problemático se
    registra y no detiene a los demás.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(seconds=GRACE_SECONDS)
    pending = list(
        QuizAttempt.objects.filter(status=QuizAttempt.Status.IN_PROGRESS, deadline__lt=cutoff).values_list('pk', flat=True)
    )
    closed = 0
    for pk in pending:
        attempt = QuizAttempt.objects.filter(pk=pk).first()
        if attempt is None:
            continue
        try:
            if finalize_attempt(attempt, expired=True, now=now).status == QuizAttempt.Status.EXPIRED:
                closed += 1
        except Exception:  # noqa: BLE001 - un intento con problemas no debe frenar el cierre de los demás
            logger.exception('No se pudo cerrar el intento %s', pk)
    return closed


# ── Empezar ───────────────────────────────────────────────────────────

def attempts_used(quiz, student):
    return quiz.attempts.filter(student=student).count()


def start_attempt(quiz, student, now=None):
    """Empieza un intento o retoma el que está en curso. Lanza ``ValidationError`` con un mensaje para el alumno.

    No es atómica a propósito: cerrar por tiempo un intento vencido debe confirmarse aunque después se
    rechace el nuevo intento (por ejemplo, porque ya no quedan).
    """
    now = now or timezone.now()
    activity = quiz.activity

    # Un intento abierto se retoma (o, si ya venció, se cierra y consume su intento).
    open_attempt = quiz.attempts.filter(student=student, status=QuizAttempt.Status.IN_PROGRESS).first()
    if open_attempt is not None:
        open_attempt = expire_if_overdue(open_attempt, now)
        if open_attempt.status == QuizAttempt.Status.IN_PROGRESS:
            return open_attempt

    activity.course.ensure_editable()
    if not activity.published:
        raise ValidationError(f'Este {noun(activity)} no está disponible.')
    if not Enrollment.objects.filter(student=student, course=activity.course).exists():
        raise ValidationError('No estás inscrito en este grupo.')
    state = window_state(activity, now)
    if state == 'not_open':
        raise ValidationError(f'El {noun(activity)} todavía no abre.')
    if state == 'closed':
        raise ValidationError(f'El {noun(activity)} ya cerró.')
    if not quiz.questions.exists():
        raise ValidationError(f'El {noun(activity)} todavía no tiene preguntas.')
    used = attempts_used(quiz, student)
    if used >= quiz.attempts_allowed:
        raise ValidationError('Ya usaste todos tus intentos.')

    try:
        with transaction.atomic():
            return QuizAttempt.objects.create(
                quiz=quiz, student=student, number=used + 1, started_at=now,
                deadline=compute_deadline(quiz, now), layout=build_layout(quiz),
            )
    except IntegrityError:  # dos pestañas empezaron a la vez: gana la primera
        return quiz.attempts.get(student=student, status=QuizAttempt.Status.IN_PROGRESS)


# ── Responder ─────────────────────────────────────────────────────────

@transaction.atomic
def save_answers(attempt, selections, now=None):
    """Guarda respuestas parciales: ``{id de pregunta: respuesta}``. Devuelve los segundos restantes.

    La respuesta es el id de la opción (opción múltiple y verdadero o falso) o el texto (respuesta corta); ``None``
    la borra. Pasado el plazo (más el margen) no se guarda nada y el intento se cierra con lo que ya había.
    """
    now = now or timezone.now()
    attempt = QuizAttempt.objects.select_for_update().get(pk=attempt.pk)
    if attempt.status != QuizAttempt.Status.IN_PROGRESS:
        raise AttemptExpired(attempt)
    if attempt.deadline and now > attempt.deadline + timedelta(seconds=GRACE_SECONDS):
        raise AttemptExpired(finalize_attempt(attempt, expired=True, now=now))

    questions = {q.pk: q for q in attempt.quiz.questions.prefetch_related('choices')}
    to_save = {}
    for question_id, value in selections.items():
        question = questions.get(question_id)
        if question is None:
            raise ValidationError(f'Hay una pregunta que no es de este {noun(attempt.quiz.activity)}.')
        stored = answer_service.coerce(question, value, {c.pk for c in question.choices.all()})
        if stored is not answer_service.IGNORE:
            to_save[question_id] = stored
    for question_id, defaults in to_save.items():
        Answer.objects.update_or_create(attempt=attempt, question_id=question_id, defaults=defaults)
    return remaining_seconds(attempt, now)


def submit_attempt(attempt, selections=None, now=None):
    """Envía el intento: guarda las últimas respuestas, lo cierra y lo califica. Enviar dos veces no hace nada."""
    now = now or timezone.now()
    try:
        if selections:
            save_answers(attempt, selections, now)
    except AttemptExpired as expired:
        return expired.attempt
    return finalize_attempt(attempt, now=now)
