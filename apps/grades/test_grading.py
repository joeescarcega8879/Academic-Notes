"""Pruebas del servicio de promedios: casos límite sin pasar por las vistas."""

import pytest

from apps.grades.factories import EvaluationFactory, GradeFactory
from apps.grades.services.grading import (
    DISPLAY_SCALE,
    PASS_RATIO,
    grade_stats,
    is_passing,
    stats_by_subject,
    weighted_average,
)

pytestmark = pytest.mark.django_db


def grade(score, max_score=10, weight=1, **kwargs):
    evaluation = EvaluationFactory(max_score=max_score, weight=weight, **kwargs.pop("evaluation", {}))
    return GradeFactory.build(evaluation=evaluation, score=score)


class TestPromedioPonderado:
    def test_sin_calificaciones_no_hay_promedio(self):
        assert weighted_average([]) is None

    def test_una_sola_calificacion(self):
        assert weighted_average([grade(7)]) == 7.0

    def test_pondera_por_peso(self):
        # (10·1 + 6·3) / 4 = 7.0
        assert weighted_average([grade(10, weight=1), grade(6, weight=3)]) == 7.0

    def test_normaliza_escalas_distintas(self):
        assert weighted_average([grade(80, max_score=100), grade(8, max_score=10)]) == 8.0

    def test_el_resultado_usa_la_escala_de_pantalla(self):
        assert weighted_average([grade(50, max_score=50)]) == DISPLAY_SCALE

    def test_peso_total_cero_no_divide_entre_cero(self):
        assert weighted_average([grade(9, weight=0), grade(5, weight=0)]) is None

    def test_peso_cero_no_influye_si_hay_otras(self):
        assert weighted_average([grade(10, weight=0), grade(6, weight=2)]) == 6.0

    def test_maximo_invalido_se_ignora(self):
        malo = grade(5)
        malo.evaluation.max_score = 0  # dato viejo previo a los validadores
        assert weighted_average([malo, grade(8)]) == 8.0
        assert weighted_average([malo]) is None

    def test_redondea_a_dos_decimales(self):
        # (10 + 10 + 9) / 3 = 9.666...
        assert weighted_average([grade(10), grade(10), grade(9)]) == 9.67

    def test_nota_cero_cuenta(self):
        assert weighted_average([grade(0), grade(10)]) == 5.0


class TestAprobacion:
    def test_el_limite_exacto_aprueba(self):
        assert is_passing(6, 10)
        assert is_passing(60, 100)

    def test_por_debajo_del_limite_reprueba(self):
        assert not is_passing(5.9, 10)

    def test_maximo_invalido_nunca_aprueba(self):
        assert not is_passing(5, 0)

    def test_respeta_la_constante(self):
        assert PASS_RATIO == 0.6

    def test_estadisticas(self):
        stats = grade_stats([grade(10), grade(6), grade(4)])
        assert (stats.count, stats.passed, stats.pass_rate) == (3, 2, 67)

    def test_tasa_sin_datos_es_none(self):
        assert grade_stats([]).pass_rate is None


def test_agrupa_por_materia():
    a1, a2, b1 = grade(10), grade(6), grade(8)
    a2.evaluation.subject = a1.evaluation.subject
    por_materia = stats_by_subject([a1, a2, b1])
    assert set(por_materia) == {a1.evaluation.subject_id, b1.evaluation.subject_id}
    assert por_materia[a1.evaluation.subject_id].average == 8.0
    assert por_materia[b1.evaluation.subject_id].average == 8.0
