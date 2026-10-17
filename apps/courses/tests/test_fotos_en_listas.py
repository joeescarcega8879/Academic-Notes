"""La foto de cada alumno en las listas del docente: se ve, cae a iniciales sin cuenta o sin foto, y no cuesta
una consulta por alumno."""

import itertools
from io import BytesIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from apps.accounts.avatars import process_avatar
from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.services.roster import unlink_student
from apps.grades.tests.factories import ActivityFactory
from apps.grades.services.gradebook import grade_activity
from apps.quizzes.tests.factories import make_quiz

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory, StudentRecordFactory

pytestmark = pytest.mark.django_db

_matriculas = itertools.count(1)


def foto():
    buffer = BytesIO()
    Image.new('RGB', (300, 300), (20, 120, 200)).save(buffer, format='PNG')
    return process_avatar(SimpleUploadedFile('f.png', buffer.getvalue()))


def cliente(user):
    client = Client()
    client.force_login(user)
    return client


def inscribir(course, *, cuenta=True, con_foto=True, nombre='Ana', apellidos='Pérez'):
    """Un alumno en la lista del grupo. Con ``cuenta`` queda enlazado; con ``con_foto``, esa cuenta tiene foto."""
    user = StudentFactory(first_name=nombre, last_name=apellidos) if cuenta else None
    ficha = StudentRecordFactory(
        organization=course.organization, user=user, first_name=nombre, last_name=apellidos,
        student_number=f'M{next(_matriculas):04d}',
    )
    EnrollmentFactory(course=course, student=ficha)
    if user and con_foto:
        user.avatar.save('a.jpg', foto(), save=True)
    return ficha


@pytest.fixture
def escenario():
    """Un docente con un grupo y una actividad, una tarea y un quiz, con un alumno reprobado para la lista de riesgo."""
    docente = ProfessorFactory()
    grupo = CourseFactory(professor=docente)
    actividad = ActivityFactory(course=grupo)
    quiz = make_quiz(grupo, questions=1)
    return docente, grupo, actividad, quiz


def pantallas(grupo, actividad, quiz):
    return {
        'detalle del grupo': reverse('course_detail', args=[grupo.pk]),
        'libreta': reverse('grades:gradesheet', args=[grupo.pk]),
        'alumnos en riesgo': reverse('reports:risk', args=[grupo.pk]),
        'actividad': reverse('grades:activity_detail', args=[actividad.pk]),
        'calificar': reverse('grades:activity_grading', args=[actividad.pk]),
        'resultados del quiz': reverse('quizzes:results', args=[quiz.activity.pk]),
        'calificaciones': reverse('grades:list'),
    }


PANTALLAS = ['detalle del grupo', 'libreta', 'alumnos en riesgo', 'actividad', 'calificar', 'resultados del quiz', 'calificaciones']


def reprobar(actividad, ficha):
    grade_activity(actividad, ficha, score=1)


class TestModelo:
    def test_iniciales_de_la_ficha(self):
        assert StudentRecordFactory.build(first_name='ana', last_name='pérez').initials == 'AP'
        assert StudentRecordFactory.build(first_name='Ana', last_name='', user=None).initials == 'A'
        assert StudentRecordFactory.build(first_name='', last_name='', user=None).initials == '?'

    def test_sin_cuenta_no_hay_foto(self, escenario):
        ficha = inscribir(escenario[1], cuenta=False)
        assert ficha.avatar_url == ''

    def test_cuenta_sin_foto_no_hay_foto(self, escenario):
        ficha = inscribir(escenario[1], con_foto=False)
        assert ficha.avatar_url == ''

    def test_con_foto_es_la_de_su_cuenta(self, escenario):
        ficha = inscribir(escenario[1])
        assert ficha.avatar_url == ficha.user.avatar_url and ficha.avatar_url.startswith(reverse('avatar', args=[ficha.user.pk]))


class TestPantallasDelDocente:
    @pytest.mark.parametrize('pantalla', PANTALLAS)
    def test_se_ve_la_foto_del_alumno_vinculado(self, escenario, pantalla):
        docente, grupo, actividad, quiz = escenario
        ficha = inscribir(grupo)
        reprobar(actividad, ficha)
        html = cliente(docente).get(pantallas(grupo, actividad, quiz)[pantalla]).content.decode()
        assert f'src="{ficha.avatar_url}"' in html

    @pytest.mark.parametrize('pantalla', PANTALLAS)
    def test_sin_cuenta_o_sin_foto_salen_las_iniciales(self, escenario, pantalla):
        docente, grupo, actividad, quiz = escenario
        sin_cuenta = inscribir(grupo, cuenta=False, nombre='Luis', apellidos='Mora')
        sin_foto = inscribir(grupo, con_foto=False, nombre='Rosa', apellidos='Vega')
        for ficha in (sin_cuenta, sin_foto):
            reprobar(actividad, ficha)
        html = cliente(docente).get(pantallas(grupo, actividad, quiz)[pantalla]).content.decode()
        assert '<img' not in html  # nadie tiene foto: ni la imagen rota ni una vacía
        assert '>LM<' in html and '>RV<' in html

    @pytest.mark.parametrize('pantalla', PANTALLAS)
    def test_no_cuesta_una_consulta_por_alumno(self, escenario, pantalla):
        docente, grupo, actividad, quiz = escenario
        client = cliente(docente)
        url = pantallas(grupo, actividad, quiz)[pantalla]

        def consultas():
            with CaptureQueriesContext(connection) as capturadas:
                assert client.get(url).status_code == 200
            return len(capturadas)

        for _ in range(2):
            reprobar(actividad, inscribir(grupo))
        con_dos = consultas()
        for _ in range(6):
            reprobar(actividad, inscribir(grupo))
        assert consultas() == con_dos


class TestPermisosDeLaFoto:
    def test_el_docente_puede_abrir_la_foto_de_su_alumno(self, escenario):
        docente, grupo, *_ = escenario
        ficha = inscribir(grupo)
        assert cliente(docente).get(ficha.avatar_url).status_code == 200

    def test_otro_docente_no_la_ve_ni_en_la_url(self, escenario):
        _, grupo, *_ = escenario
        ficha = inscribir(grupo)
        assert cliente(ProfessorFactory()).get(ficha.avatar_url).status_code == 404

    def test_al_desvincular_al_alumno_deja_de_verse(self, escenario):
        docente, grupo, actividad, quiz = escenario
        ficha = inscribir(grupo)
        url_foto = ficha.avatar_url
        unlink_student(ficha)
        ficha.refresh_from_db()
        assert ficha.avatar_url == ''
        html = cliente(docente).get(reverse('course_detail', args=[grupo.pk])).content.decode()
        assert url_foto not in html
        assert cliente(docente).get(url_foto).status_code == 404
