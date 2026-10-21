"""Pruebas del inicio y cierre de sesión."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD
from apps.courses.tests.factories import EnrollmentFactory

pytestmark = pytest.mark.django_db


class TestLogin:
    def test_login_con_email(self, client, student, enrollment):
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

    def test_usuario_autenticado_en_login_va_a_su_dashboard(self, student_client, enrollment):
        assert student_client.get(reverse("login")).url == reverse("student_dashboard")

    def test_alumno_sin_organizacion_entra_a_su_perfil(self, client, student):
        response = client.post(
            reverse("login"), {"username": student.email, "password": PASSWORD, "role": "student"}
        )
        assert response.status_code == 302
        assert response.url == reverse("profile")

    def test_el_rol_elegido_fija_la_organizacion_activa(self, client, professor, course):
        from apps.organizations.tests.factories import MembershipFactory
        from apps.organizations.models import Membership

        # Alumno en la organización de otro profesor y profesor en la suya.
        MembershipFactory(user=professor, organization=EnrollmentFactory().course.organization)
        response = client.post(
            reverse("login"), {"username": professor.email, "password": PASSWORD, "role": "student"}
        )
        assert response.url == reverse("student_dashboard")
        asignada = Membership.objects.get(user=professor, role=Membership.Role.STUDENT)
        assert client.session["organization_id"] == asignada.organization_id

    def test_logout_cierra_la_sesion(self, student_client):
        response = student_client.post(reverse("logout"))
        assert response.status_code == 302 and response.url == reverse("login")
        assert "_auth_user_id" not in student_client.session

    def test_logout_por_get_no_cierra_la_sesion(self, student_client):
        assert student_client.get(reverse("logout")).status_code == 405
        assert "_auth_user_id" in student_client.session


class TestPantallaDeLogin:
    def test_una_contrasena_incorrecta_explica_que_paso(self, client, student):
        html = client.post(reverse("login"), {"username": student.email, "password": "incorrecta"}).content.decode()
        assert 'class="flash flash-error"' in html and "El correo o la contraseña no son correctos" in html

    def test_un_usuario_que_no_existe_recibe_el_mismo_aviso_que_una_contrasena_mala(self, client, student):
        mala = client.post(reverse("login"), {"username": student.email, "password": "incorrecta"}).content.decode()
        inexistente = client.post(reverse("login"), {"username": "nadie@prueba.test", "password": "incorrecta"}).content.decode()
        aviso = "El correo o la contraseña no son correctos"
        assert aviso in mala and aviso in inexistente

    def test_el_rol_elegido_se_conserva_si_el_login_falla(self, client, student):
        html = client.post(
            reverse("login"), {"username": student.email, "password": "incorrecta", "role": "student"}
        ).content.decode()
        assert 'value="student" checked' in html and 'value="professor" checked' not in html

    def test_sin_rol_elegido_no_marca_ninguno(self, client):
        html = client.get(reverse("login")).content.decode()
        assert " checked" not in html

    def test_los_campos_estan_en_espanol_y_con_autocompletado(self, client):
        html = client.get(reverse("login")).content.decode()
        assert "Correo o usuario" in html and "Contraseña" in html
        assert 'autocomplete="username"' in html and 'autocomplete="current-password"' in html
        assert "Email or Username" not in html

    def test_no_queda_nada_de_otros_proyectos_ni_controles_que_no_hacen_nada(self, client):
        html = client.get(reverse("login")).content.decode()
        assert "Universidad del Plata Sur" not in html
        assert "Mantener sesión" not in html and "tweaks" not in html.lower()

    def test_usa_la_hoja_de_estilos_de_acceso(self, client):
        html = client.get(reverse("login")).content.decode()
        assert "css/acceso.css" in html and "css/portada.css" in html
