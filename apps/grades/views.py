import csv
from datetime import date

from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, CreateView, UpdateView, DeleteView

from apps.accounts.mixins import OrganizationMemberMixin, TeacherRequiredMixin
from apps.courses.models import Enrollment, Course
from core.utils import csv_safe, parse_id

from .models import Grade
from .forms import GradeForm
from .services.gradebook import grade_activity, remove_grade
from .services.grading import overall_average

def visible_grades(request):
    """Calificaciones que el usuario puede ver en la organización activa.

    El alumno ve las suyas; quien da clase, las de sus grupos.
    """
    grades = Grade.objects.for_organization(request.organization).select_related('student__user', 'activity__course')
    if request.membership.is_student:
        # Un alumno no ve las actividades en borrador ni sus notas.
        return grades.filter(student__user=request.user, activity__published=True)
    return grades.filter(activity__course__professor=request.user)


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
        context['average'] = overall_average(context['grades'])

        organization = self.request.organization
        if self.request.membership.is_teacher:
            context['courses'] = (
                Course.objects.for_organization(organization).filter(professor=user).prefetch_related('activities')
            )
        else:
            context['courses'] = (
                Enrollment.objects.for_organization(organization).filter(student__user=user).select_related('course')
            )
        return context

class GradeSaveMixin:
    """Guarda la calificación por el servicio: aplica la penalización por entrega tardía y deja bitácora."""

    success_url = reverse_lazy('grades:list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        kwargs['organization'] = self.request.organization
        return kwargs

    def form_valid(self, form):
        data = form.cleaned_data
        try:
            self.object = grade_activity(
                data['activity'], data['student'], score=data['score'], feedback=data['feedback'], by=self.request.user,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        return redirect(self.get_success_url())


class GradeCreateView(GradeSaveMixin, TeacherRequiredMixin, CreateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm

    def get_initial(self):
        # Desde la pantalla de una actividad se llega con el alumno y la actividad ya elegidos.
        initial = super().get_initial()
        for name in ('activity', 'student'):
            value = parse_id(self.request.GET.get(name, ''))
            if value is not None:
                initial[name] = value
        return initial


class GradeUpdateView(GradeSaveMixin, TeacherRequiredMixin, UpdateView):
    model = Grade
    template_name = 'calificacion_form.html'
    form_class = GradeForm

    def get_queryset(self):
        # solo calificaciones de sus grupos activos, en la organización activa
        return visible_grades(self.request).filter(activity__course__status='active')

class GradeExportView(OrganizationMemberMixin, View):
    """Exporta a CSV las calificaciones que el usuario puede ver."""

    def get(self, request):
        grades = visible_grades(request)

        # ``materia`` era el nombre del parámetro antes de llamarle «grupo»: los enlaces viejos siguen sirviendo.
        course_id = (request.GET.get('grupo') or request.GET.get('materia') or '').strip()
        if course_id:
            course_id = parse_id(course_id)
            if course_id is None:
                return HttpResponseBadRequest('El parámetro "grupo" debe ser un número.')
            grades = grades.filter(activity__course_id=course_id)

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
            'activity__course__name', 'student__last_name', 'activity__date',
        )

        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = (
            'attachment; filename="calificaciones-%s.csv"' % timezone.localdate().isoformat()
        )
        response.write('\ufeff')  # BOM para que Excel respete los acentos

        writer = csv.writer(response)
        show_student = request.membership.is_teacher
        header = ['Grupo', 'Evaluación', 'Tipo', 'Fecha', 'Peso', 'Calificación', 'Máximo', 'Comentario']
        if show_student:
            header = ['Matrícula', 'Alumno', 'Email'] + header
        writer.writerow(header)

        for grade in grades:
            activity = grade.activity
            row = [
                csv_safe(activity.course.name),
                csv_safe(activity.title),
                activity.get_type_display(),
                activity.date.isoformat() if activity.date else '',
                activity.weight,
                grade.score,
                activity.max_score,
                csv_safe(grade.feedback),
            ]
            if show_student:
                row = [
                    csv_safe(grade.student.student_number),
                    csv_safe(grade.student),
                    csv_safe(grade.student.email),
                ] + row
            writer.writerow(row)

        return response


class GradeDeleteView(TeacherRequiredMixin, DeleteView):
    model = Grade
    template_name = 'calificacion_confirm_delete.html'
    success_url = reverse_lazy('grades:list')

    def get_queryset(self):
        # Un grupo archivado es de solo lectura.
        return visible_grades(self.request).filter(activity__course__status='active')

    def form_valid(self, form):
        remove_grade(self.object, by=self.request.user)
        return redirect(self.get_success_url())
