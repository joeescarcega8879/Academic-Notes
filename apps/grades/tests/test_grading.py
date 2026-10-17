"""Servicio de calificaciones: casos límite del cálculo, sin pasar por las vistas.

La mayoría de las pruebas usan objetos simples (sin base de datos) para fijar las reglas del cálculo;
el final prueba los agregados con modelos reales.
"""

from decimal import Decimal
from itertools import count
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.courses.tests.factories import CourseFactory, StudentRecordFactory

from apps.grades.tests.factories import ActivityFactory, GradeFactory
from apps.grades.models import Activity
from apps.grades.services.grading import (
    DISPLAY_SCALE,
    CourseResult,
    GroupStats,
    PeriodSpec,
    CriterionSpec,
    SchemeSnapshot,
    course_result,
    course_stats,
    group_results,
    overall_average,
    overall_stats,
    results_by_course,
    student_average,
)

_ids = count(1)


def scheme(periods=None, scale=10, pass_mark=6, decimals=2):
    """Esquema de prueba. ``periods``: ``[(nombre, peso, [(criterio, peso), ...]), ...]``."""
    periods = periods or [("Periodo", 100, [("General", 100)])]
    return SchemeSnapshot(
        course_id=1, scale_max=scale, pass_mark=Decimal(str(pass_mark)), decimals=decimals,
        periods=tuple(
            PeriodSpec(
                id=next(_ids), name=name, weight=Decimal(str(weight)),
                criteria=tuple(CriterionSpec(next(_ids), cname, Decimal(str(cweight))) for cname, cweight in criteria),
            )
            for name, weight, criteria in periods
        ),
    )


def criterion(spec, name):
    return next(c for p in spec.periods for c in p.criteria if c.name == name)


def grade(spec, name, score, max_score=10, weight=1, student_id=1, published=True):
    """Calificación en el criterio ``name`` del esquema ``spec``."""
    activity = SimpleNamespace(
        max_score=max_score, weight=weight, criterion_id=criterion(spec, name).id, course_id=spec.course_id,
        published=published,
    )
    return SimpleNamespace(score=score, student_id=student_id, activity=activity)


def final(spec, *grades):
    return course_result(spec, grades).final


# ── Un solo criterio: la base del cálculo ─────────────────────────────

class TestPromedioPonderado:
    def test_sin_calificaciones_no_hay_resultado(self):
        resultado = course_result(scheme(), [])
        assert (resultado.final, resultado.ratio, resultado.passed, resultado.graded) == (None, None, None, 0)

    def test_una_sola_calificacion(self):
        s = scheme()
        assert final(s, grade(s, "General", 7)) == 7.0

    def test_pondera_por_el_peso_de_cada_evaluacion(self):
        s = scheme()
        # (10·1 + 6·3) / 4 = 7.0
        assert final(s, grade(s, "General", 10, weight=1), grade(s, "General", 6, weight=3)) == 7.0

    def test_normaliza_maximos_distintos(self):
        s = scheme()
        assert final(s, grade(s, "General", 80, max_score=100), grade(s, "General", 8, max_score=10)) == 8.0

    def test_una_nota_cero_cuenta(self):
        s = scheme()
        assert final(s, grade(s, "General", 0), grade(s, "General", 10)) == 5.0

    def test_el_peso_cero_no_influye_si_hay_otras(self):
        s = scheme()
        assert final(s, grade(s, "General", 10, weight=0), grade(s, "General", 6, weight=2)) == 6.0

    def test_peso_total_cero_no_divide_entre_cero(self):
        s = scheme()
        assert final(s, grade(s, "General", 9, weight=0), grade(s, "General", 5, weight=0)) is None

    def test_un_maximo_invalido_se_ignora(self):
        s = scheme()
        assert final(s, grade(s, "General", 5, max_score=0), grade(s, "General", 8)) == 8.0
        assert final(s, grade(s, "General", 5, max_score=0)) is None

    def test_una_nota_sobre_el_maximo_no_se_recorta(self):
        s = scheme()
        assert final(s, grade(s, "General", 12)) == 12.0  # crédito extra

    def test_cuenta_las_calificaciones_consideradas(self):
        s = scheme()
        resultado = course_result(s, [grade(s, "General", 8), grade(s, "General", 9), grade(s, "General", 1, weight=0)])
        assert resultado.graded == 2


# ── Escalas ───────────────────────────────────────────────────────────

class TestEscalas:
    @pytest.mark.parametrize("escala, nota, esperado", [(10, 8.5, 8.5), (100, 85, 85.0), (5, 4, 4.0), (20, 15, 15.0)])
    def test_el_resultado_usa_la_escala_del_esquema(self, escala, nota, esperado):
        s = scheme(scale=escala, pass_mark=1)
        assert final(s, grade(s, "General", nota, max_score=escala)) == esperado

    def test_la_proporcion_no_depende_de_la_escala(self):
        s10, s100 = scheme(scale=10), scheme(scale=100, pass_mark=60)
        assert course_result(s10, [grade(s10, "General", 7)]).ratio == course_result(s100, [grade(s100, "General", 7)]).ratio

    def test_display_lleva_cualquier_escala_a_diez(self):
        s = scheme(scale=100, pass_mark=60)
        assert course_result(s, [grade(s, "General", 85, max_score=100)]).display == 8.5
        assert DISPLAY_SCALE == 10


# ── Criterios ─────────────────────────────────────────────────────────

class TestCriterios:
    @pytest.fixture
    def s(self):
        return scheme([("P", 100, [("Exámenes", 60), ("Tareas", 40)])])

    def test_pondera_los_criterios(self, s):
        # 0.6·8 + 0.4·5 = 6.8
        assert final(s, grade(s, "Exámenes", 8), grade(s, "Tareas", 5)) == 6.8

    def test_un_criterio_sin_notas_no_hunde_el_promedio(self, s):
        assert final(s, grade(s, "Exámenes", 8)) == 8.0  # no 4.8

    def test_los_pesos_de_los_criterios_son_relativos(self):
        s = scheme([("P", 100, [("Exámenes", 30), ("Tareas", 20)])])
        assert final(s, grade(s, "Exámenes", 8), grade(s, "Tareas", 5)) == 6.8  # igual que 60/40

    def test_un_criterio_de_peso_cero_se_ignora(self):
        s = scheme([("P", 100, [("Exámenes", 100), ("Extra", 0)])])
        assert final(s, grade(s, "Exámenes", 6), grade(s, "Extra", 10)) == 6.0

    def test_todos_los_criterios_en_cero_no_dan_resultado(self):
        s = scheme([("P", 100, [("A", 0), ("B", 0)])])
        assert final(s, grade(s, "A", 9), grade(s, "B", 9)) is None

    def test_dentro_de_cada_criterio_pesan_las_evaluaciones(self, s):
        # Exámenes: (10·1 + 4·1)/2 = 7 ; Tareas: 5 ; 0.6·7 + 0.4·5 = 6.2
        resultado = final(s, grade(s, "Exámenes", 10), grade(s, "Exámenes", 4), grade(s, "Tareas", 5))
        assert resultado == 6.2

    def test_una_nota_de_un_criterio_ajeno_no_cuenta(self, s):
        otro = scheme([("X", 100, [("Otro", 100)])])
        assert final(s, grade(s, "Exámenes", 8), grade(otro, "Otro", 1)) == 8.0

    def test_desglose_por_criterio(self, s):
        resultado = course_result(s, [grade(s, "Exámenes", 8), grade(s, "Exámenes", 6)])
        (periodo,) = resultado.periods
        examenes, tareas = periodo.criteria
        assert (examenes.name, float(examenes.ratio), examenes.graded) == ("Exámenes", 0.7, 2)
        assert (tareas.name, tareas.ratio, tareas.graded) == ("Tareas", None, 0)


# ── Periodos ──────────────────────────────────────────────────────────

class TestPeriodos:
    @pytest.fixture
    def s(self):
        return scheme([
            ("Parcial 1", 30, [("Exámenes", 50), ("Tareas", 50)]),
            ("Parcial 2", 70, [("Exámenes", 100)]),
        ])

    def test_pondera_los_periodos(self):
        s = scheme([("P1", 30, [("A", 100)]), ("P2", 70, [("B", 100)])])
        # 0.3·10 + 0.7·5 = 6.5
        assert final(s, grade(s, "A", 10), grade(s, "B", 5)) == 6.5

    def test_un_periodo_sin_notas_no_hunde_el_final(self):
        s = scheme([("P1", 30, [("A", 100)]), ("P2", 70, [("B", 100)])])
        assert final(s, grade(s, "A", 9)) == 9.0

    def test_un_periodo_de_peso_cero_se_ignora(self):
        s = scheme([("P1", 100, [("A", 100)]), ("P2", 0, [("B", 100)])])
        assert final(s, grade(s, "A", 6), grade(s, "B", 10)) == 6.0

    def test_los_pesos_de_los_periodos_son_relativos(self):
        s = scheme([("P1", 3, [("A", 100)]), ("P2", 7, [("B", 100)])])
        assert final(s, grade(s, "A", 10), grade(s, "B", 5)) == 6.5

    def test_caso_completo_a_mano(self):
        s = scheme([
            ("Parcial 1", 40, [("Exámenes", 70), ("Tareas", 30)]),
            ("Parcial 2", 60, [("Examen final", 100)]),
        ])
        # Parcial 1 = .7·.9 + .3·.8 = .87 ; Parcial 2 = .7 ; Final = .4·.87 + .6·.7 = .768 -> 7.68
        assert final(
            s,
            grade(s, "Exámenes", 9),
            grade(s, "Tareas", 80, max_score=100),
            grade(s, "Examen final", 7),
        ) == 7.68

    def test_el_desglose_incluye_cada_periodo(self, s):
        resultado = course_result(s, [grade(s, "Exámenes", 8)])
        assert [p.name for p in resultado.periods] == ["Parcial 1", "Parcial 2"]
        assert resultado.periods[0].ratio is not None and resultado.periods[1].ratio is None


# ── Redondeo ──────────────────────────────────────────────────────────

class TestRedondeo:
    @pytest.mark.parametrize("nota, decimales, esperado", [
        (7.125, 2, 7.13),   # round() de Python daría 7.12
        (2.675, 2, 2.68),   # round(2.675, 2) = 2.67 por el error del flotante
        (8.25, 1, 8.3),
        (6.5, 0, 7.0),      # el redondeo al par daría 6
        (7.5, 0, 8.0),
        (7.4, 0, 7.0),
        (9.999, 2, 10.0),
    ])
    def test_mitad_hacia_arriba(self, nota, decimales, esperado):
        s = scheme(decimals=decimales, pass_mark=0)
        assert final(s, grade(s, "General", nota)) == esperado

    def test_se_redondea_una_sola_vez_al_final(self):
        s = scheme([("P", 100, [("A", 50), ("B", 50)])], decimals=0, pass_mark=0)
        # A = 6.4 y B = 6.4 -> 6.4 -> 6. Si cada nivel redondeara antes, daría 6 igual; con 5.5 y 5.4 se nota:
        # (5.5 + 5.4)/2 = 5.45 -> 5 ; redondeando antes (6 y 5) -> 5.5 -> 6
        assert final(s, grade(s, "A", 5.5), grade(s, "B", 5.4)) == 5.0

    def test_la_proporcion_no_se_redondea(self):
        s = scheme(decimals=0, pass_mark=0)
        assert course_result(s, [grade(s, "General", 6.4)]).ratio == pytest.approx(0.64)

    def test_no_arrastra_ruido_de_flotantes(self):
        s = scheme(pass_mark=0)
        # 0.1 + 0.2 != 0.3 en flotantes; con Decimal el promedio de 1/10 y 2/10 es exactamente 1.5
        assert final(s, grade(s, "General", 1, max_score=10), grade(s, "General", 2, max_score=10)) == 1.5


# ── Aprobación ────────────────────────────────────────────────────────

class TestAprobacion:
    def test_el_limite_exacto_aprueba(self):
        s = scheme(pass_mark=6)
        assert course_result(s, [grade(s, "General", 6)]).passed is True

    def test_por_debajo_del_limite_reprueba(self):
        s = scheme(pass_mark=6)
        assert course_result(s, [grade(s, "General", 5.99)]).passed is False

    def test_se_decide_con_la_nota_redondeada(self):
        # 5.95 se muestra como 6.0 con un decimal: el alumno ve que aprueba
        con_un_decimal = scheme(decimals=1, pass_mark=6)
        con_dos = scheme(decimals=2, pass_mark=6)
        assert course_result(con_un_decimal, [grade(con_un_decimal, "General", 5.95)]).passed is True
        assert course_result(con_dos, [grade(con_dos, "General", 5.95)]).passed is False

    def test_con_enteros_5_5_aprueba(self):
        s = scheme(decimals=0, pass_mark=6)
        resultado = course_result(s, [grade(s, "General", 5.5)])
        assert (resultado.final, resultado.passed) == (6.0, True)

    @pytest.mark.parametrize("escala, minimo, nota, aprueba", [
        (100, 70, 70, True), (100, 70, 69.99, False), (5, 3, 3, True), (5, 3, 2.99, False), (20, 10, 10, True),
    ])
    def test_el_minimo_se_expresa_en_la_escala_del_esquema(self, escala, minimo, nota, aprueba):
        s = scheme(scale=escala, pass_mark=minimo)
        assert course_result(s, [grade(s, "General", nota, max_score=escala)]).passed is aprueba

    def test_un_minimo_de_cero_siempre_aprueba(self):
        s = scheme(pass_mark=0)
        assert course_result(s, [grade(s, "General", 0)]).passed is True

    def test_un_minimo_igual_a_la_escala_exige_la_maxima(self):
        s = scheme(pass_mark=10)
        assert course_result(s, [grade(s, "General", 9.99)]).passed is False
        assert course_result(s, [grade(s, "General", 10)]).passed is True


# ── Agregados con modelos reales ──────────────────────────────────────

@pytest.mark.django_db
class TestConModelos:
    def test_con_la_plantilla_por_defecto(self, course):
        alumno = StudentRecordFactory(organization=course.organization)
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM)
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        notas = [GradeFactory(activity=examen, student=alumno, score=8), GradeFactory(activity=tarea, student=alumno, score=6)]
        # Solo Exámenes (40) y Tareas (30) tienen notas: (8·.4 + 6·.3) / .7 = 7.1428… -> 7.14
        resultado = results_by_course(notas)[course.pk]
        assert (resultado.final, resultado.passed) == (7.14, True)

    def test_resultados_de_varios_grupos_con_esquemas_distintos(self):
        a, b = CourseFactory(), CourseFactory()
        b.scheme.scale_max, b.scheme.pass_mark = 100, 60
        b.scheme.save()
        alumno_a = StudentRecordFactory(organization=a.organization)
        alumno_b = StudentRecordFactory(organization=b.organization)
        notas = [
            GradeFactory(activity=ActivityFactory(course=a, max_score=10), student=alumno_a, score=8),
            GradeFactory(activity=ActivityFactory(course=b, max_score=100), student=alumno_b, score=90),
        ]
        resultados = results_by_course(notas)
        assert resultados[a.pk].final == 8.0 and resultados[b.pk].final == 90.0
        assert student_average(resultados) == 8.5  # (8.0 + 9.0) / 2 en escala 0–10

    def test_promedio_general_sin_resultados(self):
        assert student_average({}) is None
        assert overall_average([]) is None

    def test_estadisticas_del_grupo(self, course):
        notas = []
        for puntaje in (10, 6, 4):
            alumno = StudentRecordFactory(organization=course.organization)
            notas.append(GradeFactory(activity=ActivityFactory(course=course), student=alumno, score=puntaje))
        resultados = group_results(notas)
        por_grupo = course_stats(resultados)[course.pk]
        assert por_grupo == GroupStats(average=6.67, students=3, passed=2)
        assert por_grupo.pass_rate == 67  # alumnos aprobados, no calificaciones

    def test_la_aprobacion_es_por_alumno_y_no_por_calificacion(self, course):
        alumno = StudentRecordFactory(organization=course.organization)
        malas = [GradeFactory(activity=ActivityFactory(course=course, weight=1), student=alumno, score=2) for _ in range(3)]
        buena = GradeFactory(activity=ActivityFactory(course=course, weight=20), student=alumno, score=10)
        stats = course_stats(group_results(malas + [buena]))[course.pk]
        assert (stats.students, stats.passed) == (1, 1)  # 3 notas reprobadas pero un final aprobado

    def test_agregado_global_usa_la_escala_de_pantalla(self):
        a, b = CourseFactory(), CourseFactory()
        b.scheme.scale_max, b.scheme.pass_mark = 100, 60
        b.scheme.save()
        notas = [
            GradeFactory(activity=ActivityFactory(course=a), student=StudentRecordFactory(organization=a.organization), score=8),
            GradeFactory(activity=ActivityFactory(course=b, max_score=100), student=StudentRecordFactory(organization=b.organization), score=60),
        ]
        stats = overall_stats(group_results(notas))
        assert (stats.average, stats.students, stats.passed) == (7.0, 2, 2)  # (8 + 6) / 2

    def test_alumnos_sin_resultado_no_cuentan(self, course):
        assert overall_stats({}) == GroupStats(average=None, students=0, passed=0)
        assert GroupStats(None, 0, 0).pass_rate is None

    def test_el_numero_de_consultas_no_crece_con_los_grupos(self):
        def escenario(n):
            notas = []
            for _ in range(n):
                curso = CourseFactory()
                notas.append(GradeFactory(
                    activity=ActivityFactory(course=curso),
                    student=StudentRecordFactory(organization=curso.organization),
                ))
            return notas

        pocas = escenario(2)
        muchas = escenario(8)
        with CaptureQueriesContext(connection) as q_pocas:
            results_by_course(pocas)
        with CaptureQueriesContext(connection) as q_muchas:
            results_by_course(muchas)
        assert len(q_muchas) == len(q_pocas)

    def test_course_result_es_un_valor_inmutable(self):
        resultado = CourseResult(None, None, 10, None, 0)
        with pytest.raises(AttributeError):
            resultado.final = 5


# ── Compatibilidad con el cálculo anterior ────────────────────────────

def test_un_esquema_general_equivale_al_calculo_anterior():
    """Los grupos migrados (un periodo, un criterio) deben dar lo mismo que la media ponderada de antes."""
    import random

    rng = random.Random(2026)
    for _ in range(200):
        s = scheme([("Periodo único", 100, [("General", 100)])])
        notas = []
        for _ in range(rng.randint(1, 8)):
            maximo = rng.choice([5, 10, 20, 50, 100])
            notas.append(grade(s, "General", round(rng.uniform(0, maximo), 1), max_score=maximo, weight=rng.choice([1, 2, 3, 0.5])))
        peso_total = sum(g.activity.weight for g in notas)
        antes = sum(g.score / g.activity.max_score * g.activity.weight for g in notas) / peso_total * 10
        # La escala del esquema es 10, igual que la DISPLAY_SCALE de antes.
        assert final(s, *notas) == pytest.approx(antes, abs=0.0051)


@pytest.mark.parametrize("nivel", ["criterio", "periodo", "evaluacion"])
def test_los_pesos_negativos_de_datos_corruptos_se_ignoran(nivel):
    """Los validadores lo impiden, pero un dato viejo con peso negativo no debe distorsionar el promedio."""
    if nivel == "criterio":
        s = scheme([("P", 100, [("Bueno", 100), ("Malo", -50)])])
    elif nivel == "periodo":
        s = scheme([("P1", 100, [("Bueno", 100)]), ("P2", -50, [("Malo", 100)])])
    else:
        s = scheme([("P", 100, [("Bueno", 100), ("Malo", 100)])])
    malo = grade(s, "Malo", 0, weight=-5 if nivel == "evaluacion" else 1)
    assert final(s, grade(s, "Bueno", 8), malo) == 8.0
