"""Migración de datos de esquemas (grades.0011): los grupos existentes conservan sus resultados."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [('grades', '0010_esquema_de_evaluacion')]


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
    """Esquema anterior a los esquemas de evaluación; al terminar, restaura el actual."""
    yield migrar(ANTES)
    migrar(hojas())


def test_cada_grupo_recibe_un_esquema_general_con_todas_sus_evaluaciones(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    Organization = old.get_model('organizations', 'Organization')
    AcademicYear = old.get_model('courses', 'AcademicYear')
    Course = old.get_model('courses', 'Course')
    Evaluation = old.get_model('grades', 'Evaluation')

    org = Organization.objects.create(name='A')
    prof = User.objects.create(dni='p', username='p', email='p@t.test', role='professor')
    ciclo = AcademicYear.objects.create(
        organization_id=org.pk, name='2026–2027', is_current=True, start_date='2026-08-01', end_date='2027-07-31',
    )
    cursos = [
        Course.objects.create(
            name=f'G{n}', code=f'C{n}', professor_id=prof.pk, organization_id=org.pk, academic_year_id=ciclo.pk,
        )
        for n in range(2)
    ]
    for curso in cursos:
        for tipo in ('exam', 'homework', 'quiz'):
            Evaluation.objects.create(course_id=curso.pk, organization_id=org.pk, title=tipo, type=tipo, weight=2)
    sin_evaluaciones = Course.objects.create(
        name='Vacío', code='V', professor_id=prof.pk, organization_id=org.pk, academic_year_id=ciclo.pk,
    )

    nuevo = migrar(hojas())
    Scheme = nuevo.get_model('grades', 'EvaluationScheme')
    Activity = nuevo.get_model('grades', 'Activity')

    assert Scheme.objects.count() == 3
    for curso in cursos + [sin_evaluaciones]:
        scheme = Scheme.objects.get(course_id=curso.pk)
        assert (scheme.scale_max, float(scheme.pass_mark), scheme.rounding_decimals) == (10, 6.0, 2)
        (periodo,) = scheme.periods.all()
        (criterio,) = periodo.criteria.all()
        assert (periodo.weight, criterio.name, criterio.weight) == (100, 'General', 100)
        assert criterio.organization_id == org.pk
        # Todas las evaluaciones del grupo en ese único criterio: el cálculo anterior no cambia.
        assert {e.criterion_id for e in Activity.objects.filter(course_id=curso.pk)} <= {criterio.pk}
    assert not Activity.objects.filter(criterion__isnull=True).exists()
    assert Activity.objects.count() == 6
