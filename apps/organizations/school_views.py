"""«Mi escuela»: la dirección arma su equipo de docentes; el docente invitado acepta con su cuenta."""

from urllib.parse import quote

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import DirectionRequiredMixin, home_url_name

from . import school
from .models import OrganizationInvitation
from .services import SESSION_KEY, active_memberships


class SchoolView(DirectionRequiredMixin, View):
    """El equipo de la escuela: quién dirige y da clase, y las invitaciones pendientes."""

    def get(self, request):
        return render(request, 'school.html', {
            'team': school.team(request.organization), 'invitations': school.open_invitations(request.organization),
            'valid_days': OrganizationInvitation.VALID_DAYS,
        })


class SchoolActionView(DirectionRequiredMixin, View):
    """Una acción de la dirección sobre sus invitaciones: se hace por POST y se vuelve a «Mi escuela»."""

    def run(self, request):
        raise NotImplementedError

    def post(self, request, **kwargs):
        try:
            message = self.run(request, **kwargs)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, message)
        return redirect('organizations:school')

    @staticmethod
    def invitation(request, pk):
        return get_object_or_404(OrganizationInvitation.objects.for_organization(request.organization).select_related('organization'), pk=pk)


class InviteView(SchoolActionView):
    def run(self, request):
        invitation = school.invite_teacher(request.organization, request.POST.get('email', ''), by=request.user)
        return f'Le mandamos la invitación a {invitation.email}. Vale {invitation.VALID_DAYS} días.'


class ResendView(SchoolActionView):
    def run(self, request, pk):
        invitation = school.resend(self.invitation(request, pk), by=request.user)
        return f'Volvimos a mandar la invitación a {invitation.email}.'


class RevokeView(SchoolActionView):
    def run(self, request, pk):
        invitation = school.revoke(self.invitation(request, pk), by=request.user)
        return f'Retiramos la invitación de {invitation.email}: su enlace ya no sirve.'


class AcceptView(View):
    """La invitación que llega por correo. Se ve sin iniciar sesión; para aceptar hace falta la cuenta del correo invitado."""

    template_name = 'school_invitation.html'

    @staticmethod
    def get_invitation(token):
        return get_object_or_404(OrganizationInvitation.objects.select_related('organization'), token=token)

    def page(self, request, invitation, error=''):
        here = request.path
        context = {
            'invitation': invitation, 'school': invitation.organization, 'login_url': f'/login/?next={quote(here)}',
            'register_url': f'/registro/?next={quote(here)}', 'error': error, 'state': 'anonymous',
        }
        if request.user.is_authenticated:
            try:
                school.check_acceptable(invitation, request.user)
            except ValidationError as problem:
                context.update(state='blocked', error=' '.join(problem.messages))
            else:
                context['state'] = 'ready'
        else:
            try:
                school.check_open(invitation)
            except ValidationError as problem:
                context.update(state='blocked', error=' '.join(problem.messages))
        return render(request, self.template_name, context)

    def get(self, request, token):
        return self.page(request, self.get_invitation(token))

    def post(self, request, token):
        invitation = self.get_invitation(token)
        if not request.user.is_authenticated:
            return redirect(f'/login/?next={quote(request.path)}')
        try:
            school.accept(invitation, request.user)
        except ValidationError as error:
            return self.page(request, invitation, error=' '.join(error.messages))
        request.session[SESSION_KEY] = invitation.organization_id
        messages.success(
            request, f'Ya eres parte de {invitation.organization.name}. Tu espacio personal sigue ahí: cámbialo desde el menú de la izquierda.',
        )
        membership = next((m for m in active_memberships(request.user) if m.organization_id == invitation.organization_id), None)
        return redirect(home_url_name(membership))

