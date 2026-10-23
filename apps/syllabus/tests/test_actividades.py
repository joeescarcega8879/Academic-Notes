"""Actividades ligadas a una semana del temario: el formulario, «+ Crear actividad», unir/quitar semanas y duplicar el grupo."""

import datetime
import re

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.courses.services.courses import clone_course
from apps.courses.tests.factories import AcademicYearFactory, CourseFactory
from apps.grades.activity_forms import ActivityForm
from apps.grades.models import Activity
from apps.grades.tests.factories import ActivityFactory
from apps.syllabus.models import Syllabus
from apps.syllabus.services import extraction, weeks as semanas
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db


def syllabus_url(course):
    return reverse('syllabus:index', args=[course.pk])


def create_url(course):
    return reverse('grades:activity_create', args=[course.pk])


@pytest.fixture
def temario(course):
    temario = SyllabusFactory(course=course)
    for i in (1, 2, 3):
        SyllabusWeekFactory(syllabus=temario, position=i, title=f'Tema {i}', topics='')
    return temario


def semana(temario, posicion):
    return temario.weeks.get(position=posicion)


class TestSemanaEnElDetalle:
    def test_el_docente_ve_la_semana_con_enlace_al_temario(self, professor_client, course, temario):
        actividad = ActivityFactory(course=course, syllabus_week=semana(temario, 2))
        html = professor_client.get(actividad.get_absolute_url()).content.decode()
        assert 'Semana del temario' in html and 'Semana 2: Tema 2' in html
        assert f'href="{syllabus_url(course)}?semana=2"' in html

    def test_el_alumno_ve_la_semana_sin_enlace(self, student_client, course, temario, enrollment):
        actividad = ActivityFactory(course=course, syllabus_week=semana(temario, 3))
        html = student_client.get(actividad.get_absolute_url()).content.decode()
        assert 'Semana 3: Tema 3' in html
        assert syllabus_url(course) not in html

    def test_sin_semana_no_aparece_la_fila(self, professor_client, activity):
        assert 'Semana del temario' not in professor_client.get(activity.get_absolute_url()).content.decode()

    def test_no_hace_consultas_de_mas_por_la_semana(self, professor_client, course, temario):
        con = ActivityFactory(course=course, syllabus_week=semana(temario, 1))
        sin = ActivityFactory(course=course)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        contados = []
        for actividad in (sin, con):
            with CaptureQueriesContext(connection) as capturadas:
                professor_client.get(actividad.get_absolute_url())
            contados.append(len(capturadas))
        assert contados[1] == contados[0]  # la semana viaja en la misma consulta


DATOS = {'title': 'Tarea nueva', 'type': 'homework', 'max_score': '10', 'weight': '1', 'allow_late': 'on', 'late_penalty': '0'}


# ── El formulario de actividades ──────────────────────────────────────

class TestFormulario:
    def test_sin_temario_no_hay_campo_de_semana(self, course):
        assert 'syllabus_week' not in ActivityForm(course=course).fields

    def test_con_temario_sin_semanas_tampoco(self, course):
        SyllabusFactory(course=course)
        assert 'syllabus_week' not in ActivityForm(course=course).fields

    def test_con_semanas_ofrece_solo_las_del_grupo(self, course, temario):
        ajena = SyllabusWeekFactory()  # de otro grupo
        campo = ActivityForm(course=course).fields['syllabus_week']
        assert set(campo.queryset) == set(temario.weeks.all()) and ajena not in campo.queryset
        assert campo.label_from_instance(semana(temario, 2)) == 'Semana 2 · Tema 2'
        assert campo.required is False

    def test_rechaza_una_semana_de_otro_grupo(self, course, temario):
        ajena = SyllabusWeekFactory()
        form = ActivityForm({**DATOS, 'syllabus_week': ajena.pk}, course=course)
        assert not form.is_valid() and 'syllabus_week' in form.errors

    def test_el_modelo_tambien_rechaza_una_semana_de_otro_grupo(self, course):
        actividad = Activity(course=course, title='X', syllabus_week=SyllabusWeekFactory())
        with pytest.raises(ValidationError) as error:
            actividad.clean()
        assert 'syllabus_week' in error.value.message_dict

    def test_guarda_la_semana_elegida_y_sin_semana_queda_vacia(self, course, temario):
        con = ActivityForm({**DATOS, 'syllabus_week': semana(temario, 2).pk}, course=course)
        assert con.is_valid(), con.errors
        assert con.save().syllabus_week == semana(temario, 2)
        sin = ActivityForm({**DATOS, 'title': 'Otra'}, course=course)
        assert sin.is_valid() and sin.save().syllabus_week is None


class TestCrearDesdeLaSemana:
    def test_el_enlace_de_la_semana_lleva_la_semana_ya_elegida(self, professor_client, course, temario):
        w = semana(temario, 2)
        html = professor_client.get(syllabus_url(course) + '?semana=2').content.decode()
        assert f'{create_url(course)}?semana={w.pk}' in html
        pagina = professor_client.get(f'{create_url(course)}?semana={w.pk}')
        assert pagina.context['form'].initial['syllabus_week'] == w.pk
        assert f'<option value="{w.pk}" selected>' in pagina.content.decode()

    @pytest.mark.parametrize('valor', ['abc', '²', '9' * 40, '-1', ''])
    def test_una_semana_rara_en_la_direccion_no_rompe_el_formulario(self, professor_client, course, temario, valor):
        assert professor_client.get(create_url(course), {'semana': valor}).status_code == 200

    def test_una_semana_ajena_en_la_direccion_no_queda_elegida(self, professor_client, course, temario):
        ajena = SyllabusWeekFactory()
        html = professor_client.get(create_url(course), {'semana': ajena.pk}).content.decode()
        selector = re.search(r'<select name="syllabus_week".*?</select>', html, re.S).group(0)
        assert 'selected' not in selector and 'Semana 1' in selector

    def test_crear_la_actividad_la_deja_en_la_semana(self, professor_client, course, temario):
        respuesta = professor_client.post(create_url(course), {**DATOS, 'syllabus_week': semana(temario, 3).pk})
        assert respuesta.status_code == 302
        assert Activity.objects.get(title='Tarea nueva').syllabus_week == semana(temario, 3)


# ── La pantalla del temario muestra las actividades ───────────────────

class TestPantalla:
    def test_cada_semana_lista_sus_actividades_y_distingue_borradores(self, professor_client, course, temario):
        ActivityFactory(course=course, title='Examen parcial', syllabus_week=semana(temario, 1))
        ActivityFactory(course=course, title='Quiz borrador', syllabus_week=semana(temario, 1), published=False)
        html = professor_client.get(syllabus_url(course) + '?semana=1').content.decode()
        assert 'Examen parcial' in html and 'Quiz borrador (borrador)' in html
        assert 'Sin actividades' not in html.split('Actividades de esta semana')[1].split('sy-foot')[0]

    def test_una_semana_sin_actividades_lo_dice(self, professor_client, course, temario):
        html = professor_client.get(syllabus_url(course) + '?semana=2').content.decode()
        assert 'Sin actividades' in html.split('Actividades de esta semana')[1]

    def test_los_puntos_de_la_lista_marcan_cuales_semanas_tienen_actividades(self, professor_client, course, temario):
        ActivityFactory(course=course, syllabus_week=semana(temario, 1))
        html = professor_client.get(syllabus_url(course)).content.decode()
        assert html.count('class="dot ok"') == 1 and html.count('class="dot warn"') == 2

    def test_una_semana_sin_clase_no_pide_actividades(self, professor_client, course, temario):
        w = semana(temario, 2)
        w.no_class = True
        w.save()
        html = professor_client.get(syllabus_url(course) + '?semana=2').content.decode()
        assert 'Actividades de esta semana' not in html and html.count('class="dot warn"') == 2

    def test_no_muestra_actividades_de_otro_grupo(self, professor_client, course, temario):
        otra = ActivityFactory(title='Ajena')
        assert 'Ajena' not in professor_client.get(syllabus_url(course)).content.decode()
        assert otra.syllabus_week is None

    def test_el_titulo_de_la_actividad_se_escapa(self, professor_client, course, temario):
        ActivityFactory(course=course, title='<b>x</b>', syllabus_week=semana(temario, 1))
        assert '<b>x</b>' not in professor_client.get(syllabus_url(course)).content.decode()


# ── Unir, quitar y reemplazar semanas ─────────────────────────────────

class TestOperacionesConActividades:
    def test_unir_pasa_las_actividades_de_la_siguiente_a_la_unida(self, course, temario):
        a = ActivityFactory(course=course, syllabus_week=semana(temario, 2))
        b = ActivityFactory(course=course, syllabus_week=semana(temario, 1))
        unida = semanas.merge_with_next(semana(temario, 1))
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.syllabus_week == unida and b.syllabus_week == unida
        assert temario.weeks.count() == 2

    def test_quitar_una_semana_deja_sus_actividades_sin_semana_pero_vivas(self, course, temario):
        a = ActivityFactory(course=course, syllabus_week=semana(temario, 2))
        semanas.delete_week(semana(temario, 2))
        a.refresh_from_db()
        assert a.syllabus_week is None and Activity.objects.filter(pk=a.pk).exists()

    def test_reemplazar_las_semanas_deja_las_actividades_sin_semana(self, course, temario):
        a = ActivityFactory(course=course, syllabus_week=semana(temario, 1))
        semanas.replace_weeks(temario, [{'title': 'N', 'topics': '', 'objectives': ''}])
        a.refresh_from_db()
        assert a.syllabus_week is None

    def test_dividir_no_toca_las_actividades(self, course, temario):
        w = semana(temario, 1)
        w.topics = 'A\nB'
        w.save()
        a = ActivityFactory(course=course, syllabus_week=w)
        semanas.split_week(w)
        a.refresh_from_db()
        assert a.syllabus_week == w

    def test_mover_semanas_conserva_el_enlace(self, course, temario):
        a = ActivityFactory(course=course, syllabus_week=semana(temario, 1))
        semanas.move_week(semana(temario, 1), +1)
        a.refresh_from_db()
        assert a.syllabus_week.position == 2


# ── Duplicar el grupo para un nuevo ciclo ─────────────────────────────

@pytest.fixture
def nuevo_ciclo(course):
    return AcademicYearFactory(
        organization=course.organization, name='Ciclo siguiente',
        start_date=datetime.date(2027, 8, 1), end_date=datetime.date(2028, 6, 30),
    )


class TestDuplicarElGrupo:
    def test_copia_el_texto_y_las_semanas_sin_fecha_de_inicio(self, course, temario, nuevo_ciclo):
        temario.start_date = datetime.date(2026, 8, 24)
        temario.text = 'Semana 1: Reales'
        temario.save()
        w = semana(temario, 2)
        w.topics, w.objectives, w.no_class = 'A\nB', 'Obj', True
        w.save()
        copia = clone_course(course, nuevo_ciclo)
        nuevo = copia.syllabus
        assert nuevo.pk != temario.pk and nuevo.text == 'Semana 1: Reales' and nuevo.start_date is None
        assert nuevo.status == Syllabus.Status.READY
        assert [(x.position, x.title) for x in nuevo.weeks.all()] == [(1, 'Tema 1'), (2, 'Tema 2'), (3, 'Tema 3')]
        segunda = nuevo.weeks.get(position=2)
        assert (segunda.topics, segunda.objectives, segunda.no_class) == ('A\nB', 'Obj', True)
        assert temario.weeks.count() == 3 and temario.start_date == datetime.date(2026, 8, 24)  # el original no cambia

    def test_copia_el_archivo_a_una_ruta_propia(self, course, nuevo_ciclo, django_capture_on_commit_callbacks):
        original = extraction.save_uploaded_file(course, SimpleUploadedFile('t.txt', b'Semana 1: A'))
        copia = clone_course(course, nuevo_ciclo)
        nuevo = copia.syllabus
        assert nuevo.file.name != original.file.name and nuevo.original_name == 't.txt'
        with nuevo.file.open('rb') as a, original.file.open('rb') as b:
            assert a.read() == b.read() == b'Semana 1: A'
        # Borrar el original (o su grupo) no deja sin archivo a la copia.
        course.delete()
        assert nuevo.file.storage.exists(nuevo.file.name)

    def test_un_temario_pendiente_se_vuelve_a_extraer_en_la_copia(self, course, nuevo_ciclo, django_capture_on_commit_callbacks):
        extraction.save_uploaded_file(course, SimpleUploadedFile('t.txt', b'Semana 1: A'))
        with django_capture_on_commit_callbacks(execute=True):
            copia = clone_course(course, nuevo_ciclo)
        nuevo = Syllabus.objects.get(course=copia)
        assert nuevo.status == Syllabus.Status.READY and nuevo.text == 'Semana 1: A'

    def test_las_actividades_copiadas_quedan_en_la_misma_semana(self, course, temario, nuevo_ciclo):
        ActivityFactory(course=course, title='En semana 2', syllabus_week=semana(temario, 2))
        ActivityFactory(course=course, title='Suelta')
        copia = clone_course(course, nuevo_ciclo)
        en_semana = copia.activities.get(title='En semana 2')
        assert en_semana.syllabus_week.syllabus.course_id == copia.pk and en_semana.syllabus_week.position == 2
        assert en_semana.syllabus_week.pk != semana(temario, 2).pk
        assert copia.activities.get(title='Suelta').syllabus_week is None
        assert copia.syllabus.weeks.count() == 3  # un solo temario copiado, no uno por actividad

    def test_un_grupo_sin_temario_se_duplica_igual(self, course, nuevo_ciclo):
        ActivityFactory(course=course)
        copia = clone_course(course, nuevo_ciclo)
        assert not Syllabus.objects.filter(course=copia).exists() and copia.activities.count() == 1

    def test_el_temario_de_otro_grupo_no_se_cuela(self, course, temario, nuevo_ciclo):
        otro = SyllabusFactory(course=CourseFactory(), text='Del otro')
        copia = clone_course(course, nuevo_ciclo)
        assert copia.syllabus.text != 'Del otro' and Syllabus.objects.filter(pk=otro.pk).exists()
