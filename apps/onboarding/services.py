"""Alta de cuentas por cuenta propia y la lista de primeros pasos del docente."""

import datetime
from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils.text import slugify

from apps.accounts.models import User
from apps.accounts.services import queue_welcome_email
from apps.courses.models import AcademicYear, Course, Enrollment
from apps.grades.models import Activity, Grade
from apps.organizations.services import ensure_individual_organization

# El ciclo escolar mexicano corre de agosto a julio.
CYCLE_START_MONTH = 8


def default_cycle(today):
    """``(nombre, inicio, fin)`` del ciclo escolar en curso en ``today``: de agosto a julio."""
    year = today.year if today.month >= CYCLE_START_MONTH else today.year - 1
    return f'{year}–{year + 1}', datetime.date(year, CYCLE_START_MONTH, 1), datetime.date(year + 1, CYCLE_START_MONTH - 1, 31)


def unique_username(email):
    """Nombre de usuario libre a partir de lo que va antes de la arroba (``ana`` → ``ana2`` si ya existe)."""
    base = (slugify(email.split('@')[0]) or 'usuario')[:140]
    candidate, suffix = base, 1
    while get_user_model().objects.filter(username__iexact=candidate).exists():
        suffix += 1
        candidate = f'{base}{suffix}'
    return candidate


def _create_user(*, first_name, last_name, email, password, role):
    email = email.strip().lower()
    if get_user_model().objects.filter(email__iexact=email).exists():
        raise ValidationError('Ya existe una cuenta con este correo.')
    try:
        with transaction.atomic():
            return get_user_model().objects.create_user(
                username=unique_username(email), email=email, password=password,
                first_name=first_name.strip(), last_name=last_name.strip(), role=role,
            )
    except IntegrityError:  # dos altas con el mismo correo a la vez
        raise ValidationError('Ya existe una cuenta con este correo.') from None


@transaction.atomic
def register_teacher(*, first_name, last_name, email, password, school_name='', today=None):
    """Alta de un docente: su cuenta, su organización individual (con su nombre o el de su escuela) y el ciclo actual."""
    user = _create_user(first_name=first_name, last_name=last_name, email=email, password=password, role=User.Role.PROFESSOR)
    organization = ensure_individual_organization(user)
    if school_name.strip():
        organization.name = school_name.strip()
        organization.save(update_fields=['name'])
    name, start, end = default_cycle(today or datetime.date.today())
    AcademicYear.objects.create(organization=organization, name=name, start_date=start, end_date=end, is_current=True)
    queue_welcome_email(user)
    return user


@transaction.atomic
def register_student(*, first_name, last_name, email, password):
    """Alta de un alumno. Sin organización todavía: la tendrá al unirse a un grupo con el código de su docente."""
    user = _create_user(first_name=first_name, last_name=last_name, email=email, password=password, role=User.Role.STUDENT)
    queue_welcome_email(user)
    return user


# ── Primeros pasos ────────────────────────────────────────────────────

@dataclass
class Step:
    key: str
    title: str
    hint: str
    done: bool
    url: str
    action: str


def teacher_steps(user, organization):
    """Los pasos para empezar a usar la libreta, con lo que ya hizo marcado. Salen de los datos, no se guardan."""
    courses = Course.objects.for_organization(organization).filter(professor=user)
    first = courses.filter(status=Course.Status.ACTIVE).order_by('id').first() or courses.order_by('id').first()
    has_students = Enrollment.objects.for_organization(organization).filter(course__in=courses).exists()
    has_activity = Activity.objects.for_organization(organization).filter(course__in=courses).exists()
    has_grade = Grade.objects.for_organization(organization).filter(activity__course__in=courses).exists()

    def link(name, *args):
        return reverse(name, args=args)

    return [
        Step('group', 'Crea tu primer grupo', 'Ponle nombre, código y el ciclo escolar.', first is not None,
             link('course_detail', first.pk) if first else link('course_create'), 'Crear grupo'),
        Step('students', 'Agrega a tus alumnos', 'Importa tu lista de Excel o CSV, o agrégalos uno por uno.', has_students,
             link('student_import', first.pk) if first else link('course_create'), 'Importar lista'),
        Step('activity', 'Crea tu primera actividad', 'Una tarea, un examen o un quiz. Nace como borrador hasta que la publiques.',
             has_activity, link('grades:activity_create', first.pk) if first else link('course_create'), 'Crear actividad'),
        Step('grade', 'Califica en la libreta', 'Escribe las notas directo en la tabla; el promedio se calcula solo.', has_grade,
             link('grades:gradesheet', first.pk) if first else link('course_create'), 'Abrir la libreta'),
    ]
