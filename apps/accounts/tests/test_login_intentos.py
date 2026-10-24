"""Límite de intentos fallidos en el inicio de sesión y dirección IP detrás de proxies."""

import pytest
from django.test import RequestFactory
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD
from core import throttle

pytestmark = pytest.mark.django_db

IP_A, IP_B = "10.1.1.1", "10.2.2.2"


def entrar(client, username, password="incorrecta", ip=IP_A):
    return client.post(reverse("login"), {"username": username, "password": password}, REMOTE_ADDR=ip)


class TestLimiteDeIntentos:
    def test_tras_cinco_fallos_del_mismo_correo_desde_la_misma_ip_se_bloquea(self, client, student):
        for _ in range(5):
            assert entrar(client, student.email).status_code == 200
        response = entrar(client, student.email)
        assert response.status_code == 429
        assert "Demasiados intentos" in response.context["error"]

    def test_bloqueado_ni_la_contrasena_correcta_entra(self, client, student, enrollment):
        for _ in range(5):
            entrar(client, student.email)
        assert entrar(client, student.email, PASSWORD).status_code == 429
        assert "_auth_user_id" not in client.session

    def test_otra_ip_no_queda_bloqueada_por_los_fallos_de_alguien_mas(self, client, student, enrollment):
        for _ in range(6):
            entrar(client, student.email, ip=IP_A)
        assert entrar(client, student.email, PASSWORD, ip=IP_B).status_code == 302

    def test_el_correo_no_distingue_mayusculas_ni_espacios(self, client, student):
        for _ in range(5):
            entrar(client, student.email)
        assert entrar(client, f"  {student.email.upper()} ").status_code == 429

    def test_un_acierto_reinicia_la_cuenta_de_fallos(self, client, student, enrollment):
        for _ in range(4):
            entrar(client, student.email)
        assert entrar(client, student.email, PASSWORD).status_code == 302
        client.post(reverse("logout"))
        for _ in range(4):
            assert entrar(client, student.email).status_code == 200  # volvió a tener sus cinco intentos

    def test_una_ip_que_prueba_muchas_cuentas_se_bloquea(self, client, student):
        for numero in range(20):
            entrar(client, f"nadie{numero}@prueba.test")
        assert entrar(client, student.email, PASSWORD).status_code == 429

    def test_un_ataque_repartido_entre_ips_contra_un_correo_se_bloquea(self, client, student, enrollment):
        for numero in range(30):
            entrar(client, student.email, ip=f"10.9.9.{numero}")
        assert entrar(client, student.email, PASSWORD, ip=IP_B).status_code == 429

    def test_los_aciertos_no_cuentan_como_fallos(self, client, student, enrollment):
        for _ in range(8):
            assert entrar(client, student.email, PASSWORD).status_code == 302
            client.post(reverse("logout"))

    def test_la_pagina_bloqueada_no_conserva_lo_escrito(self, client, student):
        for _ in range(5):
            entrar(client, student.email)
        assert student.email not in entrar(client, student.email).content.decode()


class TestDireccionDelCliente:
    def llamada(self, **meta):
        return RequestFactory().get("/", **meta)

    def test_sin_proxy_es_remote_addr_aunque_venga_la_cabecera(self, settings):
        settings.TRUSTED_PROXY_COUNT = 0
        request = self.llamada(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6")
        assert throttle.client_ip(request) == "10.0.0.1"

    def test_con_un_proxy_es_la_ultima_de_la_cabecera(self, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        request = self.llamada(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9")
        assert throttle.client_ip(request) == "203.0.113.9"  # lo que el cliente escribió (6.6.6.6) no cuenta

    def test_con_dos_proxies_es_la_penultima(self, settings):
        settings.TRUSTED_PROXY_COUNT = 2
        request = self.llamada(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9, 172.16.0.5")
        assert throttle.client_ip(request) == "203.0.113.9"

    def test_si_la_cabecera_trae_menos_direcciones_que_proxies_se_usa_remote_addr(self, settings):
        settings.TRUSTED_PROXY_COUNT = 2
        request = self.llamada(REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="203.0.113.9")
        assert throttle.client_ip(request) == "10.0.0.1"

    def test_sin_cabecera_se_usa_remote_addr(self, settings):
        settings.TRUSTED_PROXY_COUNT = 1
        assert throttle.client_ip(self.llamada(REMOTE_ADDR="10.0.0.1")) == "10.0.0.1"


class TestPiezasDelLimitador:
    def test_exceeded_no_anota_y_reset_olvida(self):
        assert throttle.exceeded("x", "a", limit=1) is False
        assert throttle.exceeded("x", "a", limit=1) is False  # mirar no cuenta
        throttle.hit("x", "a", window=60)
        assert throttle.exceeded("x", "a", limit=1) is True
        throttle.reset("x", "A ")
        assert throttle.exceeded("x", "a", limit=1) is False
