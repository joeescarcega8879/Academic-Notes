"""Cálculo de promedios y aprobación.

Única fuente de verdad para las vistas web y, más adelante, la API. Cada
calificación se normaliza contra el ``max_score`` de su evaluación antes de
ponderarla, de modo que evaluaciones sobre 100 y sobre 10 se pueden mezclar.
El resultado se expresa en ``DISPLAY_SCALE`` (0–10, la escala de la UI).
"""

from collections import defaultdict
from dataclasses import dataclass

# Un alumno aprueba al alcanzar el 60 % del puntaje máximo de la evaluación.
PASS_RATIO = 0.6

# Escala en la que se muestran los promedios.
DISPLAY_SCALE = 10


@dataclass(frozen=True)
class GradeStats:
    """Resumen de un conjunto de calificaciones."""

    average: float | None
    count: int
    passed: int

    @property
    def pass_rate(self):
        """Porcentaje entero de calificaciones aprobatorias, o None sin datos."""
        return round(self.passed * 100 / self.count) if self.count else None


def is_passing(score, max_score):
    """True si ``score`` alcanza el mínimo aprobatorio de una evaluación."""
    return max_score > 0 and score >= max_score * PASS_RATIO


def weighted_average(grades):
    """Promedio ponderado en la escala de ``DISPLAY_SCALE``, o None si no hay base.

    ``grades`` es un iterable de ``Grade`` con ``evaluation`` ya cargada. Se
    ignoran las evaluaciones sin máximo válido y las de peso cero, que no
    aportan información. Si ninguna aporta, no hay promedio.
    """
    return grade_stats(grades).average


def grade_stats(grades):
    """Promedio, total y aprobadas de un iterable de ``Grade``."""
    total_weight = 0.0
    weighted_ratio = 0.0
    count = 0
    passed = 0
    for grade in grades:
        evaluation = grade.evaluation
        if evaluation.max_score <= 0:
            continue
        count += 1
        if is_passing(grade.score, evaluation.max_score):
            passed += 1
        total_weight += evaluation.weight
        weighted_ratio += (grade.score / evaluation.max_score) * evaluation.weight

    average = round(weighted_ratio / total_weight * DISPLAY_SCALE, 2) if total_weight else None
    return GradeStats(average=average, count=count, passed=passed)


def stats_by_subject(grades):
    """``{subject_id: GradeStats}`` para un iterable de ``Grade``."""
    buckets = defaultdict(list)
    for grade in grades:
        buckets[grade.evaluation.subject_id].append(grade)
    return {subject_id: grade_stats(items) for subject_id, items in buckets.items()}
