"""Correos transaccionales: una plantilla de texto y una HTML por mensaje en ``templates/emails/``."""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string


def send_email(*, to, subject, template, context=None):
    """Manda ``emails/<template>.txt`` (y su versión ``.html``) a ``to``. Se llama desde las tareas de Celery."""
    context = {
        'site_name': settings.SITE_NAME, 'site_url': settings.SITE_URL, 'support_email': settings.SUPPORT_EMAIL,
        **(context or {}),
    }
    message = EmailMultiAlternatives(
        subject, render_to_string(f'emails/{template}.txt', context), settings.DEFAULT_FROM_EMAIL, [to],
    )
    message.attach_alternative(render_to_string(f'emails/{template}.html', context), 'text/html')
    message.send()
