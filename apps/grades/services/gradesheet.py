"""La libreta: alumnos × actividades de un grupo, con la calificación final de cada alumno.

``build_gradesheet`` arma toda la tabla con pocas consultas; ``set_cell`` es la edición de una celda. Los
números llegan ya formateados (punto decimal, sin ceros de sobra) para que la página y las respuestas JSON de
la edición en línea muestren exactamente lo mismo.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import F

from apps.courses.services.text import normalize_text

from ..models import Activity, Grade
from .gradebook import grade_activity, late_penalty_for, remove_grade
from .grading import ZERO, _dec, course_result, course_stats, snapshots_for
from .schemes import ensure_scheme

# Más largo que esto no es una calificación: se rechaza antes de convertirlo a número.
MAX_SCORE_TEXT = 20


def fmt(value, decimals=2, *, trim=True):
    """Texto de un número con ``decimals`` decimales (mitad hacia arriba); ``trim`` quita los ceros sobrantes."""
    if value is None:
        return ''
    text = format(_dec(value).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP), 'f')
    if trim and '.' in text:
        text = text.rstrip('0').rstrip('.')
    return text


def parse_score(text, max_score):
    """Número que escribió el docente (acepta coma decimal); ``None`` si la celda quedó vacía.

    Lanza ``ValidationError`` con un mensaje para el docente si no es un número entre 0 y ``max_score``.
    """
    raw = (text or '').strip().replace(',', '.')
    if raw == '':
        return None
    if len(raw) > MAX_SCORE_TEXT:
        raise ValidationError('Escribe un número.')
    try:
        score = float(raw)
    except ValueError:
        raise ValidationError('Escribe un número.') from None
    # Con la comparación encadenada también se rechazan nan e inf.
    if not 0 <= score <= max_score:
        raise ValidationError(f'Debe estar entre 0 y {max_score:g}.')
    return score


# ── Edición de una celda ──────────────────────────────────────────────

def set_cell(activity, student, text, *, by=None):
    """Fija la calificación de ``student`` en ``activity`` con lo escrito en la celda.

    Celda vacía = quitar la calificación (queda en la bitácora). Escribir el mismo valor que ya había no hace
    nada, para no llenar la bitácora. Al cambiar una nota se conserva su comentario y, si el docente había
    perdonado la penalización por entrega tardía, se sigue perdonando. Devuelve la ``Grade`` o ``None``.
    """
    score = parse_score(text, activity.max_score)
    grade = Grade.objects.filter(activity=activity, student=student).first()
    if score is None:
        if grade is not None:
            remove_grade(grade, by=by)
        return None
    if grade is not None and grade.raw_score == score:
        return grade
    waived = grade is not None and grade.late_penalty == 0 and late_penalty_for(activity, student) > 0
    return grade_activity(
        activity, student, score=score, feedback=grade.feedback if grade else '', by=by, waive_penalty=waived,
    )


# ── Presentación ──────────────────────────────────────────────────────

def describe_cell(grade):
    """Lo que muestra una celda: la nota que escribió el docente y una nota al pie si la efectiva es otra."""
    if grade is None:
        return {'raw': '', 'score': '', 'note': '', 'auto': False}
    notes = []
    if grade.late_penalty:
        notes.append(f'−{fmt(grade.late_penalty)} % tardía → {fmt(grade.score)}')
    auto = grade.source == Grade.Source.QUIZ
    if auto:
        notes.append('automática')
    return {'raw': fmt(grade.raw_score), 'score': fmt(grade.score), 'note': ' · '.join(notes), 'auto': auto}


def describe_result(result, decimals):
    """Calificación final de un alumno lista para mostrar."""
    if result is None or result.final is None:
        return {'text': '', 'passed': None}
    return {'text': fmt(result.final, decimals, trim=False), 'passed': result.passed}


@dataclass
class Column:
    activity: Activity
    graded: int = 0
    average: str = ''


@dataclass
class Row:
    student: object
    cells: list = field(default_factory=list)
    final: dict = field(default_factory=dict)


@dataclass
class CriterionGroup:
    criterion: object
    columns: list


@dataclass
class PeriodGroup:
    period: object
    criteria: list

    @property
    def span(self):
        return sum(len(group.columns) for group in self.criteria)


@dataclass
class Gradesheet:
    course: object
    scheme: object
    periods: list
    columns: list
    rows: list
    group: dict

    @property
    def multiple_periods(self):
        return len(self.periods) > 1

    def row_for(self, student_id):
        return next((row for row in self.rows if row.student.pk == student_id), None)

    def column_for(self, activity_id):
        return next((column for column in self.columns if column.activity.pk == activity_id), None)


def enrolled_students(course):
    """Alumnos inscritos en el grupo, en orden alfabético sin importar acentos («Álvarez» antes que «Zapata»).

    El orden de la base de datos no lo garantiza (SQLite pone la «Á» después de la «Z»).
    """
    return sorted(
        (enrollment.student for enrollment in course.enrollments.select_related('student__user')),
        key=lambda s: (normalize_text(s.last_name), normalize_text(s.first_name), s.pk),
    )


def build_gradesheet(course):
    """Toda la libreta del grupo: columnas agrupadas por periodo y criterio, una fila por alumno inscrito."""
    scheme = ensure_scheme(course)
    decimals = scheme.rounding_decimals

    by_criterion = defaultdict(list)
    activities = Activity.objects.filter(course=course).order_by(F('date').asc(nulls_last=True), 'id')
    for activity in activities:
        by_criterion[activity.criterion_id].append(Column(activity))

    periods, columns = [], []
    for period in scheme.periods.prefetch_related('criteria'):
        groups = [
            CriterionGroup(criterion, by_criterion[criterion.pk]) for criterion in period.criteria.all()
            if by_criterion.get(criterion.pk)
        ]
        if groups:
            periods.append(PeriodGroup(period, groups))
            columns.extend(column for group in groups for column in group.columns)

    students = enrolled_students(course)
    by_student, by_activity = defaultdict(dict), defaultdict(list)
    grades = Grade.objects.filter(activity__course=course, student__in=students).select_related('activity')
    for grade in grades:
        by_student[grade.student_id][grade.activity_id] = grade
        by_activity[grade.activity_id].append(grade)

    spec = snapshots_for([course.pk])[course.pk]
    rows, results = [], {}
    for student in students:
        own = by_student.get(student.pk, {})
        result = course_result(spec, own.values())
        results[(course.pk, student.pk)] = result
        rows.append(Row(
            student=student,
            cells=[{**describe_cell(own.get(c.activity.pk)), 'activity_id': c.activity.pk} for c in columns],
            final=describe_result(result, decimals),
        ))

    for column in columns:
        scores = [_dec(grade.score) for grade in by_activity.get(column.activity.pk, [])]
        column.graded = len(scores)
        column.average = fmt(sum(scores, ZERO) / len(scores)) if scores else ''

    stats = course_stats(results).get(course.pk)
    group = {
        'average': fmt(stats.average, decimals, trim=False) if stats else '',
        'passed': stats.passed if stats else 0,
        'students': stats.students if stats else 0,
    }
    return Gradesheet(course=course, scheme=scheme, periods=periods, columns=columns, rows=rows, group=group)
