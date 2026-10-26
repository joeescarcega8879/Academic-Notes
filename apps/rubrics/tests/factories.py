from apps.organizations.services import teaching_organization
from apps.rubrics.services import library

# Cada criterio: los puntos de sus niveles, del mejor al peor. Por omisión, 2 criterios de 4 niveles que valen 12 en total.
DEFAULT_ROWS = ((4, 3, 2, 0), (8, 6, 3, 0))
LEVELS = ['Excelente', 'Bueno', 'Regular', 'Insuficiente']


def make_draft(rows=DEFAULT_ROWS, *, name='Ensayo', description=''):
    """Borrador limpio (ya con ``Decimal``) listo para ``library.create_rubric``."""
    from decimal import Decimal

    levels = LEVELS[:len(rows[0])] if len(rows[0]) <= len(LEVELS) else [f'Nivel {n}' for n in range(len(rows[0]))]
    return {
        'name': name, 'description': description, 'levels': levels,
        'criteria': [
            {'name': f'Criterio {i + 1}', 'cells': [{'points': Decimal(str(p)), 'text': f'{levels[j]} del criterio {i + 1}'} for j, p in enumerate(row)]}
            for i, row in enumerate(rows)
        ],
    }


def make_rubric(author, *, rows=DEFAULT_ROWS, name='Ensayo', organization=None):
    """Rúbrica del docente (versión 1) en su organización."""
    return library.create_rubric(
        organization=organization or teaching_organization(author), author=author, draft=make_draft(rows, name=name),
    )


def rubric_activity(course, rubric=None, **kwargs):
    """Tarea publicada del grupo que se califica con ``rubric`` (su versión vigente)."""
    from apps.grades.models import Activity
    from apps.grades.tests.factories import ActivityFactory

    rubric = rubric or make_rubric(course.professor)
    activity = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, **kwargs)
    activity.rubric_version = rubric.current_version
    activity.save()
    return activity


def choices_for(version, level_index=0):
    """``{criterio: nivel}`` eligiendo en todos los criterios el nivel de esa posición (0 = el mejor)."""
    return {criterion.pk: criterion.levels.all()[level_index].pk for criterion in version.criteria.prefetch_related('levels')}
