import factory

from apps.accounts.factories import StudentFactory

from .models import Membership, Organization


class OrganizationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Organization

    name = factory.Sequence(lambda n: f"Organización {n}")
    type = Organization.Type.INSTITUTION


class MembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Membership

    user = factory.SubFactory(StudentFactory)
    organization = factory.SubFactory(OrganizationFactory)
    role = Membership.Role.STUDENT
