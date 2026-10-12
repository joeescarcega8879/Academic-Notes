from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """``Subject`` pasa a ``Course`` (el grupo de un docente); ``Enrollment.subject`` a ``course``."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('courses', '0003_organizacion_obligatoria'),
    ]

    operations = [
        migrations.RenameModel(old_name='Subject', new_name='Course'),
        migrations.RenameField(model_name='enrollment', old_name='subject', new_name='course'),
        migrations.AlterField(
            model_name='course',
            name='professor',
            field=models.ForeignKey(
                limit_choices_to={'role': 'professor'}, on_delete=django.db.models.deletion.CASCADE,
                related_name='courses', to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
