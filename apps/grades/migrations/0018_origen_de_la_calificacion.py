from django.db import migrations, models


class Migration(migrations.Migration):
    """``Grade.source``: las calificaciones existentes las fijó el docente."""

    dependencies = [
        ('grades', '0017_calificacion_original_obligatoria'),
    ]

    operations = [
        migrations.AddField(
            model_name='grade',
            name='source',
            field=models.CharField(choices=[('manual', 'Docente'), ('quiz', 'Quiz (automática)')], default='manual', max_length=10),
        ),
    ]
