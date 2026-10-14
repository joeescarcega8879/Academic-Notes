from django.conf import settings
from django.db import migrations

from core.permissions import move_renamed_permissions


def forwards(apps, schema_editor):
    move_renamed_permissions(apps, 'courses', 'course', 'subject', 'course')


class Migration(migrations.Migration):
    """Los permisos de «Materia» (add_subject…) pasan a los de «Grupo» (add_course…)."""

    dependencies = [
        ('courses', '0013_codigo_de_invitacion_unico'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
