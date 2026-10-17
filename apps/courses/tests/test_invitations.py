"""Código de invitación: enlazar la cuenta de un alumno con su lugar en la lista."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from apps.accounts.tests.factories import StudentFactory
from apps.messaging.models import Conversation
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY

from apps.courses.tests.factories import AcademicYearFactory, CourseFactory, EnrollmentFactory, StudentRecordFactory
from apps.courses.models import INVITE_ALPHABET, Course, Student
from apps.courses.services.courses import archive_course, clone_course
from apps.courses.services.invitations import (
    MAX_FAILURES, NOT_FOUND, InvitationError, disable_invite_code, redeem_invitation, regenerate_invite_code,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def limpiar_intentos():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def lugar(course):
    """Alumno de la lista (sin cuenta), inscrito en el grupo."""
    ficha = StudentRecordFactory(
        organization=course.organization, user=None, student_number="00123", first_name="Ana", last_name="Pérez López",
    )
    EnrollmentFactory(course=course, student=ficha)
    return ficha


def canjear(user, course, number="00123", last_name="Pérez López", code=None):
    return redeem_invitation(user, code or course.invite_code, number, last_name)


# ── Código del grupo ──────────────────────────────────────────────────

class TestCodigo:
    def test_cada_grupo_nace_con_un_codigo_legible(self, course):
        assert len(course.invite_code) == 8
        assert set(course.invite_code) <= set(INVITE_ALPHABET)
        assert not set(course.invite_code) & set("01OIL")

    def test_los_codigos_son_distintos_entre_grupos(self):
        assert len({CourseFactory().invite_code for _ in range(20)}) == 20

    def test_regenerar_cambia_el_codigo(self, course):
        anterior = course.invite_code
        regenerate_invite_code(course)
        course.refresh_from_db()
        assert course.invite_code not in ("", anterior)

    def test_desactivar_lo_vacia_y_guardar_el_grupo_no_lo_reactiva(self, course):
        disable_invite_code(course)
        course.name = "Otro nombre"
        course.save()
        course.refresh_from_db()
        assert course.invite_code == ""

    def test_guardar_el_grupo_no_cambia_su_codigo(self, course):
        codigo = course.invite_code
        course.name = "Otro nombre"
        course.save()
        assert Course.objects.get(pk=course.pk).invite_code == codigo

    def test_un_grupo_duplicado_tiene_su_propio_codigo(self, course):
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        assert copia.invite_code and copia.invite_code != course.invite_code


# ── Canjear ───────────────────────────────────────────────────────────

class TestCanjear:
    def test_enlaza_la_cuenta_con_su_lugar(self, course, lugar):
        cuenta = StudentFactory()
        assert canjear(cuenta, course) == lugar
        lugar.refresh_from_db()
        assert lugar.user == cuenta

    def test_lo_hace_miembro_y_crea_su_conversacion(self, course, lugar):
        cuenta = StudentFactory()
        canjear(cuenta, course)
        assert Membership.objects.get(user=cuenta).organization == course.organization
        assert Conversation.objects.filter(course=course, student=cuenta).count() == 1

    @pytest.mark.parametrize("codigo", ["{c}", "{c_min}", " {c} ", "{c_guion}"])
    def test_el_codigo_tolera_mayusculas_espacios_y_guiones(self, course, lugar, codigo):
        c = course.invite_code
        formateado = codigo.format(c=c, c_min=c.lower(), c_guion=f"{c[:4]}-{c[4:]}")
        assert canjear(StudentFactory(), course, code=formateado) == lugar

    @pytest.mark.parametrize("apellidos", ["pérez lópez", "PEREZ LOPEZ", " Perez  Lopez "])
    def test_los_apellidos_ignoran_acentos_mayusculas_y_espacios(self, course, lugar, apellidos):
        assert canjear(StudentFactory(), course, last_name=apellidos) == lugar

    def test_es_idempotente(self, course, lugar):
        cuenta = StudentFactory()
        canjear(cuenta, course)
        assert canjear(cuenta, course) == lugar

    def test_si_la_lista_no_trae_apellidos_basta_la_matricula(self, course):
        ficha = StudentRecordFactory(organization=course.organization, user=None, student_number="77", last_name="")
        EnrollmentFactory(course=course, student=ficha)
        assert canjear(StudentFactory(), course, number="77", last_name="Lo que sea") == ficha

    @pytest.mark.parametrize("number, last_name, code", [
        ("00999", "Pérez López", None),  # matrícula que no está en la lista
        ("00123", "Gómez", None),  # apellidos distintos
        ("00123", "Pérez López", "ZZZZZZZZ"),  # código inexistente
        ("", "Pérez López", None),  # sin matrícula
        ("00123", "Pérez López", ""),  # sin código
    ])
    def test_datos_que_no_coinciden_dan_el_mismo_mensaje(self, course, lugar, number, last_name, code):
        with pytest.raises(InvitationError) as error:
            redeem_invitation(StudentFactory(), course.invite_code if code is None else code, number, last_name)
        assert str(error.value) == NOT_FOUND
        lugar.refresh_from_db()
        assert lugar.user is None

    def test_la_matricula_de_otro_grupo_no_sirve(self, course, lugar):
        otro = CourseFactory(professor=course.professor)
        with pytest.raises(InvitationError, match="No encontramos"):
            canjear(StudentFactory(), otro)  # la matrícula 00123 no está inscrita en `otro`

    def test_la_matricula_de_otra_organizacion_no_sirve(self, course):
        StudentRecordFactory(student_number="00555", last_name="Ruiz", user=None)  # otra organización
        with pytest.raises(InvitationError, match="No encontramos"):
            canjear(StudentFactory(), course, number="00555", last_name="Ruiz")

    def test_un_codigo_desactivado_no_sirve(self, course, lugar):
        codigo = course.invite_code
        disable_invite_code(course)
        with pytest.raises(InvitationError, match="No encontramos"):
            canjear(StudentFactory(), course, code=codigo)

    def test_un_codigo_regenerado_invalida_el_anterior(self, course, lugar):
        anterior = course.invite_code
        regenerate_invite_code(course)
        with pytest.raises(InvitationError, match="No encontramos"):
            canjear(StudentFactory(), course, code=anterior)
        assert canjear(StudentFactory(), course) == lugar

    def test_un_grupo_archivado_no_admite_invitaciones(self, course, lugar):
        archive_course(course)
        with pytest.raises(InvitationError, match="No encontramos"):
            canjear(StudentFactory(), course)

    def test_no_se_puede_tomar_un_lugar_ya_enlazado_a_otra_cuenta(self, course, lugar):
        canjear(StudentFactory(), course)
        with pytest.raises(InvitationError, match="otra cuenta"):
            canjear(StudentFactory(), course)

    def test_una_cuenta_no_toma_dos_lugares_en_la_misma_organizacion(self, course, lugar):
        cuenta = StudentFactory()
        ya = StudentRecordFactory(organization=course.organization, user=cuenta)
        with pytest.raises(InvitationError, match="otro alumno"):
            canjear(cuenta, course)
        lugar.refresh_from_db()
        assert lugar.user is None and ya.user == cuenta

    def test_no_agrega_a_nadie_a_la_lista(self, course, lugar):
        total = Student.objects.count()
        with pytest.raises(InvitationError):
            canjear(StudentFactory(), course, number="12345", last_name="Nuevo")
        assert Student.objects.count() == total


# ── Límite de intentos ────────────────────────────────────────────────

class TestLimiteDeIntentos:
    def fallar(self, cuenta, course, veces):
        for _ in range(veces):
            with pytest.raises(InvitationError, match="No encontramos"):
                canjear(cuenta, course, number="00000")

    def test_bloquea_tras_demasiados_fallos_aunque_luego_acierte(self, course, lugar):
        cuenta = StudentFactory()
        self.fallar(cuenta, course, MAX_FAILURES)
        with pytest.raises(InvitationError, match="Demasiados intentos"):
            canjear(cuenta, course)  # datos correctos, pero ya está bloqueada
        lugar.refresh_from_db()
        assert lugar.user is None

    def test_el_bloqueo_es_por_cuenta(self, course, lugar):
        self.fallar(StudentFactory(), course, MAX_FAILURES)
        assert canjear(StudentFactory(), course) == lugar

    def test_acertar_reinicia_el_contador(self, course, lugar):
        cuenta = StudentFactory()
        self.fallar(cuenta, course, MAX_FAILURES - 1)
        canjear(cuenta, course)
        self.fallar(cuenta, course, MAX_FAILURES - 1)  # vuelve a tener margen


# ── Pantallas ─────────────────────────────────────────────────────────

class TestUnirse:
    def datos(self, course, **cambios):
        return {"code": course.invite_code, "student_number": "00123", "last_name": "Pérez López", **cambios}

    def test_flujo_completo(self, client, course, lugar):
        cuenta = StudentFactory()
        client.force_login(cuenta)
        assert client.get(reverse("join_course")).status_code == 200
        response = client.post(reverse("join_course"), self.datos(course), follow=True)
        assert response.redirect_chain[-1][0] == reverse("student_dashboard")
        assert client.session[SESSION_KEY] == course.organization_id
        assert [e.course for e in response.context["enrollments"]] == [course]
        assert any("quedó enlazada" in str(m) for m in response.context["messages"])

    def test_datos_incorrectos_muestran_el_error_sin_enlazar(self, client, course, lugar):
        client.force_login(StudentFactory())
        response = client.post(reverse("join_course"), self.datos(course, student_number="1"))
        assert response.status_code == 200
        assert NOT_FOUND in str(response.context["form"].non_field_errors())
        lugar.refresh_from_db()
        assert lugar.user is None

    def test_campos_obligatorios(self, client, course):
        client.force_login(StudentFactory())
        response = client.post(reverse("join_course"), {})
        assert set(response.context["form"].errors) == {"code", "student_number", "last_name"}

    def test_alumno_sin_organizacion_puede_usarla(self, client, course, lugar):
        cuenta = StudentFactory()
        assert not Membership.objects.filter(user=cuenta).exists()
        client.force_login(cuenta)
        assert client.get(reverse("join_course")).status_code == 200

    def test_el_enlace_aparece_en_el_menu_del_alumno(self, client, course, lugar):
        client.force_login(StudentFactory())
        assert reverse("join_course") in client.get(reverse("profile")).content.decode()

    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("join_course")).url.startswith("/login/")


class TestAdministrarCodigo:
    def url(self, course):
        return reverse("course_invite", args=[course.pk])

    def test_regenerar(self, professor_client, course):
        anterior = course.invite_code
        response = professor_client.post(self.url(course), {"action": "regenerate"}, follow=True)
        course.refresh_from_db()
        assert course.invite_code != anterior
        assert any(course.invite_code in str(m) for m in response.context["messages"])

    def test_desactivar_y_activar(self, professor_client, course):
        professor_client.post(self.url(course), {"action": "disable"})
        course.refresh_from_db()
        assert course.invite_code == ""
        professor_client.post(self.url(course), {"action": "enable"})
        course.refresh_from_db()
        assert len(course.invite_code) == 8

    def test_accion_desconocida_no_cambia_nada(self, professor_client, course):
        codigo = course.invite_code
        professor_client.post(self.url(course), {"action": "otra"})
        course.refresh_from_db()
        assert course.invite_code == codigo

    def test_el_detalle_muestra_el_codigo_al_docente_y_no_al_alumno(self, professor_client, student_client, course, enrollment):
        assert course.invite_code in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
        assert course.invite_code not in student_client.get(reverse("course_detail", args=[course.pk])).content.decode()

    def test_grupo_de_otro_docente_es_404(self, professor_client):
        ajeno = CourseFactory()
        codigo = ajeno.invite_code
        assert professor_client.post(self.url(ajeno), {"action": "regenerate"}).status_code == 404
        ajeno.refresh_from_db()
        assert ajeno.invite_code == codigo

    def test_grupo_archivado_es_404(self, professor_client, course):
        archive_course(course)
        assert professor_client.post(self.url(course), {"action": "regenerate"}).status_code == 404

    def test_el_alumno_no_puede(self, student_client, course, enrollment):
        codigo = course.invite_code
        assert student_client.post(self.url(course), {"action": "regenerate"}).status_code == 302
        course.refresh_from_db()
        assert course.invite_code == codigo

    def test_solo_acepta_post(self, professor_client, course):
        assert professor_client.get(self.url(course)).status_code == 405
