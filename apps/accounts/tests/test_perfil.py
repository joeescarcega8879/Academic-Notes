"""Pruebas del perfil."""

import pytest
from django.urls import reverse

from apps.accounts.models import ProfessorProfile, StudentProfile
from apps.accounts.tests.factories import StudentFactory

pytestmark = pytest.mark.django_db


class TestPerfil:
    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("profile")).status_code == 302

    def test_alumno_ve_su_formulario_extra(self, student_client):
        assert student_client.get(reverse("profile")).status_code == 200

    def test_alumno_guarda_datos_y_perfil_academico(self, student_client, student):
        response = student_client.post(
            reverse("profile"),
            {
                "first_name": "Sofía",
                "last_name": "López",
                "email": student.email,
                "phone": "5512345678",
                "program": "ISC",
                "semester": 5,
                "enrollment_number": "A12345",
            },
        )
        assert response.status_code == 302
        student.refresh_from_db()
        assert student.first_name == "Sofía"
        profile = StudentProfile.objects.get(user=student)
        assert (profile.program, profile.semester) == ("ISC", 5)

    def test_profesor_guarda_departamento(self, professor_client, professor):
        response = professor_client.post(
            reverse("profile"),
            {"first_name": "Ana", "last_name": "Pérez", "email": professor.email, "department": "Física"},
        )
        assert response.status_code == 302
        assert ProfessorProfile.objects.get(user=professor).department == "Física"

    def test_email_duplicado_no_se_guarda(self, student_client, student):
        otro = StudentFactory()
        response = student_client.post(
            reverse("profile"),
            {
                "first_name": "X",
                "last_name": "Y",
                "email": otro.email,
                "program": "ISC",
                "semester": 1,
                "enrollment_number": "A99999",
            },
        )
        assert response.status_code == 200
        student.refresh_from_db()
        assert student.email != otro.email
