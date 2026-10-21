import factory

from apps.courses.tests.factories import CourseFactory

from apps.syllabus.models import Syllabus, SyllabusWeek


class SyllabusFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Syllabus

    course = factory.SubFactory(CourseFactory)
    text = 'Semana 1: Números reales\nTemas: reales, intervalos'
    status = Syllabus.Status.READY


class SyllabusWeekFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = SyllabusWeek

    syllabus = factory.SubFactory(SyllabusFactory)
    position = factory.Sequence(lambda n: n + 1)
    title = factory.Sequence(lambda n: f'Semana de prueba {n}')
    topics = 'Tema A\nTema B'
