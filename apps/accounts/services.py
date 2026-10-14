"""Correo confirmado y restablecer contraseña: enlaces firmados y envío por Celery."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

VERIFY_SALT = 'accounts.verify-email'
VERIFY_MAX_AGE = 7 * 24 * 3600  # el enlace de confirmación vale una semana


def verification_token(user):
    """Token firmado que liga el enlace a este usuario Y a este correo: si cambia el correo, el enlace viejo ya no sirve."""
    return signing.dumps({'u': user.pk, 'e': user.email}, salt=VERIFY_SALT)


def verification_url(user):
    return settings.SITE_URL + reverse('verify_email', args=[verification_token(user)])


def confirm_email(token):
    """Marca el correo como confirmado y devuelve el usuario; ``None`` si el enlace es inválido, venció o es de otro correo."""
    try:
        payload = signing.loads(token, salt=VERIFY_SALT, max_age=VERIFY_MAX_AGE)
        user = get_user_model().objects.get(pk=payload['u'])
    except (signing.BadSignature, get_user_model().DoesNotExist, KeyError, TypeError):
        return None
    if user.email != payload['e']:
        return None
    if user.email_verified_at is None:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at'])
    return user


def reset_url(user):
    """Enlace de Django para elegir una contraseña nueva (el token deja de valer al cambiarla o al iniciar sesión)."""
    path = reverse('password_reset_confirm', kwargs={
        'uidb64': urlsafe_base64_encode(force_bytes(user.pk)), 'token': default_token_generator.make_token(user),
    })
    return settings.SITE_URL + path


def _after_commit(task, *args):
    """Encola la tarea cuando la transacción ya se confirmó: el worker no debe buscar un usuario que aún no existe."""
    transaction.on_commit(lambda: task.delay(*args))


def queue_welcome_email(user):
    from .tasks import send_welcome_email

    _after_commit(send_welcome_email, user.pk)


def queue_verification_email(user):
    from .tasks import send_verification_email

    _after_commit(send_verification_email, user.pk)


def queue_password_reset_email(user):
    from .tasks import send_password_reset_email

    _after_commit(send_password_reset_email, user.pk)
