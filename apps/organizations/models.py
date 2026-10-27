from django.conf import settings
from django.db import models
from django.utils import timezone

from .managers import OrganizationManager


class Organization(models.Model):
    """Tenant. El docente individual es una organización de un solo miembro."""

    class Type(models.TextChoices):
        INDIVIDUAL = 'individual', 'Docente individual'
        INSTITUTION = 'institution', 'Institución'

    class Plan(models.TextChoices):
        FREE = 'free', 'Gratis'
        TEACHER = 'teacher', 'Pro'
        TEACHER_PLUS = 'teacher_plus', 'Plus'
        BASIC = 'basic', 'Institución Básico'
        STANDARD = 'standard', 'Institución Estándar'
        ENTERPRISE = 'enterprise', 'Institución Enterprise'

    name = models.CharField(max_length=150)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.INDIVIDUAL)
    plan = models.CharField(max_length=20, choices=Plan.choices, default=Plan.FREE)
    is_active = models.BooleanField(default=True)
    # Interruptor de la IA asistida: apagado por omisión; solo lo enciende el propietario. Sin él no se envía nada a la IA.
    ai_enabled = models.BooleanField('IA asistida', default=False, db_default=False)
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
    # La dirección de una escuela: quien invita docentes y administra su equipo.
    DIRECTION_ROLES = (Role.OWNER, Role.ADMIN, Role.COORDINATOR)

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

    @property
    def is_student(self):
        return self.role == self.Role.STUDENT

    @property
    def is_direction(self):
        """Dirección de una institución (el propietario de un docente individual no es «dirección»)."""
        return self.role in self.DIRECTION_ROLES and self.organization.type == Organization.Type.INSTITUTION


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


class OrganizationInvitation(TenantModel):
    """Invitación de la dirección de una escuela a un docente, por su correo exacto.

    Es de un solo uso y vence a los 14 días. Quien acepta conserva su cuenta y su espacio personal: la escuela se suma
    a sus espacios con el rol de docente.
    """

    VALID_DAYS = 14

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')
    email = models.EmailField('correo')
    token = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            # Una sola invitación abierta por correo y escuela (una vencida se retira antes de invitar otra vez).
            models.UniqueConstraint(
                fields=['organization', 'email'], condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name='unique_open_invitation_per_email',
            ),
        ]

    def __str__(self):
        return f'{self.email} → {self.organization}'

    @property
    def is_open(self):
        """Sigue pendiente: ni aceptada ni retirada (puede estar vencida)."""
        return self.accepted_at is None and self.revoked_at is None

    @property
    def is_expired(self):
        return self.is_open and self.expires_at <= timezone.now()

    @property
    def is_usable(self):
        return self.is_open and self.expires_at > timezone.now()

