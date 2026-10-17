"""Migración de datos de ciclos (courses.0009): los grupos existentes reciben un ciclo actual por organización."""

import datetime

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [('courses', '0007_enrollment_apunta_a_student')]


def migrar(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def hojas():
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    return executor.loader.graph.leaf_nodes()


@pytest.fixture
def estado_previo(transactional_db):
    """Esquema anterior a los ciclos; al terminar, restaura el esquema actual."""
    yield migrar(ANTES)
    migrar(hojas())


def test_cada_organizacion_con_grupos_recibe_su_ciclo_actual(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    Organization = old.get_model('organizations', 'Organization')
    Course = old.get_model('courses', 'Course')

    org_a = Organization.objects.create(name='A')
    org_b = Organization.objects.create(name='B')
    sin_grupos = Organization.objects.create(name='Vacía')
    prof_a = User.objects.create(dni='a', username='a', email='a@t.test', role='professor')
    prof_b = User.objects.create(dni='b', username='b', email='b@t.test', role='professor')
    for code, prof, org in (('M1', prof_a, org_a), ('M2', prof_a, org_a), ('M3', prof_b, org_b)):
        Course.objects.create(name=code, code=code, professor_id=prof.pk, organization_id=org.pk)

    nuevo = migrar(hojas())
    AcademicYear = nuevo.get_model('courses', 'AcademicYear')
    Course = nuevo.get_model('courses', 'Course')

    # Un ciclo actual por organización con grupos, ninguno para la que no tiene.
    ciclos = AcademicYear.objects.all()
    assert {c.organization_id for c in ciclos} == {org_a.pk, org_b.pk}
    assert all(c.is_current for c in ciclos)
    assert not AcademicYear.objects.filter(organization_id=sin_grupos.pk).exists()

    # Todos los grupos quedan en el ciclo de su organización, activos.
    for grupo in Course.objects.select_related('academic_year'):
        assert grupo.academic_year.organization_id == grupo.organization_id
        assert grupo.status == 'active' and grupo.archived_at is None

    # El ciclo abarca de agosto a julio y contiene hoy.
    for ciclo in ciclos:
        assert ciclo.start_date.month == 8 and ciclo.end_date.month == 7
        assert ciclo.start_date <= datetime.date.today() <= ciclo.end_date
