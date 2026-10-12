"""Prueba de la migración de datos organizations.0002 sobre un esquema histórico.

Se retrocede la base al estado previo al backfill (columnas ``organization``
nulas), se siembran datos con los modelos históricos y se avanza de nuevo.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [
    ('organizations', '0001_initial'),
    ('subjects', '0002_agregar_organizacion'),
    ('grades', '0004_agregar_organizacion'),
    ('messaging', '0003_agregar_organizacion'),
]


def migrar(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


@pytest.fixture
def estado_previo(transactional_db):
    """Esquema anterior al backfill; al terminar, restaura el esquema actual."""
    yield migrar(ANTES)
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    migrar(executor.loader.graph.leaf_nodes())


def test_backfill_asigna_organizacion_a_todo(estado_previo):
    old = estado_previo
    User = old.get_model('accounts', 'User')
    Subject = old.get_model('subjects', 'Subject')
    Enrollment = old.get_model('subjects', 'Enrollment')
    Evaluation = old.get_model('grades', 'Evaluation')
    Grade = old.get_model('grades', 'Grade')
    Conversation = old.get_model('messaging', 'Conversation')
    Message = old.get_model('messaging', 'Message')

    ana = User.objects.create(dni='ana', username='ana', email='ana@t.test', role='professor', first_name='Ana', last_name='Ruiz')
    beto = User.objects.create(dni='beto', username='beto', email='beto@t.test', role='professor')
    sin_materias = User.objects.create(dni='lalo', username='lalo', email='lalo@t.test', role='professor')
    sofia = User.objects.create(dni='sofia', username='sofia', email='sofia@t.test', role='student')
    sin_clases = User.objects.create(dni='nadie', username='nadie', email='nadie@t.test', role='student')

    algebra = Subject.objects.create(name='Álgebra', code='ALG', professor_id=ana.pk)
    fisica = Subject.objects.create(name='Física', code='FIS', professor_id=beto.pk)
    for materia in (algebra, fisica):
        Enrollment.objects.create(student_id=sofia.pk, subject_id=materia.pk)
        Conversation.objects.create(student_id=sofia.pk, subject_id=materia.pk)
    evaluacion = Evaluation.objects.create(subject_id=algebra.pk, title='Parcial')
    Grade.objects.create(evaluation_id=evaluacion.pk, student_id=sofia.pk, score=9)
    conversacion = Conversation.objects.get(subject_id=algebra.pk)
    Message.objects.create(conversation_id=conversacion.pk, sender_id=sofia.pk, body='Hola')

    nuevo = migrar([('organizations', '0002_backfill_organizaciones')])
    Organization = nuevo.get_model('organizations', 'Organization')
    Membership = nuevo.get_model('organizations', 'Membership')

    # Una organización individual por profesor, también para quien no tiene materias.
    assert Organization.objects.count() == 3
    assert set(Organization.objects.values_list('type', flat=True)) == {'individual'}
    assert Organization.objects.filter(name='Ana Ruiz').exists()
    assert Membership.objects.filter(role='owner').count() == 3
    assert Membership.objects.get(user_id=sin_materias.pk, role='owner')

    # Cada materia y todo lo que cuelga de ella queda en la organización de su profesor.
    org_ana = Membership.objects.get(user_id=ana.pk).organization_id
    org_beto = Membership.objects.get(user_id=beto.pk).organization_id
    assert org_ana != org_beto
    modelos = {
        'subjects': ('Subject', 'Enrollment'),
        'grades': ('Evaluation', 'Grade'),
        'messaging': ('Conversation', 'Message'),
    }
    for app, nombres in modelos.items():
        for nombre in nombres:
            assert nuevo.get_model(app, nombre).objects.filter(organization__isnull=True).count() == 0, nombre
    assert nuevo.get_model('subjects', 'Subject').objects.get(code='ALG').organization_id == org_ana
    assert nuevo.get_model('subjects', 'Subject').objects.get(code='FIS').organization_id == org_beto
    assert nuevo.get_model('grades', 'Grade').objects.get().organization_id == org_ana
    assert nuevo.get_model('messaging', 'Message').objects.get().organization_id == org_ana
    assert nuevo.get_model('messaging', 'Conversation').objects.get(subject__code='FIS').organization_id == org_beto

    # La alumna es miembro de las dos organizaciones; quien no cursa nada, de ninguna.
    assert set(Membership.objects.filter(user_id=sofia.pk, role='student').values_list('organization_id', flat=True)) == {
        org_ana,
        org_beto,
    }
    assert not Membership.objects.filter(user_id=sin_clases.pk).exists()


def test_backfill_es_idempotente(estado_previo):
    # En este estado histórico dni aún es único y no nulo: se da uno distinto a cada usuario.
    User = estado_previo.get_model('accounts', 'User')
    User.objects.create(dni='ana', username='ana', email='ana@t.test', role='professor')

    migrar([('organizations', '0002_backfill_organizaciones')])
    migrar(ANTES)
    nuevo = migrar([('organizations', '0002_backfill_organizaciones')])

    assert nuevo.get_model('organizations', 'Organization').objects.count() == 1
    assert nuevo.get_model('organizations', 'Membership').objects.count() == 1
