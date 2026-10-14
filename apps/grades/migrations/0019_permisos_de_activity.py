from django.conf import settings
from django.db import migrations

from core.permissions import move_renamed_permissions


def forwards(apps, schema_editor):
    move_renamed_permissions(apps, 'grades', 'activity', 'evaluation', 'activity')


class Migration(migrations.Migration):
    """Los permisos de «Evaluación» (add_evaluation…) pasan a los de «Actividad» (add_activity…)."""

    dependencies = [
        ('grades', '0018_origen_de_la_calificacion'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
