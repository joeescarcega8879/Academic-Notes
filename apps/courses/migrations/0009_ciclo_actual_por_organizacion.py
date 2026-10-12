import datetime

from django.db import migrations


def forwards(apps, schema_editor):
    """Cada organización con grupos recibe el ciclo agosto–julio en curso, marcado como actual."""
    AcademicYear = apps.get_model('courses', 'AcademicYear')
    Course = apps.get_model('courses', 'Course')

    today = datetime.date.today()
    start_year = today.year if today.month >= 8 else today.year - 1
    name = f'{start_year}–{start_year + 1}'

    # order_by() vacío: el ordering del modelo (name) rompería el DISTINCT y repetiría organizaciones.
    for organization_id in Course.objects.order_by().values_list('organization_id', flat=True).distinct():
        year = AcademicYear.objects.create(
            organization_id=organization_id, name=name, is_current=True,
            start_date=datetime.date(start_year, 8, 1), end_date=datetime.date(start_year + 1, 7, 31),
        )
        Course.objects.filter(organization_id=organization_id).update(academic_year=year)


def backwards(apps, schema_editor):
    apps.get_model('courses', 'Course').objects.update(academic_year=None)
    apps.get_model('courses', 'AcademicYear').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('courses', '0008_ciclo_escolar'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
