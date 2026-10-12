import secrets

from django.db import migrations

# Mismo alfabeto que courses.models.INVITE_ALPHABET (sin 0/O ni 1/I/L). Se copia para que la migración
# no dependa del código actual.
ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'


def forwards(apps, schema_editor):
    Course = apps.get_model('courses', 'Course')
    used = set(Course.objects.exclude(invite_code='').values_list('invite_code', flat=True))
    for course in Course.objects.filter(invite_code='').order_by('pk'):
        code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        while code in used:
            code = ''.join(secrets.choice(ALPHABET) for _ in range(8))
        used.add(code)
        Course.objects.filter(pk=course.pk).update(invite_code=code)


class Migration(migrations.Migration):
    """Paso 2: cada grupo existente recibe su código."""

    dependencies = [
        ('courses', '0011_codigo_de_invitacion'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
