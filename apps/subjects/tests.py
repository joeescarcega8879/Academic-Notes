"""Pruebas de materias: acceso por rol, dashboards con estadísticas y detalle."""

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from apps.accounts.factories import ProfessorFactory
from apps.grades.factories import EvaluationFactory, GradeFactory

from .factories import EnrollmentFactory, SubjectFactory

pytestmark = pytest.mark.django_db


# ── Acceso por rol ────────────────────────────────────────────────────

class TestAccesoPorRol:
    def test_anonimo_va_al_login(self, client):
        for name in ("professor_dashboard", "student_dashboard"):
            response = client.get(reverse(name))
            assert response.status_code == 302
            assert response.url.startswith("/login/?next=")

    def test_cada_rol_ve_su_dashboard(self, professor_client, student_client):
        assert professor_client.get(reverse("professor_dashboard")).status_code == 200
        assert student_client.get(reverse("student_dashboard")).status_code == 200

    def test_cruce_de_roles_redirige_al_dashboard_propio(self, professor_client, student_client):
        assert professor_client.get(reverse("student_dashboard")).url == reverse("professor_dashboard")
        assert student_client.get(reverse("professor_dashboard")).url == reverse("student_dashboard")


# ── Dashboard del profesor ────────────────────────────────────────────

class TestDashboardProfesor:
    @pytest.fixture
    def escenario(self, professor):
        """2 alumnos, 2 evaluaciones (peso 1 y 3) y 3 notas: 10 y 6 de s1, 4 de s2."""
        subject = SubjectFactory(professor=professor)
        s1 = EnrollmentFactory(subject=subject).student
        s2 = EnrollmentFactory(subject=subject).student
        e1 = EvaluationFactory(subject=subject, max_score=10, weight=1)
        e2 = EvaluationFactory(subject=subject, max_score=10, weight=3)
        GradeFactory(evaluation=e1, student=s1, score=10)
        GradeFactory(evaluation=e2, student=s1, score=6)
        GradeFactory(evaluation=e1, student=s2, score=4)
        return subject

    def test_estadisticas_exactas(self, professor_client, escenario):
        context = professor_client.get(reverse("professor_dashboard")).context
        # (10·1 + 6·3 + 4·1) / (1 + 3 + 1) = 6.4
        assert context["group_average"] == 6.4
        # Aprueba con >= 60 % del máximo: 10 y 6 sí, 4 no -> 2 de 3
        assert context["pass_rate"] == 67
        assert context["total_students"] == 2
        assert context["total_evaluations"] == 2
        assert context["graded_count"] == 3

    def test_estadisticas_por_materia(self, professor_client, escenario):
        subject = professor_client.get(reverse("professor_dashboard")).context["subjects"][0]
        assert (subject.student_count, subject.average, subject.pass_rate) == (2, 6.4, 67)

    def test_sin_datos_no_inventa_cifras(self, professor_client, professor):
        SubjectFactory(professor=professor)
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
        a = EnrollmentFactory(student=student).subject
        b = EnrollmentFactory(student=student).subject
        GradeFactory(evaluation=EvaluationFactory(subject=a, weight=1), student=student, score=10)
        GradeFactory(evaluation=EvaluationFactory(subject=a, weight=3), student=student, score=6)
        GradeFactory(evaluation=EvaluationFactory(subject=b, weight=1), student=student, score=8)

        context = student_client.get(reverse("student_dashboard")).context
        por_materia = {e.subject_id: e.subject_average for e in context["enrollments"]}
        assert por_materia == {a.pk: 7.0, b.pk: 8.0}  # (10+18)/4 y 8/1
        assert context["average"] == 7.2  # (10 + 18 + 8) / 5

    def test_sin_notas_el_promedio_es_none(self, student_client, enrollment):
        context = student_client.get(reverse("student_dashboard")).context
        assert context["average"] is None
        assert context["enrollments"][0].subject_average is None

    def test_solo_muestra_sus_materias(self, student_client, enrollment):
        EnrollmentFactory()  # otro alumno
        context = student_client.get(reverse("student_dashboard")).context
        assert [e.subject for e in context["enrollments"]] == [enrollment.subject]


# ── Detalle de materia ────────────────────────────────────────────────

class TestDetalleDeMateria:
    def test_profesor_titular_ve_su_materia(self, professor_client, subject):
        assert professor_client.get(reverse("subject_detail", args=[subject.pk])).status_code == 200

    def test_otro_profesor_recibe_404(self, subject):
        client = Client()
        client.force_login(ProfessorFactory())
        assert client.get(reverse("subject_detail", args=[subject.pk])).status_code == 404

    def test_alumno_inscrito_ve_evaluaciones_y_promedio(self, student_client, student, subject, enrollment):
        e1 = EvaluationFactory(subject=subject, weight=1)
        EvaluationFactory(subject=subject, weight=1)  # aún sin nota
        GradeFactory(evaluation=e1, student=student, score=9)
        response = student_client.get(reverse("subject_detail", args=[subject.pk]))
        assert response.status_code == 200
        assert response.context["subject_average"] == 9.0
        rows = response.context["evaluation_rows"]
        assert len(rows) == 2
        assert sorted(r["grade"] is None for r in rows) == [False, True]

    def test_alumno_no_inscrito_recibe_404(self, student_client, subject):
        assert student_client.get(reverse("subject_detail", args=[subject.pk])).status_code == 404

    def test_anonimo_va_al_login(self, client, subject):
        assert client.get(reverse("subject_detail", args=[subject.pk])).status_code == 302


# ── Inscripciones ─────────────────────────────────────────────────────

def test_no_se_puede_inscribir_dos_veces(db):
    enrollment = EnrollmentFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        EnrollmentFactory(student=enrollment.student, subject=enrollment.subject)
