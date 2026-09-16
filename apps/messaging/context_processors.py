from .models import Message

def unread_messages(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'unread_count': 0}

    qs = Message.objects.filter(read_at__isnull=True).exclude(sender=user)
    if user.role == 'student':
        qs = qs.filter(conversation__student=user)
    elif user.role == 'professor':
        qs = qs.filter(conversation__subject__professor=user)
    else:
        return {'unread_count': 0}
    return {'unread_count': qs.count()}