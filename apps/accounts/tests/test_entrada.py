"""Entrar y salir: la raíz del sitio, el destino ``next`` del login y el cierre de sesión por POST."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD, StudentFactory
from apps.courses.factories import EnrollmentFactory
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership

pytestmark = pytest.mark.django_db


class TestRaiz:
    def test_anonimo_ve_la_portada(self, client):
        response = client.get("/")
        html = response.content.decode()
        assert response.status_code == 200 and reverse("register") in html and reverse("login") in html

    def test_docente_va_a_su_inicio(self, professor_client):
        assert professor_client.get("/").url == reverse("professor_dashboard")

    def test_alumno_va_a_su_inicio(self, student_client, enrollment):
        assert student_client.get("/").url == reverse("student_dashboard")

    def test_sin_membresia_va_al_perfil(self):
        usuario = StudentFactory()
        client = Client()
        client.force_login(usuario)
        assert client.get("/").url == reverse("profile")

    def test_rol_sin_pantallas_va_al_perfil(self):
        usuario = StudentFactory()
        MembershipFactory(user=usuario, role=Membership.Role.PARENT)
        client = Client()
        client.force_login(usuario)
        assert client.get("/").url == reverse("profile")


class TestNext:
    def entrar(self, client, usuario, **extra):
        return client.post(reverse("login"), {"username": usuario.email, "password": PASSWORD, **extra})

    def test_el_login_requerido_conserva_a_donde_iba(self, client, course):
        destino = reverse("course_detail", args=[course.pk])
        response = client.get(destino)
        assert response.status_code == 302 and "next=" in response.url

    def test_tras_entrar_va_a_donde_iba_por_la_url(self, client, professor, course):
        destino = reverse("course_detail", args=[course.pk])
        response = client.post(
            f"{reverse('login')}?next={destino}", {"username": professor.email, "password": PASSWORD},
        )
        assert response.url == destino

    def test_tras_entrar_va_a_donde_iba_por_el_formulario(self, client, professor, course):
        destino = reverse("course_detail", args=[course.pk])
        assert self.entrar(client, professor, next=destino).url == destino

    def test_el_flujo_completo(self, client, professor, course):
        destino = reverse("course_detail", args=[course.pk])
        pedido = client.get(destino)
        respuesta = client.post(pedido.url, {"username": professor.email, "password": PASSWORD})
        assert respuesta.url == destino
        assert client.get(respuesta.url).status_code == 200

    @pytest.mark.parametrize("destino", [
        "https://malicioso.example/", "//malicioso.example/", "javascript:alert(1)", "http://testserver.evil.example/",
        "\\\\malicioso.example",
    ])
    def test_un_next_externo_se_ignora(self, client, professor, destino):
        assert self.entrar(client, professor, next=destino).url == reverse("professor_dashboard")
        assert Client().post(
            f"{reverse('login')}?next={destino}", {"username": professor.email, "password": PASSWORD},
        ).url == reverse("professor_dashboard")

    def test_sin_next_va_al_inicio_de_su_rol(self, client, professor):
        assert self.entrar(client, professor).url == reverse("professor_dashboard")

    def test_el_next_sobrevive_a_una_contrasena_incorrecta(self, client, professor):
        destino = reverse("professor_dashboard")
        response = client.post(
            f"{reverse('login')}?next={destino}", {"username": professor.email, "password": "mal"},
        )
        assert response.status_code == 200
        assert f'name="next" value="{destino}"' in response.content.decode()

    def test_el_login_no_pinta_un_next_peligroso(self, client):
        html = client.get(f"{reverse('login')}?next=https://malicioso.example/").content.decode()
        assert "malicioso" not in html

    def test_ya_autenticado_en_login_con_next_va_alli(self, professor_client, course):
        destino = reverse("course_detail", args=[course.pk])
        assert professor_client.get(f"{reverse('login')}?next={destino}").url == destino

    def test_ya_autenticado_con_next_externo_va_a_su_inicio(self, professor_client):
        assert professor_client.get(f"{reverse('login')}?next=https://malicioso.example/").url == reverse("professor_dashboard")

    def test_el_rol_elegido_sigue_mandando_a_su_organizacion_aunque_haya_next(self, client, professor, course):
        # El alumno que escribe un next propio de otra pantalla de alumno llega ahí.
        alumno = EnrollmentFactory().student.user
        destino = reverse("student_dashboard")
        response = client.post(reverse("login"), {"username": alumno.email, "password": PASSWORD, "next": destino, "role": "student"})
        assert response.url == destino


class TestCerrarSesion:
    def test_solo_por_post(self, professor_client):
        assert professor_client.get(reverse("logout")).status_code == 405
        assert professor_client.post(reverse("logout")).status_code == 302

    def test_exige_csrf(self, professor):
        client = Client(enforce_csrf_checks=True)
        client.force_login(professor)
        assert client.post(reverse("logout")).status_code == 403
        assert "_auth_user_id" in client.session

    def test_el_menu_cierra_sesion_con_un_formulario_post(self, professor_client):
        html = professor_client.get(reverse("professor_dashboard")).content.decode()
        assert f'method="post" action="{reverse("logout")}"' in html
        assert f'href="{reverse("logout")}"' not in html

    def test_despues_de_salir_se_pide_login(self, professor_client):
        professor_client.post(reverse("logout"))
        assert professor_client.get(reverse("professor_dashboard")).url.startswith(reverse("login"))
