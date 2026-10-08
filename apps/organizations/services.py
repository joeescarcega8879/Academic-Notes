"""Reglas de negocio de organizaciones y membresías."""

from .models import Membership, Organization


def teaching_organization(user):
    """Primera organización donde ``user`` da clase, o None."""
    membership = (
        Membership.objects
        .filter(user=user, role__in=Membership.TEACHING_ROLES)
        .select_related('organization')
        .order_by('id')
        .first()
    )
    return membership.organization if membership else None


def ensure_individual_organization(user):
    """Organización donde ``user`` da clase; si no tiene, crea la individual con su membresía de propietario."""
    existing = teaching_organization(user)
    if existing is not None:
        return existing

    organization = Organization.objects.create(
        name=user.get_full_name() or user.username or user.email,
        type=Organization.Type.INDIVIDUAL,
    )
    Membership.objects.create(user=user, organization=organization, role=Membership.Role.OWNER)
    return organization


def ensure_student_membership(user, organization):
    """Garantiza que ``user`` sea miembro de ``organization`` (sin degradar un rol existente)."""
    membership, _ = Membership.objects.get_or_create(
        user=user, organization=organization, defaults={'role': Membership.Role.STUDENT},
    )
    return membership
