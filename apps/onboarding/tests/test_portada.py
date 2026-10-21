"""Portada: lo que ve quien llega sin sesión, que sus números salgan de los planes y que sus recursos existan."""

import re

import pytest
from django.contrib.staticfiles import finders
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.organizations import plans

pytestmark = pytest.mark.django_db


def portada():
    return Client().get('/').content.decode()


class TestPortada:
    def test_es_publica(self):
        respuesta = Client().get('/')
        assert respuesta.status_code == 200
        assert 'Tu libreta lista en' in respuesta.content.decode()

    def test_los_botones_llevan_al_registro_y_al_inicio_de_sesion(self):
        html = portada()
        for nombre in ('register', 'register_student', 'login', 'pricing', 'terms', 'privacy'):
            assert f'href="{reverse(nombre)}"' in html, nombre

    def test_con_sesion_redirige_a_su_inicio_en_lugar_de_mostrarla(self):
        cliente = Client()
        cliente.force_login(ProfessorFactory())
        assert cliente.get('/').status_code == 302

    def test_usa_el_nombre_del_sitio_y_no_el_anterior(self):
        html = portada()
        assert 'Academic Notes' in html and ('Grade' + 'Link') not in html

    def test_no_enlaza_a_paginas_que_piden_sesion(self):
        assert f'href="{reverse("help")}"' not in portada()


class TestLibretaDeEjemplo:
    def test_trae_cuatro_alumnos_con_tres_notas_cada_uno_y_se_avisa_que_es_un_ejemplo(self):
        html = portada()
        filas = re.search(r'<tbody id="sheet-body">(.*?)</tbody>', html, re.S).group(1)
        assert filas.count('<tr>') == 4 and filas.count('<input') == 12
        assert 'datos inventados' in html

    def test_los_promedios_de_partida_son_los_de_la_ponderacion_inicial(self):
        # 50 / 30 / 20 sobre las notas de la plantilla; si se cambia una nota hay que cambiar su promedio.
        html = portada()
        filas = re.search(r'<tbody id="sheet-body">(.*?)</tbody>', html, re.S).group(1)
        promedios = re.findall(r'<strong>([\d.]+)</strong>', filas)
        esperados = []
        for fila in re.findall(r'<tr>(.*?)</tr>', filas, re.S):
            notas = [float(n) for n in re.findall(r'value="([\d.]+)"', fila)]
            esperados.append(f'{round(sum(n * w for n, w in zip(notas, (0.5, 0.3, 0.2))) + 1e-9, 1):.1f}')
        assert promedios == esperados == ['9.5', '7.3', '5.9', '8.4']

    def test_las_fotos_tienen_texto_alternativo(self):
        html = portada()
        imagenes = re.findall(r'<img [^>]*>', html)
        assert len(imagenes) == 2
        assert all(re.search(r'alt="[^"]{15,}"', img) for img in imagenes)


class TestPlanes:
    def test_los_precios_y_topes_salen_de_la_tabla_de_planes(self):
        html = portada()
        assert f'${plans.TEACHER.monthly_price}' in html
        assert f'{plans.FREE.groups}' in html and f'{plans.FREE.students}' in html and f'{plans.FREE.questions}' in html

    def test_el_plan_de_pago_se_presenta_como_proximamente_y_sin_cobro(self):
        html = portada()
        assert 'Próximamente' in html and 'Todavía no cobramos en línea' in html
        assert f'href="{reverse("pricing")}#aviso"' in html


class TestRecursos:
    @pytest.mark.parametrize('ruta', ['css/portada.css', 'js/portada.js', 'images/portada-aula.jpg', 'images/portada-equipo.jpg'])
    def test_los_archivos_estaticos_existen(self, ruta):
        assert finders.find(ruta), ruta

    def test_las_fotos_pesan_poco(self):
        for ruta in ('images/portada-aula.jpg', 'images/portada-equipo.jpg'):
            with open(finders.find(ruta), 'rb') as archivo:
                assert len(archivo.read()) < 250 * 1024, ruta
