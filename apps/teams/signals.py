from django.db.models.signals import post_delete
from django.dispatch import receiver

from apps.courses.models import Enrollment

from .models import TeamMember
from .services.teams import drop_member


@receiver(post_delete, sender=Enrollment)
def leave_teams_when_unenrolled(sender, instance, **kwargs):
    """Quien sale del grupo sale también de sus equipos (y pierde su copia de la entrega del equipo)."""
    members = TeamMember.objects.filter(activity__course_id=instance.course_id, student_id=instance.student_id)
    for member in members.select_related('team'):
        drop_member(member)
