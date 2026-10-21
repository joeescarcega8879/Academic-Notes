"""Página de Precios: sale de la tabla de planes y reúne la lista de espera del plan de pago."""

from dataclasses import replace

import re

import pytest
from django.contrib import admin
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.organizations import plans
from apps.organizations.models import Organization

from apps.onboarding.models import WaitlistEntry

pytestmark = pytest.mark.django_db

URL = reverse('pricing')
Plan = Organization.Plan


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


def pedir(client, email='docente@ejemplo.mx', **extra):
    datos = {'email': email, 'accept': 'on', 'website': '', **extra}
    return client.post(URL, datos)


class TestPagina:
    def test_es_publica_y_no_pide_sesion(self):
        respuesta = Client().get(URL)
        assert respuesta.status_code == 200
        assert 'Empieza gratis. Paga solo cuando lo necesites.' in respuesta.content.decode()

    def test_muestra_los_dos_planes_con_sus_precios_y_topes(self):
        html = Client().get(URL).content.decode()
        for esperado in ('Gratis', 'Pro', '$0', '$149', '$1,490', '2 meses gratis', 'Grupos activos: 2',
                         'Alumnos en grupos activos: 60', 'Preguntas en el banco: 30'):
            assert esperado in html, esperado

    def test_el_plan_de_pago_dice_que_todavia_no_se_cobra_y_no_ofrece_comprar(self):
        html = Client().get(URL).content.decode()
        assert 'Próximamente' in html and 'Todavía no cobramos en línea' in html
        assert 'Avísame cuando esté disponible' in html
        assert 'checkout' not in html.lower() and 'Pagar' not in html

    def test_todo_sale_de_la_tabla_de_planes_si_cambia_un_tope_o_un_precio(self, monkeypatch):
        monkeypatch.setattr(plans, 'FREE', replace(plans.FREE, groups=3, students=90))
        monkeypatch.setattr(plans, 'TEACHER', replace(plans.TEACHER, monthly_price=199, annual_price=1990))
        html = Client().get(URL).content.decode()
        for esperado in ('Grupos activos: 3', 'Alumnos en grupos activos: 90', '$199', '$1,990'):
            assert esperado in html, esperado
        assert '$149' not in html and 'Grupos activos: 2' not in html

    def test_lo_que_solo_tiene_el_plan_de_pago_aparece_en_su_tarjeta(self):
        html = Client().get(URL).content.decode()
        tarjeta = html.split('id="plan-docente"')[1].split('id="aviso"')[0]
        for esperado in ('Todo lo del plan Gratis', 'Grupos activos: sin tope', 'Quizzes con tiempo límite', 'Boletas en PDF sin marca de agua'):
            assert esperado in tarjeta, esperado

    def test_compara_los_planes(self):
        html = Client().get(URL).content.decode()
        assert 'Compara los planes' in html and html.count('Sin tope') >= 3

    def test_no_promete_lo_que_no_existe(self):
        html = Client().get(URL).content.decode()
        for prohibido in ('WhatsApp', 'portal de padres', 'panel de dirección'):
            assert prohibido.lower() not in html.lower(), prohibido

    def test_plus_se_anuncia_con_su_precio_pero_sin_poder_comprarse(self):
        html = Client().get(URL).content.decode()
        tarjeta = html.split('id="plan-plus"')[1].split('</article>')[0]
        for esperado in ('Plus', '$249', '$2,490', '2 meses gratis', 'Próximamente', 'Todo lo del plan Pro',
                         'Genera tareas, quizzes y exámenes desde tu temario', 'Calificación asistida', 'Tú apruebas todo',
                         'todavía está en construcción'):
            assert esperado.lower() in tarjeta.lower(), esperado
        assert 'checkout' not in html.lower() and 'Pagar' not in html

    def test_la_ia_es_solo_de_plus(self):
        html = Client().get(URL).content.decode()
        gratis = html.split('id="plan-gratis"')[1].split('</article>')[0]
        pro = html.split('id="plan-docente"')[1].split('id="aviso"')[0]
        assert 'tu temario' not in gratis and 'tu temario' not in pro and 'IA' not in pro
        fila = re.search(r'IA para planear y calificar</th>(.*?)</tr>', html, re.S).group(1)
        assert fila.count('<td>') == 3 and fila.count('Sí') == 1
        assert fila.split('</td>')[2].count('Sí') == 1  # solo la tercera columna (Plus)

    def test_el_precio_de_plus_sale_de_la_tabla_de_planes(self, monkeypatch):
        monkeypatch.setattr(plans, 'PLUS', replace(plans.PLUS, monthly_price=299, annual_price=2990))
        html = Client().get(URL).content.decode()
        assert '$299' in html and '$2,990' in html and '$249' not in html

    def test_las_escuelas_van_a_un_piloto_por_correo(self, settings):
        settings.SUPPORT_EMAIL = 'ayuda@ejemplo.mx'
        html = Client().get(URL).content.decode()
        assert '¿Eres una escuela?' in html and 'mailto:ayuda@ejemplo.mx?subject=Quiero%20un%20piloto' in html

    def test_titulo_y_descripcion_para_buscadores(self):
        html = Client().get(URL).content.decode()
        assert '<title>Precios · Academic Notes</title>' in html
        assert '<meta name="description"' in html and 'Tus alumnos nunca pagan' in html

    def test_el_nombre_es_academic_notes(self):
        html = Client().get(URL).content.decode()
        assert 'Academic Notes' in html and ('Grade' + 'Link') not in html


class TestEnlaces:
    def test_la_portada_y_los_pies_llevan_a_precios(self):
        for url in ('/', '/terminos/', '/privacidad/', '/login/', '/registro/'):
            assert f'href="{URL}"' in Client().get(url).content.decode(), url

    def test_el_pie_de_la_portada_y_de_precios_lleva_a_precios(self):
        for url in ('/', URL):
            pie = Client().get(url).content.decode().split('<footer')[1]
            assert f'href="{URL}"' in pie, url

    def test_la_barra_de_la_portada_lleva_a_precios(self):
        barra = Client().get('/').content.decode().split('<header class="nav portada-nav">')[1].split('</header>')[0]
        assert f'href="{URL}"' in barra

    def test_sin_sesion_la_barra_ofrece_entrar_y_crear_cuenta(self):
        html = Client().get(URL).content.decode()
        assert reverse('login') in html and reverse('register') in html and 'Ir a mi cuenta' not in html

    def test_con_sesion_ofrece_ir_a_su_cuenta_y_no_registrarse(self):
        html = cliente(ProfessorFactory()).get(URL).content.decode()
        assert 'Ir a mi cuenta' in html and 'Empezar gratis' not in html and 'Crear cuenta' not in html


class TestListaDeEspera:
    def test_guarda_el_correo_normalizado_y_confirma(self):
        respuesta = pedir(Client(), email='  Docente@Ejemplo.MX ')
        assert respuesta.status_code == 302 and respuesta.url == f'{URL}?lista=pro#aviso'
        entrada = WaitlistEntry.objects.get()
        assert (entrada.email, entrada.plan, entrada.user) == ('docente@ejemplo.mx', Plan.TEACHER, None)
        confirmacion = Client().get(f'{URL}?lista=pro').content.decode()
        assert confirmacion.count('Te avisaremos por correo') == 1
        assert confirmacion.count('Avísame cuando esté disponible') == 1  # queda el de Plus

    def test_sin_el_parametro_no_se_ve_la_confirmacion(self):
        assert 'Te avisaremos por correo' not in Client().get(URL).content.decode()

    def test_repetir_el_correo_no_duplica_y_responde_igual(self):
        client = Client()
        primera, segunda = pedir(client), pedir(client, email='DOCENTE@ejemplo.mx')
        assert primera.url == segunda.url
        assert WaitlistEntry.objects.count() == 1

    def test_pide_la_casilla_del_aviso_de_privacidad(self):
        respuesta = Client().post(URL, {'email': 'a@ejemplo.mx', 'website': ''})
        assert respuesta.status_code == 200 and 'Marca la casilla' in respuesta.content.decode()
        assert WaitlistEntry.objects.count() == 0

    @pytest.mark.parametrize('correo', ['', 'no-es-correo', 'a@', 'x' * 260 + '@ejemplo.mx'])
    def test_un_correo_invalido_no_se_guarda(self, correo):
        respuesta = pedir(Client(), email=correo)
        assert respuesta.status_code == 200 and WaitlistEntry.objects.count() == 0

    def test_un_robot_que_llena_la_trampa_no_guarda_nada_ni_se_entera(self):
        respuesta = pedir(Client(), website='http://spam.example')
        assert respuesta.status_code == 302 and respuesta.url == URL
        assert WaitlistEntry.objects.count() == 0

    def test_frena_los_abusos_desde_una_misma_conexion(self):
        client = Client()
        for i in range(5):
            assert pedir(client, email=f'persona{i}@ejemplo.mx').status_code == 302
        sexta = pedir(client, email='persona5@ejemplo.mx')
        assert sexta.status_code == 429 and 'varios intentos' in sexta.content.decode()
        assert WaitlistEntry.objects.count() == 5

    def test_con_sesion_el_correo_viene_listo_y_la_entrada_queda_ligada(self):
        docente = ProfessorFactory()
        client = cliente(docente)
        assert docente.email in client.get(URL).content.decode()
        pedir(client, email=docente.email)
        assert WaitlistEntry.objects.get().user == docente

    def test_un_alumno_tambien_puede_pedirlo(self):
        alumno = StudentFactory()
        assert pedir(cliente(alumno), email=alumno.email).status_code == 302

    def test_borrar_la_cuenta_conserva_la_entrada_sin_ligar(self):
        docente = ProfessorFactory()
        pedir(cliente(docente), email='otro@ejemplo.mx')
        docente.delete()
        assert WaitlistEntry.objects.get().user is None

    def test_el_correo_escrito_no_se_refleja_sin_escapar(self):
        respuesta = pedir(Client(), email='<script>alert(1)</script>@ejemplo.mx')
        assert respuesta.status_code == 200
        assert '<script>alert(1)</script>' not in respuesta.content.decode()

    def test_sin_plan_se_apunta_a_pro(self):
        pedir(Client())
        assert set(WaitlistEntry.objects.values_list('plan', flat=True)) == {Plan.TEACHER}

    def test_se_puede_apuntar_a_plus_y_confirma_en_su_tarjeta(self):
        respuesta = pedir(Client(), plan=Plan.TEACHER_PLUS)
        assert respuesta.status_code == 302 and respuesta.url == f'{URL}?lista=plus#aviso-plus'
        assert WaitlistEntry.objects.get().plan == Plan.TEACHER_PLUS
        html = Client().get(respuesta.url).content.decode()
        plus = html.split('id="plan-plus"')[1].split('</article>')[0]
        assert 'Te avisaremos por correo cuando el plan Plus' in plus
        assert 'Te avisaremos' not in html.split('id="plan-docente"')[1].split('id="plan-plus"')[0]

    def test_el_mismo_correo_puede_estar_en_la_lista_de_pro_y_en_la_de_plus(self):
        pedir(Client())
        pedir(Client(), plan=Plan.TEACHER_PLUS)
        assert WaitlistEntry.objects.count() == 2

    def test_un_plan_que_no_esta_en_la_lista_se_rechaza(self):
        respuesta = pedir(Client(), plan=Plan.ENTERPRISE)
        assert respuesta.status_code == 200 and WaitlistEntry.objects.count() == 0

    def test_el_error_de_un_formulario_no_aparece_en_el_otro(self):
        respuesta = Client().post(URL, {'email': 'a@ejemplo.mx', 'website': '', 'plan': Plan.TEACHER_PLUS})
        html = respuesta.content.decode()
        assert respuesta.status_code == 200
        plus = html.split('id="plan-plus"')[1].split('</article>')[0]
        pro = html.split('id="plan-docente"')[1].split('id="plan-plus"')[0]
        assert 'Marca la casilla' in plus and 'Marca la casilla' not in pro


class TestAdminYPrivacidad:
    def test_la_lista_se_consulta_en_el_admin(self):
        modelo = admin.site._registry[WaitlistEntry]
        assert 'email' in modelo.list_display and 'plan' in modelo.list_filter

    def test_el_aviso_de_privacidad_dice_para_que_se_guarda_el_correo(self):
        html = Client().get('/privacidad/').content.decode()
        assert 'Lista de espera del plan de pago' in html and 'solo para enviarte ese aviso' in html


class TestPantallaDelPlanSigueIgual:
    def test_usa_la_misma_tabla_comparativa(self):
        docente = ProfessorFactory()
        html = cliente(docente).get(reverse('organizations:plan')).content.decode()
        assert 'Quizzes con tiempo límite' in html and 'Sin tope' in html and '$1,490' in html
