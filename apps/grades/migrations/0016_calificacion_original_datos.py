from django.db import migrations, models


def forwards(apps, schema_editor):
    """Las calificaciones existentes no tienen penalización: lo que se guardó es lo que escribió el docente."""
    apps.get_model('grades', 'Grade').objects.filter(raw_score__isnull=True).update(raw_score=models.F('score'))


class Migration(migrations.Migration):
    dependencies = [
        ('grades', '0015_calificacion_original_y_bitacora'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
