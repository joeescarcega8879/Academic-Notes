"""Banco de preguntas: validar y guardar preguntas con sus opciones."""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.organizations import limits
from apps.organizations.models import Membership

from ..models import Choice, Question
from .answers import normalize

MIN_CHOICES = 2
MAX_CHOICES = 8
TRUE_FALSE_LABELS = ('Verdadero', 'Falso')
MAX_ACCEPTED_LENGTH = 200
MAX_CHOICE_LENGTH = 500

# «No toques el grupo» en ``save_question`` (``None`` ya significa «pregunta general»).
UNSET = object()


def teaching_courses(user, organization):
    """Los grupos activos de ``user`` en la organización: donde puede crear preguntas y armar quizzes."""
    from apps.courses.models import Course

    return Course.objects.for_organization(organization).filter(professor=user, status=Course.Status.ACTIVE)


def bank_courses(user, organization):
    """Los grupos de ``user`` con banco: los activos y los archivados que aún conservan preguntas."""
    from apps.courses.models import Course

    return Course.objects.for_organization(organization).filter(professor=user).filter(
        Q(status=Course.Status.ACTIVE) | Q(bank_questions__isnull=False),
    ).distinct().order_by('name')


def visible_questions(organization, user):
    """Las preguntas que ``user`` ve en el banco: las de sus grupos y las generales (sin grupo)."""
    from ..models import Question

    return Question.objects.for_organization(organization).filter(Q(course__isnull=True) | Q(course__professor=user))


def questions_for_course(organization, course):
    """Las preguntas que se pueden poner en un quiz de ``course``: las de su banco y las generales."""
    from ..models import Question

    return Question.objects.for_organization(organization).filter(Q(course=course) | Q(course__isnull=True))


def validate_choices(choices):
    """Opciones de una pregunta de opción múltiple: ``[(texto, es_correcta), ...]`` -> lista limpia.

    Exige entre 2 y 8 opciones con texto, sin repetidas, y exactamente una correcta. Las opciones en blanco se
    ignoran (los formularios traen filas vacías de sobra).
    """
    cleaned = [(text.strip(), bool(correct)) for text, correct in choices if text and text.strip()]
    if len(cleaned) < MIN_CHOICES:
        raise ValidationError(f'Escribe al menos {MIN_CHOICES} opciones.')
    if len(cleaned) > MAX_CHOICES:
        raise ValidationError(f'Máximo {MAX_CHOICES} opciones.')
    texts = [text.casefold() for text, _ in cleaned]
    if len(set(texts)) != len(texts):
        raise ValidationError('Hay opciones repetidas.')
    if sum(1 for _, correct in cleaned if correct) != 1:
        raise ValidationError('Marca exactamente una respuesta correcta.')
    return cleaned


def validate_accepted(answers):
    """Respuestas que acepta una pregunta de respuesta corta: ``[(texto, _), ...]`` -> ``[(texto, True), ...]``.

    Exige de 1 a 8 con texto, sin repetidas una vez normalizadas (mayúsculas, acentos y signos no las distinguen).
    """
    cleaned = [text.strip() for text, _ in answers if text and text.strip()]
    if not cleaned:
        raise ValidationError('Escribe al menos una respuesta que se acepte.')
    if len(cleaned) > MAX_CHOICES:
        raise ValidationError(f'Máximo {MAX_CHOICES} respuestas aceptadas.')
    if any(len(text) > MAX_ACCEPTED_LENGTH for text in cleaned):
        raise ValidationError(f'Una respuesta aceptada no puede pasar de {MAX_ACCEPTED_LENGTH} caracteres.')
    normalized = [normalize(text) for text in cleaned]
    if not all(normalized):
        raise ValidationError('Una respuesta aceptada necesita letras o números.')
    if len(set(normalized)) != len(normalized):
        raise ValidationError('Hay respuestas repetidas: mayúsculas, acentos y signos no cuentan como diferencia.')
    return [(text, True) for text in cleaned]


def validate_items(items):
    """Elementos de una pregunta de ordenar, ya en el orden correcto: ``[(texto, _), ...]`` -> ``[(texto, False), ...]``.

    Exige de 2 a 8 con texto y sin repetidos (mayúsculas y acentos no los distinguen).
    """
    cleaned = [text.strip() for text, _ in items if text and text.strip()]
    if len(cleaned) < MIN_CHOICES:
        raise ValidationError(f'Escribe al menos {MIN_CHOICES} elementos para ordenar.')
    if len(cleaned) > MAX_CHOICES:
        raise ValidationError(f'Máximo {MAX_CHOICES} elementos.')
    if any(len(text) > MAX_CHOICE_LENGTH for text in cleaned):
        raise ValidationError(f'Un elemento no puede pasar de {MAX_CHOICE_LENGTH} caracteres.')
    if len({normalize(text) or text.casefold() for text in cleaned}) != len(cleaned):
        raise ValidationError('Hay elementos repetidos.')
    return [(text, False) for text in cleaned]


def can_edit_question(user, membership, question):
    """Edita la autora o el autor, o quien es propietario de la organización."""
    if question.author_id == user.pk:
        return True
    return membership is not None and membership.role == Membership.Role.OWNER


@transaction.atomic
def save_question(
    *, organization, author, kind, text, points, explanation='', topic='',
    choices=None, true_is_correct=None, question=None, course=UNSET, ai_generated=False,
):
    """Crea o actualiza una pregunta con sus opciones.

    Opción múltiple: ``choices`` es ``[(texto, es_correcta), ...]``. Verdadero o falso: ``true_is_correct`` dice si
    la respuesta correcta es "Verdadero". Respuesta corta: ``choices`` son las respuestas que se aceptan. Respuesta
    abierta: no lleva opciones. El tipo de una pregunta existente no cambia.

    ``course`` es el grupo del banco (``None``: pregunta general). Sin indicarlo, una pregunta nueva es general y
    una existente conserva su grupo. ``ai_generated`` marca la pregunta como propuesta por la IA y aprobada por el docente.
    """
    if question is not None and question.kind != kind:
        raise ValidationError('El tipo de una pregunta no se puede cambiar.')
    if question is not None and question.organization_id != organization.pk:
        raise ValidationError('La pregunta es de otra organización.')
    if course is not UNSET and course is not None and course.organization_id != organization.pk:
        raise ValidationError('El grupo es de otra organización.')

    if kind == Question.Kind.TRUE_FALSE:
        if true_is_correct is None:
            raise ValidationError('Indica si la respuesta correcta es verdadero o falso.')
        rows = [(TRUE_FALSE_LABELS[0], bool(true_is_correct)), (TRUE_FALSE_LABELS[1], not true_is_correct)]
    elif kind == Question.Kind.MULTIPLE_CHOICE:
        rows = validate_choices(choices or [])
    elif kind == Question.Kind.SHORT_ANSWER:
        rows = validate_accepted(choices or [])
    elif kind == Question.Kind.OPEN:
        rows = []  # no tiene respuestas que comparar: la califica el docente
    elif kind == Question.Kind.ORDERING:
        rows = validate_items(choices or [])  # en el orden correcto; el alumno los verá revueltos
    else:
        raise ValidationError('Tipo de pregunta desconocido.')

    if question is None:
        limits.check_limit(organization, 'questions')  # crear una pregunta cuenta contra el banco del plan
        question = Question(organization=organization, author=author, kind=kind, ai_generated=ai_generated)
    if course is not UNSET:
        question.course = course
    question.text = text.strip()
    question.points = points
    question.explanation = explanation.strip()
    question.topic = topic.strip()
    question.full_clean(exclude=['author'])
    question.save()

    question.choices.all().delete()
    for position, (choice_text, correct) in enumerate(rows):
        Choice.objects.create(question=question, text=choice_text, is_correct=correct, position=position)
    return question


@transaction.atomic
def copy_bank(source, clone):
    """Copia al banco de ``clone`` las preguntas vigentes del banco de ``source``, con sus opciones y sin cambiar su texto.

    Las archivadas y las generales (que ya sirven en todos los grupos) no se copian. Devuelve cuántas copió. Las copias
    cuentan contra el tope de preguntas del plan: si no caben todas, no se copia ninguna y lanza ``PlanLimitError``.
    """
    questions = list(source.bank_questions.filter(is_archived=False).prefetch_related('choices').order_by('id'))
    if not questions:
        return 0
    limits.check_limit(clone.organization, 'questions', adding=len(questions))
    for question in questions:
        copy = Question.objects.create(
            organization=question.organization, author=question.author, course=clone, kind=question.kind, text=question.text,
            points=question.points, explanation=question.explanation, topic=question.topic, ai_generated=question.ai_generated,
        )
        for choice in question.choices.all():
            Choice.objects.create(question=copy, text=choice.text, is_correct=choice.is_correct, position=choice.position)
    return len(questions)


@transaction.atomic
def duplicate_question(question, *, by, course=UNSET):
    """Copia una pregunta (con sus opciones) a nombre de ``by``, lista para editar.

    La copia queda en el mismo grupo, o en ``course`` (``None``: general) si se indica: así se reutiliza una pregunta
    en el banco de otro grupo.
    """
    copy = save_question(
        organization=question.organization, author=by, kind=question.kind, text=f'{question.text} (copia)',
        points=question.points, explanation=question.explanation, topic=question.topic,
        course=question.course if course is UNSET else course,
        choices=[(c.text, c.is_correct) for c in question.choices.all()] if question.kind in (
            Question.Kind.MULTIPLE_CHOICE, Question.Kind.SHORT_ANSWER, Question.Kind.ORDERING,
        ) else None,
        true_is_correct=(
            next(c.is_correct for c in question.choices.all() if c.text == TRUE_FALSE_LABELS[0])
            if question.kind == Question.Kind.TRUE_FALSE else None
        ),
    )
    return copy
