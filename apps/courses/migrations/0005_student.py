import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1: tabla ``Student`` y columna nullable ``Enrollment.student_new``."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organizations', '0002_backfill_organizaciones'),
        ('courses', '0004_renombrar_subject_a_course'),
    ]

    operations = [
        migrations.CreateModel(
            name='Student',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('student_number', models.CharField(blank=True, max_length=30, verbose_name='matrícula')),
                ('first_name', models.CharField(max_length=150, verbose_name='nombre(s)')),
                ('last_name', models.CharField(blank=True, max_length=150, verbose_name='apellidos')),
                ('email', models.EmailField(blank=True, max_length=254, verbose_name='correo')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='student_records', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['last_name', 'first_name'],
            },
        ),
        migrations.AddConstraint(
            model_name='student',
            constraint=models.UniqueConstraint(
                condition=models.Q(('student_number', ''), _negated=True),
                fields=('organization', 'student_number'), name='unique_student_number_per_organization',
            ),
        ),
        migrations.AddConstraint(
            model_name='student',
            constraint=models.UniqueConstraint(
                condition=models.Q(('user__isnull', False)),
                fields=('organization', 'user'), name='unique_student_user_per_organization',
            ),
        ),
        migrations.AddField(
            model_name='enrollment',
            name='student_new',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='courses.student'),
        ),
    ]
