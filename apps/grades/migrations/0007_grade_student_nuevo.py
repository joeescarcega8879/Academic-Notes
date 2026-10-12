import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1: columna nullable ``Grade.student_new`` hacia ``Student``."""

    dependencies = [
        ('courses', '0007_enrollment_apunta_a_student'),
        ('grades', '0006_renombrar_subject_a_course'),
    ]

    operations = [
        migrations.AddField(
            model_name='grade',
            name='student_new',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='courses.student'),
        ),
    ]
