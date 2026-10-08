"""Fixtures compartidas por toda la suite."""

import pytest
from django.test import Client

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.grades.factories import EvaluationFactory
from apps.subjects.factories import EnrollmentFactory, SubjectFactory


@pytest.fixture
def professor(db):
    return ProfessorFactory()


@pytest.fixture
def student(db):
    return StudentFactory()


@pytest.fixture
def subject(professor):
    return SubjectFactory(professor=professor)


@pytest.fixture
def enrollment(subject, student):
    return EnrollmentFactory(subject=subject, student=student)


@pytest.fixture
def evaluation(subject):
    return EvaluationFactory(subject=subject)


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
