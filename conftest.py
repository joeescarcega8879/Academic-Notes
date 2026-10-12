"""Fixtures compartidas por toda la suite."""

import pytest
from django.test import Client

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.grades.factories import ActivityFactory
from apps.courses.factories import EnrollmentFactory, CourseFactory


@pytest.fixture
def professor(db):
    return ProfessorFactory()


@pytest.fixture
def student(db):
    return StudentFactory()


@pytest.fixture
def course(professor):
    return CourseFactory(professor=professor)


@pytest.fixture
def enrollment(course, student):
    return EnrollmentFactory(course=course, student=student)


@pytest.fixture
def activity(course):
    return ActivityFactory(course=course)


def _client_for(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def professor_client(professor):
    return _client_for(professor)


@pytest.fixture
def student_client(student):
    return _client_for(student)
