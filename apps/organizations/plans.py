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
    ai_assistant: bool = False
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

# Plus = Pro + toda la IA (sección 13 de ``New_Phases.md``). Precio de lista: hipótesis a ajustar con el costo real de la IA.
PLUS = replace(TEACHER, key=Plan.TEACHER_PLUS, name='Plus', ai_assistant=True, monthly_price=249, annual_price=2490)

# Los demás planes se asignan a mano (piloto, instituciones): sin topes y con las funciones de Pro.
PLANS = {
    Plan.FREE: FREE,
    Plan.TEACHER: TEACHER,
    Plan.TEACHER_PLUS: PLUS,
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
# Lo que promete Plus. La IA todavía no está construida, así que no entra en ``FEATURES`` (lo que se mide y se aplica).
AI_PROMISES = (
    'Genera tareas, quizzes y exámenes desde tu temario',
    'Calificación asistida de tareas con código anónimo del alumno',
    'Tú apruebas todo: nada llega a tus alumnos sin tu visto bueno',
    'Cuota mensual de usos de IA',
)
LIMIT_KEYS = tuple(key for key, _ in LIMITS)
FEATURE_KEYS = tuple(key for key, _ in FEATURES)


def comparison_rows():
    """Gratis frente a Pro (Plus no cambia nada aquí), fila por fila: topes (``None`` = sin tope) y funciones (``feature=True``)."""
    return [
        {'label': label, 'free': FREE.limit(key), 'paid': TEACHER.limit(key), 'plus': PLUS.limit(key)} for key, label in LIMITS
    ] + [
        {'label': label, 'free': FREE.has(key), 'paid': TEACHER.has(key), 'plus': PLUS.has(key), 'feature': True} for key, label in FEATURES
    ]


def public_comparison_rows():
    """La tabla de la página de Precios: las filas de siempre y la IA, que solo trae Plus."""
    return comparison_rows() + [
        {'label': 'IA para planear y calificar', 'free': False, 'paid': False, 'plus': PLUS.ai_assistant, 'feature': True},
    ]


def spec_for(plan_key):
    """El ``PlanSpec`` de un valor de ``Organization.plan``; uno desconocido se trata como Gratis (lo más prudente)."""
    return PLANS.get(plan_key, FREE)
