"""Pruebas del servicio de mensajes no leídos."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.factories import ProfessorFactory
from apps.subjects.factories import EnrollmentFactory

from .factories import ConversationFactory, MessageFactory
from .services import mark_all_read, unread_messages_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def hilo(professor, student, subject, enrollment):
    return ConversationFactory(subject=subject, student=student)


class TestNoLeidos:
    def test_alumno_ve_lo_que_envio_el_profesor(self, hilo, professor, student):
        mensaje = MessageFactory(conversation=hilo, sender=professor)
        assert list(unread_messages_for(student)) == [mensaje]

    def test_profesor_ve_lo_que_envio_el_alumno(self, hilo, professor, student):
        mensaje = MessageFactory(conversation=hilo, sender=student)
        assert list(unread_messages_for(professor)) == [mensaje]

    def test_no_cuenta_los_propios_ni_los_leidos(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=student)
        MessageFactory(conversation=hilo, sender=professor, read_at="2026-01-01T00:00:00Z")
        assert unread_messages_for(student).count() == 0

    def test_no_cuenta_conversaciones_ajenas(self, hilo, professor):
        ajena = ConversationFactory()
        MessageFactory(conversation=ajena, sender=ajena.student)
        assert unread_messages_for(professor).count() == 0

    def test_otro_profesor_no_recibe_mensajes_de_la_materia(self, hilo, student):
        MessageFactory(conversation=hilo, sender=student)
        assert unread_messages_for(ProfessorFactory()).count() == 0

    def test_rol_desconocido_no_tiene_no_leidos(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=professor)
        student.role = ""
        assert unread_messages_for(student).count() == 0


class TestMarcarLeidos:
    def test_marca_solo_los_dirigidos_al_usuario(self, hilo, professor, student):
        para_alumno = MessageFactory(conversation=hilo, sender=professor)
        para_profesor = MessageFactory(conversation=hilo, sender=student)

        assert mark_all_read(student) == 1
        para_alumno.refresh_from_db()
        para_profesor.refresh_from_db()
        assert para_alumno.read_at is not None
        assert para_profesor.read_at is None

    def test_no_toca_conversaciones_de_otros(self, hilo, student):
        ajena = ConversationFactory()
        mensaje = MessageFactory(conversation=ajena, sender=ajena.student)
        mark_all_read(student)
        mensaje.refresh_from_db()
        assert mensaje.read_at is None


def test_la_consulta_de_no_leidos_se_hace_una_vez_por_pagina(student_client, hilo, professor):
    for _ in range(3):
        MessageFactory(conversation=hilo, sender=professor)
    EnrollmentFactory(student=hilo.student)  # relleno: más datos no deben añadir consultas

    with CaptureQueriesContext(connection) as queries:
        response = student_client.get(reverse("student_dashboard"))

    assert response.context["unread_count"] == 3
    conteos = [q["sql"] for q in queries if "COUNT(*)" in q["sql"] and "messaging_message" in q["sql"]]
    assert len(conteos) == 1, conteos
