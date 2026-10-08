import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """La columna ya fue llenada por organizations.0002; ahora es obligatoria."""

    dependencies = [
        ('organizations', '0002_backfill_organizaciones'),
        ('subjects', '0002_agregar_organizacion'),
    ]

    operations = [
        migrations.AlterField(
            model_name='subject',
            name='organization',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization'),
        ),
        migrations.AlterField(
            model_name='enrollment',
            name='organization',
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='organizations.organization'),
        ),
    ]
