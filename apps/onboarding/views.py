"""La puerta de entrada: portada, alta de docentes y alumnos, páginas legales y la lista de primeros pasos."""

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from apps.accounts.mixins import TeacherRequiredMixin, home_url_name
from apps.organizations import plans
from apps.organizations.models import Organization
from apps.organizations.services import SESSION_KEY, active_memberships, pick_membership
from core import throttle
from core.utils import safe_next_url

from . import services
from .forms import RegisterForm, TeacherRegisterForm, WaitlistForm
from .models import WaitlistEntry

LOGIN_BACKEND = 'apps.accounts.backends.EmailOrUsernameBackend'
HIDDEN_SESSION_KEY = 'onboarding_hidden'


class LandingView(View):
    """La raíz del sitio: la portada para quien no ha entrado y su inicio para quien sí."""

    def get(self, request):
        if request.user.is_authenticated:
            return redirect(home_url_name(request.membership))
        return render(request, 'onboarding/landing.html', self.pricing_context())

    @staticmethod
    def pricing_context():
        """Los dos planes de la portada, con los mismos números que ``/precios/`` (salen de ``plans``)."""
        free = plans.FREE
        free_bullets = [f'{label}: {free.limit(key)}' for key, label in plans.LIMITS if free.limit(key) is not None]
        return {
            'free': free, 'paid': plans.TEACHER, 'plus': plans.PLUS,
            'free_bullets': free_bullets + ['Boletas en PDF con marca de agua'],
            'paid_bullets': PricingView.paid_bullets(), 'plus_bullets': PricingView.plus_bullets(),
        }


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
        return render(request, self.template_name, {
            'form': form, 'role': self.role, 'title': self.title, 'lead': self.lead, 'next': safe_next_url(request),
        }, status=status)

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
        return redirect(safe_next_url(request) or self.success_url)


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


class PricingView(View):
    """Precios: los tres planes, lo que cambia entre ellos y la lista de espera de los planes de pago.

    Todo sale de ``apps.organizations.plans``: si cambia un tope o un precio, esta página cambia sola. Todavía no
    se cobra en línea ni existe la IA de Plus, así que los planes de pago ofrecen «Avísame» (lista de espera) en
    lugar de comprar.
    """

    template_name = 'onboarding/pricing.html'
    JOINED_PARAM = 'lista'
    WAITLIST_PLANS = {Organization.Plan.TEACHER: 'pro', Organization.Plan.TEACHER_PLUS: 'plus'}

    @staticmethod
    def free_bullets():
        free = plans.FREE
        lines = [
            'Libreta con calificación final ponderada por criterio y periodo',
            'Importa tu lista desde Excel o CSV, con vista previa',
            'Tareas, proyectos, participación y exámenes',
            'Quizzes que se califican solos (sin tiempo límite)',
        ]
        lines += [f'{label}: {free.limit(key)}' for key, label in plans.LIMITS if free.limit(key) is not None]
        lines += ['Concentrado en Excel con columnas fijas', 'Boletas en PDF con marca de agua']
        return lines

    @staticmethod
    def paid_bullets():
        lines = ['Todo lo del plan Gratis']
        for row in plans.comparison_rows():
            if row['free'] == row['paid']:
                continue
            lines.append(row['label'] if row.get('feature') else f'{row["label"]}: sin tope' if row['paid'] is None else f'{row["label"]}: {row["paid"]}')
        return lines

    @staticmethod
    def plus_bullets():
        return ['Todo lo del plan Pro', *plans.AI_PROMISES]

    def context(self, request, form, **extra):
        """Cada plan de pago tiene su formulario; el recién enviado (con sus errores) es ``form``, el otro va limpio."""
        initial = {'email': request.user.email} if request.user.is_authenticated else {}
        sent = self.WAITLIST_PLANS.get(form.data.get('plan') or Organization.Plan.TEACHER, 'pro') if form.is_bound else None
        forms = {slug: form if slug == sent else WaitlistForm(initial=initial) for slug in self.WAITLIST_PLANS.values()}
        return {
            'free': plans.FREE, 'paid': plans.TEACHER, 'plus': plans.PLUS,
            'free_bullets': self.free_bullets(), 'paid_bullets': self.paid_bullets(), 'plus_bullets': self.plus_bullets(),
            'comparison': plans.public_comparison_rows(), 'forms': forms,
            'joined': self.WAITLIST_PLANS.get(self.joined_plan(request)), **extra,
        }

    def joined_plan(self, request):
        """El plan por el que acaba de apuntarse (``?lista=pro|plus``), o ``None``."""
        value = request.GET.get(self.JOINED_PARAM)
        return next((plan for plan, slug in self.WAITLIST_PLANS.items() if slug == value), None)

    def get(self, request):
        return render(request, self.template_name, self.context(request, WaitlistForm()))

    def post(self, request):
        form = WaitlistForm(request.POST)
        if not throttle.allow('waitlist', throttle.client_ip(request), limit=5, window=3600):
            form.is_valid()
            form.add_error(None, 'Hiciste varios intentos desde tu conexión. Vuelve a intentarlo en un rato.')
            return render(request, self.template_name, self.context(request, form), status=429)
        if not form.is_valid():
            return render(request, self.template_name, self.context(request, form))
        if form.is_bot:
            return redirect('pricing')  # sin guardar nada y sin dar pistas
        # Repetir el correo no duplica ni avisa de que ya estaba: se responde igual.
        plan = form.cleaned_data['plan']
        WaitlistEntry.objects.get_or_create(
            email=form.cleaned_data['email'], plan=plan,
            defaults={'user': request.user if request.user.is_authenticated else None},
        )
        slug = self.WAITLIST_PLANS[plan]
        return redirect(f'{reverse("pricing")}?{self.JOINED_PARAM}={slug}#aviso{"" if slug == "pro" else "-" + slug}')


class LegalView(TemplateView):
    """Términos y aviso de privacidad. ``draft`` muestra el aviso de que el texto aún no pasa por revisión legal."""

    draft = True

    def get_context_data(self, **kwargs):
        return super().get_context_data(draft=self.draft, **kwargs)


class HelpView(LoginRequiredMixin, View):
    """Guía de uso y preguntas frecuentes, según quien la abre (docente o alumno)."""

    def get(self, request):
        return render(request, 'ayuda.html')


class DismissChecklistView(TeacherRequiredMixin, View):
    def post(self, request):
        request.session[HIDDEN_SESSION_KEY] = True
        return redirect('professor_dashboard')
