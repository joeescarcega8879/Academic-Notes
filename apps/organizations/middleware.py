from .models import Membership

SESSION_KEY = 'organization_id'


class OrganizationMiddleware:
    """Expone ``request.organization`` y ``request.membership`` (la organización activa).

    La activa es la guardada en sesión si el usuario sigue siendo miembro; si no,
    la primera membresía. Sin sesión o sin membresías ambas son None.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membership = None
        request.organization = None

        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            memberships = list(
                Membership.objects
                .filter(user=user, organization__is_active=True)
                .select_related('organization')
                .order_by('id')
            )
            wanted = request.session.get(SESSION_KEY)
            request.membership = next(
                (m for m in memberships if m.organization_id == wanted),
                memberships[0] if memberships else None,
            )
            if request.membership:
                request.organization = request.membership.organization

        return self.get_response(request)
