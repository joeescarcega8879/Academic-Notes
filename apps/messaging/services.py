"""Consultas compartidas de mensajería (no leídos y marcado como leído)."""

from django.utils import timezone

from .models import Message


def unread_messages_for(user):
    """Mensajes sin leer dirigidos a ``user`` (los que otros enviaron en sus conversaciones)."""
    unread = Message.objects.filter(read_at__isnull=True).exclude(sender=user)
    if user.role == 'student':
        return unread.filter(conversation__student=user)
    if user.role == 'professor':
        return unread.filter(conversation__subject__professor=user)
    return unread.none()


def unread_count_for_request(request):
    """Cuenta de no leídos, calculada una sola vez por petición.

    Los context processors de mensajes y notificaciones la necesitan en cada
    página; se guarda en la petición para no repetir la consulta.
    """
    if not hasattr(request, '_unread_messages_count'):
        request._unread_messages_count = unread_messages_for(request.user).count()
    return request._unread_messages_count


def mark_all_read(user, when=None):
    """Marca como leídos todos los mensajes pendientes de ``user``."""
    return unread_messages_for(user).update(read_at=when or timezone.now())
