from django.conf import settings
from django.db import models

from .managers import OrganizationManager


class Organization(models.Model):
    """Tenant. El docente individual es una organización de un solo miembro."""

    class Type(models.TextChoices):
        INDIVIDUAL = 'individual', 'Docente individual'
        INSTITUTION = 'institution', 'Institución'

    class Plan(models.TextChoices):
        FREE = 'free', 'Gratis'
        TEACHER = 'teacher', 'Docente'
        TEACHER_PLUS = 'teacher_plus', 'Docente Plus'
        BASIC = 'basic', 'Institución Básico'
        STANDARD = 'standard', 'Institución Estándar'
        ENTERPRISE = 'enterprise', 'Institución Enterprise'

    name = models.CharField(max_length=150)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.INDIVIDUAL)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Rol de un usuario dentro de una organización (un rol por organización)."""

    class Role(models.TextChoices):
        OWNER = 'owner', 'Propietario'
        ADMIN = 'admin', 'Administrador'
        COORDINATOR = 'coordinator', 'Coordinador'
        TEACHER = 'teacher', 'Docente'
        STUDENT = 'student', 'Alumno'
        PARENT = 'parent', 'Padre o tutor'

    # El propietario de una organización individual es quien da clase en ella.
    TEACHING_ROLES = (Role.OWNER, Role.TEACHER)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='memberships')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='memberships')
    role = models.CharField(max_length=20, choices=Role.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        constraints = [
            models.UniqueConstraint(fields=['user', 'organization'], name='unique_membership_per_organization'),
        ]

    def __str__(self):
        return f'{self.user} · {self.get_role_display()} en {self.organization}'

    @property
    def is_teacher(self):
        return self.role in self.TEACHING_ROLES


class TenantModel(models.Model):
    """Base de los modelos que pertenecen a una organización.

    ``organization`` es la columna que filtra ``for_organization``. Los modelos
    hijos la derivan del padre indicado en ``organization_source`` en cada
    ``save()``, de modo que nunca puede discrepar de él.
    """

    organization_source = None

    organization = models.ForeignKey(
        Organization, on_delete=models.PROTECT, related_name='+', editable=False,
    )

    objects = OrganizationManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.organization_source:
            parent = getattr(self, self.organization_source)
            self.organization_id = parent.organization_id
        super().save(*args, **kwargs)
