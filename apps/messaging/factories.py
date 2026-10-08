import factory

from apps.accounts.factories import StudentFactory
from apps.subjects.factories import SubjectFactory

from .models import Conversation, Message


class ConversationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Conversation
        django_get_or_create = ("subject", "student")

    subject = factory.SubFactory(SubjectFactory)
    student = factory.SubFactory(StudentFactory)


class MessageFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Message

    conversation = factory.SubFactory(ConversationFactory)
    sender = factory.LazyAttribute(lambda o: o.conversation.student)
    body = "Hola"
