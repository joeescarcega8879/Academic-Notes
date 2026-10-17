import factory

from apps.accounts.tests.factories import StudentFactory
from apps.courses.tests.factories import CourseFactory

from apps.messaging.models import Conversation, Message


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation
        django_get_or_create = ("course", "student")

    course = factory.SubFactory(CourseFactory)
    student = factory.SubFactory(StudentFactory)


class MessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    sender = factory.LazyAttribute(lambda o: o.conversation.student)
    body = "Hola"
