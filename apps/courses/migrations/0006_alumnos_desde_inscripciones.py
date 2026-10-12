from django.db import migrations


def student_for(apps, user_id, organization_id, cache):
    """Ficha de ``Student`` del usuario en la organización; la crea con los datos de su cuenta."""
    key = (user_id, organization_id)
    if key not in cache:
        User = apps.get_model('accounts', 'User')
        StudentProfile = apps.get_model('accounts', 'StudentProfile')
        Student = apps.get_model('courses', 'Student')
        user = User.objects.get(pk=user_id)
        profile = StudentProfile.objects.filter(user_id=user_id).first()
        number = (profile.enrollment_number or '').strip() if profile else ''
        # La matrícula antigua era única global, así que no puede chocar dentro de una organización.
        cache[key] = Student.objects.create(
            organization_id=organization_id, user_id=user_id, student_number=number,
            first_name=user.first_name or user.username, last_name=user.last_name, email=user.email,
        ).pk
    return cache[key]


def forwards(apps, schema_editor):
    Enrollment = apps.get_model('courses', 'Enrollment')
    cache = {}
    for enrollment in Enrollment.objects.all().iterator():
        student_id = student_for(apps, enrollment.student_id, enrollment.organization_id, cache)
        Enrollment.objects.filter(pk=enrollment.pk).update(student_new_id=student_id)


def backwards(apps, schema_editor):
    apps.get_model('courses', 'Student').objects.all().delete()


class Migration(migrations.Migration):
    """Paso 2: un ``Student`` por (cuenta, organización) con inscripción, con su matrícula."""

    dependencies = [
        ('accounts', '0003_user_notifications_read_at'),
        ('courses', '0005_student'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
