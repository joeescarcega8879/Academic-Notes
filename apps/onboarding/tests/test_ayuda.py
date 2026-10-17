"""Ayuda: guía y preguntas frecuentes según el rol, con enlaces que sí llevan a alguna parte."""

import re

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory

pytestmark = pytest.mark.django_db

URL = reverse('help')


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


class TestAyuda:
    def test_sin_sesion_va_al_login(self):
        respuesta = Client().get(URL)
        assert respuesta.status_code == 302 and '/login/' in respuesta.url

    def test_el_docente_ve_su_guia(self):
        html = cliente(ProfessorFactory()).get(URL).content.decode()
        assert 'Empieza en seis pasos' in html and 'Guía para docentes' in html
        assert 'Cómo empezar' not in html

    def test_el_alumno_ve_su_guia(self):
        html = cliente(StudentFactory()).get(URL).content.decode()
        assert 'Cómo empezar' in html and 'Guía para alumnos' in html
        assert 'Empieza en seis pasos' not in html

    def test_un_alumno_sin_organizacion_tambien_la_ve(self):
        # Quien se acaba de registrar aún no pertenece a ninguna organización.
        alumno = StudentFactory()
        assert not alumno.memberships.exists()
        assert cliente(alumno).get(URL).status_code == 200

    @pytest.mark.parametrize('fabrica', [ProfessorFactory, StudentFactory], ids=['docente', 'alumno'])
    def test_ofrece_el_correo_de_soporte_y_las_paginas_legales(self, fabrica, settings):
        settings.SUPPORT_EMAIL = 'ayuda@ejemplo.mx'
        html = cliente(fabrica()).get(URL).content.decode()
        assert 'mailto:ayuda@ejemplo.mx' in html
        assert reverse('terms') in html and reverse('privacy') in html

    @pytest.mark.parametrize('fabrica', [ProfessorFactory, StudentFactory], ids=['docente', 'alumno'])
    def test_ningun_enlace_interno_esta_roto(self, fabrica):
        client = cliente(fabrica())
        html = client.get(URL).content.decode()
        rutas = {h for h in re.findall(r'<a\b[^>]*\bhref="(/[^"#]*)', html) if h != URL}
        assert rutas, 'la guía debería enlazar a otras pantallas'
        for ruta in sorted(rutas):
            assert client.get(ruta).status_code in (200, 302), ruta


class TestBarraLateral:
    @pytest.mark.parametrize('fabrica', [ProfessorFactory, StudentFactory], ids=['docente', 'alumno'])
    def test_ayuda_y_ajustes_ya_no_son_enlaces_vacios(self, fabrica):
        html = cliente(fabrica()).get(reverse('profile')).content.decode()
        sidebar = html.split('<aside class="sidebar">')[1].split('</aside>')[0]
        assert 'href="#"' not in sidebar
        assert f'href="{URL}"' in sidebar

    def test_el_docente_tiene_ajustes_y_el_alumno_no(self):
        ajustes = reverse('organizations:settings')
        docente = cliente(ProfessorFactory()).get(reverse('profile')).content.decode()
        alumno = cliente(StudentFactory()).get(reverse('profile')).content.decode()
        assert f'href="{ajustes}"' in docente
        assert f'href="{ajustes}"' not in alumno

    def test_la_opcion_activa_se_resalta(self):
        client = cliente(ProfessorFactory())
        assert re.search(rf'href="{URL}" class="is-active"', client.get(URL).content.decode())
        ajustes = reverse('organizations:settings')
        assert re.search(rf'href="{ajustes}" class="is-active"', client.get(ajustes).content.decode())
