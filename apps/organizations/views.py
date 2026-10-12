from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views import View

from apps.accounts.mixins import home_url_name

from .services import SESSION_KEY


class SwitchOrganizationView(LoginRequiredMixin, View):
    """Cambia la organización activa a otra de la que el usuario es miembro."""

    def post(self, request):
        raw = request.POST.get('organization', '')
        membership = next((m for m in request.memberships if str(m.organization_id) == raw), None)
        if membership is None:
            raise Http404('No perteneces a esa organización.')
        request.session[SESSION_KEY] = membership.organization_id
        return redirect(home_url_name(membership))
