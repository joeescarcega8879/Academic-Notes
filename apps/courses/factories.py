import factory
from django.contrib.auth import get_user_model

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.organizations.factories import OrganizationFactory

from .models import Course, Enrollment, Student
from .services import student_for_user


class CourseFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Course

    name = factory.Sequence(lambda n: f"Materia {n}")
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
