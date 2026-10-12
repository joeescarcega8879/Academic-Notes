def active_organization(request):
    """Organización activa y rol del usuario en ella, para plantillas."""
    membership = getattr(request, 'membership', None)
    return {
        'organization': getattr(request, 'organization', None),
        'membership': membership,
        'memberships': getattr(request, 'memberships', []),
        'is_teacher': bool(membership and membership.is_teacher),
        'is_student': bool(membership and membership.is_student),
    }
