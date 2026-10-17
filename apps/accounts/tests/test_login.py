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
