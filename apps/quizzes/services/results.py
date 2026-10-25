"""Del intento a la libreta, retroalimentación para el alumno y análisis para el docente."""

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

from apps.courses.services.text import sort_enrollments
from apps.grades.models import Grade
from apps.grades.services.gradebook import grade_activity, remove_grade

from ..models import Answer, QuizAttempt, QuizConfig

TWO_PLACES = Decimal('0.01')


# ── Calificación en la libreta ────────────────────────────────────────

def fraction(attempt):
    """Proporción de aciertos del intento (0–1), calculada sobre los puntos del quiz."""
    if not attempt.max_points:
        return Decimal(0)
    return Decimal(attempt.score) / Decimal(attempt.max_points)


def finished_attempts(quiz, student):
    """Intentos terminados del alumno, del más antiguo al más reciente."""
    return list(
        quiz.attempts.filter(student=student).exclude(status=QuizAttempt.Status.IN_PROGRESS).order_by('submitted_at', 'number')
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
        rows.append({
            'question': question,
            'choices': [{'choice': by_id[c], 'chosen': c == chosen, 'correct': by_id[c].is_correct} for c in ids],
            'answered': chosen is not None,
            'is_correct': bool(answer and answer.is_correct),
            'points': answer.points_awarded if answer and answer.points_awarded is not None else Decimal(0),
        })
    return rows


# ── Análisis para el docente ──────────────────────────────────────────

def question_stats(quiz):
    """Por pregunta: cuántos la respondieron, cuántos acertaron y cómo se repartieron las opciones.

    Cuenta solo intentos terminados. Sirve para detectar preguntas mal planteadas (nadie acierta, o todos).
    """
    attempts = quiz.attempts.exclude(status=QuizAttempt.Status.IN_PROGRESS).count()
    rows = Answer.objects.filter(attempt__quiz=quiz).exclude(attempt__status=QuizAttempt.Status.IN_PROGRESS).values_list(
        'question_id', 'choice_id', 'is_correct',
    )
    chosen = {}
    correct = Counter()
    for question_id, choice_id, is_correct in rows:
        chosen.setdefault(question_id, Counter())[choice_id] += 1
        if is_correct:
            correct[question_id] += 1
    stats = []
    for question in quiz.questions.prefetch_related('choices'):
        counts = chosen.get(question.pk, Counter())
        answered = sum(n for choice_id, n in counts.items() if choice_id is not None)
        stats.append({
            'question': question,
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
                for c in question.choices.all()
            ],
        })
    return stats


def student_rows(quiz):
    """Una fila por alumno inscrito: sus intentos, mejor y último resultado, y su calificación en la libreta."""
    enrollments = sort_enrollments(quiz.activity.course.enrollments.select_related('student__user'))
    attempts_by_student = {}
    for attempt in quiz.attempts.select_related('student').order_by('number'):
        attempts_by_student.setdefault(attempt.student_id, []).append(attempt)
    grades = {g.student_id: g for g in Grade.objects.filter(activity=quiz.activity)}
    rows = []
    for enrollment in enrollments:
        attempts = attempts_by_student.get(enrollment.student_id, [])
        done = [a for a in attempts if a.is_finished]
        rows.append({
            'student': enrollment.student,
            'attempts': attempts,
            'done': done,
            'in_progress': any(not a.is_finished for a in attempts),
            'best': round(float(max(fraction(a) for a in done)) * 100) if done else None,
            'last': round(float(fraction(done[-1])) * 100) if done else None,
            'grade': grades.get(enrollment.student_id),
        })
    return rows


def summary(quiz):
    """Cifras generales del quiz sobre sus intentos terminados."""
    done = list(quiz.attempts.exclude(status=QuizAttempt.Status.IN_PROGRESS))
    fractions = [float(fraction(a)) * 100 for a in done]
    students = {a.student_id for a in done}
    return {
        'attempts': len(done),
        'students': len(students),
        'enrolled': quiz.activity.course.enrollments.count(),
        'average': round(sum(fractions) / len(fractions)) if fractions else None,
        'highest': round(max(fractions)) if fractions else None,
        'lowest': round(min(fractions)) if fractions else None,
        'expired': sum(1 for a in done if a.status == QuizAttempt.Status.EXPIRED),
    }
