"""Ajustes del docente: nombre de su organización, ciclo actual y estado de la cuenta."""

import datetime

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.courses.factories import AcademicYearFactory
from apps.organizations.factories import MembershipFactory, OrganizationFactory
from apps.organizations.models import Membership, Organization
from apps.organizations.services import SESSION_KEY

pytestmark = pytest.mark.django_db

URL = reverse('organizations:settings')


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


def organizacion_de(user):
    return Membership.objects.get(user=user).organization


class TestAcceso:
    def test_sin_sesion_va_al_login(self):
        respuesta = Client().get(URL)
        assert respuesta.status_code == 302 and '/login/' in respuesta.url

    def test_un_alumno_no_entra(self):
        respuesta = cliente(StudentFactory()).get(URL)
        assert respuesta.status_code == 302 and respuesta.url != URL

    def test_el_docente_entra(self):
        respuesta = cliente(ProfessorFactory()).get(URL)
        assert respuesta.status_code == 200
        assert 'Ajustes' in respuesta.content.decode()


class TestNombreDeLaOrganizacion:
    def test_el_propietario_lo_cambia(self):
        docente = ProfessorFactory()
        respuesta = cliente(docente).post(URL, {'name': 'Escuela Primaria Benito Juárez'}, follow=True)
        assert organizacion_de(docente).name == 'Escuela Primaria Benito Juárez'
        assert 'Guardamos el nombre de tu organización.' in respuesta.content.decode()

    def test_limpia_espacios_y_saltos_de_linea(self):
        docente = ProfessorFactory()
        cliente(docente).post(URL, {'name': '  Colegio\n  Del   Valle  '})
        assert organizacion_de(docente).name == 'Colegio Del Valle'

    @pytest.mark.parametrize('nombre', ['', '   ', 'x' * 151])
    def test_un_nombre_invalido_no_se_guarda_y_se_explica(self, nombre):
        docente = ProfessorFactory()
        antes = organizacion_de(docente).name
        respuesta = cliente(docente).post(URL, {'name': nombre})
        assert respuesta.status_code == 200
        assert 'field-error' in respuesta.content.decode()
        assert organizacion_de(docente).name == antes

    def test_solo_cambia_la_organizacion_propia_aunque_se_mande_otra(self):
        docente, otro = ProfessorFactory(), ProfessorFactory()
        ajena = organizacion_de(otro)
        nombre_ajeno = ajena.name
        cliente(docente).post(URL, {'name': 'Mi escuela', 'id': ajena.pk, 'organization': ajena.pk, 'pk': ajena.pk})
        assert organizacion_de(docente).name == 'Mi escuela'
        ajena.refresh_from_db()
        assert ajena.name == nombre_ajeno

    def test_no_toca_el_tipo_ni_el_plan(self):
        docente = ProfessorFactory()
        organizacion = organizacion_de(docente)
        tipo, plan = organizacion.type, organizacion.plan
        cliente(docente).post(URL, {'name': 'Otra', 'type': 'institution', 'plan': 'enterprise', 'is_active': ''})
        organizacion.refresh_from_db()
        assert (organizacion.type, organizacion.plan, organizacion.is_active) == (tipo, plan, True)

    def test_un_docente_invitado_a_una_institucion_la_ve_pero_no_la_renombra(self):
        docente = ProfessorFactory()
        institucion = OrganizationFactory(name='Colegio Alfa')
        MembershipFactory(user=docente, organization=institucion, role=Membership.Role.TEACHER)
        client = cliente(docente)
        session = client.session
        session[SESSION_KEY] = institucion.pk
        session.save()
        respuesta = client.get(URL)
        html = respuesta.content.decode()
        assert respuesta.status_code == 200 and 'Colegio Alfa' in html
        assert 'Guardar nombre' not in html
        assert client.post(URL, {'name': 'Hackeado'}).status_code == 404
        assert Organization.objects.get(pk=institucion.pk).name == 'Colegio Alfa'


class TestCicloYCuenta:
    def test_muestra_el_ciclo_actual_y_no_el_de_otra_organizacion(self):
        # El ajeno empieza después: una consulta sin filtrar por organización lo devolvería antes que el propio
        # (los ciclos se ordenan del más reciente al más antiguo).
        AcademicYearFactory(
            organization=organizacion_de(ProfessorFactory()), name='Ciclo Ajeno', is_current=True,
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2027, 8, 31),
        )
        docente = ProfessorFactory()
        AcademicYearFactory(organization=organizacion_de(docente), name='Ciclo 2026-2027', is_current=True)
        html = cliente(docente).get(URL).content.decode()
        assert 'Ciclo 2026-2027' in html and 'Ciclo Ajeno' not in html
        assert reverse('academic_years') in html

    def test_sin_ciclo_actual_lo_dice(self):
        docente = ProfessorFactory()  # la organización individual de la fábrica nace sin ciclo
        assert 'Aún no hay un ciclo' in cliente(docente).get(URL).content.decode()

    def test_correo_sin_confirmar_ofrece_reenviarlo(self):
        docente = ProfessorFactory(email_verified_at=None)
        html = cliente(docente).get(URL).content.decode()
        assert 'Sin confirmar' in html and reverse('resend_verification') in html

    def test_correo_confirmado_se_marca(self):
        docente = ProfessorFactory(email_verified_at=timezone.now())
        html = cliente(docente).get(URL).content.decode()
        assert 'Confirmado' in html and 'Sin confirmar' not in html

    def test_enlaces_a_perfil_notificaciones_y_contrasena(self):
        html = cliente(ProfessorFactory()).get(URL).content.decode()
        assert reverse('profile') in html and f'{reverse("profile")}#preferencias' in html
        assert reverse('password_change') in html
        perfil = cliente(ProfessorFactory()).get(reverse('profile')).content.decode()
        assert 'id="preferencias"' in perfil
