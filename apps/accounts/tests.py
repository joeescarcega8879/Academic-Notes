"""Pruebas de cuentas: login, perfil y notificaciones."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.grades.factories import EvaluationFactory, GradeFactory
from apps.messaging.factories import ConversationFactory, MessageFactory
from apps.subjects.factories import EnrollmentFactory

from .factories import PASSWORD, ProfessorFactory, StudentFactory
from .models import ProfessorProfile, StudentProfile

pytestmark = pytest.mark.django_db


# ── Login / logout ────────────────────────────────────────────────────

class TestLogin:
    def test_login_con_email(self, client, student):
        response = client.post(reverse("login"), {"username": student.email, "password": PASSWORD})
        assert response.status_code == 302
        assert response.url == reverse("student_dashboard")

    def test_login_con_username(self, client, professor):
        response = client.post(reverse("login"), {"username": professor.username, "password": PASSWORD})
        assert response.status_code == 302
        assert response.url == reverse("professor_dashboard")

    def test_contrasena_incorrecta_no_inicia_sesion(self, client, student):
        response = client.post(reverse("login"), {"username": student.email, "password": "incorrecta"})
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_usuario_inexistente(self, client, db):
        response = client.post(reverse("login"), {"username": "nadie@prueba.test", "password": PASSWORD})
        assert response.status_code == 200
        assert "_auth_user_id" not in client.session

    def test_rol_elegido_debe_coincidir_con_la_cuenta(self, client, student):
        response = client.post(
            reverse("login"), {"username": student.email, "password": PASSWORD, "role": "professor"}
        )
        assert response.status_code == 200
        assert response.context["error"]
        assert "_auth_user_id" not in client.session

    def test_usuario_autenticado_en_login_va_a_su_dashboard(self, student_client):
        assert student_client.get(reverse("login")).url == reverse("student_dashboard")

    def test_logout_cierra_la_sesion(self, student_client):
        response = student_client.get(reverse("logout"))
        assert response.status_code == 302
        assert "_auth_user_id" not in student_client.session


# ── Perfil ────────────────────────────────────────────────────────────

class TestPerfil:
    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("profile")).status_code == 302

    def test_alumno_ve_su_formulario_extra(self, student_client):
        assert student_client.get(reverse("profile")).status_code == 200

    def test_alumno_guarda_datos_y_perfil_academico(self, student_client, student):
        response = student_client.post(
            reverse("profile"),
            {
                "first_name": "Sofía",
                "last_name": "López",
                "email": student.email,
                "phone": "5512345678",
                "program": "ISC",
                "semester": 5,
                "enrollment_number": "A12345",
            },
        )
        assert response.status_code == 302
        student.refresh_from_db()
        assert student.first_name == "Sofía"
        profile = StudentProfile.objects.get(user=student)
        assert (profile.program, profile.semester) == ("ISC", 5)

    def test_profesor_guarda_departamento(self, professor_client, professor):
        response = professor_client.post(
            reverse("profile"),
            {"first_name": "Ana", "last_name": "Pérez", "email": professor.email, "department": "Física"},
        )
        assert response.status_code == 302
        assert ProfessorProfile.objects.get(user=professor).department == "Física"

    def test_email_duplicado_no_se_guarda(self, student_client, student):
        otro = StudentFactory()
        response = student_client.post(
            reverse("profile"),
            {
                "first_name": "X",
                "last_name": "Y",
                "email": otro.email,
                "program": "ISC",
                "semester": 1,
                "enrollment_number": "A99999",
            },
        )
        assert response.status_code == 200
        student.refresh_from_db()
        assert student.email != otro.email


# ── Notificaciones ────────────────────────────────────────────────────

class TestNotificaciones:
    @pytest.fixture
    def inscrito(self, student, subject):
        return EnrollmentFactory(student=student, subject=subject)

    def context(self, client):
        return client.get(reverse("student_dashboard")).context

    def test_mensaje_sin_leer_del_profesor_cuenta(self, student_client, student, subject, professor, inscrito):
        conversation = ConversationFactory(subject=subject, student=student)
        MessageFactory(conversation=conversation, sender=professor)
        context = self.context(student_client)
        assert context["notifications_count"] == 1
        assert context["notifications"][0]["type"] == "message"

    def test_mensajes_propios_no_cuentan(self, student_client, student, subject, inscrito):
        MessageFactory(conversation=ConversationFactory(subject=subject, student=student), sender=student)
        assert self.context(student_client)["notifications_count"] == 0

    def test_profesor_recibe_mensajes_del_alumno(self, professor_client, student, subject, inscrito):
        MessageFactory(conversation=ConversationFactory(subject=subject, student=student), sender=student)
        context = professor_client.get(reverse("professor_dashboard")).context
        assert context["notifications_count"] == 1

    def test_calificacion_reciente_notifica_al_alumno(self, student_client, student, subject, inscrito):
        GradeFactory(evaluation=EvaluationFactory(subject=subject), student=student)
        context = self.context(student_client)
        assert context["notifications_count"] == 1
        assert context["notifications"][0]["type"] == "grade"

    def test_respeta_la_preferencia_notify_grades(self, student_client, student, subject, inscrito):
        student.notify_grades = False
        student.save()
        GradeFactory(evaluation=EvaluationFactory(subject=subject), student=student)
        assert self.context(student_client)["notifications_count"] == 0

    def test_anonimo_no_tiene_notificaciones(self, client, db):
        response = client.get(reverse("login"))
        assert response.context["notifications_count"] == 0


class TestMarcarLeidas:
    def test_marca_mensajes_y_calificaciones_como_leidos(self, student_client, student, subject, professor):
        EnrollmentFactory(student=student, subject=subject)
        MessageFactory(conversation=ConversationFactory(subject=subject, student=student), sender=professor)
        GradeFactory(evaluation=EvaluationFactory(subject=subject), student=student)

        response = student_client.post(reverse("notifications_read"), {"next": reverse("student_dashboard")})
        assert response.status_code == 302
        assert response.url == reverse("student_dashboard")

        student.refresh_from_db()
        assert student.notifications_read_at is not None
        context = student_client.get(reverse("student_dashboard")).context
        assert context["notifications_count"] == 0

    @pytest.mark.parametrize("destino", ["https://malicioso.example/", "//malicioso.example", "javascript:alert(1)"])
    def test_next_externo_cae_en_el_perfil(self, student_client, destino):
        response = student_client.post(reverse("notifications_read"), {"next": destino})
        assert response.url == reverse("profile")

    def test_no_marca_mensajes_de_otros_usuarios(self, student_client):
        ajeno = ConversationFactory()
        mensaje = MessageFactory(conversation=ajeno, sender=ajeno.student)
        student_client.post(reverse("notifications_read"))
        mensaje.refresh_from_db()
        assert mensaje.read_at is None

    def test_exige_post(self, student_client):
        assert student_client.get(reverse("notifications_read")).status_code == 405

    def test_anonimo_va_al_login(self, client):
        assert client.post(reverse("notifications_read")).status_code == 302


# ── Backend de autenticación ──────────────────────────────────────────

def test_backend_ignora_cuentas_inactivas(db):
    usuario = ProfessorFactory(is_active=False)
    client = Client()
    response = client.post(reverse("login"), {"username": usuario.email, "password": PASSWORD})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session

