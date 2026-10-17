"""Pruebas de materias: acceso por rol, dashboards con estadísticas y detalle."""

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.grades.tests.factories import ActivityFactory, GradeFactory

from apps.courses.tests.factories import EnrollmentFactory, CourseFactory

pytestmark = pytest.mark.django_db


# ── Acceso por rol ────────────────────────────────────────────────────

class TestAccesoPorRol:
    def test_anonimo_va_al_login(self, client):
        for name in ("professor_dashboard", "student_dashboard"):
            response = client.get(reverse(name))
            assert response.status_code == 302
            assert response.url.startswith("/login/?next=")

    def test_cada_rol_ve_su_dashboard(self, professor_client, student_client, enrollment):
        assert professor_client.get(reverse("professor_dashboard")).status_code == 200
        assert student_client.get(reverse("student_dashboard")).status_code == 200

    def test_cruce_de_roles_redirige_al_dashboard_propio(self, professor_client, student_client, enrollment):
        assert professor_client.get(reverse("student_dashboard")).url == reverse("professor_dashboard")
        assert student_client.get(reverse("professor_dashboard")).url == reverse("student_dashboard")


# ── Dashboard del profesor ────────────────────────────────────────────

class TestDashboardProfesor:
    @pytest.fixture
    def escenario(self, professor):
        """2 alumnos, 2 evaluaciones (peso 1 y 3) y 3 notas: 10 y 6 de s1, 4 de s2."""
        course = CourseFactory(professor=professor)
        s1 = EnrollmentFactory(course=course).student
        s2 = EnrollmentFactory(course=course).student
        e1 = ActivityFactory(course=course, max_score=10, weight=1)
        e2 = ActivityFactory(course=course, max_score=10, weight=3)
        GradeFactory(activity=e1, student=s1, score=10)
        GradeFactory(activity=e2, student=s1, score=6)
        GradeFactory(activity=e1, student=s2, score=4)
        return course

    def test_estadisticas_exactas(self, professor_client, escenario):
        context = professor_client.get(reverse("professor_dashboard")).context
        # El promedio es el de los finales de cada alumno: s1 = (10·1 + 6·3)/4 = 7.0 y s2 = 4.0 -> 5.5
        assert context["group_average"] == 5.5
        # Aprueba el alumno cuyo final alcanza el mínimo (6): s1 sí, s2 no -> 1 de 2
        assert context["pass_rate"] == 50
        assert context["total_students"] == 2
        assert context["total_activities"] == 2
        assert context["graded_count"] == 3

    def test_estadisticas_por_materia(self, professor_client, escenario):
        course = professor_client.get(reverse("professor_dashboard")).context["courses"][0]
        assert (course.student_count, course.average, course.pass_rate) == (2, 5.5, 50)

    def test_sin_datos_no_inventa_cifras(self, professor_client, professor):
        CourseFactory(professor=professor)
        context = professor_client.get(reverse("professor_dashboard")).context
        assert context["group_average"] is None
        assert context["pass_rate"] is None
        assert context["total_students"] == 0

    def test_no_cuenta_datos_de_otros_profesores(self, professor_client, escenario):
        GradeFactory(score=1)  # materia de otro profesor
        context = professor_client.get(reverse("professor_dashboard")).context
        assert context["graded_count"] == 3


# ── Dashboard del alumno ──────────────────────────────────────────────

class TestDashboardAlumno:
    def test_promedio_general_y_por_materia(self, student_client, student):
        profesor = ProfessorFactory()
        a = EnrollmentFactory(student=student, course=CourseFactory(professor=profesor)).course
        b = EnrollmentFactory(student=student, course=CourseFactory(professor=profesor)).course
        GradeFactory(activity=ActivityFactory(course=a, weight=1), student=student, score=10)
        GradeFactory(activity=ActivityFactory(course=a, weight=3), student=student, score=6)
        GradeFactory(activity=ActivityFactory(course=b, weight=1), student=student, score=8)

        context = student_client.get(reverse("student_dashboard")).context
        por_materia = {e.course_id: e.course_average for e in context["enrollments"]}
        assert por_materia == {a.pk: 7.0, b.pk: 8.0}  # (10+18)/4 y 8/1
        assert context["average"] == 7.5  # media de los finales de cada materia: (7.0 + 8.0) / 2

    def test_sin_notas_el_promedio_es_none(self, student_client, enrollment):
        context = student_client.get(reverse("student_dashboard")).context
        assert context["average"] is None
        assert context["enrollments"][0].course_average is None

    def test_solo_muestra_sus_materias(self, student_client, enrollment):
        EnrollmentFactory()  # otro alumno
        context = student_client.get(reverse("student_dashboard")).context
        assert [e.course for e in context["enrollments"]] == [enrollment.course]


# ── Detalle de materia ────────────────────────────────────────────────

class TestDetalleDeMateria:
    def test_profesor_titular_ve_su_materia(self, professor_client, course):
        assert professor_client.get(reverse("course_detail", args=[course.pk])).status_code == 200

    def test_otro_profesor_recibe_404(self, course):
        client = Client()
        client.force_login(ProfessorFactory())
        assert client.get(reverse("course_detail", args=[course.pk])).status_code == 404

    def test_alumno_inscrito_ve_evaluaciones_y_promedio(self, student_client, student, course, enrollment):
        e1 = ActivityFactory(course=course, weight=1)
        ActivityFactory(course=course, weight=1)  # aún sin nota
        GradeFactory(activity=e1, student=student, score=9)
        response = student_client.get(reverse("course_detail", args=[course.pk]))
        assert response.status_code == 200
        assert response.context["course_average"] == 9.0
        rows = response.context["activity_rows"]
        assert len(rows) == 2
        assert sorted(r["grade"] is None for r in rows) == [False, True]

    def test_alumno_no_inscrito_recibe_404(self, student_client, course, enrollment):
        otra = CourseFactory(professor=course.professor)  # misma organización, sin inscripción
        assert student_client.get(reverse("course_detail", args=[otra.pk])).status_code == 404

    def test_anonimo_va_al_login(self, client, course):
        assert client.get(reverse("course_detail", args=[course.pk])).status_code == 302


# ── Inscripciones ─────────────────────────────────────────────────────

def test_no_se_puede_inscribir_dos_veces(db):
    enrollment = EnrollmentFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        EnrollmentFactory(student=enrollment.student, course=enrollment.course)
