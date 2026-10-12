"""Migración de datos del código de invitación (courses.0012): los grupos existentes reciben uno único."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [('courses', '0011_codigo_de_invitacion')]


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
    """Esquema anterior al llenado de códigos; al terminar, restaura el esquema actual."""
    yield migrar(ANTES)
    migrar(hojas())


def test_cada_grupo_existente_recibe_un_codigo_unico(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    Organization = old.get_model('organizations', 'Organization')
    AcademicYear = old.get_model('courses', 'AcademicYear')
    Course = old.get_model('courses', 'Course')

    org = Organization.objects.create(name='A')
    prof = User.objects.create(dni='p', username='p', email='p@t.test', role='professor')
    ciclo = AcademicYear.objects.create(
        organization_id=org.pk, name='2026–2027', is_current=True, start_date='2026-08-01', end_date='2027-07-31',
    )
    for n in range(30):
        Course.objects.create(
            name=f'G{n}', code=f'C{n}', professor_id=prof.pk, organization_id=org.pk, academic_year_id=ciclo.pk,
        )
    assert set(Course.objects.values_list('invite_code', flat=True)) == {''}

    nuevo = migrar(hojas())
    codigos = list(nuevo.get_model('courses', 'Course').objects.values_list('invite_code', flat=True))
    assert len(codigos) == 30 and len(set(codigos)) == 30
    assert all(len(c) == 8 and not set(c) & set('01OIL') for c in codigos)
