from .services import SESSION_KEY, active_memberships, pick_membership


class OrganizationMiddleware:
    """Expone la organización activa: ``request.organization``, ``request.membership``
    y ``request.memberships`` (todas las del usuario, para el selector).

    La activa es la guardada en sesión si el usuario sigue siendo miembro; si no,
    la primera membresía. Sin sesión o sin membresías quedan en None / [].
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membership = None
        request.organization = None
        request.memberships = []

        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            request.memberships = active_memberships(user)
            request.membership = pick_membership(request.memberships, request.session.get(SESSION_KEY))
            if request.membership:
                request.organization = request.membership.organization

        return self.get_response(request)
