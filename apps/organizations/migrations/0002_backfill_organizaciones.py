"""Migración de datos: cada profesor existente obtiene su organización individual.

- Cada materia pasa a la organización de su profesor, y sus inscripciones,
  evaluaciones, calificaciones, conversaciones y mensajes a la de la materia.
- Cada alumno se hace miembro (rol alumno) de las organizaciones en las que
  está inscrito. Un alumno sin inscripciones no recibe organización.

Es idempotente: se puede volver a ejecutar sin duplicar organizaciones.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Organization = apps.get_model('organizations', 'Organization')
    Membership = apps.get_model('organizations', 'Membership')
    User = apps.get_model('accounts', 'User')
    Subject = apps.get_model('subjects', 'Subject')
    Enrollment = apps.get_model('subjects', 'Enrollment')
    Evaluation = apps.get_model('grades', 'Evaluation')
    Grade = apps.get_model('grades', 'Grade')
    Conversation = apps.get_model('messaging', 'Conversation')
    Message = apps.get_model('messaging', 'Message')

    org_by_user = {}

    def organization_for(user_id):
        """Organización donde da clase el usuario; la crea (individual) si no existe."""
        if user_id in org_by_user:
            return org_by_user[user_id]
        membership = (
            Membership.objects
            .filter(user_id=user_id, role__in=['owner', 'teacher'])
            .order_by('id')
            .first()
        )
        if membership:
            org_id = membership.organization_id
        else:
            user = User.objects.get(pk=user_id)
            name = ('%s %s' % (user.first_name, user.last_name)).strip() or user.username or user.email
            org = Organization.objects.create(name=name, type='individual', plan='free')
            Membership.objects.create(user_id=user_id, organization_id=org.pk, role='owner')
            org_id = org.pk
        org_by_user[user_id] = org_id
        return org_id

    # Todo profesor tiene organización, aunque aún no tenga materias.
    for user_id in User.objects.filter(role='professor').order_by('id').values_list('pk', flat=True):
        organization_for(user_id)

    for subject in Subject.objects.filter(organization__isnull=True).iterator():
        org_id = organization_for(subject.professor_id)
        Subject.objects.filter(pk=subject.pk).update(organization_id=org_id)
        Enrollment.objects.filter(subject_id=subject.pk).update(organization_id=org_id)
        Evaluation.objects.filter(subject_id=subject.pk).update(organization_id=org_id)
        Grade.objects.filter(evaluation__subject_id=subject.pk).update(organization_id=org_id)
        Conversation.objects.filter(subject_id=subject.pk).update(organization_id=org_id)
        Message.objects.filter(conversation__subject_id=subject.pk).update(organization_id=org_id)

    pairs = Enrollment.objects.values_list('student_id', 'organization_id').distinct()
    for student_id, org_id in pairs:
        Membership.objects.get_or_create(
            user_id=student_id, organization_id=org_id, defaults={'role': 'student'},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0001_initial'),
        ('accounts', '0003_user_notifications_read_at'),
        ('subjects', '0002_agregar_organizacion'),
        ('grades', '0004_agregar_organizacion'),
        ('messaging', '0003_agregar_organizacion'),
    ]

    operations = [
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
