"""Acceso, envío y no leídos de la mensajería, vistos desde el navegador."""

import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.messaging.context_processors import unread_messages
from apps.messaging.models import Conversation, Message
from apps.messaging.tests.factories import MessageFactory

pytestmark = pytest.mark.django_db

LISTA = '/mensajes/'


def detalle(conversacion):
    return f'/mensajes/{conversacion.pk}/'


def conv_items(html):
    """El HTML de cada ``.conv-item`` renderizado."""
    return re.findall(r'<a class="conv-item.*?</a>', html, re.S)


# Las fixtures `professor` y `student` de conftest se sobrescriben aquí para tener nombres conocidos.
@pytest.fixture
def professor():
    return ProfessorFactory(first_name='Ana', last_name='Perez')


@pytest.fixture
def student():
    return StudentFactory(first_name='Sofia', last_name='Lopez')


@pytest.fixture
def conversacion(enrollment):
    """Al inscribir al alumno una señal crea la conversación con el docente."""
    return Conversation.objects.get(student=enrollment.student.user, course=enrollment.course)


@pytest.fixture
def conversacion_ajena():
    """La de otro alumno con otro docente, a la que ni ``student`` ni ``professor`` pertenecen."""
    inscripcion = EnrollmentFactory(course=CourseFactory())
    return Conversation.objects.get(student=inscripcion.student.user, course=inscripcion.course)


class TestSenal:
    def test_crea_la_conversacion_al_inscribir(self, enrollment, student, course):
        assert Conversation.objects.filter(course=course, student=student).count() == 1

    def test_cada_inscripcion_tiene_su_conversacion(self, enrollment, conversacion_ajena):
        assert Conversation.objects.count() == 2


class TestAcceso:
    def test_el_profesor_ve_la_lista(self, professor_client, enrollment):
        response = professor_client.get(LISTA)
        assert response.status_code == 200
        assert 'mensajes.html' in [t.name for t in response.templates]

    def test_el_alumno_ve_la_lista(self, student_client, enrollment):
        assert student_client.get(LISTA).status_code == 200

    def test_el_anonimo_va_al_login(self, client):
        response = client.get(LISTA)
        assert response.status_code == 302
        assert '/login/' in response['Location']

    def test_un_participante_ve_el_detalle(self, student_client, conversacion):
        assert student_client.get(detalle(conversacion)).status_code == 200

    def test_el_detalle_ajeno_da_404(self, student_client, enrollment, conversacion_ajena):
        assert student_client.get(detalle(conversacion_ajena)).status_code == 404


class TestEnvio:
    def test_el_post_crea_el_mensaje(self, student_client, student, conversacion):
        response = student_client.post(f'{detalle(conversacion)}enviar/', {'body': 'Hola profe'})
        assert response.status_code == 302
        mensaje = Message.objects.get(conversation=conversacion)
        assert mensaje.sender == student

    def test_un_cuerpo_vacio_no_crea_nada(self, student_client, conversacion):
        student_client.post(f'{detalle(conversacion)}enviar/', {'body': '   '})
        assert not Message.objects.filter(conversation=conversacion).exists()


class TestNoLeidos:
    def test_el_contador_llega_al_contexto(self, student_client, conversacion, professor):
        MessageFactory(conversation=conversacion, sender=professor)
        response = student_client.get(LISTA)
        assert 'unread_count' in response.context
        assert response.context['unread_count'] == 1

    def test_la_insignia_se_dibuja_en_el_menu(self, student_client, conversacion, professor):
        MessageFactory(conversation=conversacion, sender=professor)
        assert 'nav-badge' in student_client.get(LISTA).content.decode()

    def test_abrir_la_conversacion_marca_como_leido(self, student_client, conversacion, professor):
        MessageFactory(conversation=conversacion, sender=professor)
        student_client.get(detalle(conversacion))
        assert not Message.objects.filter(read_at__isnull=True).exists()

    def test_el_anonimo_no_cuenta_no_leidos(self):
        request = RequestFactory().get('/login/')
        request.user = AnonymousUser()
        assert unread_messages(request) == {'unread_count': 0}


class TestContraparte:
    """Antes ``counterpart(user)`` no se podía llamar sin argumentos desde la plantilla."""

    def test_el_alumno_ve_al_profesor_en_la_lista(self, student_client, student, conversacion):
        items = conv_items(student_client.get(LISTA).content.decode())
        assert items, 'no se renderizó ningún .conv-item'
        assert 'Ana Perez' in items[0]
        assert student.email not in items[0]
        assert '>AP<' in items[0]

    def test_el_profesor_ve_al_alumno_en_la_lista(self, professor_client, conversacion):
        items = conv_items(professor_client.get(LISTA).content.decode())
        assert items, 'no se renderizó ningún .conv-item'
        assert 'Sofia Lopez' in items[0]
        assert '>SL<' in items[0]


class TestMenu:
    def test_marca_mensajes_como_activo_en_el_detalle(self, student_client, conversacion):
        assert 'is-active' in student_client.get(detalle(conversacion)).content.decode()
