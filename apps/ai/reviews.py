"""Calificación sugerida por IA (T5c): pedirla, generarla (en Celery), confirmarla o descartarla.

Regla de oro: la IA sugiere, el docente decide. Una sugerencia no es una calificación: el alumno no ve nada y el promedio
no cambia hasta que el docente la confirma (una por una, editándola si quiere, o en bloque las que traen evidencia en
todos los puntos). A la IA viaja solo el cuerpo del trabajo, **depurado** (``redaction``), y un token al azar por
solicitud; nunca la portada ni datos del alumno.
"""

import datetime
import hashlib
import logging
import secrets
from collections import Counter
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.courses.models import Enrollment
from apps.grades.models import Grade, GradeHistory, Submission
from apps.grades.services.gradebook import grade_activity

from . import drafts, services
from . import review_generation as gen
from .models import AIRequest, AIReview
from .redaction import redactor_for

logger = logging.getLogger(__name__)

MAX_PER_REQUEST = 50
STALE_AFTER = datetime.timedelta(minutes=10)
BUCKETS = ((0, 'menos de 60 %'), (60, '60–69'), (70, '70–79'), (80, '80–89'), (90, '90–100'))


# ── Qué se puede revisar ──────────────────────────────────────────────

def body_of(submission):
    """``(texto, motivo)``: el trabajo de una entrega, o por qué no se puede revisar (``texto`` vacío)."""
    if submission.read_status in (Submission.ReadStatus.PARTIAL, Submission.ReadStatus.EMPTY):
        reason = 'Legible a medias' if submission.read_status == Submission.ReadStatus.PARTIAL else 'Sin cuerpo'
        return '', reason
    body = (submission.body_text if submission.read_status else submission.text).strip()
    if not body:
        return '', 'Sin texto que revisar'
    if len(body) > gen.MAX_BODY_CHARS:
        return '', 'Demasiado largo'
    return body, ''


def overview(activity):
    """Las entregas de la actividad que se pueden pedir a la IA (``ready``) y cuántas no y por qué (``skipped``).

    Cuentan solo las que no tienen calificación ni una revisión ya pedida.
    """
    graded = set(Grade.objects.filter(activity=activity).values_list('student_id', flat=True))
    reviewed = set(AIReview.objects.filter(submission__activity=activity).values_list('submission_id', flat=True))
    ready, skipped = [], Counter()
    for submission in Submission.objects.filter(activity=activity).select_related('student').order_by('student__last_name', 'student__first_name'):
        if submission.student_id in graded or submission.pk in reviewed:
            continue
        _, reason = body_of(submission)
        if reason:
            skipped[reason] += 1
        else:
            ready.append(submission)
    return ready, skipped


def reviews_of(activity):
    return AIReview.objects.filter(submission__activity=activity).select_related('submission__student', 'submission__activity')


# ── Pedir ─────────────────────────────────────────────────────────────

def _enqueue(review_id):
    from . import tasks

    transaction.on_commit(lambda: tasks.run_review.delay(review_id))


def request_reviews(activity, user):
    """Deja en marcha la revisión de las entregas listas. Devuelve ``(revisiones creadas, entregas que no cupieron)``.

    Cada trabajo revisado gasta un uso de la cuota mensual del plan; si no alcanza para todas se piden las primeras.
    """
    activity.course.ensure_editable()
    services.check_available(activity.organization)
    ready, _ = overview(activity)
    if not ready:
        raise ValidationError('No hay entregas listas para revisar con IA.')
    summary = services.usage_summary(activity.organization)
    room = MAX_PER_REQUEST if summary['remaining'] is None else min(MAX_PER_REQUEST, summary['remaining'])
    created = []
    with transaction.atomic():
        for submission in ready[:room]:
            review, was_created = AIReview.objects.get_or_create(submission=submission, defaults={'requested_by': user})
            if was_created:
                created.append(review)
                _enqueue(review.pk)
    return created, len(ready) - len(created)


def retry(review, *, user):
    """Vuelve a pedir una revisión que falló o que el docente descartó."""
    with transaction.atomic():
        locked = AIReview.objects.select_for_update().get(pk=review.pk)
        if locked.status not in (AIReview.Status.FAILED, AIReview.Status.DISCARDED):
            raise ValidationError('Esta revisión no está en un estado que se pueda volver a pedir.')
        activity = locked.submission.activity
        activity.course.ensure_editable()
        services.check_available(activity.organization)
        if Grade.objects.filter(activity=activity, student=locked.submission.student).exists():
            raise ValidationError('Este alumno ya tiene calificación.')
        _, reason = body_of(locked.submission)
        if reason:
            raise ValidationError(f'{reason}: califícala a mano.')
        locked.status, locked.error, locked.requested_by = AIReview.Status.QUEUED, '', user
        locked.score, locked.feedback, locked.aspects, locked.token = None, '', [], ''
        locked.save()
        _enqueue(locked.pk)


def expire_stale(activity, now=None):
    """Si el trabajo en segundo plano se perdió (el servidor se reinició), no dejar al docente esperando para siempre."""
    now = now or timezone.now()
    AIReview.objects.filter(
        submission__activity=activity, status=AIReview.Status.QUEUED, updated_at__lt=now - STALE_AFTER,
    ).update(
        status=AIReview.Status.FAILED, error='La revisión tardó demasiado y se canceló. No se descontó ningún uso. Intenta de nuevo.',
    )


# ── Correr (Celery) ───────────────────────────────────────────────────

def _fail(review_id, message):
    AIReview.objects.filter(pk=review_id, status=AIReview.Status.QUEUED).update(
        status=AIReview.Status.FAILED, error=message[:300], updated_at=timezone.now(),
    )


def _ask(review):
    """Depura el trabajo, lo manda a la IA y devuelve ``(resultado validado, token, caracteres, huella, sustituciones)``."""
    submission = review.submission
    activity = submission.activity
    body, reason = body_of(submission)
    if reason:
        raise gen.ReviewError(f'{reason}: califícala a mano.')
    classmates = [e.student for e in Enrollment.objects.filter(course=activity.course).select_related('student')]
    redactor = redactor_for(submission.student, classmates, activity.course.professor)
    clean_body = redactor.apply(body)
    token = secrets.token_hex(8)
    prompt = gen.build_prompt(
        redactor.apply(activity.title).text, redactor.apply(activity.instructions).text, activity.max_score, clean_body.text, token,
    )
    data = drafts._generate(
        organization=review.organization, user=review.requested_by, kind=AIRequest.Kind.GRADE_REVIEW, prompt=prompt,
        schema=gen.SCHEMA, system=gen.SYSTEM, contains_student_data=True,
    )
    result = gen.parse_result(data, token=token, body=clean_body.text, max_score=activity.max_score)
    sent = f'{gen.SYSTEM}\n{prompt}'
    return result, token, len(sent), hashlib.sha256(sent.encode('utf-8')).hexdigest(), clean_body.replacements


def run(review_id):
    """Pide la calificación a la IA y guarda la sugerencia. Si algo falla queda «No se pudo», con el motivo."""
    review = AIReview.objects.select_related(
        'submission__student', 'submission__activity__course__professor', 'requested_by',
    ).filter(pk=review_id, status=AIReview.Status.QUEUED).first()
    if review is None:
        return
    try:
        result, token, chars, digest, replacements = _ask(review)
    except (services.AIUnavailable, services.AIFailed, gen.ReviewError) as error:
        _fail(review_id, ' '.join(error.messages))
        return
    except Exception:
        logger.exception('No se pudo revisar la entrega %s con IA', review.submission_id)
        _fail(review_id, 'Ocurrió un error inesperado al revisar este trabajo. Intenta de nuevo.')
        return
    with transaction.atomic():
        current = AIReview.objects.select_for_update().filter(pk=review_id).first()
        if current is None or current.status != AIReview.Status.QUEUED:  # lo descartaron mientras la IA pensaba
            return
        current.status, current.error = AIReview.Status.SUGGESTED, ''
        current.token, current.input_chars, current.input_hash, current.replacements = token, chars, digest, replacements
        current.score, current.feedback, current.aspects = result['score'], result['feedback'], result['aspects']
        current.save()


# ── Decidir ───────────────────────────────────────────────────────────

def parse_score(raw):
    """Calificación escrita por el docente (acepta coma decimal) o ``ValidationError``."""
    try:
        value = Decimal(str(raw).strip().replace(',', '.'))
        if not value.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        raise ValidationError('Escribe la calificación como un número.') from None
    return float(value)


def confirm(review, *, user, score=None, feedback=None, bulk=False):
    """Convierte la sugerencia en la calificación del alumno. ``score`` y ``feedback`` son lo que el docente corrigió."""
    with transaction.atomic():
        locked = AIReview.objects.select_for_update().get(pk=review.pk)
        if locked.status != AIReview.Status.SUGGESTED:
            raise ValidationError('Esta sugerencia ya no está pendiente.')
        submission = locked.submission
        activity, student = submission.activity, submission.student
        if Grade.objects.filter(activity=activity, student=student).exists():
            raise ValidationError(f'{student} ya tiene calificación. Descarta la sugerencia.')
        value = locked.score if score is None else score
        grade_activity(
            activity, student, score=value, feedback=locked.feedback if feedback is None else feedback, by=user,
            origin=GradeHistory.Origin.AI_BULK if bulk else GradeHistory.Origin.AI,
        )
        locked.status, locked.final_score = AIReview.Status.CONFIRMED, value
        locked.confirmed_by, locked.confirmed_at, locked.confirmed_in_bulk = user, timezone.now(), bulk
        locked.save()


def discard(review):
    with transaction.atomic():
        locked = AIReview.objects.select_for_update().get(pk=review.pk)
        if locked.status in (AIReview.Status.CONFIRMED, AIReview.Status.DISCARDED):
            raise ValidationError('Esta sugerencia ya no está pendiente.')
        locked.status = AIReview.Status.DISCARDED
        locked.save()


def bulk_candidates(activity):
    """Sugerencias que se pueden confirmar sin cambios: con evidencia en todos los puntos y sin calificación previa."""
    graded = set(Grade.objects.filter(activity=activity).values_list('student_id', flat=True))
    return [
        review for review in reviews_of(activity).filter(status=AIReview.Status.SUGGESTED)
        if review.fully_evidenced and review.submission.student_id not in graded
    ]


def bulk_summary(reviews, max_score):
    """Lo que se le muestra al docente antes de confirmar en bloque: cuántas, promedio y distribución por porcentaje."""
    scores = [review.score for review in reviews]
    buckets = [0] * len(BUCKETS)
    for value in scores:
        percent = value * 100 / max_score if max_score else 0
        buckets[max(i for i, (start, _) in enumerate(BUCKETS) if percent >= start)] += 1
    tallest = max(buckets, default=0)
    return {
        'count': len(scores), 'average': round(sum(scores) / len(scores), 2) if scores else None,
        'distribution': [
            {'label': label, 'count': count, 'height': round(count * 100 / tallest) if tallest else 0}
            for (_, label), count in zip(BUCKETS, buckets)
        ],
    }


def confirm_bulk(activity, user):
    """Confirma sin cambios las sugerencias con evidencia completa. Devuelve ``(confirmadas, [(alumno, motivo)])``."""
    saved, skipped = 0, []
    for review in bulk_candidates(activity):
        try:
            confirm(review, user=user, bulk=True)
        except ValidationError as error:
            skipped.append((str(review.submission.student), ' '.join(error.messages)))
        else:
            saved += 1
    return saved, skipped
