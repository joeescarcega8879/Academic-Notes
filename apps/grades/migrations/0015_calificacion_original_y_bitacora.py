import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1: ``Grade.raw_score`` (nullable por ahora), ``Grade.late_penalty`` y la bitácora ``GradeHistory``."""

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('courses', '0013_codigo_de_invitacion_unico'),
        ('organizations', '0002_backfill_organizaciones'),
        ('grades', '0014_entregas'),
    ]

    operations = [
        migrations.AddField(
            model_name='grade',
            name='raw_score',
            field=models.FloatField(null=True, validators=[django.core.validators.MinValueValidator(0)]),
        ),
        migrations.AddField(
            model_name='grade',
            name='late_penalty',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.CreateModel(
            name='GradeHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('activity_title', models.CharField(max_length=255)),
                ('student_name', models.CharField(max_length=300)),
                ('action', models.CharField(choices=[('created', 'Calificó'), ('updated', 'Cambió la calificación'), ('deleted', 'Eliminó la calificación')], max_length=10)),
                ('old_score', models.FloatField(blank=True, null=True)),
                ('new_score', models.FloatField(blank=True, null=True)),
                ('old_feedback', models.TextField(blank=True)),
                ('new_feedback', models.TextField(blank=True)),
                ('late_penalty', models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ('changed_at', models.DateTimeField(auto_now_add=True)),
                ('activity', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grade_history', to='grades.activity')),
                ('changed_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('grade', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='history', to='grades.grade')),
                ('organization', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('student', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='grade_history', to='courses.student')),
            ],
            options={
                'verbose_name_plural': 'grade history',
                'ordering': ['-changed_at', '-id'],
            },
        ),
    ]
