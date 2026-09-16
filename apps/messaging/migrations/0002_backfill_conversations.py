from django.db import migrations


def create_conversations(apps, schema_editor):
    Enrollment = apps.get_model('subjects', 'Enrollment')
    Conversation = apps.get_model('messaging', 'Conversation')
    for enrollment in Enrollment.objects.all().iterator():
        Conversation.objects.get_or_create(
            subject_id=enrollment.subject_id,
            student_id=enrollment.student_id,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('messaging', '0001_initial'),
        ('subjects', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(create_conversations, migrations.RunPython.noop),
    ]
