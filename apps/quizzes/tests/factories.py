import factory
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory
from apps.grades.tests.factories import ActivityFactory
from apps.grades.models import Activity
from apps.organizations.services import teaching_organization

from apps.quizzes.models import Answer, Question, QuizAttempt
from apps.quizzes.services.bank import save_question
from apps.quizzes.services.builder import add_questions

DEFAULT_CHOICES = [('Opción A', True), ('Opción B', False), ('Opción C', False)]


class QuestionFactory(factory.django.DjangoModelFactory):
    """Pregunta válida del banco (con sus opciones). Por defecto, de opción múltiple en la organización de su autor."""

    class Meta:
        model = Question

    author = factory.SubFactory(ProfessorFactory)
    organization = factory.LazyAttribute(lambda o: teaching_organization(o.author))
    course = None  # el grupo del banco; sin él, una pregunta general
    kind = Question.Kind.MULTIPLE_CHOICE
    text = factory.Sequence(lambda n: f'Pregunta {n}')
    points = 1
    explanation = ''
    topic = ''
    choices = None  # [(texto, es_correcta), ...] para opción múltiple; las respuestas aceptadas en una respuesta corta y los elementos, en orden, al ordenar
    true_is_correct = True  # para verdadero o falso

    @classmethod
    def _create(cls, model_class, *args, choices=None, true_is_correct=True, **kwargs):
        kind = kwargs['kind']
        return save_question(
            organization=kwargs['organization'], author=kwargs['author'], kind=kind, text=kwargs['text'],
            points=kwargs['points'], explanation=kwargs['explanation'], topic=kwargs['topic'], course=kwargs['course'],
            choices=(choices or DEFAULT_CHOICES) if kind == Question.Kind.MULTIPLE_CHOICE else (
                choices if kind in (Question.Kind.SHORT_ANSWER, Question.Kind.ORDERING, Question.Kind.MATCHING) else None
            ),
            true_is_correct=true_is_correct if kind == Question.Kind.TRUE_FALSE else None,
        )


def make_quiz(course, questions=2, *, published=True, points=1, **config):
    """Quiz armado en ``course``: una actividad de tipo quiz con ``questions`` preguntas de opción múltiple.

    La primera opción de cada pregunta ("Opción A") es la correcta. ``config`` ajusta su ``QuizConfig``
    (intentos, tiempo límite, orden, retroalimentación, política) y el resto de argumentos de la actividad se
    pasan con ``activity=`` si hace falta algo especial.
    """
    activity_options = config.pop('activity', {})
    activity = ActivityFactory(course=course, type=Activity.Type.QUIZ, published=False, **activity_options)
    quiz = activity.quiz
    for field, value in config.items():
        setattr(quiz, field, value)
    quiz.save()
    bank = [
        QuestionFactory(author=course.professor, organization=course.organization, points=points)
        for _ in range(questions)
    ]
    if bank:
        add_questions(quiz, bank)
    if published and bank:
        activity.published = True
        activity.save()
    return quiz


class QuizAttemptFactory(factory.django.DjangoModelFactory):
    """Intento ya enviado (sin respuestas). Para uno en curso: ``status='in_progress'``."""

    class Meta:
        model = QuizAttempt

    number = 1
    status = QuizAttempt.Status.SUBMITTED
    started_at = factory.LazyFunction(timezone.now)
    submitted_at = factory.LazyFunction(timezone.now)
    score = 0
    max_points = 0


def answer(attempt, question, choice=None):
    """Respuesta del alumno a ``question`` (sin calificar)."""
    return Answer.objects.create(attempt=attempt, question=question, choice=choice)
