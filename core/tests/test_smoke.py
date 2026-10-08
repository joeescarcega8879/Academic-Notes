"""Pruebas de humo de la Fase 0: la configuración por entorno carga y responde."""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse


def test_settings_por_entorno_activos():
    assert settings.SETTINGS_MODULE == "core.settings.test"
    assert settings.DEBUG is False


@pytest.mark.django_db
def test_la_base_de_datos_responde():
    User = get_user_model()
    assert User._meta.label == "accounts.User"
    assert User.objects.count() == 0


def test_las_rutas_existentes_siguen_resolviendo():
    assert reverse("login") == "/login/"
