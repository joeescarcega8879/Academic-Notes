
"""El interruptor de la IA en Ajustes y el contador de usos en «Plan y facturación»."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.ai import services
from apps.ai.models import AIRequest
from apps.organizations.models import Membership, Organization
from apps.organizations.services import SESSION_KEY, teaching_organization
from apps.organizations.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

AJUSTES = reverse('organizations:settings')
PLAN = reverse('organizations:plan')


def cliente(user, org=None):
    c = Client()
    c.force_login(user)
    if org is not None:
        sesion = c.session
        sesion[SESSION_KEY] = org.pk
        sesion.save()
    return c


def con_plan(professor, plan, *, ia=False):
    org = teaching_organization(professor)
    org.plan, org.ai_enabled = plan, ia
    org.save()
    return org


def encender(c, valor):
    return c.post(AJUSTES, {'action': 'ai', 'enabled': valor}, follow=True)


class TestInterruptor:
    def test_plus_ve_el_estado_el_contador_y_el_boton(self, professor):
        org = con_plan(professor, Organization.Plan.TEACHER_PLUS)
        AIRequest.objects.bulk_create([AIRequest(organization=org, kind='probe', provider='fake', status='ok') for _ in range(12)])
        html = cliente(professor).get(AJUSTES).content.decode()
        assert 'IA asistida' in html and 'Apagada' in html and 'Encender la IA' in html
        assert '12 / 300' in html and f'Se renuevan el {services.renewal_label()}' in html

    def test_el_propietario_la_enciende_y_la_apaga(self, professor):
        org = con_plan(professor, Organization.Plan.TEACHER_PLUS)
        c = cliente(professor)
        respuesta = encender(c, 'on')
        org.refresh_from_db()
        assert org.ai_enabled is True and 'La IA asistida quedó encendida.' in respuesta.content.decode()
        assert 'Apagar la IA' in respuesta.content.decode()
        encender(c, 'off')
        org.refresh_from_db()
        assert org.ai_enabled is False

    def test_cualquier_valor_raro_la_deja_apagada(self, professor):
        org = con_plan(professor, Organization.Plan.TEACHER_PLUS, ia=True)
        encender(cliente(professor), 'quizas')
        org.refresh_from_db()
        assert org.ai_enabled is False

    @pytest.mark.parametrize('plan', [Organization.Plan.FREE, Organization.Plan.TEACHER])
    def test_un_plan_sin_ia_no_ve_el_boton_y_no_puede_encenderla(self, professor, plan):
        org = con_plan(professor, plan)
        c = cliente(professor)
        html = c.get(AJUSTES).content.decode()
        assert 'plan Plus, próximamente' in html and 'Encender la IA' not in html
        respuesta = encender(c, 'on')
        org.refresh_from_db()
        assert org.ai_enabled is False and 'no incluye la IA asistida' in respuesta.content.decode()

    def test_un_docente_invitado_no_la_enciende(self, professor):
        org = con_plan(professor, Organization.Plan.TEACHER_PLUS)
        invitado = ProfessorFactory()
        MembershipFactory(user=invitado, organization=org, role=Membership.Role.TEACHER)
        c = cliente(invitado, org)
        html = c.get(AJUSTES).content.decode()
        assert 'Solo quien administra' in html and 'Encender la IA' not in html
        assert c.post(AJUSTES, {'action': 'ai', 'enabled': 'on'}).status_code == 404
        org.refresh_from_db()
        assert org.ai_enabled is False

    def test_actua_solo_sobre_la_organizacion_activa(self, professor):
        propia = con_plan(professor, Organization.Plan.TEACHER_PLUS)
        ajena = con_plan(ProfessorFactory(), Organization.Plan.TEACHER_PLUS)
        encender(cliente(professor), 'on')
        propia.refresh_from_db(), ajena.refresh_from_db()
        assert propia.ai_enabled is True and ajena.ai_enabled is False

    def test_el_alumno_no_entra_a_ajustes(self, student_client):
        assert student_client.post(AJUSTES, {'action': 'ai', 'enabled': 'on'}).status_code == 302

    def test_guardar_el_nombre_sigue_funcionando(self, professor):
        con_plan(professor, Organization.Plan.TEACHER_PLUS)
        cliente(professor).post(AJUSTES, {'name': 'Mi escuela'})
        assert teaching_organization(professor).name == 'Mi escuela'


class TestContadorEnElPlan:
    def test_plus_muestra_los_usos_de_ia(self, professor):
        org = con_plan(professor, Organization.Plan.TEACHER_PLUS)
        AIRequest.objects.bulk_create([AIRequest(organization=org, kind='probe', provider='fake', status='ok') for _ in range(7)])
        html = cliente(professor).get(PLAN).content.decode()
        assert 'Usos de IA este mes' in html and '7 / 300' in html

    @pytest.mark.parametrize('plan', [Organization.Plan.FREE, Organization.Plan.TEACHER])
    def test_los_otros_planes_no_muestran_nada_de_ia(self, professor, plan):
        con_plan(professor, plan)
        assert 'Usos de IA' not in cliente(professor).get(PLAN).content.decode()
