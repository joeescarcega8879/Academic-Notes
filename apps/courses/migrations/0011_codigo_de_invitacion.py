from django.db import migrations, models


class Migration(migrations.Migration):
    """Paso 1: columna ``Course.invite_code`` (vacía = invitaciones desactivadas)."""

    dependencies = [
        ('courses', '0010_ciclo_obligatorio_y_codigo_por_ciclo'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='invite_code',
            field=models.CharField(blank=True, default='', max_length=12),
        ),
    ]
