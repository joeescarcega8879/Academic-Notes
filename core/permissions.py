"""Ayuda para migraciones de datos: permisos de modelos que cambiaron de nombre."""

from django.conf import settings

ACTIONS = ('add', 'change', 'delete', 'view')


def move_renamed_permissions(apps, app_label, model, old_name, verbose_name):
    """Pasa los permisos ``<acción>_<old_name>`` de un modelo renombrado a ``<acción>_<model>``.

    Django renombra el tipo de contenido al renombrar un modelo, pero deja los permisos con el código
    viejo («add_subject») y además crea los nuevos («add_course»): en el admin se ven dos juegos. Aquí se
    conservan los usuarios y grupos que tenían el permiso viejo y se borra el viejo. Sin el tipo de
    contenido (una base nueva) no hay nada que mover.
    """
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    User = apps.get_model(*settings.AUTH_USER_MODEL.split('.'))

    content_type = ContentType.objects.filter(app_label=app_label, model=model).first()
    if content_type is None:
        return
    user_links, group_links = User.user_permissions.through, Group.permissions.through
    for action in ACTIONS:
        old = Permission.objects.filter(content_type=content_type, codename=f'{action}_{old_name}').first()
        if old is None:
            continue
        new, _ = Permission.objects.get_or_create(
            content_type=content_type, codename=f'{action}_{model}', defaults={'name': f'Can {action} {verbose_name}'},
        )
        for link in user_links.objects.filter(permission_id=old.pk):
            user_links.objects.get_or_create(user_id=link.user_id, permission_id=new.pk)
        for link in group_links.objects.filter(permission_id=old.pk):
            group_links.objects.get_or_create(group_id=link.group_id, permission_id=new.pk)
        old.delete()
