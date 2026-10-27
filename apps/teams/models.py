from django.db import models

from apps.organizations.models import TenantModel


class Team(TenantModel):
    """Un equipo de un proyecto que se entrega por equipos. Los equipos son de la actividad, no del grupo:
    cada proyecto puede formarlos distinto."""

    organization_source = 'activity'

    activity = models.ForeignKey('grades.Activity', on_delete=models.CASCADE, related_name='teams')
    name = models.CharField('nombre', max_length=80)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [models.UniqueConstraint(fields=['activity', 'name'], name='unique_team_name_per_activity')]

    def __str__(self):
        return self.name


class TeamMember(TenantModel):
    """Un alumno en un equipo. Un alumno está en un solo equipo por proyecto."""

    organization_source = 'team'

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='members')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='team_memberships')
    # Copia del proyecto del equipo: permite que la base garantice «un equipo por alumno y proyecto».
    activity = models.ForeignKey('grades.Activity', on_delete=models.CASCADE, related_name='+', editable=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['activity', 'student'], name='unique_team_member_per_activity')]

    def __str__(self):
        return f'{self.student} · {self.team}'

    def save(self, *args, **kwargs):
        self.activity_id = self.team.activity_id
        super().save(*args, **kwargs)
