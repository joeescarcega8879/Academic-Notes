"""Cálculo de calificaciones finales, promedios y aprobación.

Única fuente de verdad para las vistas web y, más adelante, la API.

Cómo se calcula la calificación final de un alumno en un grupo (según el ``EvaluationScheme``):

1. Cada nota se normaliza contra el ``max_score`` de su evaluación (``score / max_score``), de modo que
   evaluaciones sobre 100 y sobre 10 se pueden mezclar.
2. **Criterio**: media de esas proporciones ponderada por el ``weight`` de cada evaluación.
3. **Periodo**: media de sus criterios ponderada por el peso del criterio.
4. **Final**: media de los periodos ponderada por el peso del periodo, expresada en la escala del esquema.

En cada nivel solo cuenta lo que ya tiene calificaciones: un criterio sin notas no hunde el promedio, y
los pesos de los demás se reescalan. Se ignoran las actividades en borrador, las que no tienen máximo válido
y las de peso cero, que no aportan información. El redondeo es "mitad hacia arriba" (7.125 → 7.13), no el del par más
cercano de Python, y se hace una sola vez, al final. Se aprueba con la calificación ya redondeada, que es
la que ve el alumno.

Los promedios entre varios grupos (que pueden tener escalas distintas) se expresan en ``DISPLAY_SCALE``.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

# Escala en la que se muestran los promedios que mezclan grupos con escalas distintas.
DISPLAY_SCALE = 10

ZERO = Decimal(0)


def _dec(value):
    """Decimal exacto de un número (los flotantes pasan por su texto para no arrastrar 0.30000000000000004)."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _round(value, decimals):
    return value.quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def _weighted_mean(pairs):
    """Media ponderada de ``(valor, peso)`` ignorando pesos <= 0; None si no queda ninguno."""
    pairs = [(value, weight) for value, weight in pairs if weight > 0]
    total = sum((weight for _, weight in pairs), ZERO)
    if total == 0:
        return None
    return sum((value * weight for value, weight in pairs), ZERO) / total


# ── Estructura del esquema ────────────────────────────────────────────

@dataclass(frozen=True)
class CriterionSpec:
    id: int
    name: str
    weight: Decimal


@dataclass(frozen=True)
class PeriodSpec:
    id: int
    name: str
    weight: Decimal
    criteria: tuple


@dataclass(frozen=True)
class SchemeSnapshot:
    """Copia inmutable de un esquema: se lee una vez y se reutiliza para muchos alumnos."""

    course_id: int
    scale_max: int
    pass_mark: Decimal
    decimals: int
    periods: tuple


def snapshot(scheme):
    """``SchemeSnapshot`` de un ``EvaluationScheme`` (conviene traerlo con ``periods__criteria`` precargados)."""
    return SchemeSnapshot(
        course_id=scheme.course_id,
        scale_max=scheme.scale_max,
        pass_mark=_dec(scheme.pass_mark),
        decimals=scheme.rounding_decimals,
        periods=tuple(
            PeriodSpec(
                id=period.id, name=period.name, weight=_dec(period.weight),
                criteria=tuple(CriterionSpec(c.id, c.name, _dec(c.weight)) for c in period.criteria.all()),
            )
            for period in scheme.periods.all()
        ),
    )


def snapshots_for(course_ids):
    """``{course_id: SchemeSnapshot}`` de los grupos indicados, en pocas consultas."""
    from ..models import EvaluationScheme

    schemes = EvaluationScheme.objects.filter(course_id__in=set(course_ids)).prefetch_related('periods__criteria')
    return {scheme.course_id: snapshot(scheme) for scheme in schemes}


# ── Resultado de un alumno en un grupo ────────────────────────────────

@dataclass(frozen=True)
class CriterionResult:
    name: str
    weight: Decimal
    ratio: Decimal | None
    graded: int


@dataclass(frozen=True)
class PeriodResult:
    name: str
    weight: Decimal
    ratio: Decimal | None
    criteria: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class CourseResult:
    """Calificación final de un alumno en un grupo, con su desglose."""

    final: float | None  # en la escala del esquema, ya redondeada
    ratio: float | None  # 0–1 sin redondear, comparable entre escalas
    scale_max: int
    passed: bool | None
    graded: int  # calificaciones consideradas
    periods: tuple = field(default_factory=tuple)

    @property
    def display(self):
        """La final expresada en ``DISPLAY_SCALE`` (para mezclar grupos de escalas distintas)."""
        return None if self.ratio is None else float(_round(_dec(self.ratio) * DISPLAY_SCALE, 2))


def _usable(grade):
    """(proporción, peso) de una calificación, o None si no aporta información."""
    activity = grade.activity
    if not activity.published:  # un borrador no cuenta para ninguna calificación
        return None
    max_score, weight = _dec(activity.max_score), _dec(activity.weight)
    if max_score <= 0 or weight <= 0:
        return None
    return _dec(grade.score) / max_score, weight


def course_result(spec, grades):
    """Resultado de UN alumno en UN grupo. ``grades`` son sus ``Grade`` (con ``activity`` cargada)."""
    by_criterion = defaultdict(list)
    for grade in grades:
        usable = _usable(grade)
        if usable is not None:
            by_criterion[grade.activity.criterion_id].append(usable)

    # Solo se recorren los criterios del esquema: las notas de criterios ajenos (otro grupo) no cuentan.
    period_results, period_pairs, graded = [], [], 0
    for period in spec.periods:
        criterion_results, criterion_pairs = [], []
        for criterion in period.criteria:
            items = by_criterion.get(criterion.id, [])
            ratio = _weighted_mean(items)
            graded += len(items)
            criterion_results.append(CriterionResult(criterion.name, criterion.weight, ratio, len(items)))
            if ratio is not None:
                criterion_pairs.append((ratio, criterion.weight))
        period_ratio = _weighted_mean(criterion_pairs)
        period_results.append(PeriodResult(period.name, period.weight, period_ratio, tuple(criterion_results)))
        if period_ratio is not None:
            period_pairs.append((period_ratio, period.weight))

    ratio = _weighted_mean(period_pairs)
    if ratio is None:
        return CourseResult(None, None, spec.scale_max, None, graded, tuple(period_results))
    final = _round(ratio * spec.scale_max, spec.decimals)
    return CourseResult(
        final=float(final), ratio=float(ratio), scale_max=spec.scale_max, passed=final >= spec.pass_mark,
        graded=graded, periods=tuple(period_results),
    )


def results_by_course(grades):
    """``{course_id: CourseResult}`` para las calificaciones de UN alumno en uno o varios grupos."""
    grades = list(grades)
    buckets = defaultdict(list)
    for grade in grades:
        buckets[grade.activity.course_id].append(grade)
    specs = snapshots_for(buckets)
    return {course_id: course_result(specs[course_id], items) for course_id, items in buckets.items() if course_id in specs}


# ── Agregados ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GroupStats:
    """Resumen de varios resultados de alumnos."""

    average: float | None
    students: int
    passed: int

    @property
    def pass_rate(self):
        """Porcentaje entero de alumnos aprobados, o None sin datos."""
        return round(self.passed * 100 / self.students) if self.students else None


def student_average(results):
    """Promedio general de UN alumno: media de sus finales de cada grupo en ``DISPLAY_SCALE``."""
    values = [_dec(r.display) for r in results.values() if r.display is not None]
    if not values:
        return None
    return float(_round(sum(values, ZERO) / len(values), 2))


def group_results(grades):
    """``{(course_id, student_id): CourseResult}`` para calificaciones de varios alumnos y grupos."""
    grades = list(grades)
    buckets = defaultdict(list)
    for grade in grades:
        buckets[(grade.activity.course_id, grade.student_id)].append(grade)
    specs = snapshots_for({course_id for course_id, _ in buckets})
    return {
        key: course_result(specs[key[0]], items) for key, items in buckets.items() if key[0] in specs
    }


def course_stats(results):
    """``{course_id: GroupStats}``: promedio y aprobación de los alumnos de cada grupo.

    El promedio de cada grupo está en la escala de su propio esquema.
    """
    by_course = defaultdict(list)
    for (course_id, _), result in results.items():
        if result.final is not None:
            by_course[course_id].append(result)
    return {course_id: _summarize(items, own_scale=True) for course_id, items in by_course.items()}


def overall_stats(results):
    """``GroupStats`` de todos los resultados juntos, con el promedio en ``DISPLAY_SCALE``."""
    items = [r for r in results.values() if r.final is not None]
    return _summarize(items, own_scale=False)


def _summarize(items, own_scale):
    if not items:
        return GroupStats(average=None, students=0, passed=0)
    values = [_dec(r.final) if own_scale else _dec(r.display) for r in items]
    return GroupStats(
        average=float(_round(sum(values, ZERO) / len(values), 2)),
        students=len(items),
        passed=sum(1 for r in items if r.passed),
    )


def overall_average(grades):
    """Promedio de unas calificaciones en ``DISPLAY_SCALE``: media de los finales de cada (alumno, grupo)."""
    return overall_stats(group_results(grades)).average
