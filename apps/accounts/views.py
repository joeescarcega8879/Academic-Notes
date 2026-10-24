from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import PasswordChangeView, PasswordResetCompleteView, PasswordResetConfirmView
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse_lazy
from django.views import View

from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY, active_memberships, pick_membership
from core import throttle
from core.utils import safe_next_url

from . import services
from .forms import ChangePasswordForm, LoginForm, NewPasswordForm, PasswordResetRequestForm
from .mixins import home_url_name
from .models import User


class LoginView(View):
    template_name = 'login.html'

    # Solo cuentan los intentos fallidos. Por (IP, correo) frena a quien adivina una contraseña sin dejar que
    # un tercero bloquee a la víctima desde otra IP; por IP frena a quien prueba muchas cuentas; por correo
    # (con tope alto) frena un ataque repartido entre muchas IP.
    FAIL_WINDOW = 15 * 60
    LIMITS = (('login-ip-email', 5), ('login-ip', 20), ('login-email', 30))
    BLOCKED_MESSAGE = 'Demasiados intentos fallidos. Espera unos 15 minutos e inténtalo de nuevo.'

    @staticmethod
    def _identities(request, username):
        ip, username = throttle.client_ip(request), username.strip().lower()
        return {'login-ip-email': f'{ip}|{username}', 'login-ip': ip, 'login-email': username}

    def _blocked(self, identities):
        return any(throttle.exceeded(scope, identities[scope], limit=limit) for scope, limit in self.LIMITS)

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(safe_next_url(request) or home_url_name(request.membership))
        return render(request, self.template_name, {'form': LoginForm(), 'next': safe_next_url(request)})

    def post(self, request):
        form = LoginForm(request, data=request.POST)
        role = request.POST.get('role')
        next_url = safe_next_url(request)

        identities = self._identities(request, request.POST.get('username', ''))
        if self._blocked(identities):  # antes de revisar la contraseña: bloqueado es bloqueado aunque la acierte
            return render(request, self.template_name, {
                'form': LoginForm(), 'next': next_url, 'role': role, 'error': self.BLOCKED_MESSAGE,
            }, status=429)

        if form.is_valid():
            user = form.get_user()
            memberships = active_memberships(user)
            if role and not self._has_role(user, memberships, role):
                return render(request, self.template_name, {
                    'form': form, 'next': next_url, 'role': role,
                    'error': 'El rol seleccionado no coincide con esta cuenta.',
                })

            throttle.reset('login-ip-email', identities['login-ip-email'])
            login(request, user)
            membership = self._membership_for(memberships, role, request.session.get(SESSION_KEY))
            if membership is not None:
                request.session[SESSION_KEY] = membership.organization_id
            return redirect(next_url or home_url_name(membership))
        for scope, _ in self.LIMITS:
            throttle.hit(scope, identities[scope], window=self.FAIL_WINDOW)
        return render(request, self.template_name, {'form': form, 'next': next_url, 'role': role})

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


# ── Correo confirmado ─────────────────────────────────────────────────

class VerifyEmailView(View):
    """El enlace del correo de confirmación. Sirve con o sin sesión iniciada."""

    def get(self, request, token):
        user = services.confirm_email(token)
        if user is None:
            messages.error(request, 'El enlace de confirmación no es válido o ya venció. Pide uno nuevo desde tu cuenta.')
        else:
            messages.success(request, 'Listo, confirmamos tu correo.')
        return redirect('home' if request.user.is_authenticated else 'login')


class ResendVerificationView(LoginRequiredMixin, View):
    def post(self, request):
        user = request.user
        if user.email_verified_at is not None:
            return redirect(safe_next_url(request) or 'home')
        if throttle.allow('resend-verification', user.pk, limit=3, window=3600):
            services.queue_verification_email(user)
            messages.success(request, f'Te enviamos un correo a {user.email}. Revisa también la carpeta de spam.')
        else:
            messages.error(request, 'Ya pediste varios correos. Espera un rato antes de pedir otro.')
        return redirect(safe_next_url(request) or 'home')


# ── Contraseñas ───────────────────────────────────────────────────────

class ForgotPasswordView(View):
    """Pide el correo y manda el enlace. La respuesta es la misma exista o no la cuenta, para no revelar quién está registrado."""

    template_name = 'auth/forgot_password.html'

    def get(self, request):
        return render(request, self.template_name, {'form': PasswordResetRequestForm()})

    def post(self, request):
        form = PasswordResetRequestForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form})
        email = form.cleaned_data['email'].strip()
        if not throttle.allow('forgot-ip', throttle.client_ip(request), limit=10, window=3600):
            form.add_error(None, 'Demasiados intentos desde tu conexión. Intenta de nuevo en un rato.')
            return render(request, self.template_name, {'form': form}, status=429)
        if throttle.allow('forgot-email', email, limit=3, window=3600):
            user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
            if user is not None:
                services.queue_password_reset_email(user)
        return redirect('password_reset_sent')


class PasswordResetConfirm(PasswordResetConfirmView):
    template_name = 'auth/reset_password.html'
    form_class = NewPasswordForm
    success_url = reverse_lazy('password_reset_complete')


class PasswordResetComplete(PasswordResetCompleteView):
    template_name = 'auth/reset_complete.html'


class ChangePasswordView(PasswordChangeView):
    """Cambiar la contraseña desde el perfil; la sesión actual sigue abierta."""

    template_name = 'auth/change_password.html'
    form_class = ChangePasswordForm
    success_url = reverse_lazy('profile')

    def form_valid(self, form):
        messages.success(self.request, 'Cambiamos tu contraseña.')
        return super().form_valid(form)


class AvatarView(LoginRequiredMixin, View):
    """Sirve la foto de perfil: solo a su dueño y a quien comparte alguna organización con él.

    La foto no cuelga de ``MEDIA_URL``: son fotos de menores y no deben abrirse con solo tener la dirección.
    """

    def get(self, request, pk):
        owner = get_object_or_404(User, pk=pk)
        if not owner.avatar:
            raise Http404
        if owner.pk != request.user.pk:
            compartidas = Membership.objects.filter(user=request.user).values('organization')
            if not Membership.objects.filter(user=owner, organization__in=compartidas).exists():
                raise Http404  # 404 y no 403: no se confirma ni que la foto exista
        try:
            archivo = owner.avatar.open('rb')
        except FileNotFoundError:
            raise Http404 from None  # la base apunta a una foto que ya no está (p. ej. un respaldo sin los archivos)
        response = FileResponse(archivo, content_type='image/jpeg')
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, max-age=86400'  # la dirección cambia con cada foto nueva
        return response
