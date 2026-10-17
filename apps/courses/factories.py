import datetime

import factory
from django.contrib.auth import get_user_model

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.organizations.tests.factories import OrganizationFactory

from .models import AcademicYear, Course, Enrollment, Student
from .services.students import student_for_user


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Grupo {n}")
    code = factory.Sequence(lambda n: f"MAT{n:03d}")
    professor = factory.SubFactory(ProfessorFactory)


class StudentRecordFactory(factory.django.DjangoModelFactory):
    """Alumno de una lista. Por defecto con cuenta enlazada; ``user=None`` para uno sin cuenta."""

    class Meta:
        model = Student

    organization = factory.SubFactory(OrganizationFactory)
    user = factory.SubFactory(StudentFactory)
    # Con cuenta, la ficha toma sus datos de ella (como student_for_user); sin cuenta, datos propios.
    first_name = factory.LazyAttribute(lambda o: o.user.first_name if o.user else "Nombre")
    last_name = factory.LazyAttribute(lambda o: o.user.last_name if o.user else "Apellido")
    email = factory.LazyAttribute(lambda o: o.user.email if o.user else "")


def as_student(value, organization):
    """Acepta una cuenta (``User``) donde se espera un ``Student``: usa o crea su ficha en la organización."""
    return student_for_user(value, organization) if isinstance(value, get_user_model()) else value


class EnrollmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Enrollment

    course = factory.SubFactory(CourseFactory)
    student = factory.SubFactory(StudentRecordFactory, organization=factory.SelfAttribute('..course.organization'))

    @classmethod
    def _adjust_kwargs(cls, **kwargs):
        kwargs['student'] = as_student(kwargs['student'], kwargs['course'].organization)
        return kwargs


class AcademicYearFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AcademicYear

    organization = factory.SubFactory(OrganizationFactory)
    name = factory.Sequence(lambda n: f"Ciclo {n}")
    start_date = datetime.date(2026, 8, 1)
    end_date = datetime.date(2027, 7, 31)
