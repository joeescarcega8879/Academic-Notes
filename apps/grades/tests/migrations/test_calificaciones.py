"""Migración de datos de calificaciones (grades.0016): lo guardado hasta hoy es lo que escribió el docente."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [('grades', '0015_calificacion_original_y_bitacora')]


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
    """Esquema anterior al llenado de ``raw_score``; al terminar, restaura el esquema actual."""
    yield migrar(ANTES)
    migrar(hojas())


def test_las_calificaciones_existentes_conservan_su_valor_como_original(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    Organization = old.get_model('organizations', 'Organization')
    AcademicYear = old.get_model('courses', 'AcademicYear')
    Course = old.get_model('courses', 'Course')
    Student = old.get_model('courses', 'Student')
    Scheme = old.get_model('grades', 'EvaluationScheme')
    Period = old.get_model('grades', 'EvaluationPeriod')
    Criterion = old.get_model('grades', 'EvaluationCriterion')
    Activity = old.get_model('grades', 'Activity')
    Grade = old.get_model('grades', 'Grade')

    org = Organization.objects.create(name='A')
    prof = User.objects.create(dni='p', username='p', email='p@t.test', role='professor')
    ciclo = AcademicYear.objects.create(
        organization_id=org.pk, name='2026–2027', is_current=True, start_date='2026-08-01', end_date='2027-07-31',
    )
    curso = Course.objects.create(
        name='G', code='G', professor_id=prof.pk, organization_id=org.pk, academic_year_id=ciclo.pk,
    )
    scheme = Scheme.objects.create(course_id=curso.pk, organization_id=org.pk)
    periodo = Period.objects.create(scheme_id=scheme.pk, organization_id=org.pk, name='P')
    criterio = Criterion.objects.create(period_id=periodo.pk, organization_id=org.pk, name='C')
    actividad = Activity.objects.create(
        course_id=curso.pk, organization_id=org.pk, title='T', criterion_id=criterio.pk, published=True,
    )
    for n, nota in enumerate((0.0, 6.5, 10.0)):
        alumno = Student.objects.create(organization_id=org.pk, first_name=f'A{n}')
        Grade.objects.create(activity_id=actividad.pk, student_id=alumno.pk, organization_id=org.pk, score=nota)
    assert set(Grade.objects.values_list('raw_score', flat=True)) == {None}

    nuevo = migrar(hojas())
    notas = list(nuevo.get_model('grades', 'Grade').objects.order_by('score'))
    assert [(g.score, g.raw_score, float(g.late_penalty)) for g in notas] == [(0.0, 0.0, 0.0), (6.5, 6.5, 0.0), (10.0, 10.0, 0.0)]
