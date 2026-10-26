"""La biblioteca de rúbricas del docente: crear, editar (con versiones), duplicar, archivar y borrar.

Regla de edición: una versión sin calificaciones se corrige en su lugar. Una versión con calificaciones queda congelada:
al guardar cambios nace la versión siguiente y las actividades que aún no han calificado con la anterior pasan a ella;
las que ya tienen calificaciones se quedan como estaban. Así ninguna nota dada cambia después.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Prefetch

from apps.grades.models import Activity
from apps.grades.services.listing import fold

from ..models import Rubric, RubricCriterion, RubricLevel, RubricScore, RubricVersion
from . import editor


def rubrics_of(user, organization, *, archived=False):
    """Las rúbricas del docente en la organización, con sus versiones y su contenido a la mano."""
    return Rubric.objects.for_organization(organization).filter(author=user, is_archived=archived).prefetch_related(
        Prefetch('versions', queryset=RubricVersion.objects.prefetch_related('criteria__levels')),
    )


def is_graded(version):
    """¿Ya se calificó con esta versión? Entonces ya no se toca."""
    return RubricScore.objects.filter(criterion__version=version).exists()


def _fill(version, draft):
    """Escribe los criterios y niveles de ``draft`` (limpio) en ``version`` y deja sus puntos totales."""
    total = 0
    for position, criterion in enumerate(draft['criteria']):
        top = max(cell['points'] for cell in criterion['cells'])
        row = RubricCriterion.objects.create(version=version, position=position, name=criterion['name'], max_points=top)
        RubricLevel.objects.bulk_create([
            RubricLevel(
                organization_id=version.organization_id, criterion=row, position=index, name=name, points=cell['points'],
                description=cell['text'],
            )
            for index, (name, cell) in enumerate(zip(draft['levels'], criterion['cells'], strict=True))
        ])
        total += top
    version.max_points = total
    version.save(update_fields=['max_points'])


@transaction.atomic
def create_rubric(*, organization, author, draft):
    """Rúbrica nueva (versión 1) a partir de un borrador ya validado."""
    rubric = Rubric.objects.create(organization=organization, author=author, name=draft['name'], description=draft['description'])
    version = RubricVersion.objects.create(rubric=rubric, number=1)
    _fill(version, draft)
    return rubric


@transaction.atomic
def save_rubric(rubric, draft):
    """Guarda los cambios. Devuelve la versión vigente y si se tuvo que crear una nueva (la anterior ya calificó)."""
    rubric.name, rubric.description = draft['name'], draft['description']
    rubric.save(update_fields=['name', 'description', 'updated_at'])
    current = RubricVersion.objects.filter(rubric=rubric).order_by('-number').first()
    if not is_graded(current):
        current.criteria.all().delete()
        _fill(current, draft)
        return current, False
    new = RubricVersion.objects.create(rubric=rubric, number=current.number + 1)
    _fill(new, draft)
    # Lo que aún no tiene calificaciones con la versión anterior pasa a la nueva; lo ya calificado se queda.
    Activity.objects.filter(rubric_version=current).exclude(grades__rubric_scores__isnull=False).update(rubric_version=new)
    return new, True


@transaction.atomic
def duplicate(rubric, *, author):
    """Copia de la vigente como rúbrica nueva (versión 1) del mismo docente."""
    draft = editor.draft_from_version(rubric.current_version)
    draft['name'] = f'{rubric.name} (copia)'[:editor.NAME_MAX]
    _, clean = editor.validate(draft)
    return create_rubric(organization=rubric.organization, author=author, draft=clean)


def resolve_version(activity, rubric):
    """La versión con la que debe quedar ``activity`` al elegir ``rubric`` (None = sin rúbrica).

    Si ya usa una versión de esa misma rúbrica se queda con ella (puede ser una anterior que ya calificó).
    Cambiar de rúbrica o quitarla cuando ya se calificó con la actual no se permite: las notas dadas
    perderían su detalle.
    """
    current = activity.rubric_version if activity.pk else None
    if current is not None and (rubric is not None and current.rubric_id == rubric.pk):
        return current
    if current is not None and RubricScore.objects.filter(grade__activity=activity).exists():
        raise ValidationError('Ya calificaste esta actividad con su rúbrica: no se puede cambiar ni quitar.')
    return rubric.current_version if rubric is not None else None


def set_archived(rubric, archived):
    rubric.is_archived = archived
    rubric.save(update_fields=['is_archived', 'updated_at'])


def usage(rubric):
    """Cuántas actividades y cuántos grupos distintos usan alguna versión de la rúbrica."""
    activities = Activity.objects.filter(rubric_version__rubric=rubric)
    return activities.count(), activities.values('course').distinct().count()


def activities_using(rubric):
    return Activity.objects.filter(rubric_version__rubric=rubric).select_related('course').order_by('course__name', 'title')


def delete_rubric(rubric):
    """Borra una rúbrica que ninguna actividad usa; si alguna la usa, hay que archivarla."""
    if Activity.objects.filter(rubric_version__rubric=rubric).exists():
        raise ValidationError('Esta rúbrica está en uso por alguna actividad. Archívala para que ya no se ofrezca.')
    rubric.delete()


def library_rows(user, organization, *, archived=False, query=''):
    """Datos para la biblioteca: cada rúbrica con su versión vigente, cuántas actividades y grupos la usan."""
    rubrics = list(rubrics_of(user, organization, archived=archived))
    counts = {
        row['rubric_version__rubric']: row
        for row in Activity.objects.filter(rubric_version__rubric__in=rubrics).values('rubric_version__rubric').annotate(
            activities=Count('id'), groups=Count('course', distinct=True),
        )
    }
    needle = fold(query)
    rows = []
    for rubric in rubrics:
        if needle and needle not in fold(f'{rubric.name} {rubric.description}'):
            continue
        version = rubric.current_version
        used = counts.get(rubric.pk, {})
        rows.append({
            'rubric': rubric, 'version': version, 'criteria': len(version.criteria.all()),
            'levels': max((len(c.levels.all()) for c in version.criteria.all()), default=0),
            'activities': used.get('activities', 0), 'groups': used.get('groups', 0),
        })
    return rows
