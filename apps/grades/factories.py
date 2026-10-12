import factory

from apps.courses.factories import CourseFactory, StudentRecordFactory, as_student

from .models import Activity, Grade


class ActivityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Activity

    course = factory.SubFactory(CourseFactory)
    title = factory.Sequence(lambda n: f"Evaluación {n}")
    type = Activity.Type.EXAM
    max_score = 10.0
    weight = 1.0
    published = True  # las pruebas tratan a las actividades como normales; el borrador se pide explícitamente


class GradeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Grade

    activity = factory.SubFactory(ActivityFactory)
    student = factory.SubFactory(StudentRecordFactory, organization=factory.SelfAttribute('..activity.organization'))
    score = 8.0

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        kwargs['student'] = as_student(kwargs['student'], kwargs['activity'].organization)
        return kwargs
