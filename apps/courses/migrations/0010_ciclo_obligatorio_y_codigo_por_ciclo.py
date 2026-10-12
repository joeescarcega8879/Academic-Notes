import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: el ciclo es obligatorio y el código deja de ser único global (ahora lo es por ciclo)."""

    dependencies = [
        ('courses', '0009_ciclo_actual_por_organizacion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='course',
            name='academic_year',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='courses', to='courses.academicyear', verbose_name='ciclo'),
        ),
        migrations.AlterField(
            model_name='course',
            name='code',
            field=models.CharField(max_length=20),
        ),
        migrations.AddConstraint(
            model_name='course',
            constraint=models.UniqueConstraint(fields=('organization', 'academic_year', 'code'), name='unique_course_code_per_year'),
        ),
    ]
