from django.db import migrations


def forwards(apps, schema_editor):
    """Enlaza cada nota con la ficha ``Student`` de su alumno en la organización de la nota.

    ``courses.0006`` ya creó las fichas de quienes tienen inscripción; una nota de alguien
    sin inscripción (posible desde el admin) recibe una ficha nueva con los datos de su cuenta.
    """
    Grade = apps.get_model('grades', 'Grade')
    Student = apps.get_model('courses', 'Student')
    User = apps.get_model('accounts', 'User')
    StudentProfile = apps.get_model('accounts', 'StudentProfile')

    cache = {}
    for grade in Grade.objects.all().iterator():
        key = (grade.student_id, grade.organization_id)
        if key not in cache:
            existing = Student.objects.filter(user_id=grade.student_id, organization_id=grade.organization_id).first()
            if existing is None:
                user = User.objects.get(pk=grade.student_id)
                profile = StudentProfile.objects.filter(user_id=user.pk).first()
                number = (profile.enrollment_number or '').strip() if profile else ''
                existing = Student.objects.create(
                    organization_id=grade.organization_id, user_id=user.pk, student_number=number,
                    first_name=user.first_name or user.username, last_name=user.last_name, email=user.email,
                )
            cache[key] = existing.pk
        Grade.objects.filter(pk=grade.pk).update(student_new_id=cache[key])


class Migration(migrations.Migration):
    """Paso 2: llena ``Grade.student_new``."""

    dependencies = [
        ('accounts', '0003_user_notifications_read_at'),
        ('courses', '0007_enrollment_apunta_a_student'),
        ('grades', '0007_grade_student_nuevo'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
