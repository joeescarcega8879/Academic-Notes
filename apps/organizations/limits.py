"""Límites y funciones por plan: ``check_limit`` y ``has_feature`` son lo único que el resto del código consulta.

Reglas (sección 2 de ``New_Phases.md``):

- Solo se bloquea **crear** (un grupo, un alumno, una pregunta); lo que ya existe sigue funcionando.
- Los grupos archivados y las preguntas archivadas no cuentan. Los alumnos se cuentan por ficha de lista
  que esté inscrita en al menos un grupo activo (el mismo alumno en dos grupos cuenta una vez).
- Una lista o importación que excede el tope se rechaza completa, no se corta a la mitad.
- Estar por encima de un tope (p. ej. tras bajar de plan) no borra ni bloquea nada: solo impide crecer.

Los modelos de ``courses`` y ``quizzes`` se importan dentro de las funciones: esos módulos dependen de
``organizations``, y al revés crearía una dependencia circular.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from .plans import FEATURE_KEYS, FEATURES, LIMIT_KEYS, LIMITS, spec_for


class PlanLimitError(ValidationError):
    """El plan no permite la acción. El mensaje ya está listo para mostrarse al docente.

    Es un ``ValidationError``: los formularios y servicios que ya manejan esos errores lo muestran sin cambios.
    """

    def __init__(self, message, *, limit=None):
        super().__init__(message, code='plan_limit')
        self.limit = limit


def plan_for(organization):
    return spec_for(organization.plan)


def has_feature(organization, feature):
    """¿El plan de la organización incluye esta función? (``FEATURE_KEYS`` en ``plans.py``)"""
    if feature not in FEATURE_KEYS:
        raise ValueError(f'Función desconocida: {feature}')
    return plan_for(organization).has(feature)


# ── Medición ──────────────────────────────────────────────────────────

def active_student_ids(organization):
    """Fichas de lista inscritas en algún grupo activo."""
    from apps.courses.models import Course, Student

    return set(
        Student.objects.filter(organization=organization, enrollments__course__status=Course.Status.ACTIVE)
        .values_list('pk', flat=True)
    )


def _count_groups(organization):
    from apps.courses.models import Course

    return Course.objects.filter(organization=organization, status=Course.Status.ACTIVE).count()


def _count_questions(organization):
    from apps.quizzes.models import Question

    return Question.objects.filter(organization=organization, is_archived=False).count()


def usage(organization):
    """Cuánto usa la organización de cada tope: ``{'groups': 2, 'students': 41, 'questions': 12}``."""
    return {
        'groups': _count_groups(organization),
        'students': len(active_student_ids(organization)),
        'questions': _count_questions(organization),
    }


def _used(organization, key):
    if key == 'groups':
        return _count_groups(organization)
    if key == 'students':
        return len(active_student_ids(organization))
    return _count_questions(organization)


# ── Comprobación ──────────────────────────────────────────────────────

def _plural(n, singular, plural):
    return f'{n} {singular if n == 1 else plural}'


def _message(plan, key, used, adding, limit):
    nombre = plan.name
    if key == 'groups':
        return (
            f'Tu plan {nombre} permite {_plural(limit, "grupo activo", "grupos activos")} y ya tienes {used}. '
            'Archiva uno o mejora tu plan.'
        )
    if key == 'students':
        if adding == 1:
            return (
                f'Tu plan {nombre} permite {_plural(limit, "alumno", "alumnos")} en grupos activos y ya tienes {used}. '
                'Archiva un grupo o mejora tu plan.'
            )
        return (
            f'Esto agregaría {adding} alumnos a los {used} que ya tienes en grupos activos, y tu plan {nombre} permite '
            f'{limit}. Reduce la lista, archiva un grupo o mejora tu plan.'
        )
    if adding == 1:
        return (
            f'Tu plan {nombre} permite {_plural(limit, "pregunta", "preguntas")} en el banco y ya tienes {used}. '
            'Archiva alguna o mejora tu plan.'
        )
    return (
        f'Esto agregaría {adding} preguntas a las {used} que ya tienes en el banco, y tu plan {nombre} permite {limit}. '
        'Importa menos, archiva algunas o mejora tu plan.'
    )


def check_limit(organization, key, *, adding=1):
    """Lanza ``PlanLimitError`` si agregar ``adding`` unidades de ``key`` pasaría el tope del plan.

    ``key``: ``'groups'``, ``'students'`` o ``'questions'``. Con ``adding=0`` o un plan sin tope no hace nada
    (ni consulta la base de datos).
    """
    if key not in LIMIT_KEYS:
        raise ValueError(f'Límite desconocido: {key}')
    plan = plan_for(organization)
    limit = plan.limit(key)
    if limit is None or adding <= 0:
        return
    used = _used(organization, key)
    if used + adding > limit:
        raise PlanLimitError(_message(plan, key, used, adding, limit), limit=key)


def flash_limit_error(request, error):
    """Muestra el aviso de un ``PlanLimitError`` como mensaje con el enlace «Mejorar plan»."""
    from django.contrib import messages

    messages.warning(request, ' '.join(error.messages), extra_tags='plan-limit')


def new_students_among(organization, student_ids):
    """Cuántas de estas fichas de lista aún no cuentan (no están inscritas en ningún grupo activo)."""
    return len(set(student_ids) - active_student_ids(organization))


def check_students(organization, student_ids):
    """Tope de alumnos al inscribir en un grupo activo a estas fichas; solo cuentan las que aún no cuentan.

    Un plan sin tope de alumnos no consulta la base de datos.
    """
    if plan_for(organization).students is None:
        return
    check_limit(organization, 'students', adding=new_students_among(organization, student_ids))


# ── Para la pantalla «Plan y facturación» ─────────────────────────────

@dataclass(frozen=True)
class LimitRow:
    key: str
    label: str
    used: int
    limit: int | None

    @property
    def unlimited(self):
        return self.limit is None

    @property
    def over(self):
        return self.limit is not None and self.used > self.limit

    @property
    def full(self):
        return self.limit is not None and self.used >= self.limit

    @property
    def percent(self):
        if not self.limit:
            return 0
        return min(100, round(self.used * 100 / self.limit))

    @property
    def tone(self):
        return 'bad' if self.over else 'warn' if self.full else 'ok'


def limit_rows(organization):
    plan = plan_for(organization)
    used = usage(organization)
    return [LimitRow(key, label, used[key], plan.limit(key)) for key, label in LIMITS]


def feature_rows(organization):
    plan = plan_for(organization)
    return [{'key': key, 'label': label, 'included': plan.has(key)} for key, label in FEATURES]
