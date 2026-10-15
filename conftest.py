"""Fixtures compartidas por toda la suite."""

import pytest
from django.test import Client

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.grades.factories import ActivityFactory
from apps.courses.factories import EnrollmentFactory, CourseFactory


@pytest.fixture
def professor(db):
    return ProfessorFactory()


@pytest.fixture
def student(db):
    return StudentFactory()


@pytest.fixture
def plan_docente(professor):
    """La organización del docente con el plan Docente (sin topes ni marca de agua), para probar sus funciones."""
    from apps.organizations.models import Membership, Organization

    organization = Membership.objects.get(user=professor).organization
    organization.plan = Organization.Plan.TEACHER
    organization.save(update_fields=['plan'])
    return organization


@pytest.fixture
def course(professor):
    return CourseFactory(professor=professor)


@pytest.fixture
def enrollment(course, student):
    return EnrollmentFactory(course=course, student=student)


@pytest.fixture
def activity(course):
    return ActivityFactory(course=course)


@pytest.fixture(autouse=True)
def limpiar_cache():
    """Los límites de intentos viven en la caché: cada prueba empieza con la suya vacía."""
    from django.core.cache import cache

    cache.clear()
    yield


@pytest.fixture(scope='session', autouse=True)
def limpiar_archivos_de_prueba():
    """Las entregas de las pruebas van a un directorio temporal que se borra al terminar la sesión."""
    yield
    import shutil
    import tempfile
    from pathlib import Path

    shutil.rmtree(Path(tempfile.gettempdir()) / 'gradelink-test-submissions', ignore_errors=True)
    shutil.rmtree(Path(tempfile.gettempdir()) / 'gradelink-test-avatars', ignore_errors=True)


def _client_for(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def professor_client(professor):
    return _client_for(professor)


@pytest.fixture
def student_client(student):
    return _client_for(student)
