"""Migración de datos que separa ``Student`` de ``User`` (courses.0006 y grades.0008).

Se retrocede al esquema previo, se siembran datos con los modelos históricos y se
avanza hasta el esquema actual.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [
    ('organizations', '0002_backfill_organizaciones'),
    ('accounts', '0003_user_notifications_read_at'),
    ('courses', '0005_student'),
    ('grades', '0006_renombrar_subject_a_course'),
    ('messaging', '0005_renombrar_subject_a_course'),
]


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
    """Esquema anterior a la separación; al terminar, restaura el esquema actual."""
    yield migrar(ANTES)
    migrar(hojas())


def test_cada_cuenta_con_inscripcion_o_nota_recibe_una_ficha_por_organizacion(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    StudentProfile = old.get_model('accounts', 'StudentProfile')
    Organization = old.get_model('organizations', 'Organization')
    Course = old.get_model('courses', 'Course')
    Enrollment = old.get_model('courses', 'Enrollment')
    Evaluation = old.get_model('grades', 'Evaluation')
    Grade = old.get_model('grades', 'Grade')

    org_a = Organization.objects.create(name='A')
    org_b = Organization.objects.create(name='B')
    prof_a = User.objects.create(dni='pa', username='pa', email='pa@t.test', role='professor')
    prof_b = User.objects.create(dni='pb', username='pb', email='pb@t.test', role='professor')
    sofia = User.objects.create(
        dni='s', username='sofia', email='sofia@t.test', role='student', first_name='Sofía', last_name='López',
    )
    sin_perfil = User.objects.create(dni='n', username='nadie', email='nadie@t.test', role='student')
    solo_nota = User.objects.create(
        dni='x', username='solonota', email='solonota@t.test', role='student', first_name='Solo',
    )
    StudentProfile.objects.create(user_id=sofia.pk, program='ISC', semester=3, enrollment_number='00123')

    algebra = Course.objects.create(name='Álgebra', code='ALG', professor_id=prof_a.pk, organization_id=org_a.pk)
    fisica = Course.objects.create(name='Física', code='FIS', professor_id=prof_b.pk, organization_id=org_b.pk)
    for curso in (algebra, fisica):
        Enrollment.objects.create(student_id=sofia.pk, course_id=curso.pk, organization_id=curso.organization_id)
    Enrollment.objects.create(student_id=sin_perfil.pk, course_id=algebra.pk, organization_id=org_a.pk)
    parcial = Evaluation.objects.create(course_id=algebra.pk, title='Parcial', organization_id=org_a.pk)
    Grade.objects.create(evaluation_id=parcial.pk, student_id=sofia.pk, score=9, organization_id=org_a.pk)
    Grade.objects.create(evaluation_id=parcial.pk, student_id=solo_nota.pk, score=5, organization_id=org_a.pk)

    nuevo = migrar(hojas())
    Student = nuevo.get_model('courses', 'Student')
    Enrollment = nuevo.get_model('courses', 'Enrollment')
    Grade = nuevo.get_model('grades', 'Grade')

    # Sofía: una ficha por organización donde cursa, con su matrícula (texto, con ceros) y sus datos.
    fichas = Student.objects.filter(user_id=sofia.pk)
    assert {f.organization_id for f in fichas} == {org_a.pk, org_b.pk}
    assert {f.student_number for f in fichas} == {'00123'}
    assert {(f.first_name, f.last_name, f.email) for f in fichas} == {('Sofía', 'López', 'sofia@t.test')}

    # Sin perfil: matrícula vacía y nombre de reserva = usuario.
    sin = Student.objects.get(user_id=sin_perfil.pk)
    assert (sin.student_number, sin.first_name, sin.organization_id) == ('', 'nadie', org_a.pk)

    # Cada inscripción y nota apunta a la ficha de su organización.
    assert Enrollment.objects.count() == 3
    for inscripcion in Enrollment.objects.select_related('student'):
        assert inscripcion.student.organization_id == inscripcion.organization_id
    assert Grade.objects.get(score=9).student.user_id == sofia.pk
    # Una nota de alguien sin inscripción recibe su propia ficha.
    assert Grade.objects.get(score=5).student.user_id == solo_nota.pk
    assert Student.objects.count() == 4
