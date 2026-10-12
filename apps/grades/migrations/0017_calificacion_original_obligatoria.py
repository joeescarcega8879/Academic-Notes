import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: toda calificación guarda lo que escribió el docente."""

    dependencies = [
        ('grades', '0016_calificacion_original_datos'),
    ]

    operations = [
        migrations.AlterField(
            model_name='grade',
            name='raw_score',
            field=models.FloatField(validators=[django.core.validators.MinValueValidator(0)]),
        ),
    ]
