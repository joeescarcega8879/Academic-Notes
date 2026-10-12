import factory

from apps.courses.factories import CourseFactory, StudentRecordFactory, as_student

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
    student = factory.SubFactory(StudentRecordFactory, organization=factory.SelfAttribute('..evaluation.organization'))
    score = 8.0

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        kwargs['student'] = as_student(kwargs['student'], kwargs['evaluation'].organization)
        return kwargs
