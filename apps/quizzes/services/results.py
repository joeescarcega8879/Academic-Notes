"""Del intento a la libreta, retroalimentación para el alumno y análisis para el docente."""

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, Sum
from django.utils import timezone

from apps.courses.services.text import sort_enrollments
from apps.grades.models import Grade
from apps.grades.services.gradebook import grade_activity, remove_grade

from ..models import Answer, Question, QuizAttempt, QuizConfig
from . import answers as answer_service

TWO_PLACES = Decimal('0.01')


# ── Calificación en la libreta ────────────────────────────────────────

def fraction(attempt):
    """Proporción de aciertos del intento (0–1), calculada sobre los puntos del quiz."""
    if not attempt.max_points:
        return Decimal(0)
    return Decimal(attempt.score) / Decimal(attempt.max_points)


MAX_FEEDBACK_LENGTH = 1000


def with_pending(attempts):
    """Marca cada intento con ``pending``: tiene respuestas abiertas que el docente todavía no califica."""
    waiting = Answer.objects.filter(attempt=OuterRef('pk'), question__kind=Question.Kind.OPEN, points_awarded__isnull=True)
    return attempts.annotate(pending=Exists(waiting))


def pending_count(attempt):
    """Cuántas respuestas abiertas de un intento terminado esperan calificación."""
    return attempt.answers.filter(question__kind=Question.Kind.OPEN, points_awarded__isnull=True).count()


def finished_attempts(quiz, student):
    """Intentos terminados y calificados del alumno, del más antiguo al más reciente.

    Un intento con respuestas abiertas por calificar no cuenta todavía: la nota llega completa o no llega.
    """
    return list(
        with_pending(quiz.attempts.filter(student=student)).filter(pending=False)
        .exclude(status=QuizAttempt.Status.IN_PROGRESS).order_by('submitted_at', 'number')
    )


def activity_score(quiz, attempts):
    """Calificación sobre los puntos de la actividad según la política del quiz, o None sin intentos terminados."""
    if not attempts:
        return None
    fractions = [fraction(a) for a in attempts]
    if quiz.attempt_policy == QuizConfig.Policy.LAST:
        chosen = fractions[-1]
    elif quiz.attempt_policy == QuizConfig.Policy.AVERAGE:
        chosen = sum(fractions, Decimal(0)) / len(fractions)
    else:
        chosen = max(fractions)
    return (chosen * Decimal(str(quiz.activity.max_score))).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def sync_grade(quiz, student, *, by=None):
    """Pone en la libreta la calificación que corresponde a los intentos del alumno.

    Si el docente fijó la nota a mano, esa manda y no se toca (para volver a la automática, la borra).
    Sin intentos terminados, se quita la calificación automática. ``by`` es quien provocó el cambio
    (None = el propio quiz al terminar un intento).
    """
    activity = quiz.activity
    grade = Grade.objects.filter(activity=activity, student=student).first()
    if grade is not None and grade.source != Grade.Source.QUIZ:
        return grade
    attempts = finished_attempts(quiz, student)
    if not attempts:
        if grade is not None:
            remove_grade(grade, by=by)
        return None
    return grade_activity(
        activity, student, score=float(activity_score(quiz, attempts)), by=by, source=Grade.Source.QUIZ,
        feedback=f'Calificación automática del {activity.get_type_display().lower()} ({len(attempts)} intento{"s" if len(attempts) != 1 else ""}).',
    )


def remove_attempt(attempt, *, by):
    """Elimina un intento (para que el alumno pueda repetirlo) y recalcula su calificación."""
    quiz, student = attempt.quiz, attempt.student
    attempt.delete()
    return sync_grade(quiz, student, by=by)


# ── Retroalimentación para el alumno ──────────────────────────────────

def quiz_is_closed(quiz, student, now=None):
    """El quiz ya no admite más intentos de este alumno: cerró o ya usó todos los suyos."""
    now = now or timezone.now()
    if quiz.activity.due_at:
        return now > quiz.activity.due_at
    used = quiz.attempts.filter(student=student).count()
    return used >= quiz.attempts_allowed and not quiz.attempts.filter(student=student, status=QuizAttempt.Status.IN_PROGRESS).exists()


def can_review(attempt, now=None):
    """Si el alumno puede ver sus respuestas, las correctas y las explicaciones de un intento terminado."""
    if not attempt.is_finished:
        return False
    mode = attempt.quiz.feedback_mode
    if mode == QuizConfig.Feedback.NONE:
        return False
    if mode == QuizConfig.Feedback.AFTER_CLOSE:
        return quiz_is_closed(attempt.quiz, attempt.student, now)
    return True


def review_rows(attempt):
    """Por pregunta, en el orden en que la vio el alumno: opciones marcadas y puntos. Para el alumno y el docente."""
    quiz = attempt.quiz
    answers = {a.question_id: a for a in attempt.answers.all()}
    questions = {q.pk: q for q in quiz.questions.prefetch_related('choices')}
    order = [qid for qid in attempt.layout.get('questions', []) if qid in questions]
    order += [qid for qid in questions if qid not in order]  # preguntas que no estaban en el orden guardado
    rows = []
    for question_id in order:
        question = questions[question_id]
        answer = answers.get(question_id)
        chosen = answer.choice_id if answer else None
        by_id = {c.pk: c for c in question.choices.all()}
        ids = [c for c in attempt.layout.get('choices', {}).get(str(question_id), []) if c in by_id]
        ids += [c for c in by_id if c not in ids]
        is_short = question.kind == Question.Kind.SHORT_ANSWER
        rows.append({
            'question': question,
            'kind': question.kind,
            # En una respuesta corta lo que se muestra es el texto del alumno y las respuestas aceptadas, no una lista de opciones.
            'choices': [] if is_short else [{'choice': by_id[c], 'chosen': c == chosen, 'correct': by_id[c].is_correct} for c in ids],
            'text': answer.text if answer and (is_short or question.kind == Question.Kind.OPEN) else '',
            'answer_id': answer.pk if answer else None,
            'feedback': answer.feedback if answer else '',
            'accepted': [c.text for c in question.correct_choices] if is_short else [],
            'answered': answer_service.has_answer(question, answer),
            'is_correct': bool(answer and answer.is_correct),
            'points': answer.points_awarded if answer and answer.points_awarded is not None else Decimal(0),
            # Abierta con texto: el docente puede calificarla; sin calificar todavía, el alumno la ve «por calificar».
            'gradable': question.kind == Question.Kind.OPEN and answer_service.has_answer(question, answer),
            'pending': bool(answer and question.kind == Question.Kind.OPEN and answer.points_awarded is None),
        })
    return rows


# ── Análisis para el docente ──────────────────────────────────────────

def question_stats(quiz):
    """Por pregunta: cuántos la respondieron, cuántos acertaron y cómo se repartieron las opciones.

    Cuenta solo intentos terminados. Sirve para detectar preguntas mal planteadas (nadie acierta, o todos).
    """
    attempts = quiz.attempts.exclude(status=QuizAttempt.Status.IN_PROGRESS).count()
    rows = Answer.objects.filter(attempt__quiz=quiz).exclude(attempt__status=QuizAttempt.Status.IN_PROGRESS).values_list(
        'question_id', 'choice_id', 'is_correct', 'text',
    )
    short_ids = set(quiz.questions.filter(kind=Question.Kind.SHORT_ANSWER).values_list('pk', flat=True))
    chosen = {}
    written = {}  # respuestas de texto que no acertaron: sirven para ver qué más convendría aceptar
    answered_text = Counter()
    correct = Counter()
    for question_id, choice_id, is_correct, text in rows:
        chosen.setdefault(question_id, Counter())[choice_id] += 1
        if text.strip():
            answered_text[question_id] += 1
            if not is_correct and question_id in short_ids:
                written.setdefault(question_id, Counter())[answer_service.normalize(text) or text.strip()] += 1
        if is_correct:
            correct[question_id] += 1
    stats = []
    for question in quiz.questions.prefetch_related('choices'):
        counts = chosen.get(question.pk, Counter())
        is_short = question.kind in answer_service.TEXT_KINDS
        answered = answered_text[question.pk] if is_short else sum(n for choice_id, n in counts.items() if choice_id is not None)
        stats.append({
            'question': question,
            'kind': question.kind,
            'common_wrong': written.get(question.pk, Counter()).most_common(5),
            'attempts': attempts,
            'answered': answered,
            'unanswered': attempts - answered,
            'correct': correct[question.pk],
            'percent_correct': round(correct[question.pk] * 100 / attempts) if attempts else None,
            'choices': [
                {
                    'choice': c, 'count': counts.get(c.pk, 0),
                    'percent': round(counts.get(c.pk, 0) * 100 / attempts) if attempts else 0,
                }
                for c in ([] if is_short else question.choices.all())
            ],
        })
    return stats


def student_rows(quiz):
    """Una fila por alumno inscrito: sus intentos, mejor y último resultado, y su calificación en la libreta."""
    enrollments = sort_enrollments(quiz.activity.course.enrollments.select_related('student__user'))
    attempts_by_student = {}
    for attempt in with_pending(quiz.attempts.select_related('student')).order_by('number'):
        attempts_by_student.setdefault(attempt.student_id, []).append(attempt)
    grades = {g.student_id: g for g in Grade.objects.filter(activity=quiz.activity)}
    rows = []
    for enrollment in enrollments:
        attempts = attempts_by_student.get(enrollment.student_id, [])
        done = [a for a in attempts if a.is_finished and not a.pending]
        rows.append({
            'student': enrollment.student,
            'attempts': attempts,
            'done': done,
            'waiting': [a for a in attempts if a.is_finished and a.pending],
            'in_progress': any(not a.is_finished for a in attempts),
            'best': round(float(max(fraction(a) for a in done)) * 100) if done else None,
            'last': round(float(fraction(done[-1])) * 100) if done else None,
            'grade': grades.get(enrollment.student_id),
        })
    return rows


def summary(quiz):
    """Cifras generales del quiz sobre sus intentos terminados."""
    done = list(with_pending(quiz.attempts.exclude(status=QuizAttempt.Status.IN_PROGRESS)))
    fractions = [float(fraction(a)) * 100 for a in done if not a.pending]
    students = {a.student_id for a in done}
    return {
        'attempts': len(done),
        'students': len(students),
        'enrolled': quiz.activity.course.enrollments.count(),
        'average': round(sum(fractions) / len(fractions)) if fractions else None,
        'highest': round(max(fractions)) if fractions else None,
        'lowest': round(min(fractions)) if fractions else None,
        'expired': sum(1 for a in done if a.status == QuizAttempt.Status.EXPIRED),
        'pending': sum(1 for a in done if a.pending),
    }


# ── Calificar respuestas abiertas ─────────────────────────────────────

def _parse_points(raw, maximum):
    """Puntos que escribió el docente: ``None`` si lo dejó en blanco; error si no es un número de 0 al máximo."""
    raw = (raw or '').strip().replace(',', '.')
    if not raw:
        return None
    try:
        points = Decimal(raw)
    except InvalidOperation:
        raise ValidationError('Los puntos deben ser un número.') from None
    if not points.is_finite():
        raise ValidationError('Los puntos deben ser un número.')
    if points < 0 or points > maximum:
        raise ValidationError(f'Los puntos van de 0 a {maximum.normalize():f}.')
    return points.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@transaction.atomic
def grade_open_answers(attempt, entries, *, by):
    """El docente califica respuestas abiertas de un intento terminado y la libreta se actualiza.

    ``entries`` es ``{id de la respuesta: (puntos, comentario)}``. Un campo de puntos en blanco deja la respuesta como
    estaba (por calificar o con los puntos que ya tenía). Si algo es inválido no se guarda nada.
    """
    attempt = QuizAttempt.objects.select_for_update(of=('self',)).select_related('quiz__activity__course', 'student').get(pk=attempt.pk)
    attempt.quiz.activity.course.ensure_editable()
    if not attempt.is_finished:
        raise ValidationError('El intento todavía está en curso.')
    answers = {a.pk: a for a in attempt.answers.select_related('question').filter(question__kind=Question.Kind.OPEN)}
    for answer_id, (raw_points, comment) in entries.items():
        answer = answers.get(answer_id)
        if answer is None:
            raise ValidationError('Hay una respuesta que no es de este intento.')
        if not answer_service.has_answer(answer.question, answer):
            continue  # en blanco: vale 0 y no hay nada que calificar
        points = _parse_points(raw_points, answer.question.points)
        comment = (comment or '').strip()
        if len(comment) > MAX_FEEDBACK_LENGTH:
            raise ValidationError(f'Un comentario no puede pasar de {MAX_FEEDBACK_LENGTH} caracteres.')
        if points is not None:
            answer.points_awarded = points
            answer.is_correct = points >= answer.question.points
        answer.feedback = comment
        answer.save()
    attempt.score = attempt.answers.aggregate(total=Sum('points_awarded'))['total'] or Decimal(0)
    attempt.save(update_fields=['score'])
    sync_grade(attempt.quiz, attempt.student, by=by)
    return attempt
