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
        if not user.is_authenticated:
            return super().handle_no_permission()
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
        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'professor':
            return redirect('professor_dashboard')
        return redirect('profile')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Sum, F
        from django.db.models.functions import Coalesce
        from apps.grades.models import Grade

        enrollments = list(
            self.request.user.enrollments
            .select_related('subject', 'subject__professor')
        )

        # Promedio ponderado del alumno (general y por materia)
        grades = Grade.objects.filter(student=self.request.user).select_related('evaluation')

        per_subject = {}
        for g in grades:
            d = per_subject.setdefault(g.evaluation.subject_id, {'weight': 0.0, 'weighted': 0.0})
            d['weight'] += g.evaluation.weight
            d['weighted'] += g.score * g.evaluation.weight

        for e in enrollments:
            d = per_subject.get(e.subject_id)
            e.subject_average = round(d['weighted'] / d['weight'], 2) if d and d['weight'] else None

        context['enrollments'] = enrollments

        agg = grades.aggregate(
            total_weight=Coalesce(Sum('evaluation__weight'), 0.0),
            weighted=Coalesce(Sum(F('score') * F('evaluation__weight')), 0.0),
        )
        average = agg['weighted'] / agg['total_weight'] if agg['total_weight'] else None
        context['average'] = round(average, 2) if average is not None else None
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
                for g in Grade.objects.filter(student=user, evaluation__subject=self.object)
            }
            rows = []
            weight = 0.0
            weighted = 0.0
            for evaluation in self.object.evaluations.all():
                grade = my_grades.get(evaluation.id)
                rows.append({'evaluation': evaluation, 'grade': grade})
                if grade:
                    weight += evaluation.weight
                    weighted += grade.score * evaluation.weight

            context['evaluation_rows'] = rows
            context['subject_average'] = round(weighted / weight, 2) if weight else None
        return context
