from datetime import timedelta

from django.urls import reverse
from django.utils import timezone


def notifications(request):
    """Notificaciones del usuario para la campana del topbar.

    - Mensajes sin leer: siempre (ambos roles).
    - Calificaciones recientes: solo alumnos y solo si notify_grades está activo.
      notify_weekly / notify_sms son preferencias de canales externos (email/SMS)
      y no afectan a este panel.
    """
    from apps.grades.models import Grade
    from apps.messaging.models import Message

    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'notifications': [], 'notifications_count': 0}

    items = []

    unread = Message.objects.filter(read_at__isnull=True).exclude(sender=user)
    if user.role == 'student':
        unread = unread.filter(conversation__student=user)
    elif user.role == 'professor':
        unread = unread.filter(conversation__subject__professor=user)
    else:
        unread = unread.none()

    unread_count = unread.count()
    recent_messages = (
        unread
        .select_related('conversation__subject', 'sender')
        .order_by('-created_at')[:5]
    )
    for message in recent_messages:
        items.append({
            'type': 'message',
            'icon': 'message-square',
            'title': message.sender.get_full_name() or message.sender.username,
            'detail': 'Te escribió en %s' % message.conversation.subject.name,
            'url': reverse('messaging:detail', args=[message.conversation_id]),
            'date': message.created_at,
        })

    grades_count = 0
    if user.role == 'student' and user.notify_grades:
        cutoff = timezone.now() - timedelta(days=7)
        recent_grades = (
            Grade.objects
            .filter(student=user, graded_at__gte=cutoff)
            .select_related('evaluation__subject')
            .order_by('-graded_at')
        )
        grades_count = recent_grades.count()
        for grade in recent_grades[:5]:
            items.append({
                'type': 'grade',
                'icon': 'clipboard',
                'title': grade.evaluation.title,
                'detail': '%s · %s' % (grade.evaluation.subject.name, grade.score),
                'url': reverse('subject_detail', args=[grade.evaluation.subject_id]),
                'date': grade.graded_at,
            })

    items.sort(key=lambda item: item['date'], reverse=True)

    return {
        'notifications': items[:8],
        'notifications_count': unread_count + grades_count,
    }
