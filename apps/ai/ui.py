"""Lo que las pantallas de quizzes y temario necesitan para ofrecer la IA: si está disponible y el panel de configuración."""

from django.urls import reverse

from apps.syllabus.models import Syllabus

from . import quiz_generation as quiz_gen
from . import services, split_generation as split_gen

NO_WEEKS = 'Arma primero las semanas del temario (con temas u objetivos) para poder usar la IA.'


def unavailable_reason(organization):
    """El motivo, listo para mostrarse, por el que la IA no se puede usar ahora; vacío si se puede."""
    try:
        services.check_available(organization)
    except services.AIUnavailable as error:
        return ' '.join(error.messages)
    return ''


def quiz_panel(organization, course, *, activity=None, week=None):
    """Contexto del panel «Generar preguntas con IA» (``partials/ai_quiz_modal.html``) como ``ai``.

    ``activity``: el quiz al que van las preguntas. ``week``: la semana que viene marcada (desde el editor de una semana).
    """
    preselected = week.pk if week is not None else (activity.syllabus_week_id if activity is not None else None)
    rows = []
    for item in quiz_gen.course_weeks(course):
        selectable = not item.no_class and quiz_gen.week_has_content(item)
        rows.append({
            'pk': item.pk, 'position': item.position, 'title': item.title or 'Sin título', 'selectable': selectable,
            'topics': len(item.topic_list), 'selected': selectable and item.pk == preselected,
            'note': 'semana sin clase' if item.no_class else ('sin temas ni objetivos' if not selectable else ''),
        })
    reason = unavailable_reason(organization)
    if not reason and not any(row['selectable'] for row in rows):
        reason = NO_WEEKS
    base_title = ''
    if week is not None:
        base_title = f'Quiz · {week.title.strip() or f"Semana {week.position}"}'
    return {
        'reason': reason, 'weeks': rows, 'usage': services.usage_summary(organization),
        'action_url': reverse('ai:quiz_generate', args=[course.pk]), 'activity': activity, 'default_title': base_title,
        'counts': quiz_gen.COUNT_CHOICES, 'mixes': quiz_gen.MIX_CHOICES, 'difficulties': quiz_gen.DIFFICULTY_CHOICES,
    }


def split_reason(organization, syllabus):
    """Por qué no se puede proponer la división del temario con IA (vacío si se puede)."""
    reason = unavailable_reason(organization)
    if reason:
        return reason
    try:
        split_gen.clean_params({}, syllabus if isinstance(syllabus, Syllabus) else Syllabus())
    except split_gen.RequestError as error:
        return ' '.join(error.messages)
    return ''
