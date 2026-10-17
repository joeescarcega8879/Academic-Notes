"""Pruebas de las notificaciones y de marcarlas como leídas."""

import pytest
from django.urls import reverse

from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.factories import ActivityFactory, GradeFactory
from apps.messaging.tests.factories import ConversationFactory, MessageFactory

pytestmark = pytest.mark.django_db


class TestNotificaciones:
    @pytest.fixture
    def inscrito(self, student, course):
        return EnrollmentFactory(student=student, course=course)

    def context(self, client):
        return client.get(reverse("student_dashboard")).context

    def test_mensaje_sin_leer_del_profesor_cuenta(self, student_client, student, course, professor, inscrito):
        conversation = ConversationFactory(course=course, student=student)
        MessageFactory(conversation=conversation, sender=professor)
        context = self.context(student_client)
        assert context["notifications_count"] == 1
        assert context["notifications"][0]["type"] == "message"

    def test_mensajes_propios_no_cuentan(self, student_client, student, course, inscrito):
        MessageFactory(conversation=ConversationFactory(course=course, student=student), sender=student)
        assert self.context(student_client)["notifications_count"] == 0

    def test_profesor_recibe_mensajes_del_alumno(self, professor_client, student, course, inscrito):
        MessageFactory(conversation=ConversationFactory(course=course, student=student), sender=student)
        context = professor_client.get(reverse("professor_dashboard")).context
        assert context["notifications_count"] == 1

    def test_calificacion_reciente_notifica_al_alumno(self, student_client, student, course, inscrito):
        GradeFactory(activity=ActivityFactory(course=course), student=student)
        context = self.context(student_client)
        assert context["notifications_count"] == 1
        assert context["notifications"][0]["type"] == "grade"

    def test_respeta_la_preferencia_notify_grades(self, student_client, student, course, inscrito):
        student.notify_grades = False
        student.save()
        GradeFactory(activity=ActivityFactory(course=course), student=student)
        assert self.context(student_client)["notifications_count"] == 0

    def test_anonimo_no_tiene_notificaciones(self, client, db):
        response = client.get(reverse("login"))
        assert response.context["notifications_count"] == 0


class TestMarcarLeidas:
    def test_marca_mensajes_y_calificaciones_como_leidos(self, student_client, student, course, professor):
        EnrollmentFactory(student=student, course=course)
        MessageFactory(conversation=ConversationFactory(course=course, student=student), sender=professor)
        GradeFactory(activity=ActivityFactory(course=course), student=student)

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
