"""Pruebas de calificaciones: validación, permisos por rol y exportación CSV."""

import csv
import io
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.factories import StudentFactory
from apps.subjects.factories import EnrollmentFactory, SubjectFactory

from .factories import EvaluationFactory, GradeFactory
from .models import Grade

pytestmark = pytest.mark.django_db


def parse_csv(response):
    """Devuelve las filas del CSV (sin BOM) como listas de columnas."""
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# ── Validación de rangos ──────────────────────────────────────────────

class TestValidacionDeRangos:
    def test_nota_negativa_no_pasa_full_clean(self, evaluation, enrollment):
        grade = Grade(evaluation=evaluation, student=enrollment.student, score=-5)
        with pytest.raises(ValidationError) as exc:
            grade.full_clean()
        assert "score" in exc.value.message_dict

    def test_peso_negativo_y_maximo_cero_no_pasan(self, subject):
        evaluation = EvaluationFactory.build(subject=subject, weight=-1, max_score=0)
        with pytest.raises(ValidationError) as exc:
            evaluation.full_clean()
        assert {"weight", "max_score"} <= set(exc.value.message_dict)

    def test_formulario_rechaza_nota_negativa(self, professor_client, evaluation, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"evaluation": evaluation.pk, "student": enrollment.student.pk, "score": -5, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_formulario_rechaza_nota_sobre_el_maximo(self, professor_client, evaluation, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"evaluation": evaluation.pk, "student": enrollment.student.pk, "score": 11, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_formulario_rechaza_alumno_no_inscrito(self, professor_client, evaluation):
        intruso = StudentFactory()
        response = professor_client.post(
            reverse("grades:create"),
            {"evaluation": evaluation.pk, "student": intruso.pk, "score": 8, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0


# ── Permisos y alcance por rol ────────────────────────────────────────

class TestPermisos:
    def test_profesor_crea_calificacion(self, professor_client, evaluation, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"evaluation": evaluation.pk, "student": enrollment.student.pk, "score": 9, "feedback": "Bien"},
        )
        assert response.status_code == 302
        grade = Grade.objects.get()
        assert (grade.score, grade.feedback) == (9, "Bien")

    def test_profesor_no_puede_calificar_evaluacion_ajena(self, professor_client):
        ajena = EvaluationFactory()
        alumno = EnrollmentFactory(subject=ajena.subject).student
        response = professor_client.post(
            reverse("grades:create"),
            {"evaluation": ajena.pk, "student": alumno.pk, "score": 9, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_alumno_no_puede_crear(self, student_client):
        response = student_client.get(reverse("grades:create"))
        assert response.status_code == 302
        assert response.url == reverse("student_dashboard")

    def test_anonimo_va_al_login(self, client):
        response = client.get(reverse("grades:list"))
        assert response.status_code == 302
        assert response.url.startswith("/login/?next=")

    def test_profesor_solo_ve_sus_calificaciones(self, professor_client, evaluation, enrollment):
        propia = GradeFactory(evaluation=evaluation, student=enrollment.student)
        GradeFactory()  # de otro profesor
        response = professor_client.get(reverse("grades:list"))
        assert list(response.context["grades"]) == [propia]

    def test_alumno_solo_ve_las_suyas(self, student_client, student, evaluation, enrollment):
        propia = GradeFactory(evaluation=evaluation, student=student)
        GradeFactory(evaluation=evaluation, student=EnrollmentFactory(subject=evaluation.subject).student)
        response = student_client.get(reverse("grades:list"))
        assert list(response.context["grades"]) == [propia]

    def test_profesor_edita_su_calificacion(self, professor_client, evaluation, enrollment):
        grade = GradeFactory(evaluation=evaluation, student=enrollment.student, score=5)
        response = professor_client.post(
            reverse("grades:update", args=[grade.pk]),
            {"evaluation": evaluation.pk, "student": enrollment.student.pk, "score": 7, "feedback": ""},
        )
        assert response.status_code == 302
        grade.refresh_from_db()
        assert grade.score == 7

    def test_profesor_no_edita_ni_borra_ajena(self, professor_client):
        ajena = GradeFactory()
        assert professor_client.get(reverse("grades:update", args=[ajena.pk])).status_code == 404
        assert professor_client.post(reverse("grades:delete", args=[ajena.pk])).status_code == 404
        assert Grade.objects.filter(pk=ajena.pk).exists()

    def test_profesor_borra_la_suya(self, professor_client, evaluation, enrollment):
        grade = GradeFactory(evaluation=evaluation, student=enrollment.student)
        response = professor_client.post(reverse("grades:delete", args=[grade.pk]))
        assert response.status_code == 302
        assert not Grade.objects.filter(pk=grade.pk).exists()


# ── Exportación CSV ───────────────────────────────────────────────────

class TestExportacionCsv:
    url = "grades:export"

    def test_profesor_incluye_alumno_y_bom(self, professor_client, evaluation, enrollment):
        GradeFactory(evaluation=evaluation, student=enrollment.student, score=9, feedback="Muy bien")
        response = professor_client.get(reverse(self.url))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert response.content.startswith("﻿".encode("utf-8"))
        assert "attachment" in response["Content-Disposition"]
        rows = parse_csv(response)
        assert rows[0][:2] == ["Alumno", "Email"]
        assert rows[1][1] == enrollment.student.email
        assert "Muy bien" in rows[1]

    def test_alumno_no_ve_columnas_de_alumno_ni_ajenas(self, student_client, student, evaluation, enrollment):
        GradeFactory(evaluation=evaluation, student=student)
        GradeFactory(evaluation=evaluation, student=EnrollmentFactory(subject=evaluation.subject).student)
        rows = parse_csv(student_client.get(reverse(self.url)))
        assert rows[0][0] == "Materia"
        assert "Alumno" not in rows[0]
        assert len(rows) == 2  # cabecera + su única calificación

    def test_filtra_por_materia(self, professor_client, professor):
        a = EvaluationFactory(subject=SubjectFactory(professor=professor, name="Álgebra"))
        b = EvaluationFactory(subject=SubjectFactory(professor=professor, name="Cálculo"))
        GradeFactory(evaluation=a, student=EnrollmentFactory(subject=a.subject).student)
        GradeFactory(evaluation=b, student=EnrollmentFactory(subject=b.subject).student)
        rows = parse_csv(professor_client.get(reverse(self.url), {"materia": a.subject_id}))
        assert [r[2] for r in rows[1:]] == ["Álgebra"]

    def test_filtra_por_rango_de_fechas(self, professor_client, evaluation):
        viejo = GradeFactory(evaluation=evaluation, student=EnrollmentFactory(subject=evaluation.subject).student)
        nuevo = GradeFactory(evaluation=evaluation, student=EnrollmentFactory(subject=evaluation.subject).student)
        Grade.objects.filter(pk=viejo.pk).update(graded_at=datetime(2026, 1, 10, 18, tzinfo=dt_timezone.utc))
        Grade.objects.filter(pk=nuevo.pk).update(graded_at=datetime(2026, 3, 10, 18, tzinfo=dt_timezone.utc))

        solo_nuevo = parse_csv(professor_client.get(reverse(self.url), {"desde": "2026-02-01"}))
        solo_viejo = parse_csv(professor_client.get(reverse(self.url), {"hasta": "2026-02-01"}))
        assert [r[1] for r in solo_nuevo[1:]] == [nuevo.student.email]
        assert [r[1] for r in solo_viejo[1:]] == [viejo.student.email]

    @pytest.mark.parametrize(
        "params",
        [
            {"desde": "abc"},
            {"hasta": "2026-13-45"},
            {"materia": "abc"},
            {"materia": "1 OR 1=1"},
        ],
    )
    def test_parametros_invalidos_dan_400_no_500(self, professor_client, params):
        assert professor_client.get(reverse(self.url), params).status_code == 400

    def test_parametros_vacios_se_ignoran(self, professor_client):
        response = professor_client.get(reverse(self.url), {"materia": "", "desde": "", "hasta": ""})
        assert response.status_code == 200

    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse(self.url)).status_code == 302


# ── Promedio ponderado ────────────────────────────────────────────────

@pytest.mark.xfail(
    strict=True,
    reason="Bug conocido: el promedio mezcla puntos crudos sin normalizar por max_score. "
    "Se arregla con services/grading.py (Sprint 2); al corregirlo hay que quitar este xfail.",
)
def test_promedio_normaliza_escalas_distintas(student_client, student, subject, enrollment):
    sobre_100 = EvaluationFactory(subject=subject, max_score=100, weight=1)
    sobre_10 = EvaluationFactory(subject=subject, max_score=10, weight=1)
    GradeFactory(evaluation=sobre_100, student=student, score=80)  # 80 %
    GradeFactory(evaluation=sobre_10, student=student, score=8)  # 80 %
    response = student_client.get(reverse("student_dashboard"))
    assert response.context["average"] == 80
