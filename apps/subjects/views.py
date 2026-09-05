from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.shortcuts import redirect
from django.views.generic import TemplateView, DetailView

from .models import Subject, Enrollment

class ProfessorDashboardView(LoginRequiredMixin, UserPassesTestMixin, TemplateView):

    template_name = "dashboard-profesor.html"

    def test_func(self):
        return self.request.user.role == 'professor'

    def handle_no_permission(self):
        user = self.request.user
        if user.role == 'student':
            return redirect('student_dashboard')
        return redirect('profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['subjects'] = (
            self.request.user.subjects.annotate(student_count=Count('enrollments')))
        
        context['total_students'] = (
            Enrollment.objects
            .filter(subject__professor=self.request.user)
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
        if user.role == 'professor':
            return redirect('professor_dashboard')
        return redirect('profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['enrollments'] = (
            self.request.user.enrollments
            .select_related('subject', 'subject__professor')
        )
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
        context['enrollments'] = self.object.enrollments.select_related('student')
        return context
