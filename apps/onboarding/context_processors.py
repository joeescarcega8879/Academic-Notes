from django.conf import settings

from . import services

HIDDEN_SESSION_KEY = 'onboarding_hidden'


def onboarding(request):
    """``site_name`` para todas las plantillas y, solo en el inicio del docente, su lista de primeros pasos.

    La lista se oculta sola al completarse los cuatro pasos, o cuando el docente la descarta.
    """
    context = {'site_name': settings.SITE_NAME, 'support_email': settings.SUPPORT_EMAIL}
    match = getattr(request, 'resolver_match', None)
    user = getattr(request, 'user', None)
    membership = getattr(request, 'membership', None)
    if (
        match is None or match.url_name != 'professor_dashboard' or user is None or not user.is_authenticated
        or membership is None or not membership.is_teacher or request.session.get(HIDDEN_SESSION_KEY)
    ):
        return context
    steps = services.teacher_steps(user, request.organization)
    done = sum(step.done for step in steps)
    if done < len(steps):
        context['onboarding'] = {'steps': steps, 'done': done, 'total': len(steps)}
    return context
