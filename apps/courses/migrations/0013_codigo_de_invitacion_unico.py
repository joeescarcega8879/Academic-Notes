from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: el código es único entre los grupos que lo tienen activo."""

    dependencies = [
        ('courses', '0012_codigos_para_grupos_existentes'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='course',
            constraint=models.UniqueConstraint(
                condition=models.Q(('invite_code', ''), _negated=True), fields=('invite_code',),
                name='unique_course_invite_code',
            ),
        ),
    ]
