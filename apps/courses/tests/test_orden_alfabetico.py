"""Las listas de alumnos van en orden alfabético sin importar acentos ni mayúsculas.

La base de datos no lo garantiza (SQLite y PostgreSQL sobre Alpine ponen «Álvarez» después de «Zapata»),
así que se ordena en Python.
"""

import pytest
from django.urls import reverse

from apps.courses.services.text import sort_enrollments, student_sort_key
from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.models import Grade
from apps.grades.tests.factories import ActivityFactory
from apps.quizzes.services.results import student_rows
from apps.quizzes.tests.factories import make_quiz
from apps.reports.services import risk

pytestmark = pytest.mark.django_db

# Orden esperado; se crean mezclados para que ni el orden de inserción ni su inverso (el de ``-enrolled_at``) acierten.
NOMBRES = [("Ana", "Álvarez"), ("Luis", "Beltrán"), ("Paco", "Díaz"), ("Eva", "Ñandú"), ("Zoe", "Zapata")]
ESPERADO = [f"{nombre} {apellido}" for nombre, apellido in NOMBRES]


@pytest.fixture
def grupo(course):
    for posicion in (2, 0, 4, 1, 3):
        nombre, apellido = NOMBRES[posicion]
        EnrollmentFactory(course=course, student__user=None, student__first_name=nombre, student__last_name=apellido)
    return course


def nombres(alumnos):
    return [str(alumno) for alumno in alumnos]


def test_la_clave_ignora_acentos_y_mayusculas(course):
    a = EnrollmentFactory(course=course, student__user=None, student__first_name="Zoe", student__last_name="álvarez").student
    b = EnrollmentFactory(course=course, student__user=None, student__first_name="Ana", student__last_name="ÁLVAREZ").student
    c = EnrollmentFactory(course=course, student__user=None, student__first_name="Ana", student__last_name="Zapata").student
    assert sorted([c, a, b], key=student_sort_key) == [b, a, c]  # mismos apellidos: decide el nombre


def test_ordenar_inscripciones(grupo):
    inscripciones = sort_enrollments(grupo.enrollments.select_related("student__user"))
    assert nombres(e.student for e in inscripciones) == ESPERADO


def test_detalle_del_grupo(professor_client, grupo):
    response = professor_client.get(grupo.get_absolute_url())
    assert nombres(e.student for e in response.context["enrollments"]) == ESPERADO


def test_detalle_de_la_actividad(professor_client, grupo):
    actividad = ActivityFactory(course=grupo)
    response = professor_client.get(actividad.get_absolute_url())
    assert nombres(e.student for e in response.context["enrollments"]) == ESPERADO


def test_resultados_del_quiz(grupo):
    quiz = make_quiz(grupo)
    assert nombres(fila["student"] for fila in student_rows(quiz)) == ESPERADO


def test_alumnos_en_riesgo_empatados_van_en_orden_alfabetico(grupo):
    assert nombres(r.student for r in risk.assess_course(grupo)) == ESPERADO


def test_exportar_calificaciones_a_csv(professor_client, grupo):
    actividad = ActivityFactory(course=grupo)
    for inscripcion in grupo.enrollments.all():
        Grade.objects.create(
            organization=grupo.organization, activity=actividad, student=inscripcion.student, raw_score=8, score=8,
        )
    contenido = professor_client.get(reverse("grades:export")).content.decode("utf-8-sig")
    posiciones = [contenido.index(nombre) for nombre in ESPERADO]
    assert posiciones == sorted(posiciones)
