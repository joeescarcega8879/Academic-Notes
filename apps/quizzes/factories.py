import factory

from apps.accounts.factories import ProfessorFactory
from apps.organizations.services import teaching_organization

from .models import Question
from .services.bank import save_question

DEFAULT_CHOICES = [('Opción A', True), ('Opción B', False), ('Opción C', False)]


class QuestionFactory(factory.django.DjangoModelFactory):
    """Pregunta válida del banco (con sus opciones). Por defecto, de opción múltiple en la organización de su autor."""

    class Meta:
        model = Question

    author = factory.SubFactory(ProfessorFactory)
    organization = factory.LazyAttribute(lambda o: teaching_organization(o.author))
    kind = Question.Kind.MULTIPLE_CHOICE
    text = factory.Sequence(lambda n: f'Pregunta {n}')
    points = 1
    explanation = ''
    topic = ''
    choices = None  # [(texto, es_correcta), ...] para opción múltiple
    true_is_correct = True  # para verdadero o falso

    @classmethod
    def _create(cls, model_class, *args, choices=None, true_is_correct=True, **kwargs):
        kind = kwargs['kind']
        return save_question(
            organization=kwargs['organization'], author=kwargs['author'], kind=kind, text=kwargs['text'],
            points=kwargs['points'], explanation=kwargs['explanation'], topic=kwargs['topic'],
            choices=(choices or DEFAULT_CHOICES) if kind == Question.Kind.MULTIPLE_CHOICE else None,
            true_is_correct=true_is_correct if kind == Question.Kind.TRUE_FALSE else None,
        )
