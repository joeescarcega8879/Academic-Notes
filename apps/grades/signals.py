from decimal import Decimal

from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from apps.courses.models import Course
from apps.courses.signals import course_cloned

from .hooks import activity_cloned

from .models import Grade, GradeHistory, Submission
from .services.schemes import copy_scheme, create_default_scheme


@receiver(post_save, sender=Course)
def create_scheme_for_new_course(sender, instance, created, raw=False, **kwargs):
    """Todo grupo nuevo nace con el esquema de plantilla: nunca una pantalla vacía."""
    if created and not raw:
        create_default_scheme(instance)


# ── Bitácora de calificaciones ────────────────────────────────────────

def _snapshot(grade):
    return {
        'score': grade.score, 'feedback': grade.feedback, 'late_penalty': Decimal(str(grade.late_penalty)),
    }


def _record(grade, action, old, new):
    """Una fila de bitácora. ``old`` y ``new`` son instantáneas (o None si no aplica)."""
    GradeHistory.objects.create(
        organization_id=grade.organization_id,
        grade=None if action == GradeHistory.Action.DELETED else grade,
        activity=grade.activity, student=grade.student,
        activity_title=grade.activity.title, student_name=str(grade.student),
        action=action,
        old_score=old['score'] if old else None, new_score=new['score'] if new else None,
        old_feedback=old['feedback'] if old else '', new_feedback=new['feedback'] if new else '',
        late_penalty=(new or old)['late_penalty'],
        changed_by=getattr(grade, '_changed_by', None),
    )


@receiver(pre_save, sender=Grade)
def remember_previous_grade(sender, instance, raw=False, **kwargs):
    if raw:
        return
    previous = Grade.objects.filter(pk=instance.pk).first() if instance.pk else None
    instance._previous_snapshot = _snapshot(previous) if previous else None


@receiver(post_save, sender=Grade)
def audit_grade_saved(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    previous = getattr(instance, '_previous_snapshot', None)
    current = _snapshot(instance)
    if created or previous is None:
        _record(instance, GradeHistory.Action.CREATED, None, current)
    elif previous != current:  # guardar sin cambiar nada no ensucia la bitácora
        _record(instance, GradeHistory.Action.UPDATED, previous, current)


@receiver(post_delete, sender=Grade)
def audit_grade_deleted(sender, instance, **kwargs):
    # Si se borra la actividad o el grupo completos, también queda constancia de cada calificación.
    _record(instance, GradeHistory.Action.DELETED, _snapshot(instance), None)


@receiver(post_delete, sender=Submission)
def delete_submission_file(sender, instance, **kwargs):
    """Al borrar una entrega (o su actividad o grupo) se borra su archivo del almacenamiento."""
    if instance.file:
        instance.file.storage.delete(instance.file.name)


@receiver(course_cloned)
def copy_course_content(sender, source, clone, **kwargs):
    """Al duplicar un grupo se copian su esquema y sus evaluaciones (sin fechas ni calificaciones)."""
    criteria = copy_scheme(source, clone)
    for activity in source.activities.all():
        copy = clone.activities.create(
            title=activity.title, instructions=activity.instructions, type=activity.type,
            max_score=activity.max_score, weight=activity.weight, date=None,
            criterion=criteria[activity.criterion_id],
        )
        activity_cloned.send(sender=type(activity), source=activity, clone=copy)
