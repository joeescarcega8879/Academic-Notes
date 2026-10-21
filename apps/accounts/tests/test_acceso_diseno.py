"""Pantallas de acceso con el diseño de la portada: registro, restablecer contraseña y recursos."""

import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

PANTALLAS = ('login', 'register', 'register_student', 'password_reset', 'password_reset_sent', 'password_reset_complete')


class TestPantallas:
    @pytest.mark.parametrize('nombre', PANTALLAS)
    def test_todas_usan_el_diseno_de_acceso_y_enlazan_a_precios(self, nombre):
        respuesta = Client().get(reverse(nombre))
        html = respuesta.content.decode()
        assert respuesta.status_code == 200
        assert 'class="portada acceso"' in html and 'css/acceso.css' in html
        assert f'href="{reverse("pricing")}"' in html

    def test_el_registro_de_docente_y_el_de_alumno_tienen_su_propio_mensaje(self):
        docente = Client().get(reverse('register')).content.decode()
        alumno = Client().get(reverse('register_student')).content.decode()
        assert 'Tu libreta lista en' in docente and 'siempre a la mano' not in docente
        assert 'siempre a la mano' in alumno and 'Tu libreta lista en' not in alumno

    def test_el_registro_conserva_el_campo_trampa_y_los_terminos(self):
        html = Client().get(reverse('register')).content.decode()
        assert 'class="hp"' in html and reverse('terms') in html and reverse('privacy') in html

    def test_el_enlace_vencido_ofrece_pedir_otro(self):
        html = Client().get(reverse('password_reset_confirm', args=['x', 'token-falso'])).content.decode()
        assert reverse('password_reset') in html


class TestRecursos:
    @pytest.mark.parametrize('ruta', ['css/acceso.css', 'js/acceso.js'])
    def test_los_archivos_estaticos_existen(self, ruta):
        assert finders.find(ruta), ruta
