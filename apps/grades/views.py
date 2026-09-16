import csv

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.db.models import Sum, F
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from .models import Grade
from .forms import GradeForm

class GradeAccessMixin(LoginRequiredMixin, UserPassesTestMixin):

    def test_func(self):
        return self.request.user.role in ('professor', 'student')

    def handle_no_permission(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'student':
            return redirect('student_dashboard')
        if user.role == 'professor':
            return redirect('professor_dashboard')
        return redirect('profile')

class ProfessorRequiredMixin(UserPassesTestMixin):
    """Solo el profesor puede crear/editar/eliminar calificaciones."""
    def test_func(self):
        return self.request.user.role == 'professor'

    def handle_no_permission(self):
        user = self.request.user
        if not user.is_authenticated:
            return super().handle_no_permission()
        if user.role == 'student':
            return redirect('student_dashboard')
        return redirect('profile')

class GradeListView(GradeAccessMixin, ListView):
    model = Grade
    template_name = 'calificaciones.html'
    context_object_name = 'grades'

    def get_queryset(self):
        user = self.request.user
        qs = Grade.objects.select_related('student', 'evaluation__subject')
        if user.role == 'student':
            return qs.filter(student=user)
        return qs.filter(evaluation__subject__professor=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Promedio ponderado (peso = weight de la evaluación)
        agg = self.get_queryset().aggregate(
            total_weight=Coalesce(Sum('evaluation__weight'), 0.0),
            weighted=Coalesce(Sum(F('score') * F('evaluation__weight')), 0.0),
        )
        average = agg['weighted'] / agg['total_weight'] if agg['total_weight'] else None
        context['average'] = round(average, 2) if average is not None else None

        if user.role == 'professor':
            context['subjects'] = user.subjects.prefetch_related('evaluations')
        else:
            context['subjects'] = user.enrollments.select_related('subject')
        return context

class GradeCreateView(ProfessorRequiredMixin, CreateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm
    success_url = reverse_lazy('grades:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

class GradeUpdateView(ProfessorRequiredMixin, UpdateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm
    success_url = reverse_lazy('grades:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_queryset(self):
        # solo calificaciones de sus materias
        return Grade.objects.filter(evaluation__subject__professor=self.request.user)

class GradeExportView(GradeAccessMixin, View):
    """Exporta a CSV las calificaciones que el usuario puede ver."""

    def get(self, request):
        user = request.user
        grades = Grade.objects.select_related('student', 'evaluation__subject')

        if user.role == 'student':
            grades = grades.filter(student=user)
        else:
            grades = grades.filter(evaluation__subject__professor=user)

        subject_id = request.GET.get('materia')
        if subject_id:
            grades = grades.filter(evaluation__subject_id=subject_id)

        desde = request.GET.get('desde')
        hasta = request.GET.get('hasta')
        if desde:
            grades = grades.filter(graded_at__date__gte=desde)
        if hasta:
            grades = grades.filter(graded_at__date__lte=hasta)

        grades = grades.order_by(
            'evaluation__subject__name', 'student__last_name', 'evaluation__date',
        )

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="calificaciones-%s.csv"' % timezone.localdate().isoformat()
        )
        response.write('\ufeff')  # BOM para que Excel respete los acentos

        writer = csv.writer(response)
        show_student = user.role == 'professor'
        header = ['Materia', 'Evaluación', 'Tipo', 'Fecha', 'Peso', 'Calificación', 'Máximo', 'Comentario']
        if show_student:
            header = ['Alumno', 'Email'] + header
        writer.writerow(header)

        for grade in grades:
            evaluation = grade.evaluation
            row = [
                evaluation.subject.name,
                evaluation.title,
                evaluation.get_type_display(),
                evaluation.date.isoformat() if evaluation.date else '',
                evaluation.weight,
                grade.score,
                evaluation.max_score,
                grade.feedback,
            ]
            if show_student:
                row = [
                    grade.student.get_full_name() or grade.student.username,
                    grade.student.email,
                ] + row
            writer.writerow(row)

        return response


class GradeDeleteView(ProfessorRequiredMixin, DeleteView):
    model = Grade
    template_name = 'calificacion_confirm_delete.html'
    success_url = reverse_lazy('grades:list')

    def get_queryset(self):
        return Grade.objects.filter(evaluation__subject__professor=self.request.user)
