"""Lista de calificaciones: grupos que se ven, búsqueda y filtros.

La usan la pantalla de Calificaciones y su exportación a CSV, para que lo que se exporta sea lo que se ve.
"""

import unicodedata

from apps.courses.models import Course

TEACHER_SEARCH_FIELDS = (
    'student__first_name', 'student__last_name', 'student__student_number', 'student__email',
    'activity__title', 'activity__course__name', 'feedback',
)
STUDENT_SEARCH_FIELDS = ('activity__title', 'activity__course__name', 'feedback')


def fold(text):
    """Texto sin acentos ni mayúsculas, para buscar «alvaro» y encontrar «Álvaro» en cualquier base de datos.

    ``icontains`` no sirve aquí: en SQLite solo ignora las mayúsculas de las letras ASCII, y en ningún motor ignora
    los acentos.
    """
    decomposed = unicodedata.normalize('NFKD', text or '')
    return ''.join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def visible_courses(request, *, include_archived=False):
    """Los grupos de la organización activa que el usuario puede ver: los suyos (docente) o en los que está (alumno)."""
    courses = Course.objects.for_organization(request.organization)
    if request.membership.is_student:
        courses = courses.filter(enrollments__student__user=request.user).distinct()
    else:
        courses = courses.filter(professor=request.user)
    if not include_archived:
        courses = courses.filter(status=Course.Status.ACTIVE)
    return courses


def normalized_params(params):
    """Los parámetros de la petición con el nombre viejo ``materia`` leído como ``grupo`` (el nuevo manda)."""
    params = params.copy()
    if not params.get('grupo') and params.get('materia'):
        params['grupo'] = params['materia']
    return params


def apply_filters(grades, data, *, teacher):
    """Aplica los filtros ya validados (``GradeFilterForm.cleaned_data``) a las calificaciones visibles.

    Sin grupo elegido solo salen las de grupos activos, salvo que se pidan los archivados. Con un grupo elegido
    sale ese grupo, aunque esté archivado. La búsqueda exige todas las palabras, cada una en cualquier campo.
    """
    course = data.get('grupo')
    if course is not None:
        grades = grades.filter(activity__course=course)
    elif not data.get('archivados'):
        grades = grades.filter(activity__course__status=Course.Status.ACTIVE)

    if data.get('desde'):
        grades = grades.filter(graded_at__date__gte=data['desde'])
    if data.get('hasta'):
        grades = grades.filter(graded_at__date__lte=data['hasta'])

    words = fold(data.get('q')).split()
    if words:
        fields = TEACHER_SEARCH_FIELDS if teacher else STUDENT_SEARCH_FIELDS
        matching = []
        for pk, *values in grades.values_list('pk', *fields):
            haystack = [fold(str(value)) for value in values if value]
            if all(any(word in text for text in haystack) for word in words):
                matching.append(pk)
        grades = grades.filter(pk__in=matching)
    return grades.order_by('-graded_at', '-pk')
