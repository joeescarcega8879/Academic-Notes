from django.contrib.auth import login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View

from apps.organizations.services import SESSION_KEY, active_memberships, pick_membership

from .forms import LoginForm, ProfileForm, StudentProfileForm, ProfessorProfileForm
from .mixins import home_url_name
from .models import User

class LoginView(View):
    template_name = 'login.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(home_url_name(request.membership))
        return render(request, self.template_name, {'form': LoginForm()})

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        role = request.POST.get('role')

        if form.is_valid():
            user = form.get_user()
            memberships = active_memberships(user)
            if role and not self._has_role(user, memberships, role):
                return render(request, self.template_name, {
                    'form': form,
                    'error': 'El rol seleccionado no coincide con esta cuenta.',
                })

            login(request, user)
            membership = self._membership_for(memberships, role, request.session.get(SESSION_KEY))
            if membership is not None:
                request.session[SESSION_KEY] = membership.organization_id
            return redirect(home_url_name(membership))
        return render(request, self.template_name, {'form': form})

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
    
    def get(self, request):
        logout(request)
        return redirect('login')
    
class NotificationsReadView(LoginRequiredMixin, View):
    """Marca como leidas las notificaciones del usuario."""

    def post(self, request):
        from apps.messaging.services import mark_all_read

        now = timezone.now()
        mark_all_read(request.user, request.membership, now)

        request.user.notifications_read_at = now
        request.user.save(update_fields=['notifications_read_at'])

        siguiente = request.POST.get('next', '')
        if not url_has_allowed_host_and_scheme(
            siguiente, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
        ):
            siguiente = reverse('profile')
        return redirect(siguiente)


class ProfileView(LoginRequiredMixin, View):
    template_name = 'perfil.html'
    login_url = '/login/'
    
    def get(self, request):
        profile_form = ProfileForm(instance=request.user)
        if request.user.role == User.Role.STUDENT:
            eform = StudentProfileForm(instance=getattr(request.user, 'student_profile', None))
        else:
            eform = ProfessorProfileForm(instance=getattr(request.user, 'professor_profile', None))
        return render(request, self.template_name, self.context(request, profile_form, eform))

    @staticmethod
    def context(request, profile_form, extra_form):
        # La matrícula pertenece a la organización activa, no a la cuenta.
        from apps.courses.models import Student

        student = Student.objects.for_organization(request.organization).filter(user=request.user).first()
        return {
            'profile_form': profile_form,
            'extra_form': extra_form,
            'student_number': student.student_number if student else '',
        }

    def post(self, request):
        pform = ProfileForm(request.POST, request.FILES, instance=request.user)
        if request.user.role == User.Role.STUDENT:
            eform = StudentProfileForm(request.POST, instance=getattr(request.user, 'student_profile', None))
        else:
            eform = ProfessorProfileForm(request.POST, instance=getattr(request.user, 'professor_profile', None))
        if pform.is_valid() and eform.is_valid():
            pform.save()
            extra = eform.save(commit=False)
            extra.user = request.user
            extra.save()
            return redirect('profile')
        return render(request, self.template_name, self.context(request, pform, eform))