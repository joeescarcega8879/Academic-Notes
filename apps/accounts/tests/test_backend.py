"""Pruebas del backend de autenticación."""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD, ProfessorFactory

pytestmark = pytest.mark.django_db


def test_backend_ignora_cuentas_inactivas(db):
    usuario = ProfessorFactory(is_active=False)
    client = Client()
    response = client.post(reverse("login"), {"username": usuario.email, "password": PASSWORD})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session
