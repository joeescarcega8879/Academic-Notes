from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Count
from django.shortcuts import redirect
from django.views.generic import TemplateView, DetailView

from .models import Subject, Enrollment

# Un alumno aprueba al alcanzar el 60% del puntaje máximo de la evaluación.
PASS_RATIO = 0.6

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
        grades = (
            Grade.objects
            .filter(evaluation__subject__professor=user)
            .select_related('evaluation')
        )

        # Estadísticas por materia: promedio ponderado y tasa de aprobación
        per_subject = {}
        for grade in grades:
            stats = per_subject.setdefault(
                grade.evaluation.subject_id,
                {'weight': 0.0, 'weighted': 0.0, 'count': 0, 'passed': 0},
            )
            stats['weight'] += grade.evaluation.weight
            stats['weighted'] += grade.score * grade.evaluation.weight
            stats['count'] += 1
            if grade.score >= grade.evaluation.max_score * PASS_RATIO:
                stats['passed'] += 1

        total_weight = 0.0
        total_weighted = 0.0
        total_count = 0
        total_passed = 0
        for subject in subjects:
            stats = per_subject.get(subject.pk)
            if stats and stats['weight']:
                subject.average = round(stats['weighted'] / stats['weight'], 2)
                total_weight += stats['weight']
                total_weighted += stats['weighted']
            else:
                subject.average = None
            subject.pass_rate = round(stats['passed'] * 100 / stats['count']) if stats and stats['count'] else None
            if stats:
                total_count += stats['count']
                total_passed += stats['passed']

        context['subjects'] = subjects
        context['total_evaluations'] = Evaluation.objects.filter(subject__professor=user).count()
        context['graded_count'] = total_count
        context['group_average'] = round(total_weighted / total_weight, 2) if total_weight else None
        context['pass_rate'] = round(total_passed * 100 / total_count) if total_count else None
        
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
