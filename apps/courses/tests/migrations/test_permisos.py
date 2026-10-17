"""Migraciones de datos courses.0014 y grades.0019: los permisos de modelos renombrados no quedan duplicados."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

ANTES = [('courses', '0013_codigo_de_invitacion_unico'), ('grades', '0018_origen_de_la_calificacion')]


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
    yield migrar(ANTES)
    migrar(hojas())


def sembrar(apps, app_label, model, old_name, verbose, assigned):
    """Tipo de contenido con sus permisos del nombre viejo (y los nuevos que Django ya habría creado)."""
    ContentType, Permission = apps.get_model('contenttypes', 'ContentType'), apps.get_model('auth', 'Permission')
    content_type, _ = ContentType.objects.get_or_create(app_label=app_label, model=model)
    for action in ('add', 'change', 'delete', 'view'):
        Permission.objects.get_or_create(
            content_type=content_type, codename=f'{action}_{old_name}', defaults={'name': f'Can {action} {old_name}'},
        )
    return {action: Permission.objects.get(content_type=content_type, codename=f'{action}_{old_name}') for action in assigned}


def test_los_permisos_viejos_pasan_a_los_nuevos_con_sus_usuarios_y_grupos(estado_previo):
    old = estado_previo
    User, Group = old.get_model('accounts', 'User'), old.get_model('auth', 'Group')
    asignados = sembrar(old, 'courses', 'course', 'subject', 'subject', ['add', 'view'])
    asignados_notas = sembrar(old, 'grades', 'activity', 'evaluation', 'evaluation', ['change'])
    user = User.objects.create(dni='u', username='u', email='u@t.test', role='professor')
    user.user_permissions.add(asignados['add'], asignados_notas['change'])
    grupo = Group.objects.create(name='Coordinación')
    grupo.permissions.add(asignados['view'])
    sin_permisos = User.objects.create(dni='v', username='v', email='v@t.test', role='professor')

    nuevo = migrar(hojas())
    Permission = nuevo.get_model('auth', 'Permission')
    user, grupo = nuevo.get_model('accounts', 'User').objects.get(pk=user.pk), nuevo.get_model('auth', 'Group').objects.get(pk=grupo.pk)

    assert not Permission.objects.filter(codename__regex=r'_(subject|evaluation)$').exists()
    assert set(user.user_permissions.values_list('codename', flat=True)) == {'add_course', 'change_activity'}
    assert set(grupo.permissions.values_list('codename', flat=True)) == {'view_course'}
    assert not nuevo.get_model('accounts', 'User').objects.get(pk=sin_permisos.pk).user_permissions.exists()
    # Un solo juego de permisos por modelo.
    for model in ('course', 'activity'):
        codenames = list(Permission.objects.filter(content_type__model=model).values_list('codename', flat=True))
        assert sorted(codenames) == sorted(f'{a}_{model}' for a in ('add', 'change', 'delete', 'view'))


def test_si_el_permiso_nuevo_ya_existe_no_se_duplica(estado_previo):
    old = estado_previo
    Permission, ContentType = old.get_model('auth', 'Permission'), old.get_model('contenttypes', 'ContentType')
    User = old.get_model('accounts', 'User')
    asignados = sembrar(old, 'courses', 'course', 'subject', 'subject', ['add'])
    nuevo_permiso, _ = Permission.objects.get_or_create(
        content_type=ContentType.objects.get(app_label='courses', model='course'), codename='add_course', defaults={'name': 'Can add course'},
    )
    user = User.objects.create(dni='u', username='u', email='u@t.test', role='professor')
    user.user_permissions.add(asignados['add'], nuevo_permiso)

    nuevo = migrar(hojas())
    assert nuevo.get_model('auth', 'Permission').objects.filter(codename='add_course').count() == 1
    assert list(nuevo.get_model('accounts', 'User').objects.get(pk=user.pk).user_permissions.values_list('codename', flat=True)) == ['add_course']


def test_en_una_base_nueva_no_hay_nada_que_mover(estado_previo):
    nuevo = migrar(hojas())
    assert not nuevo.get_model('auth', 'Permission').objects.filter(codename__regex=r'_(subject|evaluation)$').exists()
