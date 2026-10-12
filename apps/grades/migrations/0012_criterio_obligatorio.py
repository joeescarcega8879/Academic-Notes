import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 3: toda evaluación tiene criterio."""

    dependencies = [
        ('grades', '0011_esquemas_para_grupos_existentes'),
    ]

    operations = [
        migrations.AlterField(
            model_name='evaluation',
            name='criterion',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='evaluations', to='grades.evaluationcriterion', verbose_name='criterio'),
        ),
    ]
