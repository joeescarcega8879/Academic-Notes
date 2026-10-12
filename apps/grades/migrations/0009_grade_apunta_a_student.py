import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: ``Grade.student`` deja de apuntar a la cuenta y apunta a ``Student``."""

    dependencies = [
        ('grades', '0008_notas_a_student'),
    ]

    operations = [
        migrations.AlterUniqueTogether(name='grade', unique_together=set()),
        migrations.RemoveField(model_name='grade', name='student'),
        migrations.RenameField(model_name='grade', old_name='student_new', new_name='student'),
        migrations.AlterField(
            model_name='grade',
            name='student',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='grades', to='courses.student'),
        ),
        migrations.AlterUniqueTogether(name='grade', unique_together={('evaluation', 'student')}),
    ]
