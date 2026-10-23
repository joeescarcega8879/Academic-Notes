"""Pantalla del temario: acceso, subir/pegar, detectar semanas y editar cada semana."""

import datetime
import io
import re

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from reportlab.pdfgen import canvas

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.models import Course
from apps.courses.tests.factories import CourseFactory
from apps.grades.tests.factories import ActivityFactory
from apps.organizations.middleware import SESSION_KEY
from apps.organizations.models import Membership
from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory
from apps.syllabus.models import MAX_SYLLABUS_BYTES, Syllabus, SyllabusWeek
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

TEMARIO = 'Semana 1: Reales\nTemas: intervalos, desigualdades\nSemana 2: Funciones\n- Dominio\n- Rango\n'


def url(course, name='index'):
    return reverse(f'syllabus:{name}', args=[course.pk])


def pdf(*lineas):
    buffer = io.BytesIO()
    lienzo = canvas.Canvas(buffer)
    for i, linea in enumerate(lineas):
        lienzo.drawString(72, 750 - 18 * i, linea)
    lienzo.showPage()
    lienzo.save()
    return buffer.getvalue()


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def temario(course):
    return SyllabusFactory(course=course, text=TEMARIO)


@pytest.fixture
def con_semanas(temario):
    for i, titulo in enumerate(['Reales', 'Funciones', 'Límites'], start=1):
        SyllabusWeekFactory(syllabus=temario, position=i, title=titulo, topics='A\nB\nC\nD')
    return temario


def semana(temario, posicion):
    return temario.weeks.get(position=posicion)


def pedir(client, course, **datos):
    return client.post(url(course), datos)


# ── Acceso ────────────────────────────────────────────────────────────

class TestAcceso:
    def test_sin_sesion_va_al_login(self, course):
        respuesta = Client().get(url(course))
        assert respuesta.status_code == 302 and reverse('login') in respuesta.url

    def test_un_alumno_no_entra_ni_cambia_nada(self, course, con_semanas):
        client = cliente(StudentFactory())
        assert client.get(url(course)).status_code == 302
        assert client.post(url(course), {'action': 'delete_week', 'week': semana(con_semanas, 1).pk}).status_code == 302
        assert con_semanas.weeks.count() == 3

    def test_otro_docente_recibe_404_al_ver_y_al_cambiar(self, course, con_semanas):
        otro = cliente(ProfessorFactory())
        assert otro.get(url(course)).status_code == 404
        assert otro.post(url(course), {'action': 'delete_week', 'week': semana(con_semanas, 1).pk}).status_code == 404
        assert con_semanas.weeks.count() == 3

    def test_un_docente_de_otra_organizacion_no_ve_el_temario(self, course, temario):
        ajeno = CourseFactory()
        assert cliente(ajeno.professor).get(url(course)).status_code == 404

    def test_un_colega_de_la_misma_organizacion_tampoco_lo_ve_ni_lo_cambia(self, course, con_semanas):
        # El temario es del docente del grupo, no de toda la organización.
        colega = ProfessorFactory()
        MembershipFactory(user=colega, organization=course.organization, role=Membership.Role.TEACHER)
        client = cliente(colega)
        session = client.session
        session[SESSION_KEY] = course.organization_id
        session.save()
        assert client.get(url(course)).status_code == 404
        assert client.post(url(course), {'action': 'delete_week', 'week': semana(con_semanas, 1).pk}).status_code == 404
        assert con_semanas.weeks.count() == 3

    def test_el_dueño_con_otra_organizacion_activa_no_ve_el_temario_de_la_primera(self, professor, course, temario):
        otra = OrganizationFactory()
        MembershipFactory(user=professor, organization=otra, role=Membership.Role.TEACHER)
        client = cliente(professor)
        session = client.session
        session[SESSION_KEY] = otra.pk
        session.save()
        assert client.get(url(course)).status_code == 404
        assert client.post(url(course), {'action': 'manual'}).status_code == 404

    def test_un_grupo_archivado_ya_no_se_edita(self, professor_client, course):
        course.status = Course.Status.ARCHIVED
        course.save()
        assert professor_client.get(url(course)).status_code == 404
        assert pedir(professor_client, course, action='manual').status_code == 404
        assert not Syllabus.objects.exists()

    def test_el_grupo_enlaza_al_temario_solo_si_esta_activo(self, professor_client, course):
        assert url(course) in professor_client.get(course.get_absolute_url()).content.decode()
        course.status = Course.Status.ARCHIVED
        course.save()
        assert url(course) not in professor_client.get(course.get_absolute_url()).content.decode()

    def test_una_accion_desconocida_o_sin_temario_es_404(self, professor_client, course, temario):
        assert pedir(professor_client, course, action='inventada').status_code == 404
        assert pedir(professor_client, course).status_code == 404
        temario.delete()
        assert pedir(professor_client, course, action='add_week').status_code == 404

    def test_el_alumno_no_ve_el_temario_en_ninguna_pantalla_suya(self, course, enrollment, con_semanas):
        html = cliente(enrollment.student.user).get(course.get_absolute_url()).content.decode()
        assert 'Temario' not in html and con_semanas.weeks.first().title not in html


# ── Sin temario y alta ────────────────────────────────────────────────

class TestAlta:
    def test_sin_temario_ofrece_subir_pegar_o_armar_a_mano(self, professor_client, course):
        html = professor_client.get(url(course)).content.decode()
        for esperado in ('Empieza con tu temario', 'Subir un archivo', 'Pegar el texto', 'Armar las semanas a mano'):
            assert esperado in html
        assert not Syllabus.objects.exists()  # solo mirar no crea nada

    def test_subir_un_pdf_extrae_el_texto(self, professor_client, course, django_capture_on_commit_callbacks):
        archivo = SimpleUploadedFile('Mi temario.pdf', pdf('Semana 1: Reales', 'Semana 2: Funciones'))
        with django_capture_on_commit_callbacks(execute=True):
            respuesta = professor_client.post(url(course), {'action': 'upload', 'file': archivo})
        assert respuesta.status_code == 302 and respuesta.url == url(course)
        temario = Syllabus.objects.get(course=course)
        assert temario.status == Syllabus.Status.READY and 'Semana 2: Funciones' in temario.text
        html = professor_client.get(url(course)).content.decode()
        assert 'Texto listo' in html and 'Mi temario.pdf' in html and 'Descargar original' in html

    def test_sin_ejecutar_la_tarea_queda_extrayendo(self, professor_client, course):
        professor_client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile('t.txt', b'Semana 1: A')})
        assert Syllabus.objects.get().status == Syllabus.Status.PENDING
        assert 'Extrayendo texto' in professor_client.get(url(course)).content.decode()

    @pytest.mark.parametrize('nombre', ['t.html', 't.exe', 't.doc', 'sin_extension'])
    def test_un_archivo_no_permitido_se_rechaza_y_no_se_guarda(self, professor_client, course, nombre):
        respuesta = professor_client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile(nombre, b'x')})
        assert respuesta.status_code == 200 and 'field-error' in respuesta.content.decode()
        assert not Syllabus.objects.exists()

    def test_un_archivo_de_mas_de_10_mb_se_rechaza(self, professor_client, course):
        grande = SimpleUploadedFile('t.txt', b'x' * (MAX_SYLLABUS_BYTES + 1))
        respuesta = professor_client.post(url(course), {'action': 'upload', 'file': grande})
        assert respuesta.status_code == 200 and 'más de 10 MB' in respuesta.content.decode()
        assert not Syllabus.objects.exists()

    def test_subir_sin_elegir_archivo_no_rompe(self, professor_client, course):
        assert pedir(professor_client, course, action='upload').status_code == 200

    def test_un_escaneo_avisa_que_hay_que_pegar_el_texto(self, professor_client, course, django_capture_on_commit_callbacks):
        buffer = io.BytesIO()
        lienzo = canvas.Canvas(buffer)
        lienzo.showPage()
        lienzo.save()
        with django_capture_on_commit_callbacks(execute=True):
            professor_client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile('scan.pdf', buffer.getvalue())})
        html = professor_client.get(url(course)).content.decode()
        assert 'Sin texto legible' in html and 'Pega el texto del temario' in html

    def test_un_archivo_dañado_avisa_sin_romper(self, professor_client, course, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            professor_client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile('roto.pdf', b'basura')})
        assert 'No pudimos leer el archivo' in professor_client.get(url(course)).content.decode()

    def test_pegar_el_texto(self, professor_client, course):
        respuesta = pedir(professor_client, course, action='paste', text='  Semana 1: Reales  ')
        assert respuesta.status_code == 302
        temario = Syllabus.objects.get()
        assert temario.text == 'Semana 1: Reales' and temario.status == Syllabus.Status.READY and not temario.file

    @pytest.mark.parametrize('texto', ['', '   \n  '])
    def test_pegar_texto_vacio_se_rechaza(self, professor_client, course, texto):
        assert pedir(professor_client, course, action='paste', text=texto).status_code == 200
        assert not Syllabus.objects.exists()

    def test_armar_a_mano_crea_un_temario_vacio_y_es_idempotente(self, professor_client, course):
        pedir(professor_client, course, action='manual')
        pedir(professor_client, course, action='manual')
        assert Syllabus.objects.count() == 1
        html = professor_client.get(url(course)).content.decode()
        assert 'Armado a mano' in html and 'Agregar la primera semana' in html

    def test_el_texto_se_muestra_escapado(self, professor_client, course):
        pedir(professor_client, course, action='paste', text='<script>alert(1)</script>')
        assert '<script>alert(1)</script>' not in professor_client.get(url(course)).content.decode()

    def test_un_texto_enorme_se_rechaza_en_lugar_de_guardarse(self, professor_client, course):
        assert pedir(professor_client, course, action='paste', text='x' * 200_001).status_code == 200
        assert not Syllabus.objects.exists()


# ── Descargar el original ─────────────────────────────────────────────

class TestDescarga:
    def subir(self, client, course, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile('Mi temario.pdf', pdf('Semana 1'))})

    def test_el_docente_descarga_con_el_nombre_original_y_sin_cache(self, professor_client, course, django_capture_on_commit_callbacks):
        self.subir(professor_client, course, django_capture_on_commit_callbacks)
        respuesta = professor_client.get(url(course, 'file'))
        assert respuesta.status_code == 200 and b'%PDF' in b''.join(respuesta.streaming_content)
        assert 'Mi temario.pdf' in respuesta['Content-Disposition'] and respuesta['Content-Disposition'].startswith('attachment')
        assert respuesta['X-Content-Type-Options'] == 'nosniff' and 'no-store' in respuesta['Cache-Control']

    def test_otro_docente_y_el_alumno_no_pueden(self, professor_client, course, django_capture_on_commit_callbacks):
        self.subir(professor_client, course, django_capture_on_commit_callbacks)
        assert cliente(ProfessorFactory()).get(url(course, 'file')).status_code == 404
        assert cliente(StudentFactory()).get(url(course, 'file')).status_code == 302
        assert Client().get(url(course, 'file')).status_code == 302

    def test_sin_archivo_es_404(self, professor_client, course, temario):
        assert professor_client.get(url(course, 'file')).status_code == 404

    def test_entrega_el_archivo_de_su_grupo_y_no_el_de_otro(self, professor_client, course, django_capture_on_commit_callbacks):
        ajeno = ProfessorFactory()
        otro_grupo = CourseFactory(professor=ajeno)
        with django_capture_on_commit_callbacks(execute=True):
            cliente(ajeno).post(url(otro_grupo), {'action': 'upload', 'file': SimpleUploadedFile('ajeno.pdf', pdf('Ajeno'))})
            professor_client.post(url(course), {'action': 'upload', 'file': SimpleUploadedFile('mio.pdf', pdf('Mio'))})
        assert 'mio.pdf' in professor_client.get(url(course, 'file'))['Content-Disposition']

    def test_sin_archivo_propio_no_cae_en_el_de_otro_grupo(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        ajeno = ProfessorFactory()
        otro_grupo = CourseFactory(professor=ajeno)
        with django_capture_on_commit_callbacks(execute=True):
            cliente(ajeno).post(url(otro_grupo), {'action': 'upload', 'file': SimpleUploadedFile('ajeno.pdf', pdf('Ajeno'))})
        assert professor_client.get(url(course, 'file')).status_code == 404


# ── Detectar semanas ──────────────────────────────────────────────────

class TestDetectar:
    def test_muestra_la_propuesta_sin_aplicarla(self, professor_client, course, temario):
        html = professor_client.get(url(course) + '?detectar=1').content.decode()
        assert 'Encontramos 2 semanas' in html and 'Usar estas semanas' in html
        assert temario.weeks.count() == 0

    def test_la_propuesta_cuenta_las_actividades_de_cada_semana(self, professor_client, course, temario):
        temario.text = 'SEMANA 1\nReales\nTarea: hoja de ejercicios\nQuiz 1\nSEMANA 2\nFunciones'
        temario.save()
        html = professor_client.get(url(course) + '?detectar=1').content.decode()
        assert '· 2 actividades' in html and html.count('actividades</span>') == 1  # la semana 2 no tiene

    def test_aplicar_crea_las_semanas(self, professor_client, course, temario):
        respuesta = pedir(professor_client, course, action='apply_detected')
        assert respuesta.status_code == 302
        assert [(w.position, w.title) for w in temario.weeks.all()] == [(1, 'Reales'), (2, 'Funciones')]

    def test_aplicar_reemplaza_las_que_habia(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='apply_detected')
        assert [w.title for w in con_semanas.weeks.all()] == ['Reales', 'Funciones']

    def test_si_el_texto_no_trae_semanas_lo_dice_y_no_toca_nada(self, professor_client, course, con_semanas):
        con_semanas.text = 'Un temario sin formato'
        con_semanas.save()
        html = professor_client.get(url(course) + '?detectar=1').content.decode()
        assert 'No encontramos encabezados' in html and 'Usar estas semanas' not in html
        pedir(professor_client, course, action='apply_detected')
        assert con_semanas.weeks.count() == 3

    def test_con_semanas_ya_creadas_pide_confirmar_antes_de_reemplazar(self, professor_client, course, con_semanas):
        assert 'confirm(' in professor_client.get(url(course) + '?detectar=1').content.decode().split('Usar estas semanas')[0]


# ── Semanas ───────────────────────────────────────────────────────────

class TestSemanas:
    def test_lista_las_semanas_y_abre_la_que_se_pide(self, professor_client, course, con_semanas):
        html = professor_client.get(url(course) + '?semana=2').content.decode()
        assert len(re.findall(r'class="sy-row[" ]', html)) == 3 and '<h2>Semana 2</h2>' in html
        assert 'value="Funciones"' in html

    @pytest.mark.parametrize('valor', ['99', '0', 'abc', '²', '9' * 40, ''])
    def test_una_semana_pedida_que_no_existe_cae_a_la_primera_sin_error(self, professor_client, course, con_semanas, valor):
        respuesta = professor_client.get(url(course), {'semana': valor})
        assert respuesta.status_code == 200 and '<h2>Semana 1</h2>' in respuesta.content.decode()

    def test_agregar_va_al_final_y_la_abre(self, professor_client, course, con_semanas):
        respuesta = pedir(professor_client, course, action='add_week')
        assert respuesta.status_code == 302 and respuesta.url.endswith('?semana=4')
        assert con_semanas.weeks.count() == 4

    def test_guardar_cambia_titulo_temas_objetivos_actividades_y_sin_clase(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 2)
        respuesta = pedir(
            professor_client, course, action='save_week', week=w.pk, title='Nuevo', topics='X\nY', objectives='Obj',
            assessment='Tarea 1\nQuiz 1', no_class='on',
        )
        assert respuesta.status_code == 302 and respuesta.url.endswith('?semana=2')
        w.refresh_from_db()
        assert (w.title, w.topics, w.objectives, w.assessment, w.no_class) == ('Nuevo', 'X\nY', 'Obj', 'Tarea 1\nQuiz 1', True)

    def test_el_editor_muestra_las_actividades_y_evaluacion_de_la_semana(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        w.assessment = 'Hoja de ejercicios'
        w.save()
        html = professor_client.get(url(course), {'semana': 1}).content.decode()
        assert 'Actividades y evaluación' in html and 'Hoja de ejercicios' in html

    def test_guardar_sin_marcar_sin_clase_lo_quita(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        w.no_class = True
        w.save()
        pedir(professor_client, course, action='save_week', week=w.pk, title='Reales')
        w.refresh_from_db()
        assert w.no_class is False

    def test_un_titulo_demasiado_largo_se_rechaza_y_conserva_lo_escrito(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        respuesta = pedir(professor_client, course, action='save_week', week=w.pk, title='x' * 201, topics='Escrito')
        html = respuesta.content.decode()
        assert respuesta.status_code == 200 and 'field-error' in html and 'Escrito' in html
        w.refresh_from_db()
        assert w.title == 'Reales'

    def test_el_titulo_se_escapa(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        pedir(professor_client, course, action='save_week', week=w.pk, title='<img src=x onerror=alert(1)>')
        html = professor_client.get(url(course)).content.decode()
        assert '<img src=x' not in html

    def test_subir_y_bajar(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='move_up', week=semana(con_semanas, 2).pk, title='Funciones')
        assert [w.title for w in con_semanas.weeks.all()] == ['Funciones', 'Reales', 'Límites']
        respuesta = pedir(professor_client, course, action='move_down', week=semana(con_semanas, 1).pk, title='Funciones')
        assert [w.title for w in con_semanas.weeks.all()] == ['Reales', 'Funciones', 'Límites']
        assert respuesta.url.endswith('?semana=2')

    def test_mover_conserva_lo_que_se_habia_escrito_sin_guardar(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 2)
        pedir(professor_client, course, action='move_up', week=w.pk, title='Editado a medias', topics='Solo esto')
        w.refresh_from_db()
        assert (w.position, w.title, w.topics) == (1, 'Editado a medias', 'Solo esto')

    def test_dividir_parte_los_temas_y_abre_la_semana_nueva(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        respuesta = pedir(professor_client, course, action='split', week=w.pk, title='Reales', topics='A\nB\nC\nD')
        assert respuesta.url.endswith('?semana=2') and con_semanas.weeks.count() == 4
        assert semana(con_semanas, 1).topic_list == ['A', 'B'] and semana(con_semanas, 2).topic_list == ['C', 'D']

    def test_dividir_sin_temas_suficientes_avisa(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        respuesta = pedir(professor_client, course, action='split', week=w.pk, title='Reales', topics='Uno')
        assert con_semanas.weeks.count() == 3 and respuesta.url.endswith('?semana=1')
        assert 'al menos dos temas' in professor_client.get(respuesta.url).content.decode()

    def test_unir_con_la_siguiente(self, professor_client, course, con_semanas):
        w = semana(con_semanas, 1)
        respuesta = pedir(professor_client, course, action='merge', week=w.pk, title='Reales', topics='A\nB')
        assert respuesta.status_code == 302 and con_semanas.weeks.count() == 2
        assert semana(con_semanas, 1).topic_list[:2] == ['A', 'B'] and semana(con_semanas, 2).title == 'Límites'

    def test_unir_la_ultima_no_hace_nada(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='merge', week=semana(con_semanas, 3).pk, title='Límites')
        assert con_semanas.weeks.count() == 3

    def test_quitar_renumera_y_abre_una_vecina(self, professor_client, course, con_semanas):
        respuesta = pedir(professor_client, course, action='delete_week', week=semana(con_semanas, 2).pk)
        assert [(w.position, w.title) for w in con_semanas.weeks.all()] == [(1, 'Reales'), (2, 'Límites')]
        assert respuesta.url.endswith('?semana=2')

    def test_quitar_la_ultima_abre_la_nueva_ultima(self, professor_client, course, con_semanas):
        respuesta = pedir(professor_client, course, action='delete_week', week=semana(con_semanas, 3).pk)
        assert respuesta.url.endswith('?semana=2')

    def test_quitar_la_unica_semana_deja_la_pantalla_sin_semanas(self, professor_client, course, temario):
        SyllabusWeekFactory(syllabus=temario, position=1)
        respuesta = pedir(professor_client, course, action='delete_week', week=temario.weeks.get().pk)
        assert respuesta.status_code == 302 and 'Agregar la primera semana' in professor_client.get(respuesta.url).content.decode()

    def test_no_se_puede_tocar_una_semana_de_otro_grupo_ni_de_otra_organizacion(self, professor_client, course, con_semanas):
        ajena = SyllabusWeekFactory()  # otro docente, otra organización
        for accion in ('save_week', 'move_up', 'split', 'merge', 'delete_week'):
            assert pedir(professor_client, course, action=accion, week=ajena.pk, title='x').status_code == 404
        assert SyllabusWeek.objects.filter(pk=ajena.pk).exists() and con_semanas.weeks.count() == 3

    @pytest.mark.parametrize('valor', ['', 'abc', '²', '9' * 40, '-1'])
    def test_un_identificador_de_semana_raro_es_404_y_no_500(self, professor_client, course, con_semanas, valor):
        assert pedir(professor_client, course, action='delete_week', week=valor).status_code == 404

    def test_hay_tope_de_semanas(self, professor_client, course, temario):
        for _ in range(60):
            SyllabusWeekFactory(syllabus=temario, position=temario.weeks.count() + 1)
        pedir(professor_client, course, action='add_week')
        assert temario.weeks.count() == 60


# ── Quitar todas las semanas ──────────────────────────────────────────

class TestQuitarTodas:
    def test_la_pantalla_ofrece_el_boton_con_confirmacion_solo_si_hay_semanas(self, professor_client, course, con_semanas):
        html = professor_client.get(url(course)).content.decode()
        assert 'Quitar todas las semanas' in html and 'confirm(' in html and 'las 3 semanas' in html
        con_semanas.weeks.all().delete()
        assert 'Quitar todas las semanas' not in professor_client.get(url(course)).content.decode()

    def test_quita_todas_de_una_vez_y_conserva_las_actividades(self, professor_client, course, con_semanas):
        actividad = ActivityFactory(course=course, syllabus_week=semana(con_semanas, 2))
        respuesta = pedir(professor_client, course, action='delete_all_weeks')
        assert respuesta.status_code == 302 and respuesta.url == url(course)
        assert con_semanas.weeks.count() == 0
        actividad.refresh_from_db()
        assert actividad.syllabus_week is None
        html = professor_client.get(respuesta.url).content.decode()
        assert 'Se quitaron las 3 semanas' in html and 'Agregar la primera semana' in html

    def test_conserva_el_temario_y_su_texto_para_volver_a_detectar(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='delete_all_weeks')
        con_semanas.refresh_from_db()
        assert con_semanas.text == TEMARIO

    def test_se_puede_repetir_sin_error(self, professor_client, course, temario):
        assert pedir(professor_client, course, action='delete_all_weeks').status_code == 302

    def test_otro_docente_y_el_alumno_no_pueden(self, course, con_semanas):
        assert pedir(cliente(ProfessorFactory()), course, action='delete_all_weeks').status_code == 404
        assert pedir(cliente(StudentFactory()), course, action='delete_all_weeks').status_code == 302
        assert con_semanas.weeks.count() == 3

    def test_otro_grupo_no_se_ve_afectado(self, professor_client, course, con_semanas):
        otro = SyllabusWeekFactory()
        pedir(professor_client, course, action='delete_all_weeks')
        assert SyllabusWeek.objects.filter(pk=otro.pk).exists()


# ── Fechas ────────────────────────────────────────────────────────────

class TestFechas:
    def test_sin_fecha_de_inicio_pide_ponerla(self, professor_client, course, con_semanas):
        assert 'Pon la fecha de inicio' in professor_client.get(url(course)).content.decode()

    def test_guardar_la_fecha_muestra_los_rangos_y_cruza_de_mes(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='start_date', start_date='2026-08-24')
        con_semanas.refresh_from_db()
        assert con_semanas.start_date == datetime.date(2026, 8, 24)
        html = professor_client.get(url(course)).content.decode()
        assert '24–28 ago' in html and '31 ago–4 sep' in html and '7–11 sep' in html

    @pytest.mark.parametrize('valor', ['', 'mañana', '2026-13-45'])
    def test_una_fecha_invalida_no_cambia_nada(self, professor_client, course, con_semanas, valor):
        con_semanas.start_date = datetime.date(2026, 8, 24)
        con_semanas.save()
        pedir(professor_client, course, action='start_date', start_date=valor)
        con_semanas.refresh_from_db()
        assert con_semanas.start_date == datetime.date(2026, 8, 24)

    def test_marca_la_semana_de_hoy_y_abre_esa_por_omision(self, professor_client, course, con_semanas):
        lunes = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
        con_semanas.start_date = lunes - datetime.timedelta(weeks=1)  # la semana 2 es la de hoy
        con_semanas.save()
        html = professor_client.get(url(course)).content.decode()
        assert 'Hoy: semana 2' in html and '<h2>Semana 2</h2>' in html and 'Esta semana' in html


# ── Eliminar el temario ───────────────────────────────────────────────

class TestEliminarTemario:
    def test_la_pantalla_ofrece_el_boton_con_confirmacion(self, professor_client, course, con_semanas):
        html = professor_client.get(url(course)).content.decode()
        assert 'Eliminar temario' in html and 'name="action" value="delete_syllabus"' in html
        assert 'las 3 semanas' in html.split('delete_syllabus')[0].rsplit('confirm(', 1)[1]

    def test_sin_temario_no_hay_que_eliminar(self, professor_client, course):
        assert 'Eliminar temario' not in professor_client.get(url(course)).content.decode()

    def test_borra_el_temario_sus_semanas_y_conserva_las_actividades(self, professor_client, course, con_semanas):
        actividad = ActivityFactory(course=course, syllabus_week=semana(con_semanas, 2))
        respuesta = pedir(professor_client, course, action='delete_syllabus')
        assert respuesta.status_code == 302 and respuesta.url == url(course)
        assert not Syllabus.objects.filter(course=course).exists() and not SyllabusWeek.objects.exists()
        actividad.refresh_from_db()
        assert actividad.syllabus_week is None
        html = professor_client.get(respuesta.url).content.decode()
        assert 'Se eliminó el temario' in html and 'Empieza con tu temario' in html

    def test_borra_tambien_el_archivo_guardado(self, professor_client, course):
        from apps.syllabus.services import extraction

        guardado = extraction.save_uploaded_file(course, SimpleUploadedFile('temario.txt', b'Semana 1: Reales'))
        nombre, almacen = guardado.file.name, guardado.file.storage
        assert almacen.exists(nombre)
        pedir(professor_client, course, action='delete_syllabus')
        assert not almacen.exists(nombre)

    def test_se_puede_volver_a_empezar_despues(self, professor_client, course, con_semanas):
        pedir(professor_client, course, action='delete_syllabus')
        pedir(professor_client, course, action='paste', text=TEMARIO)
        assert Syllabus.objects.get(course=course).text.startswith('Semana 1')

    def test_sin_temario_responde_404(self, professor_client, course):
        assert pedir(professor_client, course, action='delete_syllabus').status_code == 404

    def test_otro_docente_el_alumno_y_un_grupo_archivado_no_pueden(self, course, con_semanas, professor_client):
        assert pedir(cliente(ProfessorFactory()), course, action='delete_syllabus').status_code == 404
        assert pedir(cliente(StudentFactory()), course, action='delete_syllabus').status_code == 302
        Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)
        assert pedir(professor_client, course, action='delete_syllabus').status_code == 404
        assert Syllabus.objects.filter(course=course).exists() and con_semanas.weeks.count() == 3
