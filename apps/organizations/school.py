"""La escuela y su equipo: la dirección invita a docentes por correo y ellos se suman con su cuenta.

Solo la dirección (propietario, administrador o coordinador de una institución) invita; un docente no invita a otros.
Quien acepta conserva su cuenta, su espacio personal y todo lo que tiene en él: la escuela se suma a sus espacios.
"""

import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core import throttle

from .models import Membership, OrganizationInvitation

MAX_OPEN_INVITATIONS = 100
EMAIL_MAX = 254
# Frenos contra el abuso: el correo sale de nuestro dominio, así que no se deja a nadie usarlo para llenar buzones.
INVITES_PER_HOUR = 30
RESENDS_PER_DAY = 3


def _direction_membership(organization, user):
    membership = Membership.objects.filter(user=user, organization=organization).select_related('organization').first()
    if membership is None or not membership.is_direction:
        raise ValidationError('Solo la dirección de la escuela puede hacer esto.')
    return membership


def clean_email(raw):
    """El correo en minúsculas y sin espacios; lanza ``ValidationError`` si no es un correo."""
    email = (raw or '').strip().lower()
    if not email or len(email) > EMAIL_MAX:
        raise ValidationError('Escribe el correo del docente.')
    try:
        validate_email(email)
    except ValidationError:
        raise ValidationError('Ese correo no es válido.') from None
    return email


def accept_path(invitation):
    return reverse('organizations:school_accept', args=[invitation.token])


def _send(invitation):
    from .tasks import send_teacher_invitation_email

    transaction.on_commit(lambda: send_teacher_invitation_email.delay(invitation.pk))


@transaction.atomic
def invite_teacher(organization, email, *, by):
    """Invita a ``email`` a la escuela como docente y le manda el correo. Lanza ``ValidationError`` con el motivo."""
    _direction_membership(organization, by)
    email = clean_email(email)
    if not throttle.allow('school-invite', organization.pk, limit=INVITES_PER_HOUR, window=3600):
        raise ValidationError('Has enviado muchas invitaciones seguidas. Espera un rato e inténtalo de nuevo.')
    if Membership.objects.filter(organization=organization, user__email__iexact=email).exists():
        raise ValidationError('Esa persona ya es parte de la escuela.')

    now = timezone.now()
    opened = OrganizationInvitation.objects.filter(organization=organization, accepted_at__isnull=True, revoked_at__isnull=True)
    opened.filter(email=email, expires_at__lte=now).update(revoked_at=now)  # una vencida no estorba a la nueva
    if opened.filter(email=email).exists():
        raise ValidationError('Ya hay una invitación pendiente para ese correo: puedes reenviarla desde la lista.')
    if opened.filter(expires_at__gt=now).count() >= MAX_OPEN_INVITATIONS:
        raise ValidationError(f'Hay {MAX_OPEN_INVITATIONS} invitaciones pendientes: retira alguna antes de enviar más.')

    invitation = OrganizationInvitation.objects.create(
        organization=organization, email=email, invited_by=by, token=secrets.token_urlsafe(32),
        expires_at=now + timedelta(days=OrganizationInvitation.VALID_DAYS),
    )
    _send(invitation)
    return invitation


@transaction.atomic
def resend(invitation, *, by):
    """Vuelve a mandar el correo de una invitación pendiente y le da otros 14 días."""
    _direction_membership(invitation.organization, by)
    if not invitation.is_open:
        raise ValidationError('Esa invitación ya se usó o se retiró.')
    if not throttle.allow('school-resend', invitation.pk, limit=RESENDS_PER_DAY, window=86400):
        raise ValidationError('Ya reenviaste esta invitación varias veces hoy. Inténtalo mañana.')
    invitation.expires_at = timezone.now() + timedelta(days=OrganizationInvitation.VALID_DAYS)
    invitation.save(update_fields=['expires_at'])
    _send(invitation)
    return invitation


@transaction.atomic
def revoke(invitation, *, by):
    """Retira una invitación pendiente: su enlace deja de servir."""
    _direction_membership(invitation.organization, by)
    if not invitation.is_open:
        raise ValidationError('Esa invitación ya se usó o se retiró.')
    invitation.revoked_at = timezone.now()
    invitation.save(update_fields=['revoked_at'])
    return invitation


def check_open(invitation):
    """Por qué la invitación ya no sirve (usada, retirada, vencida o de una escuela inactiva); si sirve, no hace nada."""
    if invitation.accepted_at is not None:
        raise ValidationError('Esta invitación ya se usó.')
    if invitation.revoked_at is not None:
        raise ValidationError('La escuela retiró esta invitación.')
    if invitation.is_expired:
        raise ValidationError('Esta invitación venció. Pide a la dirección de la escuela que te envíe otra.')
    if not invitation.organization.is_active:
        raise ValidationError('Esta escuela ya no está activa.')


def check_acceptable(invitation, user):
    """Por qué ``user`` no puede aceptar ``invitation`` (``ValidationError``); si puede, no hace nada."""
    check_open(invitation)
    if user.email.strip().lower() != invitation.email:
        raise ValidationError(f'Esta invitación es para {invitation.email}. Inicia sesión con una cuenta con ese correo.')
    if user.role != 'professor':
        raise ValidationError('Tu cuenta es de alumno. Para entrar como docente hace falta una cuenta de docente.')


@transaction.atomic
def accept(invitation, user):
    """``user`` se suma a la escuela como docente. Devuelve su ``Membership``. Lanza ``ValidationError`` con el motivo.

    No toca nada más: su espacio personal, sus grupos y sus alumnos siguen donde estaban.
    """
    invitation = OrganizationInvitation.objects.select_for_update().select_related('organization').get(pk=invitation.pk)
    check_acceptable(invitation, user)
    membership, created = Membership.objects.get_or_create(
        user=user, organization=invitation.organization, defaults={'role': Membership.Role.TEACHER},
    )
    if not created and membership.role not in Membership.TEACHING_ROLES + Membership.DIRECTION_ROLES:
        raise ValidationError('Ya tienes otro rol en esta escuela.')
    invitation.accepted_at, invitation.accepted_by = timezone.now(), user
    invitation.save(update_fields=['accepted_at', 'accepted_by'])
    return membership


def team(organization):
    """Quienes dirigen y dan clase en la escuela, con cuántos grupos tiene cada docente en ella."""
    from apps.courses.models import Course

    groups = {}
    for professor_id in Course.objects.filter(organization=organization, status=Course.Status.ACTIVE).values_list('professor_id', flat=True):
        groups[professor_id] = groups.get(professor_id, 0) + 1
    members = Membership.objects.filter(
        organization=organization, role__in=Membership.TEACHING_ROLES + Membership.DIRECTION_ROLES,
    ).select_related('user').order_by('user__last_name', 'user__first_name', 'id')
    return [{'membership': member, 'groups': groups.get(member.user_id, 0)} for member in members]


def open_invitations(organization):
    """Las invitaciones pendientes (vencidas incluidas, para poder reenviarlas), las más recientes primero."""
    return OrganizationInvitation.objects.for_organization(organization).filter(
        accepted_at__isnull=True, revoked_at__isnull=True,
    ).select_related('invited_by')
