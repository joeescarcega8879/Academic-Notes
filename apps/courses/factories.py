import factory

from apps.accounts.factories import ProfessorFactory, StudentFactory

from .models import Enrollment, Course


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Materia {n}")
    code = factory.Sequence(lambda n: f"MAT{n:03d}")
    professor = factory.SubFactory(ProfessorFactory)


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    student = factory.SubFactory(StudentFactory)
    course = factory.SubFactory(CourseFactory)
