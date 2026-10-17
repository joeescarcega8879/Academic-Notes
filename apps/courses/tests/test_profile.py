"""El perfil: nada de cifras de ejemplo, el resumen sale de las calificaciones reales del alumno."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import StudentFactory
from apps.courses.services.courses import archive_course
from apps.grades.tests.factories import ActivityFactory
from apps.grades.services.gradebook import grade_activity
from apps.organizations.tests.factories import MembershipFactory
from apps.organizations.models import Membership

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.courses.services.summary import student_summary

pytestmark = pytest.mark.django_db


@pytest.fixture
def grupo_aprobado(student):
    grupo = EnrollmentFactory(student=student).course
    grade_activity(ActivityFactory(course=grupo), student_record(student, grupo), score=9)
    return grupo


def student_record(user, course):
    return course.enrollments.get(student__user=user).student


class TestResumen:
    def test_sin_grupos(self, student, enrollment):
        enrollment.delete()
        resumen = student_summary(student, enrollment.course.organization)
        assert (resumen["groups"], resumen["average"], resumen["tone"]) == (0, None, "")
        assert resumen["passed_share"] == resumen["failed_share"] == resumen["pending_share"] == 0

    def test_grupo_sin_calificaciones_es_pendiente_no_reprobado(self, student, enrollment):
        resumen = student_summary(student, enrollment.course.organization)
        assert (resumen["groups"], resumen["passed"], resumen["failed"], resumen["pending"]) == (1, 0, 0, 1)
        assert resumen["average"] is None and resumen["tone"] == ""

    def test_aprobadas_reprobadas_y_pendientes(self, student, grupo_aprobado):
        reprobado = EnrollmentFactory(student=student, course=CourseFactory(organization=grupo_aprobado.organization)).course
        grade_activity(ActivityFactory(course=reprobado), student_record(student, reprobado), score=2)
        EnrollmentFactory(student=student, course=CourseFactory(organization=grupo_aprobado.organization))
        resumen = student_summary(student, grupo_aprobado.organization)
        assert (resumen["groups"], resumen["passed"], resumen["failed"], resumen["pending"]) == (3, 1, 1, 1)
        assert resumen["average"] == 5.5  # (9 + 2) / 2
        assert resumen["tone"] == "bad"
        assert (resumen["passed_share"], resumen["failed_share"], resumen["pending_share"]) == (33, 33, 33)

    def test_todo_aprobado_es_verde(self, student, grupo_aprobado):
        resumen = student_summary(student, grupo_aprobado.organization)
        assert (resumen["average"], resumen["tone"], resumen["passed_share"]) == (9.0, "ok", 100)

    def test_un_borrador_no_cuenta(self, student, enrollment):
        borrador = ActivityFactory(course=enrollment.course, published=False)
        grade_activity(borrador, enrollment.student, score=1)
        resumen = student_summary(student, enrollment.course.organization)
        assert resumen["average"] is None and resumen["recent"] == []

    def test_un_grupo_archivado_queda_fuera(self, student, grupo_aprobado):
        archive_course(grupo_aprobado)
        resumen = student_summary(student, grupo_aprobado.organization)
        assert (resumen["groups"], resumen["average"]) == (0, None)

    def test_las_notas_de_otro_alumno_no_cuentan(self, student, grupo_aprobado):
        otro = EnrollmentFactory(course=grupo_aprobado).student
        grade_activity(ActivityFactory(course=grupo_aprobado), otro, score=1)
        assert student_summary(student, grupo_aprobado.organization)["average"] == 9.0

    def test_recientes_las_mas_nuevas_primero_y_con_tope(self, student, enrollment):
        for i in range(6):
            grade_activity(ActivityFactory(course=enrollment.course, title=f"Act {i}"), enrollment.student, score=8)
        recientes = student_summary(student, enrollment.course.organization)["recent"]
        assert [g.activity.title for g in recientes] == ["Act 5", "Act 4", "Act 3", "Act 2"]


class TestPagina:
    def test_el_alumno_ve_sus_cifras_y_ninguna_de_ejemplo(self, student_client, student, grupo_aprobado):
        html = student_client.get(reverse("profile")).content.decode()
        assert "Promedio general" in html and ">9.0<" in html
        assert "7.8" not in html and "Cálculo II" not in html and "Prof. Méndez" not in html
        assert "1 grupo activo" in html
        assert grupo_aprobado.name in html

    def test_alumno_sin_calificaciones(self, student_client, enrollment):
        html = student_client.get(reverse("profile")).content.decode()
        assert "Aún no tienes calificaciones publicadas" in html and ">—<" in html and "7.8" not in html

    def test_el_docente_no_ve_el_resumen_de_alumno(self, professor_client, course):
        response = professor_client.get(reverse("profile"))
        html = response.content.decode()
        assert response.status_code == 200 and response.context["summary"] is None
        assert "Promedio general" not in html and "7.8" not in html and "Docente" in html

    def test_cuenta_sin_membresia_sigue_funcionando(self):
        client = Client()
        client.force_login(StudentFactory())
        response = client.get(reverse("profile"))
        assert response.status_code == 200 and response.context["summary"] is None

    def test_rol_sin_pantallas_funciona(self):
        usuario = StudentFactory()
        MembershipFactory(user=usuario, role=Membership.Role.PARENT)
        client = Client()
        client.force_login(usuario)
        assert client.get(reverse("profile")).status_code == 200

    def test_la_campana_de_notificaciones_es_la_real(self, student_client, enrollment):
        grade_activity(ActivityFactory(course=enrollment.course), enrollment.student, score=8)
        html = student_client.get(reverse("profile")).content.decode()
        assert "data-notif-toggle" in html and reverse("notifications_read") in html

    def test_el_alumno_ve_su_matricula_de_la_organizacion(self, student_client, student, enrollment):
        enrollment.student.student_number = "A777"
        enrollment.student.save()
        assert "Matrícula A777" in student_client.get(reverse("profile")).content.decode()


class TestDetallesDelPerfil:
    def test_documento_vacio_no_dice_none(self, student_client, enrollment):
        html = student_client.get(reverse("profile")).content.decode()
        assert 'value="None"' not in html

    def test_alumno_sin_perfil_academico_no_deja_huecos_en_el_menu(self, student_client, enrollment):
        html = student_client.get(reverse("profile")).content.decode()
        assert "º sem" not in html and "Alumno(a)" in html

    def test_los_campos_academicos_estan_en_espanol(self, student_client, professor_client, enrollment):
        alumno = student_client.get(reverse("profile")).content.decode()
        docente = professor_client.get(reverse("profile")).content.decode()
        assert "Programa" in alumno and "Semestre" in alumno and "Program:" not in alumno
        assert "Departamento" in docente and "Department:" not in docente
