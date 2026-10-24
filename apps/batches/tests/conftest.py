import datetime

import pytest
from django.utils import timezone

from apps.batches.tests.factories import inscribir
from apps.grades.models import Activity
from apps.grades.tests.factories import ActivityFactory


@pytest.fixture
def tarea(course):
    """Una tarea cuya fecha límite ya pasó: lo que entra por el lote no debe salir como tardía."""
    return ActivityFactory(
        course=course, type=Activity.Type.HOMEWORK, due_at=timezone.now() - datetime.timedelta(days=3), allow_late=True,
        late_penalty=20,
    )


@pytest.fixture
def ana(course):
    return inscribir(course, '20240001', 'Ana', 'Pérez')


@pytest.fixture
def beto(course):
    return inscribir(course, '20240002', 'Beto', 'Gómez')
