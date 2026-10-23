from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin, home_url_name
from apps.courses.models import AcademicYear

from . import limits, plans
from .forms import OrganizationNameForm
from .models import Membership
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


class PlanView(TeacherRequiredMixin, View):
    """«Plan y facturación»: el plan actual, cuánto se usa de cada tope y qué ofrece el plan de pago.

    Todavía no se cobra en línea: el plan Pro se activa con el equipo (el plan de la organización se asigna
    desde el admin). Cuando exista la pasarela, el botón de abajo pasa a ser el pago.
    """

    template_name = 'plan.html'

    def get(self, request):
        organization = request.organization
        plan = limits.plan_for(organization)
        rows = limits.limit_rows(organization)
        subject = quote('Quiero el plan Pro')
        ai_usage, ai_renews = self.ai_usage(organization)
        lines = [
            'Hola, quiero activar el plan Pro.', '',
            f'Organización: {organization.name} (id {organization.pk})', f'Correo: {request.user.email}',
        ]
        body = quote('\n'.join(lines))
        return render(request, self.template_name, {
            'plan': plan, 'limit_rows': rows, 'feature_rows': limits.feature_rows(organization),
            'ai_usage': ai_usage, 'ai_renews': ai_renews,
            'over_limit': any(row.over for row in rows), 'comparison': plans.comparison_rows(), 'paid_plan': plans.TEACHER,
            'upgrade_mailto': f'mailto:{settings.SUPPORT_EMAIL}?subject={subject}&body={body}',
        })


    @staticmethod
    def ai_usage(organization):
        """Usos de IA del mes y cuándo se renuevan, o ``(None, '')`` si el plan no incluye IA."""
        from apps.ai import services as ai

        summary = ai.usage_summary(organization)
        return summary, (ai.renewal_label() if summary else '')


class SettingsView(TeacherRequiredMixin, View):
    """Ajustes del docente: su organización, el ciclo actual y el estado de su cuenta.

    Solo el propietario cambia el nombre de la organización; un docente invitado a una institución lo ve, no lo edita.
    """

    template_name = 'ajustes.html'

    @staticmethod
    def can_rename(request):
        return request.membership.role == Membership.Role.OWNER

    @staticmethod
    def can_manage_ai(request):
        return request.membership.role == Membership.Role.OWNER

    def show(self, request, form):
        from apps.ai import services as ai

        current_year = AcademicYear.objects.for_organization(request.organization).filter(is_current=True).first()
        return render(request, self.template_name, {
            'form': form, 'can_rename': self.can_rename(request), 'current_year': current_year,
            'plan': limits.plan_for(request.organization), 'limit_rows': limits.limit_rows(request.organization),
            'ai_usage': ai.usage_summary(request.organization), 'ai_renews': ai.renewal_label(),
            'can_manage_ai': self.can_manage_ai(request),
        })

    def get(self, request):
        return self.show(request, OrganizationNameForm(instance=request.organization))

    def post(self, request):
        if request.POST.get('action') == 'ai':
            return self.toggle_ai(request)
        if not self.can_rename(request):
            raise Http404
        # Siempre sobre la organización activa de la sesión, nunca una que venga en la petición.
        form = OrganizationNameForm(request.POST, instance=request.organization)
        if form.is_valid():
            form.save()
            messages.success(request, 'Guardamos el nombre de tu organización.')
            return redirect('organizations:settings')
        return self.show(request, form)

    def toggle_ai(self, request):
        """Enciende o apaga la IA de la organización activa. Solo el propietario, y solo si su plan la incluye."""
        if not self.can_manage_ai(request):
            raise Http404
        organization = request.organization
        if not limits.has_feature(organization, 'ai_assistant'):
            messages.warning(request, 'Tu plan no incluye la IA asistida. Está disponible en el plan Plus.')
            return redirect('organizations:settings')
        organization.ai_enabled = request.POST.get('enabled') == 'on'
        organization.save(update_fields=['ai_enabled'])
        messages.success(request, 'La IA asistida quedó encendida.' if organization.ai_enabled else 'La IA asistida quedó apagada.')
        return redirect('organizations:settings')
