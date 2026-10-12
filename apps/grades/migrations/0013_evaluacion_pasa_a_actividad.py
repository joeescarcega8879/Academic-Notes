import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """``Evaluation`` pasa a ``Activity`` y gana publicación, apertura, límite de entrega y política de tardías.

    Las actividades existentes quedan publicadas (ya las veían los alumnos); las nuevas nacen en borrador.
    """

    dependencies = [
        ('courses', '0013_codigo_de_invitacion_unico'),
        ('grades', '0012_criterio_obligatorio'),
    ]

    operations = [
        migrations.RenameModel(old_name='Evaluation', new_name='Activity'),
        migrations.RenameField(model_name='activity', old_name='description', new_name='instructions'),
        migrations.RenameField(model_name='grade', old_name='evaluation', new_name='activity'),
        migrations.AlterModelOptions(name='activity', options={'ordering': ['-date', 'title'], 'verbose_name_plural': 'activities'}),
        migrations.AlterField(
            model_name='activity',
            name='course',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='courses.course'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='criterion',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='activities', to='grades.evaluationcriterion', verbose_name='criterio'),
        ),
        migrations.AlterField(model_name='activity', name='title', field=models.CharField(max_length=255, verbose_name='título')),
        migrations.AlterField(model_name='activity', name='instructions', field=models.TextField(blank=True, verbose_name='instrucciones')),
        migrations.AlterField(
            model_name='activity',
            name='type',
            field=models.CharField(
                choices=[('quiz', 'Quiz'), ('exam', 'Examen'), ('homework', 'Tarea'), ('project', 'Proyecto'), ('participation', 'Participación')],
                default='homework', max_length=20, verbose_name='tipo',
            ),
        ),
        migrations.AlterField(
            model_name='activity',
            name='max_score',
            field=models.FloatField(default=10.0, validators=[django.core.validators.MinValueValidator(0.01)], verbose_name='puntos'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='weight',
            field=models.FloatField(default=1.0, validators=[django.core.validators.MinValueValidator(0)], verbose_name='peso'),
        ),
        migrations.AlterField(model_name='activity', name='date', field=models.DateField(blank=True, null=True, verbose_name='fecha')),
        # Las filas existentes quedan publicadas; después el valor por defecto pasa a borrador.
        migrations.AddField(model_name='activity', name='published', field=models.BooleanField(default=True, verbose_name='publicada')),
        migrations.AlterField(model_name='activity', name='published', field=models.BooleanField(default=False, verbose_name='publicada')),
        migrations.AddField(model_name='activity', name='opens_at', field=models.DateTimeField(blank=True, null=True, verbose_name='abre')),
        migrations.AddField(model_name='activity', name='due_at', field=models.DateTimeField(blank=True, null=True, verbose_name='fecha límite de entrega')),
        migrations.AddField(model_name='activity', name='allow_late', field=models.BooleanField(default=True, verbose_name='permite entregas tardías')),
        migrations.AddField(
            model_name='activity',
            name='late_penalty',
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5,
                validators=[django.core.validators.MinValueValidator(0), django.core.validators.MaxValueValidator(100)],
                verbose_name='penalización por entrega tardía (%)',
            ),
        ),
    ]
