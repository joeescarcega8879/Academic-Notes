import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

WEIGHT_VALIDATORS = [django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)]


class Migration(migrations.Migration):
    """Paso 1: esquema, periodos y criterios; ``Evaluation.criterion`` nullable por ahora."""

    dependencies = [
        ('organizations', '0002_backfill_organizaciones'),
        ('courses', '0013_codigo_de_invitacion_unico'),
        ('grades', '0009_grade_apunta_a_student'),
    ]

    operations = [
        migrations.CreateModel(
            name='EvaluationScheme',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scale_max', models.PositiveSmallIntegerField(default=10, help_text='La calificación máxima posible: 10, 100, 5…', validators=[django.core.validators.MinValueValidator(1)], verbose_name='escala máxima')),
                ('pass_mark', models.DecimalField(decimal_places=2, default=6, help_text='Se compara con la calificación ya redondeada.', max_digits=6, validators=[django.core.validators.MinValueValidator(0)], verbose_name='mínimo aprobatorio')),
                ('rounding_decimals', models.PositiveSmallIntegerField(choices=[(0, 'Enteros'), (1, '1 decimal'), (2, '2 decimales')], default=2, verbose_name='redondeo')),
                ('course', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='scheme', to='courses.course')),
                ('organization', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
            ],
        ),
        migrations.AddConstraint(
            model_name='evaluationscheme',
            constraint=models.CheckConstraint(condition=models.Q(('pass_mark__lte', models.F('scale_max'))), name='scheme_pass_mark_within_scale'),
        ),
        migrations.CreateModel(
            name='EvaluationPeriod',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='nombre')),
                ('weight', models.DecimalField(decimal_places=2, default=100, max_digits=5, validators=WEIGHT_VALIDATORS, verbose_name='peso (%)')),
                ('position', models.PositiveSmallIntegerField(default=0, verbose_name='orden')),
                ('organization', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('scheme', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='periods', to='grades.evaluationscheme')),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),
        migrations.CreateModel(
            name='EvaluationCriterion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=80, verbose_name='nombre')),
                ('weight', models.DecimalField(decimal_places=2, default=100, max_digits=5, validators=WEIGHT_VALIDATORS, verbose_name='peso (%)')),
                ('default_type', models.CharField(blank=True, max_length=20, verbose_name='tipo de evaluación')),
                ('position', models.PositiveSmallIntegerField(default=0, verbose_name='orden')),
                ('organization', models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization')),
                ('period', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='criteria', to='grades.evaluationperiod')),
            ],
            options={
                'ordering': ['position', 'id'],
            },
        ),
        migrations.AddField(
            model_name='evaluation',
            name='criterion',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='evaluations', to='grades.evaluationcriterion', verbose_name='criterio'),
        ),
    ]
