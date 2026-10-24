"""Propuestas de IA: pedirlas, generarlas (en Celery), revisarlas y aplicarlas.

Regla de oro: la IA propone, el docente decide. Nada de lo generado existe como pregunta, quiz o semana hasta que el
docente lo aprueba y pulsa el botón; publicar el quiz sigue siendo un paso aparte.
"""

import datetime
import logging
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.grades.models import Activity
from apps.quizzes.models import Question, QuizConfig
from apps.quizzes.services import builder
from apps.quizzes.services.bank import questions_for_course, save_question, validate_choices
from apps.syllabus.models import Syllabus
from apps.syllabus.services import weeks as week_ops

from . import assignment_generation as task_gen
from . import quiz_generation as quiz_gen
from . import services, split_generation as split_gen
from .models import AIDraft, AIRequest

logger = logging.getLogger(__name__)

STALE_AFTER = datetime.timedelta(minutes=10)
BANK_SAMPLE = 500  # preguntas del banco contra las que se compara para avisar de parecidas
RETRY_DELAYS = (3, 8)  # segundos de espera antes de cada reintento cuando el proveedor falla por algo pasajero
PENDING, APPROVED, DISCARDED, REGENERATING, CREATED = 'pending', 'approved', 'discarded', 'regenerating', 'created'


def _generate(**kwargs):
    """``services.generate_json`` que reintenta si el proveedor falla por algo pasajero (servidor saturado, límite de uso).

    Cada intento fallido queda en ``AIRequest`` como error y no cuenta contra la cuota.
    """
    for delay in (*RETRY_DELAYS, None):
        try:
            return services.generate_json(**kwargs)
        except services.AIFailed as error:
            if delay is None or not error.retryable:
                raise
            time.sleep(delay)


def queryset_for(user, organization):
    """Las propuestas que ``user`` pidió en ``organization``."""
    return AIDraft.objects.for_organization(organization).filter(requested_by=user)


def open_quiz_drafts(user, organization, course, activity=None):
    """Propuestas de preguntas sin resolver de un quiz (o, sin ``activity``, las pedidas desde una semana)."""
    return queryset_for(user, organization).filter(
        course=course, kind=AIDraft.Kind.QUIZ_QUESTIONS, activity=activity,
        status__in=(AIDraft.Status.PENDING, AIDraft.Status.READY, AIDraft.Status.FAILED),
    )


def open_assignment_drafts(user, organization, course):
    """Propuestas de tareas sin resolver de un grupo."""
    return queryset_for(user, organization).filter(
        course=course, kind=AIDraft.Kind.ASSIGNMENTS,
        status__in=(AIDraft.Status.PENDING, AIDraft.Status.READY, AIDraft.Status.FAILED),
    )


def _enqueue(task_name, *args):
    from . import tasks

    task = getattr(tasks, task_name)
    transaction.on_commit(lambda: task.delay(*args))


@contextmanager
def locked(draft_id):
    """La propuesta bloqueada para cambiarla: la tarea de Celery y el docente no se pisan."""
    with transaction.atomic():
        yield AIDraft.objects.select_for_update().get(pk=draft_id)


# ── Pedir ─────────────────────────────────────────────────────────────

def request_quiz(*, user, organization, course, params, activity=None, title=''):
    """Crea la propuesta y encola su generación. Lanza ``AIUnavailable`` si la IA no se puede usar ahora."""
    services.check_available(organization)
    draft = AIDraft.objects.create(
        course=course, requested_by=user, kind=AIDraft.Kind.QUIZ_QUESTIONS, activity=activity,
        new_activity_title=title.strip()[:255], params=params,
    )
    _enqueue('run_draft', draft.pk)
    return draft


def request_assignments(*, user, organization, course, params):
    services.check_available(organization)
    draft = AIDraft.objects.create(course=course, requested_by=user, kind=AIDraft.Kind.ASSIGNMENTS, params=params)
    _enqueue('run_draft', draft.pk)
    return draft


def request_split(*, user, organization, course, params):
    services.check_available(organization)
    draft = AIDraft.objects.create(course=course, requested_by=user, kind=AIDraft.Kind.SYLLABUS_SPLIT, params=params)
    _enqueue('run_draft', draft.pk)
    return draft


def retry(draft):
    """Vuelve a intentar una propuesta que falló."""
    if draft.status != AIDraft.Status.FAILED:
        raise ValidationError('Esta propuesta no está en un estado que se pueda reintentar.')
    services.check_available(draft.organization)
    draft.status, draft.error, draft.items, draft.dropped = AIDraft.Status.PENDING, '', [], 0
    draft.save()
    _enqueue('run_draft', draft.pk)


def expire_if_stale(draft, now=None):
    """Si el trabajo en segundo plano se perdió (el servidor se reinició), no dejar al docente esperando para siempre."""
    now = now or timezone.now()
    if now - draft.updated_at < STALE_AFTER:
        return draft
    if draft.status == AIDraft.Status.PENDING:
        draft.status = AIDraft.Status.FAILED
        draft.error = 'La generación tardó demasiado y se canceló. No se descontó ningún uso. Intenta de nuevo.'
        draft.save()
    elif any(item.get('state') == REGENERATING for item in draft.items):
        for item in draft.items:
            if item.get('state') == REGENERATING:
                item['state'], item['note'] = PENDING, 'No se pudo regenerar a tiempo. Intenta de nuevo.'
        draft.save()
    return draft


# ── Generar (corre en Celery) ─────────────────────────────────────────

def run(draft_id):
    """Genera las propuestas. Nunca lanza: si algo falla la propuesta queda ``failed`` con un motivo legible."""
    draft = AIDraft.objects.select_related('course').filter(pk=draft_id, status=AIDraft.Status.PENDING).first()
    if draft is None:
        return None
    try:
        {
            AIDraft.Kind.QUIZ_QUESTIONS: _generate_quiz, AIDraft.Kind.ASSIGNMENTS: _generate_assignments,
            AIDraft.Kind.SYLLABUS_SPLIT: _generate_split,
        }[draft.kind](draft)
        draft.status = AIDraft.Status.READY
    except (services.AIUnavailable, services.AIFailed, quiz_gen.RequestError, split_gen.RequestError) as error:
        draft.status, draft.error = AIDraft.Status.FAILED, ' '.join(error.messages)[:300]
    except Exception:  # noqa: BLE001 - una tarea en segundo plano no debe dejar la propuesta «generando» para siempre
        logger.exception('Falló la generación de la propuesta de IA %s', draft_id)
        draft.status, draft.error = AIDraft.Status.FAILED, 'Algo salió mal al generar. Intenta de nuevo en unos minutos.'
    draft.save()
    return draft


def _weeks_of(draft):
    wanted = draft.params.get('week_ids', [])
    weeks = [week for week in quiz_gen.course_weeks(draft.course) if week.pk in wanted]
    if len(weeks) != len(wanted):
        raise quiz_gen.RequestError('Alguna de las semanas elegidas ya no existe. Vuelve a elegirlas.')
    return weeks


def _bank_sample(draft):
    questions = questions_for_course(draft.organization, draft.course).filter(is_archived=False)
    return list(questions.order_by('-updated_at').values_list('id', 'text')[:BANK_SAMPLE])


def _generate_quiz(draft):
    weeks = _weeks_of(draft)
    data = _generate(
        organization=draft.organization, user=draft.requested_by, kind=AIRequest.Kind.QUIZ,
        prompt=quiz_gen.build_prompt(draft.params, weeks), schema=quiz_gen.SCHEMA, system=quiz_gen.SYSTEM,
    )
    draft.items, draft.dropped = quiz_gen.parse_items(data, weeks, draft.params, existing=_bank_sample(draft))
    if not draft.items:
        raise quiz_gen.RequestError(
            'La IA no devolvió preguntas que se puedan usar (venían incompletas o no citaban el temario). '
            'Intenta de nuevo o elige otras semanas.'
        )


def _generate_assignments(draft):
    weeks = _weeks_of(draft)
    data = _generate(
        organization=draft.organization, user=draft.requested_by, kind=AIRequest.Kind.ASSIGNMENT,
        prompt=task_gen.build_prompt(draft.params, weeks), schema=task_gen.SCHEMA, system=task_gen.SYSTEM,
    )
    draft.items, draft.dropped = task_gen.parse_items(data, weeks, draft.params)
    if not draft.items:
        raise quiz_gen.RequestError(
            'La IA no devolvió alternativas que se puedan usar (venían incompletas o no citaban el temario). '
            'Intenta de nuevo o elige otras semanas.'
        )


def _generate_split(draft):
    syllabus = Syllabus.objects.filter(course=draft.course).first()
    if syllabus is None:
        raise split_gen.RequestError('El grupo ya no tiene temario.')
    split_gen.clean_params({}, syllabus)  # el texto pudo cambiar desde que se pidió
    data = _generate(
        organization=draft.organization, user=draft.requested_by, kind=AIRequest.Kind.SYLLABUS_SPLIT,
        prompt=split_gen.build_prompt(draft.params, syllabus.text), schema=split_gen.SCHEMA, system=split_gen.SYSTEM,
    )
    draft.items = split_gen.parse_weeks(data, syllabus.text)
    if not draft.items:
        raise split_gen.RequestError('La IA no pudo dividir este temario. Intenta de nuevo o arma las semanas a mano.')


# ── Regenerar una pregunta ────────────────────────────────────────────

def request_regeneration(draft, index, user):
    """Pide otra pregunta en lugar de la ``index``. Cuenta como un uso, como cualquier solicitud correcta."""
    services.check_available(draft.organization)
    with locked(draft.pk) as current:
        _require_reviewable(current)
        item = item_at(current, index)
        if item['state'] == REGENERATING:
            return current
        item['state'] = REGENERATING
        item.pop('note', None)
        current.save()
    _enqueue('regenerate_item', draft.pk, index)
    return current


def _label(item):
    return item.get('text') or item.get('title', '')


def _replacement(draft, old):
    """Otra propuesta en lugar de ``old``: ``(propuesta, aviso)``. Sin propuesta válida, ``(None, aviso)``."""
    weeks = _weeks_of(draft)
    avoid = [_label(item) for item in draft.items]  # también la que se cambia: se quiere otra distinta
    if draft.kind == AIDraft.Kind.ASSIGNMENTS:
        data = _generate(
            organization=draft.organization, user=draft.requested_by, kind=AIRequest.Kind.ASSIGNMENT,
            prompt=task_gen.build_prompt(draft.params, weeks, count=1, avoid=avoid), schema=task_gen.SCHEMA, system=task_gen.SYSTEM,
        )
        found, _ = task_gen.parse_items(data, weeks, draft.params, limit=1)
        return (found[0] if found else None), 'La IA no devolvió una alternativa válida. Intenta de nuevo.'
    data = _generate(
        organization=draft.organization, user=draft.requested_by, kind=AIRequest.Kind.QUIZ,
        prompt=quiz_gen.build_prompt(draft.params, weeks, count=1, mix=old['kind'], avoid=avoid),
        schema=quiz_gen.SCHEMA, system=quiz_gen.SYSTEM,
    )
    found, _ = quiz_gen.parse_items(data, weeks, draft.params, mix=old['kind'], limit=1, existing=_bank_sample(draft))
    return ({**found[0], 'points': old['points']} if found else None), 'La IA no devolvió una pregunta válida. Intenta de nuevo.'


def regenerate(draft_id, index):
    """Cambia la propuesta ``index`` por otra nueva (corre en Celery)."""
    draft = AIDraft.objects.select_related('course').filter(pk=draft_id, status=AIDraft.Status.READY).first()
    if draft is None or not 0 <= index < len(draft.items) or draft.items[index].get('state') != REGENERATING:
        return
    old = draft.items[index]
    replacement, note = None, ''
    try:
        replacement, failure = _replacement(draft, old)
        if replacement is None:
            note = failure
    except (services.AIUnavailable, services.AIFailed, quiz_gen.RequestError) as error:
        note = ' '.join(error.messages)
    except Exception:  # noqa: BLE001
        logger.exception('Falló al regenerar una propuesta de %s', draft_id)
        note = 'Algo salió mal al regenerar. Intenta de nuevo.'
    with locked(draft_id) as current:
        if 0 <= index < len(current.items) and current.items[index].get('state') == REGENERATING and _label(current.items[index]) == _label(old):
            current.items[index] = replacement or {**old, 'state': PENDING, 'note': note}
            current.save()


# ── Revisar ───────────────────────────────────────────────────────────

def _require_reviewable(draft):
    if draft.status != AIDraft.Status.READY:
        raise ValidationError('Esta propuesta ya no se puede modificar.')


def item_at(draft, index):
    try:
        return draft.items[index]
    except (IndexError, TypeError):
        raise ValidationError('Esa propuesta ya no existe.') from None


def _points(raw, default):
    try:
        points = Decimal(str(raw).replace(',', '.'))
    except InvalidOperation:
        return default
    if not points.is_finite() or not Decimal('0.01') <= points <= 100:
        return default
    return quiz_gen.format_points(points)


def save_review_state(draft, post):
    """Guarda lo que el docente marcó (aprobadas) y escribió (puntos) sin cambiar nada más."""
    approved = set(post.getlist('approve'))
    for index, item in enumerate(draft.items):
        if item['state'] in (DISCARDED, REGENERATING):
            continue
        item['state'] = APPROVED if str(index) in approved else PENDING
        if f'points-{index}' in post:
            item['points'] = _points(post[f'points-{index}'], item['points'])


def set_state(draft, index, state):
    item = item_at(draft, index)
    if item['state'] == REGENERATING:
        raise ValidationError('Esa propuesta se está regenerando. Espera un momento.')
    if item['state'] == CREATED:
        raise ValidationError('Esa alternativa ya se creó como actividad.')
    item['state'] = state


def edit_item(draft, index, post):
    """Aplica lo que el docente corrigió en una propuesta de quiz (con las mismas reglas del banco de preguntas)."""
    item = item_at(draft, index)
    text = post.get('edit_text', '').strip()
    if not text:
        raise ValidationError('La pregunta no puede quedar vacía.')
    if len(text) > quiz_gen.TEXT_MAX:
        raise ValidationError(f'La pregunta puede tener hasta {quiz_gen.TEXT_MAX} caracteres.')
    explanation = post.get('edit_explanation', '').strip()[:quiz_gen.EXPLANATION_MAX]
    if item['kind'] == Question.Kind.TRUE_FALSE:
        if post.get('edit_correct') not in ('true', 'false'):
            raise ValidationError('Indica si la respuesta correcta es verdadero o falso.')
        item['true_is_correct'] = post['edit_correct'] == 'true'
    else:
        options = post.getlist('edit_option')
        correct = post.get('edit_correct', '')
        rows = [(option, str(position) == correct) for position, option in enumerate(options)]
        if any(len(option.strip()) > quiz_gen.CHOICE_MAX for option in options):
            raise ValidationError(f'Cada opción puede tener hasta {quiz_gen.CHOICE_MAX} caracteres.')
        item['choices'] = [{'text': option, 'correct': is_correct} for option, is_correct in validate_choices(rows)]
    item.update(text=text, explanation=explanation, edited=True, similar=None)


def discard_all(draft):
    draft.status = AIDraft.Status.DISCARDED
    draft.save()


def edit_assignment(draft, index, post):
    """Aplica lo que el docente corrigió en una alternativa de tarea (los criterios deben sumar los puntos)."""
    item = item_at(draft, index)
    if item['state'] != PENDING:
        raise ValidationError('Esa alternativa ya no se puede editar.')
    draft.items[index] = task_gen.edited_item(item, post)


def settle_assignments(draft):
    """Cierra la propuesta cuando ya no queda ninguna alternativa por decidir."""
    if any(item['state'] in (PENDING, REGENERATING) for item in draft.items):
        return
    draft.status = AIDraft.Status.APPLIED if draft.count(CREATED) else AIDraft.Status.DISCARDED


def close_assignments(draft):
    """«Terminar»: descarta las alternativas que quedan y cierra la propuesta."""
    for item in draft.items:
        if item['state'] in (PENDING, REGENERATING):
            item['state'] = DISCARDED
    settle_assignments(draft)


# ── Aprobar y aplicar ─────────────────────────────────────────────────

def _default_title(draft, week):
    base = week.title.strip() or f'Semana {week.position}'
    return (draft.new_activity_title or f'Quiz · {base}')[:255]


@transaction.atomic
def apply_quiz(draft_id, user):
    """Guarda las preguntas aprobadas en el banco del grupo y las agrega al quiz (que se crea si hacía falta).

    Todo o nada: si no caben en el banco del plan o el quiz ya tiene intentos, no se guarda nada. Devuelve la actividad.
    """
    draft = AIDraft.objects.select_for_update().select_related('course', 'activity').get(pk=draft_id)
    _require_reviewable(draft)
    approved = [item for item in draft.items if item['state'] == APPROVED]
    if not approved:
        raise ValidationError('Aprueba al menos una pregunta.')
    course = draft.course
    course.ensure_editable()
    questions = []
    for item in approved:
        question = save_question(
            organization=draft.organization, author=user, kind=item['kind'], text=item['text'], points=item['points'],
            explanation=item['explanation'], topic=item['topic'], course=course, ai_generated=True,
            choices=[(c['text'], c['correct']) for c in item['choices']] if item['kind'] == Question.Kind.MULTIPLE_CHOICE else None,
            true_is_correct=item['true_is_correct'] if item['kind'] == Question.Kind.TRUE_FALSE else None,
        )
        item['question_id'] = question.pk
        questions.append(question)
    activity, created = draft.activity, False
    if activity is None:
        weeks = {week.position: week for week in _weeks_of_or_empty(draft)}
        first = weeks.get(min(item['week'] for item in approved)) or next(iter(weeks.values()), None)
        activity = Activity(
            course=course, type=Activity.Type.QUIZ, title=_default_title(draft, first) if first else (draft.new_activity_title or 'Quiz'),
            syllabus_week=first, published=False,
        )
        activity.save()
        created = True
    quiz, _ = QuizConfig.objects.get_or_create(activity=activity)
    builder.add_questions(quiz, questions)
    if created:
        builder.sync_activity_points(quiz)
    draft.status, draft.applied_by, draft.applied_at, draft.activity = AIDraft.Status.APPLIED, user, timezone.now(), activity
    draft.save()
    return activity


@transaction.atomic
def create_assignment(draft_id, index, user):
    """Crea la actividad (borrador, hecha con IA) de la alternativa ``index``. Las demás siguen disponibles."""
    draft = AIDraft.objects.select_for_update().select_related('course').get(pk=draft_id)
    _require_reviewable(draft)
    item = item_at(draft, index)
    if item['state'] != PENDING:
        raise ValidationError('Esta alternativa ya no se puede crear.')
    course = draft.course
    course.ensure_editable()
    week = next((week for week in _weeks_of_or_empty(draft) if week.pk == item.get('week_id')), None)
    activity = Activity(
        course=course, title=item['title'], instructions=task_gen.render_instructions(item), type=item['type'],
        max_score=float(item['points']), syllabus_week=week, published=False, ai_generated=True,
    )
    activity.save()
    item['state'], item['activity_id'] = CREATED, activity.pk
    draft.applied_by, draft.applied_at = user, timezone.now()
    settle_assignments(draft)
    draft.save()
    return activity


def _weeks_of_or_empty(draft):
    wanted = draft.params.get('week_ids', [])
    return [week for week in quiz_gen.course_weeks(draft.course) if week.pk in wanted]


@transaction.atomic
def apply_split(draft_id, user):
    """Reemplaza las semanas del temario por las propuestas. Las actividades que apuntaban a una semana quedan sin semana."""
    draft = AIDraft.objects.select_for_update().select_related('course').get(pk=draft_id)
    _require_reviewable(draft)
    draft.course.ensure_editable()
    syllabus = Syllabus.objects.filter(course=draft.course).first()
    if syllabus is None:
        raise ValidationError('El grupo ya no tiene temario.')
    week_ops.replace_weeks(syllabus, [{key: value for key, value in week.items() if key != 'source'} for week in draft.items])
    draft.status, draft.applied_by, draft.applied_at = AIDraft.Status.APPLIED, user, timezone.now()
    draft.save()
    return len(draft.items)

