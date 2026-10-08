import factory
from django.contrib.auth import get_user_model

from .models import ProfessorProfile, StudentProfile

PASSWORD = "Prueba123!"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: f"usuario{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@prueba.test")
    first_name = "Nombre"
    last_name = factory.Sequence(lambda n: f"Apellido{n}")
    role = "student"
    password = PASSWORD

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        # El manager custom exige email y hashea la contraseña.
        return model_class.objects.create_user(**kwargs)


class ProfessorFactory(UserFactory):
    role = "professor"
    username = factory.Sequence(lambda n: f"profesor{n}")


class StudentFactory(UserFactory):
    role = "student"
    username = factory.Sequence(lambda n: f"alumno{n}")


class ProfessorProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProfessorProfile

    user = factory.SubFactory(ProfessorFactory)
    department = "Matemáticas"


class StudentProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = StudentProfile

    user = factory.SubFactory(StudentFactory)
    program = "Ingeniería"
    semester = 3
    enrollment_number = factory.Sequence(lambda n: f"A{n:05d}")
