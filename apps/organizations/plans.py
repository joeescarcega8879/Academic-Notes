"""Los planes y sus límites, en un solo lugar (sección 2 de ``New_Phases.md``).

Cambiar un tope o un precio es editar esta tabla: nada más en el código conoce los números. ``None`` en un
límite significa sin tope. Quien consulta los planes lo hace por ``apps.organizations.limits``.
"""

from dataclasses import dataclass, replace

from .models import Organization

Plan = Organization.Plan


@dataclass(frozen=True)
class PlanSpec:
    key: str
    name: str
    # Topes (None = sin tope)
    groups: int | None = None
    students: int | None = None
    questions: int | None = None
    # Funciones
    timed_quizzes: bool = True
    custom_workbook: bool = True
    clean_transcripts: bool = True
    # Precios en MXN; None = no se vende por autoservicio
    monthly_price: int | None = None
    annual_price: int | None = None

    @property
    def is_free(self):
        return self.key == Plan.FREE

    def limit(self, key):
        return getattr(self, key)

    def has(self, feature):
        return getattr(self, feature)


FREE = PlanSpec(
    key=Plan.FREE, name='Gratis',
    groups=2, students=60, questions=30,
    timed_quizzes=False, custom_workbook=False, clean_transcripts=False,
)

TEACHER = PlanSpec(key=Plan.TEACHER, name='Pro', monthly_price=149, annual_price=1490)

# Los demás planes se asignan a mano (piloto, instituciones): sin topes y con todas las funciones.
PLANS = {
    Plan.FREE: FREE,
    Plan.TEACHER: TEACHER,
    Plan.TEACHER_PLUS: replace(TEACHER, key=Plan.TEACHER_PLUS, name='Plus', monthly_price=None, annual_price=None),
    Plan.BASIC: replace(TEACHER, key=Plan.BASIC, name='Institución Básico', monthly_price=None, annual_price=None),
    Plan.STANDARD: replace(TEACHER, key=Plan.STANDARD, name='Institución Estándar', monthly_price=None, annual_price=None),
    Plan.ENTERPRISE: replace(TEACHER, key=Plan.ENTERPRISE, name='Institución Enterprise', monthly_price=None, annual_price=None),
}

# Lo que se mide y lo que se promete, con el nombre que ve el docente (en este orden).
LIMITS = (
    ('groups', 'Grupos activos'),
    ('students', 'Alumnos en grupos activos'),
    ('questions', 'Preguntas en el banco'),
)
FEATURES = (
    ('timed_quizzes', 'Quizzes con tiempo límite'),
    ('custom_workbook', 'Excel con las columnas que elijas, en tu orden'),
    ('clean_transcripts', 'Boletas en PDF sin marca de agua'),
)
LIMIT_KEYS = tuple(key for key, _ in LIMITS)
FEATURE_KEYS = tuple(key for key, _ in FEATURES)


def comparison_rows():
    """Gratis frente a Pro, fila por fila: topes (``None`` = sin tope) y funciones (``feature=True``, sí/no)."""
    return [
        {'label': label, 'free': FREE.limit(key), 'paid': TEACHER.limit(key)} for key, label in LIMITS
    ] + [
        {'label': label, 'free': FREE.has(key), 'paid': TEACHER.has(key), 'feature': True} for key, label in FEATURES
    ]


def spec_for(plan_key):
    """El ``PlanSpec`` de un valor de ``Organization.plan``; uno desconocido se trata como Gratis (lo más prudente)."""
    return PLANS.get(plan_key, FREE)
