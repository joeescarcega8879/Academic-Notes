import factory

from apps.accounts.factories import StudentFactory
from apps.courses.factories import CourseFactory

from .models import Evaluation, Grade


class EvaluationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Evaluation

    course = factory.SubFactory(CourseFactory)
    title = factory.Sequence(lambda n: f"Evaluación {n}")
    type = Evaluation.Type.EXAM
    max_score = 10.0
    weight = 1.0


class GradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Grade

    evaluation = factory.SubFactory(EvaluationFactory)
    student = factory.SubFactory(StudentFactory)
    score = 8.0
