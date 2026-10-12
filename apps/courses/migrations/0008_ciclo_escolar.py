import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1: ``AcademicYear``; ``Course`` gana ciclo (nullable por ahora), estado y fecha de archivado."""

    dependencies = [
        ('organizations', '0002_backfill_organizaciones'),
        ('courses', '0007_enrollment_apunta_a_student'),
    ]

    operations = [
        migrations.CreateModel(
            name='AcademicYear',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=60, verbose_name='nombre')),
                ('start_date', models.DateField(verbose_name='inicio')),
                ('end_date', models.DateField(verbose_name='fin')),
                ('is_current', models.BooleanField(default=False, verbose_name='ciclo actual')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
            ],
            options={
                'ordering': ['-start_date', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='academicyear',
            constraint=models.UniqueConstraint(fields=('organization', 'name'), name='unique_academic_year_name_per_organization'),
        ),
        migrations.AddConstraint(
            model_name='academicyear',
            constraint=models.UniqueConstraint(
                condition=models.Q(('is_current', True)), fields=('organization',),
                name='unique_current_academic_year_per_organization',
            ),
        ),
        migrations.AddConstraint(
            model_name='academicyear',
            constraint=models.CheckConstraint(
                condition=models.Q(('end_date__gte', models.F('start_date'))), name='academic_year_end_not_before_start',
            ),
        ),
        migrations.AddField(
            model_name='course',
            name='academic_year',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='courses', to='courses.academicyear', verbose_name='ciclo'),
        ),
        migrations.AddField(
            model_name='course',
            name='status',
            field=models.CharField(choices=[('active', 'Activo'), ('archived', 'Archivado')], default='active', max_length=10),
        ),
        migrations.AddField(
            model_name='course',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
