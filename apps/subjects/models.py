from django.db import models
from django.conf import settings

from apps.organizations.models import Organization, TenantModel
from apps.organizations.services import ensure_individual_organization, ensure_student_membership


class Subject(TenantModel):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    schedule = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=7, default='#1e3a5f')  # Hex color code

    # A diferencia de sus hijos, la materia sí elige su organización (en el admin).
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')

    professor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subjects', limit_choices_to={'role': 'professor'})

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        # Sin organización explícita, la materia pertenece a donde da clase su profesor.
        if self.organization_id is None:
            self.organization = ensure_individual_organization(self.professor)
        super().save(*args, **kwargs)


class Enrollment(TenantModel):
    organization_source = 'subject'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='enrollments', limit_choices_to={'role': 'student'})
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'subject')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f"{self.student.username} enrolled in {self.subject.name}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Inscribirse a una materia hace al alumno miembro de su organización.
        ensure_student_membership(self.student, self.subject.organization)
