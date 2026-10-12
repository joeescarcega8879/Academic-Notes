"""Consultas compartidas de mensajería (no leídos y marcado como leído)."""

from django.utils import timezone

from .models import Message


def unread_messages_for(user, membership):
    """Mensajes sin leer dirigidos a ``user`` en la organización de ``membership``.

    Son los que otros enviaron en sus conversaciones de esa organización. Sin
    membresía (o sin rol docente/alumno) no hay nada.
    """
    if membership is None:
        return Message.objects.none()
    unread = (
        Message.objects
        .for_organization(membership.organization)
        .filter(read_at__isnull=True)
        .exclude(sender=user)
    )
    if membership.is_student:
        return unread.filter(conversation__student=user)
    if membership.is_teacher:
        return unread.filter(conversation__subject__professor=user)
    return unread.none()


def unread_count_for_request(request):
    """Cuenta de no leídos en la organización activa, calculada una sola vez por petición.

    Los context processors de mensajes y notificaciones la necesitan en cada
    página; se guarda en la petición para no repetir la consulta.
    """
    if not hasattr(request, '_unread_messages_count'):
        request._unread_messages_count = unread_messages_for(request.user, request.membership).count()
    return request._unread_messages_count


def mark_all_read(user, membership, when=None):
    """Marca como leídos todos los mensajes pendientes de ``user`` en la organización de ``membership``."""
    return unread_messages_for(user, membership).update(read_at=when or timezone.now())
