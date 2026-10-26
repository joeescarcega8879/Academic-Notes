from django import template

from ..services.grading import adjusted_by_hand, panel_rows, rubric_points

register = template.Library()


@register.inclusion_tag('partials/rubric_panel.html')
def rubric_panel(activity, grade=None):
    """La rúbrica de una actividad para el alumno: cómo se calificará y, ya calificada, el nivel que obtuvo en cada criterio."""
    version = activity.rubric_version
    if version is None:
        return {'version': None}
    scored = grade is not None and grade.rubric_scores.exists()
    return {
        'version': version, 'rows': panel_rows(version, grade if scored else None), 'scored': scored,
        'points': rubric_points(grade) if scored else None, 'adjusted': scored and adjusted_by_hand(grade),
    }
