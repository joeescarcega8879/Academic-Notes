from django.db import migrations


class Migration(migrations.Migration):
    """``Conversation.subject`` pasa a ``course``; ``unique_together`` se actualiza solo."""

    dependencies = [
        ('courses', '0004_renombrar_subject_a_course'),
        ('messaging', '0004_organizacion_obligatoria'),
    ]

    operations = [
        migrations.RenameField(model_name='conversation', old_name='subject', new_name='course'),
    ]
