from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.shortcuts import redirect
from django.views.generic import TemplateView, DetailView

from apps.grades.services.grading import grade_stats, stats_by_subject

from .models import Subject, Enrollment

class ProfessorDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):

    template_name = "dashboard-profesor.html"

    def test_func(self):
        return self.request.user.role == 'professor'

    def handle_no_permission(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'student':
            return redirect('student_dashboard')
        return redirect('profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Evaluation, Grade

        user = self.request.user
        subjects = list(user.subjects.annotate(student_count=Count('enrollments')))
        grades = list(
            Grade.objects
            .filter(evaluation__subject__professor=user)
            .select_related('evaluation')
        )

        per_subject = stats_by_subject(grades)
        for subject in subjects:
            stats = per_subject.get(subject.pk)
            subject.average = stats.average if stats else None
            subject.pass_rate = stats.pass_rate if stats else None

        overall = grade_stats(grades)
        context['subjects'] = subjects
        context['total_evaluations'] = Evaluation.objects.filter(subject__professor=user).count()
        context['graded_count'] = overall.count
        context['group_average'] = overall.average
        context['pass_rate'] = overall.pass_rate

        context['total_students'] = (
            Enrollment.objects
            .filter(subject__professor=user)
            .values('student')
            .distinct()
            .count()
        )
        return context

class StudentDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):

    template_name = 'dashboard-alumno.html'

    def test_func(self):
        return self.request.user.role == 'student'

    def handle_no_permission(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'professor':
            return redirect('professor_dashboard')
        return redirect('profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Grade

        enrollments = list(
            self.request.user.enrollments
            .select_related('subject', 'subject__professor')
        )

        # Promedio ponderado del alumno (general y por materia)
        grades = list(Grade.objects.filter(student=self.request.user).select_related('evaluation'))

        per_subject = stats_by_subject(grades)
        for e in enrollments:
            stats = per_subject.get(e.subject_id)
            e.subject_average = stats.average if stats else None

        context['enrollments'] = enrollments
        context['average'] = grade_stats(grades).average
        return context

class SubjectDetailView(LoginRequiredMixin, DetailView):

    model = Subject
    template_name = 'materia.html'
    context_object_name = 'subject'

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == 'professor':
            return qs.filter(professor=user)
        return qs.filter(enrollments__student=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['enrollments'] = self.object.enrollments.select_related('student')
        context['my_enrollment'] = self.object.enrollments.filter(student=user).first()

        # Vista alumno: evaluaciones de la materia + su calificación
        if user.role == 'student':
            from apps.grades.models import Grade

            my_grades = {
                g.evaluation_id: g
                for g in Grade.objects.filter(student=user, evaluation__subject=self.object).select_related('evaluation')
            }
            rows = [
                {'evaluation': evaluation, 'grade': my_grades.get(evaluation.id)}
                for evaluation in self.object.evaluations.all()
            ]

            context['evaluation_rows'] = rows
            context['subject_average'] = grade_stats(my_grades.values()).average
        return context
