"""Correos de la escuela. Reintentan con espera creciente si el proveedor falla."""

from celery import shared_task
from django.conf import settings

from apps.accounts.emails import send_email

from . import school
from .models import OrganizationInvitation

RETRY = {'autoretry_for': (Exception,), 'retry_backoff': True, 'retry_kwargs': {'max_retries': 3}}


@shared_task(name='apps.organizations.tasks.send_teacher_invitation_email', **RETRY)
def send_teacher_invitation_email(invitation_id):
    invitation = OrganizationInvitation.objects.select_related('organization', 'invited_by').filter(pk=invitation_id).first()
    if invitation is None or not invitation.is_usable:
        return
    inviter = invitation.invited_by
    send_email(
        to=invitation.email, subject=f'{invitation.organization.name} te invita a {settings.SITE_NAME}', template='school_invitation',
        context={
            'school': invitation.organization, 'inviter': inviter.get_full_name() if inviter else '',
            'accept_url': settings.SITE_URL + school.accept_path(invitation), 'valid_days': invitation.VALID_DAYS,
        },
    )
