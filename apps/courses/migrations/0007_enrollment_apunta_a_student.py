import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: ``Enrollment.student`` deja de apuntar a la cuenta y apunta a ``Student``."""

    dependencies = [
        ('courses', '0006_alumnos_desde_inscripciones'),
    ]

    operations = [
        migrations.AlterUniqueTogether(name='enrollment', unique_together=set()),
        migrations.RemoveField(model_name='enrollment', name='student'),
        migrations.RenameField(model_name='enrollment', old_name='student_new', new_name='student'),
        migrations.AlterField(
            model_name='enrollment',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='enrollments', to='courses.student'),
        ),
        migrations.AlterUniqueTogether(name='enrollment', unique_together={('student', 'course')}),
    ]
