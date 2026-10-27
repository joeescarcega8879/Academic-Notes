"""La escuela y su equipo: la dirección invita a docentes por correo y ellos aceptan con su cuenta."""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.tests.factories import CourseFactory
from apps.organizations import school
from apps.organizations.models import Membership, Organization, OrganizationInvitation
from apps.organizations.services import SESSION_KEY, teaching_organization
from apps.onboarding.tests.test_registration import datos
from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory

pytestmark = pytest.mark.django_db

DIA = datetime.timedelta(days=1)
User = get_user_model()


def cliente_de(usuario, organizacion=None):
    client = Client()
    client.force_login(usuario)
    if organizacion is not None:
        sesion = client.session
        sesion[SESSION_KEY] = organizacion.pk
        sesion.save()
    return client


@pytest.fixture
def escuela():
    return OrganizationFactory(name='Colegio Benito Juárez', type=Organization.Type.INSTITUTION)


@pytest.fixture
def directora(escuela):
    usuario = ProfessorFactory(first_name='Rosa', last_name='Directora', email='directora@colegio.test')
    MembershipFactory(user=usuario, organization=escuela, role=Membership.Role.ADMIN)
    return usuario


@pytest.fixture
def docente():
    return ProfessorFactory(first_name='Luis', last_name='Docente', email='luis@colegio.test')


def invitar(escuela, directora, correo='luis@colegio.test'):
    return school.invite_teacher(escuela, correo, by=directora)


# ── Quién es «dirección» ──────────────────────────────────────────────

class TestDireccion:
    @pytest.mark.parametrize('rol, tipo, esperado', [
        (Membership.Role.OWNER, Organization.Type.INSTITUTION, True),
        (Membership.Role.ADMIN, Organization.Type.INSTITUTION, True),
        (Membership.Role.COORDINATOR, Organization.Type.INSTITUTION, True),
        (Membership.Role.TEACHER, Organization.Type.INSTITUTION, False),
        (Membership.Role.STUDENT, Organization.Type.INSTITUTION, False),
        (Membership.Role.OWNER, Organization.Type.INDIVIDUAL, False),  # el docente individual no es «dirección»
    ])
    def test_es_direccion(self, rol, tipo, esperado):
        membresia = MembershipFactory(organization=OrganizationFactory(type=tipo), role=rol)
        assert membresia.is_direction is esperado

    def test_un_coordinador_no_da_clase_pero_dirige(self, escuela):
        membresia = MembershipFactory(organization=escuela, role=Membership.Role.COORDINATOR, user=ProfessorFactory())
        assert membresia.is_direction and not membresia.is_teacher


class TestEstadoDeLaInvitacion:
    def test_vigente_vencida_usada_y_retirada(self, escuela, directora, docente):
        vigente = invitar(escuela, directora, 'a@x.test')
        assert (vigente.is_open, vigente.is_usable, vigente.is_expired) == (True, True, False)
        OrganizationInvitation.objects.filter(pk=vigente.pk).update(expires_at=timezone.now() - DIA)
        vigente.refresh_from_db()
        assert (vigente.is_open, vigente.is_usable, vigente.is_expired) == (True, False, True)

    def test_una_usada_o_retirada_que_ya_paso_de_fecha_no_cuenta_como_vencida(self, escuela, directora, docente):
        usada, retirada = invitar(escuela, directora), invitar(escuela, directora, 'b@x.test')
        school.accept(usada, docente)
        school.revoke(retirada, by=directora)
        OrganizationInvitation.objects.update(expires_at=timezone.now() - DIA)
        for invitacion in OrganizationInvitation.objects.exclude(email='directora@colegio.test'):
            assert (invitacion.is_open, invitacion.is_usable, invitacion.is_expired) == (False, False, False)


# ── Invitar ───────────────────────────────────────────────────────────

class TestInvitar:
    def test_crea_la_invitacion_y_manda_el_correo(self, escuela, directora, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            invitacion = invitar(escuela, directora, '  Luis@Colegio.TEST ')
        assert invitacion.email == 'luis@colegio.test' and invitacion.organization == escuela and invitacion.invited_by == directora
        assert invitacion.is_usable and invitacion.expires_at - invitacion.created_at > 13 * DIA
        correo, = mail.outbox
        assert correo.to == ['luis@colegio.test'] and 'Colegio Benito Juárez' in correo.subject
        assert school.accept_path(invitacion) in correo.body and 'Rosa Directora' in correo.body and '14 días' in correo.body
        assert 'no pierdes nada' in correo.body

    def test_el_enlace_es_largo_y_distinto_cada_vez(self, escuela, directora):
        uno, dos = invitar(escuela, directora, 'a@x.test'), invitar(escuela, directora, 'b@x.test')
        assert len(uno.token) >= 40 and uno.token != dos.token

    @pytest.mark.parametrize('correo', ['', '   ', 'sin-arroba', 'a@', '@b.test', 'dos@@x.test', 'a b@x.test', 'x' * 250 + '@x.test'])
    def test_un_correo_invalido(self, escuela, directora, correo):
        with pytest.raises(ValidationError):
            invitar(escuela, directora, correo)
        assert not OrganizationInvitation.objects.exists()

    def test_solo_la_direccion_invita(self, escuela, docente):
        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        with pytest.raises(ValidationError, match='Solo la dirección'):
            invitar(escuela, docente, 'otro@x.test')

    def test_quien_no_es_de_la_escuela_no_invita(self, escuela, docente):
        with pytest.raises(ValidationError, match='Solo la dirección'):
            invitar(escuela, docente, 'otro@x.test')

    def test_el_propietario_de_un_docente_individual_no_invita(self):
        profesor = ProfessorFactory()
        individual = teaching_organization(profesor)
        with pytest.raises(ValidationError, match='Solo la dirección'):
            school.invite_teacher(individual, 'a@x.test', by=profesor)

    def test_quien_ya_es_parte_de_la_escuela_no_se_invita(self, escuela, directora, docente):
        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        with pytest.raises(ValidationError, match='ya es parte'):
            invitar(escuela, directora, 'LUIS@colegio.test')

    def test_una_invitacion_abierta_por_correo(self, escuela, directora):
        invitar(escuela, directora)
        with pytest.raises(ValidationError, match='pendiente'):
            invitar(escuela, directora, 'LUIS@colegio.test')
        assert OrganizationInvitation.objects.count() == 1

    def test_una_vencida_no_estorba_a_la_nueva(self, escuela, directora):
        vieja = invitar(escuela, directora)
        OrganizationInvitation.objects.filter(pk=vieja.pk).update(expires_at=timezone.now() - DIA)
        nueva = invitar(escuela, directora)
        vieja.refresh_from_db()
        assert vieja.revoked_at is not None and nueva.is_usable and nueva.pk != vieja.pk

    def test_el_mismo_correo_en_otra_escuela_no_choca(self, escuela, directora):
        otra = OrganizationFactory(type=Organization.Type.INSTITUTION)
        otra_directora = ProfessorFactory()
        MembershipFactory(user=otra_directora, organization=otra, role=Membership.Role.OWNER)
        invitar(escuela, directora)
        assert school.invite_teacher(otra, 'luis@colegio.test', by=otra_directora).organization == otra

    def test_tope_de_invitaciones_pendientes(self, escuela, directora, monkeypatch):
        monkeypatch.setattr(school, 'MAX_OPEN_INVITATIONS', 2)
        invitar(escuela, directora, 'a@x.test')
        invitar(escuela, directora, 'b@x.test')
        with pytest.raises(ValidationError, match='2 invitaciones pendientes'):
            invitar(escuela, directora, 'c@x.test')

    def test_freno_por_hora(self, escuela, directora, monkeypatch):
        monkeypatch.setattr(school, 'INVITES_PER_HOUR', 2)
        invitar(escuela, directora, 'a@x.test')
        invitar(escuela, directora, 'b@x.test')
        with pytest.raises(ValidationError, match='muchas invitaciones'):
            invitar(escuela, directora, 'c@x.test')


class TestReenviarYRetirar:
    def test_reenviar_da_otros_14_dias_y_manda_otro_correo(self, escuela, directora, django_capture_on_commit_callbacks):
        invitacion = invitar(escuela, directora)
        OrganizationInvitation.objects.filter(pk=invitacion.pk).update(expires_at=timezone.now() - DIA)
        invitacion.refresh_from_db()
        with django_capture_on_commit_callbacks(execute=True):
            school.resend(invitacion, by=directora)
        invitacion.refresh_from_db()
        assert invitacion.is_usable and invitacion.expires_at > timezone.now() + 13 * DIA and len(mail.outbox) == 1

    def test_reenviar_tiene_tope_por_dia(self, escuela, directora):
        invitacion = invitar(escuela, directora)
        for _ in range(school.RESENDS_PER_DAY):
            school.resend(invitacion, by=directora)
        with pytest.raises(ValidationError, match='varias veces'):
            school.resend(invitacion, by=directora)

    def test_retirar_inutiliza_el_enlace(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        school.revoke(invitacion, by=directora)
        with pytest.raises(ValidationError, match='retiró'):
            school.accept(invitacion, docente)
        assert not Membership.objects.filter(user=docente, organization=escuela).exists()

    def test_no_se_retira_ni_reenvia_lo_ya_cerrado(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        school.accept(invitacion, docente)
        invitacion.refresh_from_db()
        for accion in (school.revoke, school.resend):
            with pytest.raises(ValidationError, match='ya se usó'):
                accion(invitacion, by=directora)

    def test_solo_la_direccion_de_esa_escuela(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        for accion in (school.revoke, school.resend):
            with pytest.raises(ValidationError, match='Solo la dirección'):
                accion(invitacion, by=docente)
        otra = OrganizationFactory(type=Organization.Type.INSTITUTION)
        otra_directora = ProfessorFactory()
        MembershipFactory(user=otra_directora, organization=otra, role=Membership.Role.OWNER)
        with pytest.raises(ValidationError, match='Solo la dirección'):
            school.revoke(invitacion, by=otra_directora)

    def test_el_correo_no_sale_si_la_invitacion_ya_no_sirve(self, escuela, directora, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            invitacion = invitar(escuela, directora)
            school.revoke(invitacion, by=directora)
        assert mail.outbox == []


# ── Aceptar ───────────────────────────────────────────────────────────

class TestAceptar:
    def test_el_docente_se_suma_como_docente_y_no_pierde_nada(self, escuela, directora, docente):
        propia = teaching_organization(docente)
        grupo = CourseFactory(professor=docente, organization=propia)
        invitacion = invitar(escuela, directora)
        membresia = school.accept(invitation=invitacion, user=docente)
        assert membresia.role == Membership.Role.TEACHER and membresia.organization == escuela
        invitacion.refresh_from_db()
        assert invitacion.accepted_by == docente and invitacion.accepted_at is not None and not invitacion.is_open
        # Su espacio personal y su grupo siguen como estaban.
        assert Membership.objects.filter(user=docente).count() == 2
        assert Membership.objects.get(user=docente, organization=propia).role == Membership.Role.OWNER
        grupo.refresh_from_db()
        assert grupo.organization == propia and grupo.professor == docente

    def test_es_de_un_solo_uso(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        school.accept(invitacion, docente)
        with pytest.raises(ValidationError, match='ya se usó'):
            school.accept(invitacion, docente)

    def test_el_correo_debe_ser_exactamente_el_invitado(self, escuela, directora):
        invitacion = invitar(escuela, directora, 'luis@colegio.test')
        otro = ProfessorFactory(email='otro@colegio.test')
        with pytest.raises(ValidationError, match='es para luis@colegio.test'):
            school.accept(invitacion, otro)
        assert not Membership.objects.filter(user=otro, organization=escuela).exists()

    def test_mayusculas_en_el_correo_de_la_cuenta_no_estorban(self, escuela, directora):
        invitacion = invitar(escuela, directora, 'luis@colegio.test')
        usuario = ProfessorFactory(email='Luis@Colegio.test')
        assert school.accept(invitacion, usuario).role == Membership.Role.TEACHER

    def test_una_cuenta_de_alumno_no_entra_como_docente(self, escuela, directora):
        alumno = StudentFactory(email='luis@colegio.test')
        with pytest.raises(ValidationError, match='cuenta es de alumno'):
            school.accept(invitar(escuela, directora), alumno)

    def test_vencida(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        OrganizationInvitation.objects.filter(pk=invitacion.pk).update(expires_at=timezone.now() - DIA)
        with pytest.raises(ValidationError, match='venció'):
            school.accept(invitacion, docente)

    def test_escuela_inactiva(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        Organization.objects.filter(pk=escuela.pk).update(is_active=False)
        invitacion.refresh_from_db()
        with pytest.raises(ValidationError, match='ya no está activa'):
            school.accept(invitacion, docente)

    def test_quien_ya_es_de_la_direccion_no_baja_de_rol(self, escuela, directora):
        invitacion = OrganizationInvitation.objects.create(
            organization=escuela, email=directora.email, token='t' * 43, expires_at=timezone.now() + DIA,
        )
        assert school.accept(invitacion, directora).role == Membership.Role.ADMIN

    def test_quien_ya_es_alumno_de_la_escuela_no_se_vuelve_docente(self, escuela, directora):
        usuario = ProfessorFactory(email='luis@colegio.test')
        invitacion = invitar(escuela, directora)
        MembershipFactory(user=usuario, organization=escuela, role=Membership.Role.STUDENT)  # entró a la escuela después de invitarlo
        with pytest.raises(ValidationError, match='otro rol'):
            school.accept(invitacion, usuario)
        assert Membership.objects.get(user=usuario, organization=escuela).role == Membership.Role.STUDENT


# ── El equipo ─────────────────────────────────────────────────────────

class TestEquipo:
    def test_lista_a_la_direccion_y_a_los_docentes_con_sus_grupos(self, escuela, directora, docente):
        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        CourseFactory(professor=docente, organization=escuela)
        CourseFactory(professor=docente, organization=escuela)
        CourseFactory(professor=docente, organization=teaching_organization(docente))  # uno personal: no cuenta
        MembershipFactory(organization=escuela, role=Membership.Role.STUDENT)  # los alumnos no son del equipo
        filas = {fila['membership'].user: fila['groups'] for fila in school.team(escuela)}
        assert filas == {directora: 0, docente: 2}

    def test_los_grupos_archivados_no_cuentan(self, escuela, directora, docente):
        from apps.courses.services.courses import archive_course

        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        archive_course(CourseFactory(professor=docente, organization=escuela))
        assert {f['membership'].user: f['groups'] for f in school.team(escuela)}[docente] == 0

    def test_las_pendientes_incluyen_las_vencidas(self, escuela, directora):
        vigente, vencida = invitar(escuela, directora, 'a@x.test'), invitar(escuela, directora, 'b@x.test')
        OrganizationInvitation.objects.filter(pk=vencida.pk).update(expires_at=timezone.now() - DIA)
        aceptada = invitar(escuela, directora, 'c@x.test')
        school.accept(aceptada, ProfessorFactory(email='c@x.test'))
        retirada = invitar(escuela, directora, 'd@x.test')
        school.revoke(retirada, by=directora)
        assert {i.pk for i in school.open_invitations(escuela)} == {vigente.pk, vencida.pk}


# ── Las pantallas ─────────────────────────────────────────────────────

class TestPantallaDeLaEscuela:
    def test_la_direccion_ve_su_equipo_y_las_invitaciones(self, escuela, directora, docente):
        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        invitar(escuela, directora, 'nueva@colegio.test')
        pagina = cliente_de(directora, escuela).get(reverse('organizations:school')).content.decode()
        assert 'Colegio Benito Juárez' in pagina and 'Rosa Directora' in pagina and 'luis@colegio.test' in pagina
        assert 'Administrador' in pagina and 'nueva@colegio.test' in pagina and 'Enviar invitación' in pagina

    def test_un_docente_de_la_escuela_no_entra(self, escuela, docente):
        MembershipFactory(user=docente, organization=escuela, role=Membership.Role.TEACHER)
        client = cliente_de(docente, escuela)
        assert client.get(reverse('organizations:school')).status_code == 302
        assert client.post(reverse('organizations:school_invite'), {'email': 'a@x.test'}).status_code == 302
        assert not OrganizationInvitation.objects.exists()

    def test_un_docente_individual_no_ve_mi_escuela(self, professor_client):
        assert professor_client.get(reverse('organizations:school')).status_code == 302

    def test_un_alumno_y_un_anonimo_no_entran(self, student_client, client):
        assert student_client.get(reverse('organizations:school')).status_code == 302
        assert client.get(reverse('organizations:school')).url.startswith('/login/')

    def test_invitar_desde_la_pantalla(self, escuela, directora, django_capture_on_commit_callbacks):
        client = cliente_de(directora, escuela)
        with django_capture_on_commit_callbacks(execute=True):
            respuesta = client.post(reverse('organizations:school_invite'), {'email': 'nueva@colegio.test'}, follow=True)
        assert OrganizationInvitation.objects.get().email == 'nueva@colegio.test'
        assert 'Le mandamos la invitación a nueva@colegio.test' in ' '.join(m.message for m in respuesta.context['messages'])
        assert len(mail.outbox) == 1

    def test_un_error_se_avisa_y_no_crea_nada(self, escuela, directora):
        respuesta = cliente_de(directora, escuela).post(reverse('organizations:school_invite'), {'email': 'mal'}, follow=True)
        assert 'no es válido' in ' '.join(m.message for m in respuesta.context['messages']) and not OrganizationInvitation.objects.exists()

    def test_reenviar_y_retirar(self, escuela, directora):
        invitacion = invitar(escuela, directora)
        client = cliente_de(directora, escuela)
        respuesta = client.post(reverse('organizations:school_resend', args=[invitacion.pk]), follow=True)
        assert 'Volvimos a mandar' in ' '.join(m.message for m in respuesta.context['messages'])
        respuesta = client.post(reverse('organizations:school_revoke', args=[invitacion.pk]), follow=True)
        assert 'ya no sirve' in ' '.join(m.message for m in respuesta.context['messages'])
        invitacion.refresh_from_db()
        assert invitacion.revoked_at is not None

    def test_la_direccion_de_otra_escuela_no_toca_mis_invitaciones(self, escuela, directora):
        invitacion = invitar(escuela, directora)
        otra = OrganizationFactory(type=Organization.Type.INSTITUTION)
        otra_directora = ProfessorFactory()
        MembershipFactory(user=otra_directora, organization=otra, role=Membership.Role.OWNER)
        client = cliente_de(otra_directora, otra)
        for nombre in ('school_resend', 'school_revoke'):
            assert client.post(reverse(f'organizations:{nombre}', args=[invitacion.pk])).status_code == 404
        assert OrganizationInvitation.objects.get().is_usable

    def test_las_acciones_solo_por_post(self, escuela, directora):
        invitacion = invitar(escuela, directora)
        client = cliente_de(directora, escuela)
        assert client.get(reverse('organizations:school_invite')).status_code == 405
        assert client.get(reverse('organizations:school_revoke', args=[invitacion.pk])).status_code == 405

    def test_la_direccion_sin_clases_entra_a_su_escuela_al_iniciar_sesion(self, escuela, directora):
        respuesta = cliente_de(directora, escuela).get(reverse('login'))
        assert respuesta.url == reverse('organizations:school')

    def test_el_menu_de_la_direccion(self, escuela, directora):
        pagina = cliente_de(directora, escuela).get(reverse('organizations:school')).content.decode()
        assert 'Mi escuela' in pagina and 'Dirección' in pagina and 'Mis grupos' not in pagina and 'Unirme a un grupo' not in pagina

    def test_un_propietario_que_da_clase_ve_su_escuela_en_el_menu(self, escuela):
        propietario = ProfessorFactory()
        MembershipFactory(user=propietario, organization=escuela, role=Membership.Role.OWNER)
        pagina = cliente_de(propietario, escuela).get(reverse('professor_dashboard')).content.decode()
        assert 'Mi escuela' in pagina and 'Mis grupos' in pagina

    def test_un_docente_individual_no_tiene_mi_escuela_en_el_menu(self, professor_client):
        assert 'Mi escuela' not in professor_client.get(reverse('professor_dashboard')).content.decode()


class TestPantallaDeLaInvitacion:
    def url(self, invitacion):
        return reverse('organizations:school_accept', args=[invitacion.token])

    def test_sin_sesion_ofrece_entrar_o_crear_cuenta_y_volver(self, client, escuela, directora):
        invitacion = invitar(escuela, directora)
        pagina = client.get(self.url(invitacion)).content.decode()
        assert 'Colegio Benito Juárez te invita' in pagina and 'luis@colegio.test' in pagina
        assert f'/login/?next={self.url(invitacion)}' in pagina.replace('%2F', '/') or '/login/?next=' in pagina
        assert '/registro/?next=' in pagina and 'Unirme a' not in pagina

    def test_con_la_cuenta_correcta_se_puede_aceptar(self, escuela, directora, docente):
        pagina = cliente_de(docente).get(self.url(invitar(escuela, directora))).content.decode()
        assert 'Unirme a Colegio Benito Juárez' in pagina and 'luis@colegio.test' in pagina

    def test_aceptar_suma_la_escuela_y_cambia_de_espacio(self, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        client = cliente_de(docente)
        respuesta = client.post(self.url(invitacion), follow=True)
        assert Membership.objects.get(user=docente, organization=escuela).role == Membership.Role.TEACHER
        assert client.session[SESSION_KEY] == escuela.pk and respuesta.redirect_chain[-1][0] == reverse('professor_dashboard')
        assert 'Ya eres parte de Colegio Benito Juárez' in ' '.join(m.message for m in respuesta.context['messages'])
        pagina = respuesta.content.decode()
        assert 'Colegio Benito Juárez' in pagina and 'org-switch' in pagina  # el selector de espacios

    def test_con_otra_cuenta_explica_y_no_deja_aceptar(self, escuela, directora):
        invitacion = invitar(escuela, directora)
        otro = ProfessorFactory(email='otro@colegio.test')
        client = cliente_de(otro)
        pagina = client.get(self.url(invitacion)).content.decode()
        assert 'es para luis@colegio.test' in pagina and 'Unirme a' not in pagina and 'Cerrar sesión y entrar con otra cuenta' in pagina
        respuesta = client.post(self.url(invitacion))
        assert respuesta.status_code == 200 and 'es para luis@colegio.test' in respuesta.content.decode()
        assert not Membership.objects.filter(user=otro, organization=escuela).exists()

    @pytest.mark.parametrize('preparar, texto', [
        (lambda i, d: school.revoke(i, by=d), 'retiró'),
        (lambda i, d: OrganizationInvitation.objects.filter(pk=i.pk).update(expires_at=timezone.now() - DIA), 'venció'),
        (lambda i, d: school.accept(i, User.objects.get(email=i.email)), 'ya se usó'),
    ])
    def test_una_invitacion_que_ya_no_sirve_lo_dice_con_o_sin_sesion(self, client, escuela, directora, docente, preparar, texto):
        invitacion = invitar(escuela, directora)
        preparar(invitacion, directora)
        assert texto in client.get(self.url(invitacion)).content.decode()
        assert texto in cliente_de(docente).get(self.url(invitacion)).content.decode()

    def test_un_enlace_inventado_es_404(self, client):
        assert client.get(reverse('organizations:school_accept', args=['no-existe'])).status_code == 404

    def test_aceptar_sin_sesion_manda_a_iniciarla(self, client, escuela, directora):
        invitacion = invitar(escuela, directora)
        respuesta = client.post(self.url(invitacion))
        assert respuesta.url.startswith('/login/?next=') and not Membership.objects.filter(organization=escuela).exclude(user=directora).exists()

    def test_despues_de_iniciar_sesion_vuelve_a_la_invitacion(self, client, escuela, directora, docente):
        invitacion = invitar(escuela, directora)
        respuesta = client.post(reverse('login'), {'username': docente.email, 'password': 'Prueba123!', 'next': self.url(invitacion)})
        assert respuesta.url == self.url(invitacion)

    def test_despues_de_registrarse_vuelve_a_la_invitacion(self, client, escuela, directora):
        invitacion = invitar(escuela, directora, 'nuevo@colegio.test')
        respuesta = client.post(reverse('register'), {**datos(email='nuevo@colegio.test'), 'next': self.url(invitacion)})
        assert respuesta.url == self.url(invitacion)
        pagina = client.get(self.url(invitacion)).content.decode()
        assert 'Unirme a Colegio Benito Juárez' in pagina

    def test_el_registro_ignora_un_next_de_otro_sitio(self, client):
        respuesta = client.post(reverse('register'), {**datos(email='nuevo@colegio.test'), 'next': 'https://malo.example/robar'})
        assert respuesta.url == reverse('professor_dashboard')
