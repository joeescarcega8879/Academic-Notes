from django.db import migrations


class Migration(migrations.Migration):
    """``Evaluation.subject`` pasa a ``course`` (el modelo ya se llama ``Course``)."""

    dependencies = [
        ('courses', '0004_renombrar_subject_a_course'),
        ('grades', '0005_organizacion_obligatoria'),
    ]

    operations = [
        migrations.RenameField(model_name='evaluation', old_name='subject', new_name='course'),
    ]
