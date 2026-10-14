"""Estado de la cuenta para las plantillas: hoy, si el correo falta por confirmar."""


def account_status(request):
    """``email_unverified``: avisa al docente (solo a quien da clase) que su correo aún no está confirmado."""
    user = getattr(request, 'user', None)
    membership = getattr(request, 'membership', None)
    if user is None or not user.is_authenticated or membership is None or not membership.is_teacher:
        return {'email_unverified': False}
    return {'email_unverified': user.email_verified_at is None}
