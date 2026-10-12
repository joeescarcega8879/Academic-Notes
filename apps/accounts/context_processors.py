from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


def notifications(request):
    """Notificaciones del usuario para la campana del topbar.

    - Mensajes sin leer: siempre (ambos roles), solo de la organización activa.
    - Calificaciones recientes: solo alumnos y solo si notify_grades está activo.
      notify_weekly / notify_sms son preferencias de canales externos (email/SMS)
      y no afectan a este panel.
    """
    from apps.grades.models import Grade
    from apps.messaging.services import unread_count_for_request, unread_messages_for

    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'notifications': [], 'notifications_count': 0}

    items = []

    unread_count = unread_count_for_request(request)
    recent_messages = (
        unread_messages_for(user, request.membership)
        .select_related('conversation__course', 'sender')
        .order_by('-created_at')[:5]
    )
    for message in recent_messages:
        items.append({
            'type': 'message',
            'icon': 'message-square',
            'title': message.sender.get_full_name() or message.sender.username,
            'detail': 'Te escribió en %s' % message.conversation.course.name,
            'url': reverse('messaging:detail', args=[message.conversation_id]),
            'date': message.created_at,
        })

    grades_count = 0
    membership = request.membership
    if membership is not None and membership.is_student and user.notify_grades:
        # Ventana de 7 dias, o desde que el usuario marco sus notificaciones como leidas.
        cutoff = timezone.now() - timedelta(days=7)
        if user.notifications_read_at and user.notifications_read_at > cutoff:
            cutoff = user.notifications_read_at
        recent_grades = (
            Grade.objects
            .for_organization(request.organization)
            .filter(student__user=user, graded_at__gt=cutoff, activity__published=True)
            .select_related('activity__course')
            .order_by('-graded_at')
        )
        grades_count = recent_grades.count()
        for grade in recent_grades[:5]:
            items.append({
                'type': 'grade',
                'icon': 'clipboard',
                'title': grade.activity.title,
                'detail': '%s · %s' % (grade.activity.course.name, grade.score),
                'url': reverse('course_detail', args=[grade.activity.course_id]),
                'date': grade.graded_at,
            })

    items.sort(key=lambda item: item['date'], reverse=True)

    return {
        'notifications': items[:8],
        'notifications_count': unread_count + grades_count,
    }
