from django.db import migrations, models


class Migration(migrations.Migration):
    """La matrícula pasa a ``courses.Student`` (única por organización); este campo queda deprecado."""

    dependencies = [
        ('accounts', '0003_user_notifications_read_at'),
    ]

    operations = [
        migrations.AlterField(
            model_name='studentprofile',
            name='enrollment_number',
            field=models.CharField(
                blank=True, default='', max_length=20,
                help_text='Deprecado: la matrícula vive en courses.Student.student_number.',
            ),
        ),
    ]
