from django.db import migrations


def forwards(apps, schema_editor):
    """Cada grupo existente recibe un esquema equivalente al cálculo anterior.

    Un periodo y un criterio "General" con todas sus evaluaciones: el promedio sigue siendo la media
    ponderada por el peso de cada evaluación, así que ningún resultado cambia al migrar. El docente
    puede reorganizarlo después.
    """
    Course = apps.get_model('courses', 'Course')
    Scheme = apps.get_model('grades', 'EvaluationScheme')
    Period = apps.get_model('grades', 'EvaluationPeriod')
    Criterion = apps.get_model('grades', 'EvaluationCriterion')
    Evaluation = apps.get_model('grades', 'Evaluation')

    for course in Course.objects.all().iterator():
        scheme = Scheme.objects.create(course_id=course.pk, organization_id=course.organization_id)
        period = Period.objects.create(
            scheme_id=scheme.pk, organization_id=course.organization_id, name='Periodo único', weight=100, position=0,
        )
        criterion = Criterion.objects.create(
            period_id=period.pk, organization_id=course.organization_id, name='General', weight=100, position=0,
        )
        Evaluation.objects.filter(course_id=course.pk).update(criterion_id=criterion.pk)


def backwards(apps, schema_editor):
    apps.get_model('grades', 'Evaluation').objects.update(criterion=None)
    apps.get_model('grades', 'EvaluationScheme').objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ('grades', '0010_esquema_de_evaluacion'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
