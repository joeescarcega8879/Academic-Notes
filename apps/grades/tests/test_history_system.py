"""La bitácora de una actividad también muestra los cambios que hizo el sistema (sin usuario), como la nota automática de un quiz."""

import pytest
from django.urls import reverse

from apps.grades.models import Grade, GradeHistory
from apps.grades.services.gradebook import grade_activity
from apps.quizzes.factories import make_quiz

pytestmark = pytest.mark.django_db


def test_el_historial_con_cambios_del_sistema_no_revienta(professor_client, course, enrollment):
    quiz = make_quiz(course, questions=1)
    grade_activity(quiz.activity, enrollment.student, score=1, source=Grade.Source.QUIZ)  # sin ``by``: lo hace el sistema
    assert GradeHistory.objects.get().changed_by is None
    response = professor_client.get(reverse("grades:activity_history", args=[quiz.activity.pk]))
    assert response.status_code == 200 and "Sistema" in response.content.decode()


def test_el_historial_nombra_a_quien_califico(professor_client, professor, course, enrollment, activity):
    grade_activity(activity, enrollment.student, score=7, by=professor)
    html = professor_client.get(reverse("grades:activity_history", args=[activity.pk])).content.decode()
    assert professor.get_full_name() in html or professor.email in html
