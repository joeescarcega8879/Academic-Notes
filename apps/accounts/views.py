from django.contrib.auth import login, logout
from django.shortcuts import render, redirect
from django.views import View

from apps.organizations.services import SESSION_KEY, active_memberships, pick_membership
from core.utils import safe_next_url

from .forms import LoginForm
from .mixins import home_url_name
from .models import User


class HomeView(View):
    """La raíz del sitio: cada quien va a su inicio, y quien no ha entrado, al login."""

    def get(self, request):
        if not request.user.is_authenticated:
            return redirect('login')
        return redirect(home_url_name(request.membership))


class LoginView(View):
    template_name = 'login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(safe_next_url(request) or home_url_name(request.membership))
        return render(request, self.template_name, {'form': LoginForm(), 'next': safe_next_url(request)})

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        role = request.POST.get('role')
        next_url = safe_next_url(request)

        if form.is_valid():
            user = form.get_user()
            memberships = active_memberships(user)
            if role and not self._has_role(user, memberships, role):
                return render(request, self.template_name, {
                    'form': form, 'next': next_url,
                    'error': 'El rol seleccionado no coincide con esta cuenta.',
                })

            login(request, user)
            membership = self._membership_for(memberships, role, request.session.get(SESSION_KEY))
            if membership is not None:
                request.session[SESSION_KEY] = membership.organization_id
            return redirect(next_url or home_url_name(membership))
        return render(request, self.template_name, {'form': form, 'next': next_url})

    @staticmethod
    def _has_role(user, memberships, role):
        """El rol elegido en el login existe en alguna organización del usuario.

        Quien aún no pertenece a ninguna (p. ej. un alumno sin inscripciones) se
        valida contra el tipo de cuenta.
        """
        if not memberships:
            return user.role == role
        if role == User.Role.PROFESSOR:
            return any(m.is_teacher for m in memberships)
        if role == User.Role.STUDENT:
            return any(m.is_student for m in memberships)
        return False

    @staticmethod
    def _membership_for(memberships, role, wanted_organization_id):
        """Membresía con la que se entra: la del rol elegido, o la activa de siempre."""
        by_role = {User.Role.PROFESSOR: lambda m: m.is_teacher, User.Role.STUDENT: lambda m: m.is_student}.get(role)
        if by_role is not None:
            chosen = next((m for m in memberships if by_role(m)), None)
            if chosen is not None:
                return chosen
        return pick_membership(memberships, wanted_organization_id)


class LogoutView(View):
    """Cerrar sesión cambia el estado: solo por POST (con CSRF), no por un enlace que cualquier página pueda disparar."""

    http_method_names = ['post', 'options']

    def post(self, request):
        logout(request)
        return redirect('login')
