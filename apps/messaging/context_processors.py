from .services import unread_count_for_request


def unread_messages(request):
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {'unread_count': 0}
    return {'unread_count': unread_count_for_request(request)}
