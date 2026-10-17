"""Pruebas del servicio de mensajes no leídos."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership
from apps.courses.factories import EnrollmentFactory

from apps.messaging.tests.factories import ConversationFactory, MessageFactory
from apps.messaging.services import mark_all_read, unread_messages_for

pytestmark = pytest.mark.django_db


@pytest.fixture
def hilo(professor, student, course, enrollment):
    return ConversationFactory(course=course, student=student)


def rol_en(user, hilo):
    """Membresía de ``user`` en la organización del hilo."""
    return Membership.objects.get(user=user, organization=hilo.organization)


class TestNoLeidos:
    def test_alumno_ve_lo_que_envio_el_profesor(self, hilo, professor, student):
        mensaje = MessageFactory(conversation=hilo, sender=professor)
        assert list(unread_messages_for(student, rol_en(student, hilo))) == [mensaje]

    def test_profesor_ve_lo_que_envio_el_alumno(self, hilo, professor, student):
        mensaje = MessageFactory(conversation=hilo, sender=student)
        assert list(unread_messages_for(professor, rol_en(professor, hilo))) == [mensaje]

    def test_no_cuenta_los_propios_ni_los_leidos(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=student)
        MessageFactory(conversation=hilo, sender=professor, read_at="2026-01-01T00:00:00Z")
        assert unread_messages_for(student, rol_en(student, hilo)).count() == 0

    def test_no_cuenta_conversaciones_ajenas(self, hilo, professor):
        ajena = ConversationFactory()
        MessageFactory(conversation=ajena, sender=ajena.student)
        assert unread_messages_for(professor, rol_en(professor, hilo)).count() == 0

    def test_otro_profesor_no_recibe_mensajes_de_la_materia(self, hilo, student):
        MessageFactory(conversation=hilo, sender=student)
        otro = ProfessorFactory()
        assert unread_messages_for(otro, Membership.objects.get(user=otro)).count() == 0

    def test_sin_membresia_no_hay_no_leidos(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=professor)
        assert unread_messages_for(student, None).count() == 0

    def test_rol_sin_funcion_docente_ni_alumno_no_tiene_no_leidos(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=professor)
        Membership.objects.filter(user=student, organization=hilo.organization).update(role=Membership.Role.PARENT)
        assert unread_messages_for(student, rol_en(student, hilo)).count() == 0

    def test_solo_cuenta_la_organizacion_de_la_membresia(self, hilo, professor, student):
        MessageFactory(conversation=hilo, sender=professor)
        otra = MembershipFactory(user=student, role=Membership.Role.STUDENT)  # otra organización
        assert unread_messages_for(student, otra).count() == 0


class TestMarcarLeidos:
    def test_marca_solo_los_dirigidos_al_usuario(self, hilo, professor, student):
        para_alumno = MessageFactory(conversation=hilo, sender=professor)
        para_profesor = MessageFactory(conversation=hilo, sender=student)

        assert mark_all_read(student, rol_en(student, hilo)) == 1
        para_alumno.refresh_from_db()
        para_profesor.refresh_from_db()
        assert para_alumno.read_at is not None
        assert para_profesor.read_at is None

    def test_no_toca_conversaciones_de_otros(self, hilo, student):
        ajena = ConversationFactory()
        mensaje = MessageFactory(conversation=ajena, sender=ajena.student)
        mark_all_read(student, rol_en(student, hilo))
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
