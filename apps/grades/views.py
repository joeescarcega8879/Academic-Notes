import csv
from datetime import date

from django.http import HttpResponse, HttpResponseBadRequest
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from apps.accounts.mixins import OrganizationMemberMixin, TeacherRequiredMixin
from apps.subjects.models import Enrollment, Subject

from .models import Grade
from .forms import GradeForm
from .services.grading import weighted_average

def visible_grades(request):
    """Calificaciones que el usuario puede ver en la organización activa.

    El alumno ve las suyas; quien da clase, las de sus materias.
    """
    grades = Grade.objects.for_organization(request.organization).select_related('student', 'evaluation__subject')
    if request.membership.is_student:
        return grades.filter(student=request.user)
    return grades.filter(evaluation__subject__professor=request.user)


class GradeListView(OrganizationMemberMixin, ListView):
    model = Grade
    template_name = 'calificaciones.html'
    context_object_name = 'grades'

    def get_queryset(self):
        return visible_grades(self.request)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Promedio ponderado sobre las mismas calificaciones que ya se listan
        context['average'] = weighted_average(context['grades'])

        organization = self.request.organization
        if self.request.membership.is_teacher:
            context['subjects'] = (
                Subject.objects.for_organization(organization).filter(professor=user).prefetch_related('evaluations')
            )
        else:
            context['subjects'] = (
                Enrollment.objects.for_organization(organization).filter(student=user).select_related('subject')
            )
        return context

class GradeCreateView(TeacherRequiredMixin, CreateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm
    success_url = reverse_lazy('grades:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['organization'] = self.request.organization
        return kwargs

class GradeUpdateView(TeacherRequiredMixin, UpdateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm
    success_url = reverse_lazy('grades:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['organization'] = self.request.organization
        return kwargs

    def get_queryset(self):
        # solo calificaciones de sus materias, en la organización activa
        return visible_grades(self.request)

class GradeExportView(OrganizationMemberMixin, View):
    """Exporta a CSV las calificaciones que el usuario puede ver."""

    def get(self, request):
        grades = visible_grades(request)

        subject_id = request.GET.get('materia', '').strip()
        if subject_id:
            if not subject_id.isdigit():
                return HttpResponseBadRequest('El parámetro "materia" debe ser un número.')
            grades = grades.filter(evaluation__subject_id=int(subject_id))

        for param, lookup in (('desde', 'graded_at__date__gte'), ('hasta', 'graded_at__date__lte')):
            raw = request.GET.get(param, '').strip()
            if not raw:
                continue
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                return HttpResponseBadRequest('El parámetro "%s" debe tener el formato AAAA-MM-DD.' % param)
            grades = grades.filter(**{lookup: day})

        grades = grades.order_by(
            'evaluation__subject__name', 'student__last_name', 'evaluation__date',
        )

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="calificaciones-%s.csv"' % timezone.localdate().isoformat()
        )
        response.write('\ufeff')  # BOM para que Excel respete los acentos

        writer = csv.writer(response)
        show_student = request.membership.is_teacher
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


class GradeDeleteView(TeacherRequiredMixin, DeleteView):
    model = Grade
    template_name = 'calificacion_confirm_delete.html'
    success_url = reverse_lazy('grades:list')

    def get_queryset(self):
        return visible_grades(self.request)
