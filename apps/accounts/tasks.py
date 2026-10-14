"""Tareas de Celery para los correos de cuentas. Reintentan con espera creciente si el proveedor falla."""

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model

from . import services
from .emails import send_email

RETRY = {'autoretry_for': (Exception,), 'retry_backoff': True, 'retry_kwargs': {'max_retries': 3}}


def _user(user_id):
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()


@shared_task(name='apps.accounts.tasks.send_welcome_email', **RETRY)
def send_welcome_email(user_id):
    user = _user(user_id)
    if user is None:
        return
    teacher = user.role == 'professor'
    send_email(
        to=user.email, subject=f'Te damos la bienvenida a {settings.SITE_NAME}', template='welcome',
        context={'user': user, 'teacher': teacher, 'verify_url': '' if user.email_verified_at else services.verification_url(user)},
    )


@shared_task(name='apps.accounts.tasks.send_verification_email', **RETRY)
def send_verification_email(user_id):
    user = _user(user_id)
    if user is None or user.email_verified_at is not None:
        return
    send_email(
        to=user.email, subject='Confirma tu correo', template='verify_email',
        context={'user': user, 'verify_url': services.verification_url(user)},
    )


@shared_task(name='apps.accounts.tasks.send_password_reset_email', **RETRY)
def send_password_reset_email(user_id):
    user = _user(user_id)
    if user is None or not user.has_usable_password():
        return
    send_email(
        to=user.email, subject='Restablece tu contraseña', template='password_reset',
        context={'user': user, 'reset_url': services.reset_url(user)},
    )
