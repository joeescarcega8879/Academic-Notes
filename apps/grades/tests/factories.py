import factory

from apps.courses.tests.factories import CourseFactory, StudentRecordFactory, as_student

from apps.grades.models import Activity, Grade


def _rubric_for(course):
    from apps.rubrics.tests.factories import make_rubric

    return make_rubric(course.professor, organization=course.organization).current_version


class ActivityFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Activity

    course = factory.SubFactory(CourseFactory)
    title = factory.Sequence(lambda n: f"Evaluación {n}")
    type = Activity.Type.EXAM
    max_score = 10.0
    weight = 1.0
    # Las pruebas tratan a las actividades como normales; el borrador se pide explícitamente. Un quiz nace en
    # borrador porque no se puede publicar sin preguntas.
    published = factory.LazyAttribute(lambda o: o.type != Activity.Type.QUIZ)
    # Un proyecto se califica siempre con rúbrica: el de las pruebas ya trae una (rubric_version=None para quitársela).
    rubric_version = factory.LazyAttribute(lambda o: _rubric_for(o.course) if o.type == Activity.Type.PROJECT else None)


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
