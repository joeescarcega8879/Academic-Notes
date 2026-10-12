import factory

from apps.accounts.factories import ProfessorFactory, StudentFactory

from .models import Enrollment, Subject


class SubjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Subject

    name = factory.Sequence(lambda n: f"Materia {n}")
    code = factory.Sequence(lambda n: f"MAT{n:03d}")
    professor = factory.SubFactory(ProfessorFactory)


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    student = factory.SubFactory(StudentFactory)
    subject = factory.SubFactory(SubjectFactory)
