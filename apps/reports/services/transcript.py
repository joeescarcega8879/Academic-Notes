"""Datos de la boleta: cómo se formó la calificación de cada alumno, criterio por criterio.

Es la fuente de la boleta PDF y del concentrado Excel, así que los dos dicen exactamente lo mismo que la
libreta y la pantalla del alumno: el cálculo lo hace ``apps.grades.services.grading``. Solo cuentan las
actividades publicadas; un borrador no aparece ni pesa.
"""

import datetime
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import F

from apps.grades.models import Activity, Grade
from apps.grades.services.grading import course_result, snapshot
from apps.grades.services.gradesheet import enrolled_students, fmt
from apps.grades.services.schemes import ensure_scheme


@dataclass
class ActivityLine:
    title: str
    type_label: str
    max_score: str
    graded: bool = False
    score: float | None = None
    raw_score: float | None = None
    penalty: Decimal = Decimal(0)

    @property
    def score_text(self):
        return fmt(self.score) if self.graded else ''

    @property
    def note(self):
        return f'{fmt(self.penalty)} % de penalización por entrega tardía' if self.graded and self.penalty else ''


@dataclass
class CriterionBlock:
    name: str
    weight: str
    value: str = ''  # en la escala del esquema, ya redondeado
    value_number: float | None = None
    lines: list = field(default_factory=list)


@dataclass
class PeriodBlock:
    name: str
    weight: str
    criteria: list = field(default_factory=list)


@dataclass
class Transcript:
    course: object
    student: object
    organization_name: str
    academic_year: str
    professor: str
    scale_max: int
    pass_mark: str
    decimals: int
    periods: list
    final: str = ''
    final_number: float | None = None
    passed: bool | None = None
    graded_count: int = 0
    generated_on: datetime.date = field(default_factory=datetime.date.today)

    @property
    def multiple_periods(self):
        return len(self.periods) > 1

    @property
    def status(self):
        return {True: 'Aprobado', False: 'No aprobado'}.get(self.passed, 'Sin calificaciones')

    def criterion_lines(self):
        """Todas las líneas de actividad, en el orden de la boleta (periodo, criterio, actividad)."""
        return [line for period in self.periods for criterion in period.criteria for line in criterion.lines]


def build_transcripts(course, students=None):
    """Una ``Transcript`` por alumno inscrito en ``course`` (o por los ``students`` indicados, en su orden)."""
    scheme = ensure_scheme(course)
    decimals = scheme.rounding_decimals
    periods = list(scheme.periods.prefetch_related('criteria'))
    spec = snapshot(scheme)
    if students is None:
        students = enrolled_students(course)

    activities = defaultdict(list)
    for activity in Activity.objects.filter(course=course, published=True).order_by(F('date').asc(nulls_last=True), 'id'):
        activities[activity.criterion_id].append(activity)

    grades = defaultdict(dict)
    for grade in Grade.objects.filter(activity__course=course, student__in=students, activity__published=True).select_related('activity'):
        grades[grade.student_id][grade.activity_id] = grade

    organization, year = course.organization.name, str(course.academic_year)
    professor = course.professor.get_full_name() or course.professor.get_username()

    transcripts = []
    for student in students:
        own = grades.get(student.pk, {})
        result = course_result(spec, own.values())
        blocks = []
        for period, period_result in zip(periods, result.periods):
            criteria = []
            for criterion, criterion_result in zip(period.criteria.all(), period_result.criteria):
                value = None if criterion_result.ratio is None else criterion_result.ratio * result.scale_max
                block = CriterionBlock(
                    name=criterion.name, weight=fmt(criterion.weight),
                    value=fmt(value, decimals, trim=False), value_number=None if value is None else float(value),
                )
                for activity in activities.get(criterion.pk, []):
                    grade = own.get(activity.pk)
                    block.lines.append(ActivityLine(
                        title=activity.title, type_label=activity.get_type_display(), max_score=fmt(activity.max_score),
                        graded=grade is not None, score=grade.score if grade else None,
                        raw_score=grade.raw_score if grade else None, penalty=grade.late_penalty if grade else Decimal(0),
                    ))
                criteria.append(block)
            blocks.append(PeriodBlock(name=period.name, weight=fmt(period.weight), criteria=criteria))
        transcripts.append(Transcript(
            course=course, student=student, organization_name=organization, academic_year=year, professor=professor,
            scale_max=result.scale_max, pass_mark=fmt(scheme.pass_mark), decimals=decimals, periods=blocks,
            final=fmt(result.final, decimals, trim=False), final_number=result.final, passed=result.passed,
            graded_count=result.graded,
        ))
    return transcripts
