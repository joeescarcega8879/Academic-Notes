"""Alumnos en riesgo: a quién conviene atender antes de que cierre el periodo.

Reglas (todas en este archivo, para que cambiarlas no obligue a buscar en las vistas):

* **Reprobado ahora**: la calificación final, ya redondeada, está por debajo del mínimo aprobatorio.
* **En riesgo por promedio**: aprueba, pero a menos de ``MARGIN`` de la escala del mínimo (con escala 10 y mínimo 6,
  por debajo de 7): un examen malo lo manda abajo.
* **En riesgo por faltantes**: tiene ``MISSING_LIMIT`` o más actividades publicadas con fecha límite vencida y
  sin entrega ni calificación. Aplica aunque aún no tenga promedio.

Solo se miran los grupos activos que tienen al menos un dato; un alumno sin calificaciones ni faltantes queda
como «sin datos», no como «bien». La entrega pendiente cuenta solo para actividades con fecha límite.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.utils import timezone

from apps.grades.models import Activity, Grade, Submission
from apps.grades.services.grading import _dec, course_result, snapshot
from apps.grades.services.gradesheet import enrolled_students, fmt
from apps.grades.services.schemes import ensure_scheme

MARGIN = Decimal('0.10')  # fracción de la escala por encima del mínimo en la que ya se considera riesgo
MISSING_LIMIT = 2

FAILING, AT_RISK, OK, NO_DATA = 'failing', 'at_risk', 'ok', 'no_data'
LEVEL_ORDER = {FAILING: 0, AT_RISK: 1, NO_DATA: 2, OK: 3}
LEVEL_LABELS = {FAILING: 'Reprobado', AT_RISK: 'En riesgo', NO_DATA: 'Sin datos', OK: 'Bien'}


@dataclass
class StudentRisk:
    student: object
    level: str
    final: float | None
    final_text: str
    missing: list = field(default_factory=list)  # títulos de las actividades vencidas sin entrega ni calificación
    reasons: list = field(default_factory=list)

    @property
    def label(self):
        return LEVEL_LABELS[self.level]

    @property
    def needs_attention(self):
        return self.level in (FAILING, AT_RISK)


def assess_course(course, *, now=None):
    """``StudentRisk`` de cada alumno inscrito: primero los reprobados, luego los de riesgo, de menor a mayor promedio."""
    now = now or timezone.now()
    scheme = ensure_scheme(course)
    spec = snapshot(scheme)
    students = enrolled_students(course)
    decimals = scheme.rounding_decimals
    pass_mark = _dec(scheme.pass_mark)
    threshold = pass_mark + MARGIN * scheme.scale_max

    grades = {}
    for grade in Grade.objects.filter(activity__course=course, student__in=students).select_related('activity'):
        grades.setdefault(grade.student_id, []).append(grade)
    overdue = list(Activity.objects.filter(course=course, published=True, due_at__lt=now).order_by('due_at', 'id'))
    graded_pairs = set(Grade.objects.filter(activity__in=overdue).values_list('student_id', 'activity_id'))
    submitted_pairs = set(Submission.objects.filter(activity__in=overdue).values_list('student_id', 'activity_id'))

    assessments = []
    for student in students:
        result = course_result(spec, grades.get(student.pk, []))
        missing = [a.title for a in overdue if (student.pk, a.pk) not in graded_pairs and (student.pk, a.pk) not in submitted_pairs]
        reasons, level = [], OK if result.final is not None else NO_DATA
        if result.final is not None:
            final = _dec(result.final)
            if final < pass_mark:
                level = FAILING
                reasons.append(f'Promedio {fmt(final, decimals, trim=False)}, por debajo del mínimo de {fmt(pass_mark)}.')
            elif final < threshold:
                level = AT_RISK
                reasons.append(f'Promedio {fmt(final, decimals, trim=False)}, muy cerca del mínimo de {fmt(pass_mark)}.')
        if len(missing) >= MISSING_LIMIT:
            if level in (OK, NO_DATA):
                level = AT_RISK
            reasons.append(f'{len(missing)} actividades vencidas sin entrega ni calificación.')
        assessments.append(StudentRisk(
            student=student, level=level, final=result.final, final_text=fmt(result.final, decimals, trim=False),
            missing=missing, reasons=reasons,
        ))
    assessments.sort(key=lambda r: (LEVEL_ORDER[r.level], r.final if r.final is not None else 99, r.student.last_name))
    return assessments


def risk_counts(assessments):
    """``{nivel: cantidad}`` para mostrar un resumen."""
    counts = {level: 0 for level in LEVEL_ORDER}
    for assessment in assessments:
        counts[assessment.level] += 1
    return counts
