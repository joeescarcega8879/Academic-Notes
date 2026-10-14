"""Pruebas de calificaciones: validación, permisos por rol y exportación CSV."""

import csv
import io
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.factories import StudentFactory
from apps.courses.factories import CourseFactory, EnrollmentFactory, StudentRecordFactory

from .factories import ActivityFactory, GradeFactory
from .models import Grade

pytestmark = pytest.mark.django_db


def parse_csv(response):
    """Devuelve las filas del CSV (sin BOM) como listas de columnas."""
    text = response.content.decode("utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


# ── Validación de rangos ──────────────────────────────────────────────

class TestValidacionDeRangos:
    def test_nota_negativa_no_pasa_full_clean(self, activity, enrollment):
        grade = Grade(activity=activity, student=enrollment.student, score=-5)
        with pytest.raises(ValidationError) as exc:
            grade.full_clean()
        assert "score" in exc.value.message_dict

    def test_peso_negativo_y_maximo_cero_no_pasan(self, course):
        activity = ActivityFactory.build(course=course, weight=-1, max_score=0)
        with pytest.raises(ValidationError) as exc:
            activity.full_clean()
        assert {"weight", "max_score"} <= set(exc.value.message_dict)

    def test_formulario_rechaza_nota_negativa(self, professor_client, activity, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"activity": activity.pk, "student": enrollment.student.pk, "score": -5, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_formulario_rechaza_nota_sobre_el_maximo(self, professor_client, activity, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"activity": activity.pk, "student": enrollment.student.pk, "score": 11, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_formulario_rechaza_alumno_no_inscrito(self, professor_client, activity):
        intruso = StudentFactory()
        response = professor_client.post(
            reverse("grades:create"),
            {"activity": activity.pk, "student": intruso.pk, "score": 8, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0


# ── Permisos y alcance por rol ────────────────────────────────────────

class TestPermisos:
    def test_profesor_crea_calificacion(self, professor_client, activity, enrollment):
        response = professor_client.post(
            reverse("grades:create"),
            {"activity": activity.pk, "student": enrollment.student.pk, "score": 9, "feedback": "Bien"},
        )
        assert response.status_code == 302
        grade = Grade.objects.get()
        assert (grade.score, grade.feedback) == (9, "Bien")

    def test_profesor_no_puede_calificar_evaluacion_ajena(self, professor_client):
        ajena = ActivityFactory()
        alumno = EnrollmentFactory(course=ajena.course).student
        response = professor_client.post(
            reverse("grades:create"),
            {"activity": ajena.pk, "student": alumno.pk, "score": 9, "feedback": ""},
        )
        assert response.status_code == 200
        assert Grade.objects.count() == 0

    def test_alumno_no_puede_crear(self, student_client, enrollment):
        response = student_client.get(reverse("grades:create"))
        assert response.status_code == 302
        assert response.url == reverse("student_dashboard")

    def test_anonimo_va_al_login(self, client):
        response = client.get(reverse("grades:list"))
        assert response.status_code == 302
        assert response.url.startswith("/login/?next=")

    def test_profesor_solo_ve_sus_calificaciones(self, professor_client, activity, enrollment):
        propia = GradeFactory(activity=activity, student=enrollment.student)
        GradeFactory()  # de otro profesor
        response = professor_client.get(reverse("grades:list"))
        assert list(response.context["grades"]) == [propia]

    def test_alumno_solo_ve_las_suyas(self, student_client, student, activity, enrollment):
        propia = GradeFactory(activity=activity, student=student)
        GradeFactory(activity=activity, student=EnrollmentFactory(course=activity.course).student)
        response = student_client.get(reverse("grades:list"))
        assert list(response.context["grades"]) == [propia]

    def test_profesor_edita_su_calificacion(self, professor_client, activity, enrollment):
        grade = GradeFactory(activity=activity, student=enrollment.student, score=5)
        response = professor_client.post(
            reverse("grades:update", args=[grade.pk]),
            {"activity": activity.pk, "student": enrollment.student.pk, "score": 7, "feedback": ""},
        )
        assert response.status_code == 302
        grade.refresh_from_db()
        assert grade.score == 7

    def test_profesor_no_edita_ni_borra_ajena(self, professor_client):
        ajena = GradeFactory()
        assert professor_client.get(reverse("grades:update", args=[ajena.pk])).status_code == 404
        assert professor_client.post(reverse("grades:delete", args=[ajena.pk])).status_code == 404
        assert Grade.objects.filter(pk=ajena.pk).exists()

    def test_profesor_borra_la_suya(self, professor_client, activity, enrollment):
        grade = GradeFactory(activity=activity, student=enrollment.student)
        response = professor_client.post(reverse("grades:delete", args=[grade.pk]))
        assert response.status_code == 302
        assert not Grade.objects.filter(pk=grade.pk).exists()


# ── Exportación CSV ───────────────────────────────────────────────────

class TestExportacionCsv:
    url = "grades:export"

    def test_profesor_incluye_alumno_y_bom(self, professor_client, activity, enrollment):
        GradeFactory(activity=activity, student=enrollment.student, score=9, feedback="Muy bien")
        response = professor_client.get(reverse(self.url))
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/csv")
        assert response.content.startswith("﻿".encode("utf-8"))
        assert "attachment" in response["Content-Disposition"]
        rows = parse_csv(response)
        assert rows[0][:3] == ["Matrícula", "Alumno", "Email"]
        assert rows[1][2] == enrollment.student.email
        assert "Muy bien" in rows[1]

    def test_alumno_no_ve_columnas_de_alumno_ni_ajenas(self, student_client, student, activity, enrollment):
        GradeFactory(activity=activity, student=student)
        GradeFactory(activity=activity, student=EnrollmentFactory(course=activity.course).student)
        rows = parse_csv(student_client.get(reverse(self.url)))
        assert rows[0][0] == "Grupo"
        assert "Alumno" not in rows[0]
        assert len(rows) == 2  # cabecera + su única calificación

    def test_filtra_por_materia(self, professor_client, professor):
        a = ActivityFactory(course=CourseFactory(professor=professor, name="Álgebra"))
        b = ActivityFactory(course=CourseFactory(professor=professor, name="Cálculo"))
        GradeFactory(activity=a, student=EnrollmentFactory(course=a.course).student)
        GradeFactory(activity=b, student=EnrollmentFactory(course=b.course).student)
        rows = parse_csv(professor_client.get(reverse(self.url), {"materia": a.course_id}))
        assert [r[3] for r in rows[1:]] == ["Álgebra"]

    def test_filtra_por_rango_de_fechas(self, professor_client, activity):
        viejo = GradeFactory(activity=activity, student=EnrollmentFactory(course=activity.course).student)
        nuevo = GradeFactory(activity=activity, student=EnrollmentFactory(course=activity.course).student)
        Grade.objects.filter(pk=viejo.pk).update(graded_at=datetime(2026, 1, 10, 18, tzinfo=dt_timezone.utc))
        Grade.objects.filter(pk=nuevo.pk).update(graded_at=datetime(2026, 3, 10, 18, tzinfo=dt_timezone.utc))

        solo_nuevo = parse_csv(professor_client.get(reverse(self.url), {"desde": "2026-02-01"}))
        solo_viejo = parse_csv(professor_client.get(reverse(self.url), {"hasta": "2026-02-01"}))
        assert [r[2] for r in solo_nuevo[1:]] == [nuevo.student.email]
        assert [r[2] for r in solo_viejo[1:]] == [viejo.student.email]

    def test_incluye_la_matricula_como_texto(self, professor_client, activity):
        alumno = StudentRecordFactory(organization=activity.organization, student_number="00123")
        GradeFactory(activity=activity, student=alumno)
        rows = parse_csv(professor_client.get(reverse(self.url)))
        assert rows[1][0] == "00123"  # con los ceros a la izquierda

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


# ── Promedio con escalas distintas (las cuatro vistas usan el mismo servicio) ──

class TestPromedioNormalizado:
    """Dos notas al 80 %, una sobre 100 y otra sobre 10, deben promediar 8.0 (escala 0–10)."""

    @pytest.fixture
    def escenario(self, student, course, enrollment):
        sobre_100 = ActivityFactory(course=course, max_score=100, weight=1)
        sobre_10 = ActivityFactory(course=course, max_score=10, weight=1)
        GradeFactory(activity=sobre_100, student=student, score=80)
        GradeFactory(activity=sobre_10, student=student, score=8)

    def test_dashboard_del_alumno(self, student_client, escenario, course):
        context = student_client.get(reverse("student_dashboard")).context
        assert context["average"] == 8.0
        assert context["enrollments"][0].course_average == 8.0

    def test_lista_de_calificaciones(self, student_client, escenario):
        assert student_client.get(reverse("grades:list")).context["average"] == 8.0

    def test_detalle_de_materia(self, student_client, escenario, course):
        response = student_client.get(reverse("course_detail", args=[course.pk]))
        assert response.context["course_average"] == 8.0

    def test_dashboard_del_profesor(self, professor_client, escenario):
        context = professor_client.get(reverse("professor_dashboard")).context
        assert context["group_average"] == 8.0
        assert context["courses"][0].average == 8.0
