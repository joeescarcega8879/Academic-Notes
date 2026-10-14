"""La puerta de entrada: portada, alta de docentes y alumnos, páginas legales y la lista de primeros pasos."""

from django.contrib import messages
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import TeacherRequiredMixin, home_url_name
from apps.organizations.services import SESSION_KEY, active_memberships, pick_membership
from core import throttle

from . import services
from .forms import RegisterForm, TeacherRegisterForm

LOGIN_BACKEND = 'apps.accounts.backends.EmailOrUsernameBackend'
HIDDEN_SESSION_KEY = 'onboarding_hidden'


class LandingView(View):
    """La raíz del sitio: la portada para quien no ha entrado y su inicio para quien sí."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(home_url_name(request.membership))
        return render(request, 'onboarding/landing.html')


class RegisterView(View):
    """Base del alta: valida, frena abusos, crea la cuenta e inicia la sesión."""

    template_name = 'auth/register.html'
    form_class = RegisterForm
    role = ''
    title = ''
    lead = ''
    success_message = ''
    success_url = 'home'

    def create_user(self, data):
        raise NotImplementedError

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(home_url_name(request.membership))
        return self.render(request, self.form_class())

    def render(self, request, form, status=200):
        return render(request, self.template_name, {'form': form, 'role': self.role, 'title': self.title, 'lead': self.lead}, status=status)

    def post(self, request):
        if request.user.is_authenticated:
            return redirect(home_url_name(request.membership))
        form = self.form_class(request.POST)
        if not throttle.allow('register', throttle.client_ip(request), limit=5, window=3600):
            form.is_valid()
            form.add_error(None, 'Se han creado muchas cuentas desde tu conexión. Intenta de nuevo en un rato.')
            return self.render(request, form, status=429)
        if not form.is_valid():
            return self.render(request, form)
        if form.is_bot:
            return redirect('home')  # sin crear nada y sin dar pistas
        try:
            user = self.create_user(form.cleaned_data)
        except ValidationError as error:
            form.add_error('email', error)
            return self.render(request, form)

        login(request, user, backend=LOGIN_BACKEND)
        membership = pick_membership(active_memberships(user))
        if membership is not None:
            request.session[SESSION_KEY] = membership.organization_id
        messages.success(request, self.success_message)
        return redirect(self.success_url)


class TeacherRegisterView(RegisterView):
    form_class = TeacherRegisterForm
    role = 'teacher'
    title = 'Crea tu cuenta de docente'
    lead = 'Importa tu lista, califica en la libreta y descarga tus boletas. Empieza gratis.'
    success_message = '¡Bienvenido! Sigue los pasos de abajo para dejar tu primer grupo listo.'
    success_url = 'professor_dashboard'

    def create_user(self, data):
        return services.register_teacher(
            first_name=data['first_name'], last_name=data['last_name'], email=data['email'],
            password=data['password1'], school_name=data.get('school_name', ''),
        )


class StudentRegisterView(RegisterView):
    role = 'student'
    title = 'Crea tu cuenta de alumno'
    lead = 'Con tu cuenta y el código que te dé tu docente te unes a tu grupo y ves tus calificaciones.'
    success_message = '¡Bienvenido! Escribe aquí el código que te dio tu docente para unirte a tu grupo.'
    success_url = 'join_course'

    def create_user(self, data):
        return services.register_student(
            first_name=data['first_name'], last_name=data['last_name'], email=data['email'], password=data['password1'],
        )


class LegalView(TemplateView):
    """Términos y aviso de privacidad. ``draft`` muestra el aviso de que el texto aún no pasa por revisión legal."""

    draft = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(draft=self.draft, **kwargs)


class DismissChecklistView(TeacherRequiredMixin, View):
    def post(self, request):
        request.session[HIDDEN_SESSION_KEY] = True
        return redirect('professor_dashboard')
