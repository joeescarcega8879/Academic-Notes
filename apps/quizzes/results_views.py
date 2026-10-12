"""Resultados de un quiz para el docente: panorama del grupo, análisis por pregunta y revisión de intentos."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.grades.models import Grade

from .builder_views import OwnQuizMixin
from .models import QuizAttempt
from .services import results


class QuizResultsView(OwnQuizMixin, View):
    """Panorama del quiz: cifras generales, cada alumno y cada pregunta."""

    def get(self, request, pk):
        quiz = self.quiz
        return render(request, 'quiz_results.html', {
            'activity': self.activity, 'course': self.activity.course, 'quiz': quiz,
            'summary': results.summary(quiz), 'students': results.student_rows(quiz), 'questions': results.question_stats(quiz),
        })


class OwnAttemptMixin(TeacherRequiredMixin):
    def get_attempt(self, pk):
        return get_object_or_404(
            QuizAttempt.objects.for_organization(self.request.organization).filter(
                quiz__activity__course__professor=self.request.user,
            ).select_related('quiz__activity__course', 'student'),
            pk=pk,
        )


class AttemptReviewView(OwnAttemptMixin, View):
    """El docente ve las respuestas de un intento (siempre con las correctas)."""

    def get(self, request, pk):
        attempt = self.get_attempt(pk)
        activity = attempt.quiz.activity
        return render(request, 'attempt_review.html', {
            'attempt': attempt, 'activity': activity, 'course': activity.course, 'rows': results.review_rows(attempt),
            'grade': Grade.objects.filter(activity=activity, student=attempt.student).first(),
        })


class AttemptDeleteView(OwnAttemptMixin, View):
    """Elimina un intento para que el alumno pueda repetirlo; la calificación se recalcula."""

    def post(self, request, pk):
        attempt = self.get_attempt(pk)
        activity = attempt.quiz.activity
        if activity.course.is_archived:
            messages.error(request, 'El grupo está archivado y es de solo lectura.')
            return redirect('quizzes:results', pk=activity.pk)
        try:
            results.remove_attempt(attempt, by=request.user)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, 'Se eliminó el intento y se recalculó la calificación.')
        return redirect('quizzes:results', pk=activity.pk)
