"""Actividades: el docente las crea y publica; el alumno las consulta."""

from django.contrib import messages
from django.utils.functional import cached_property
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, UpdateView

from apps.accounts.mixins import OrganizationMemberMixin, TeacherRequiredMixin
from apps.courses.models import Course

from .activity_forms import ActivityForm
from .models import Activity, Grade


class OwnActiveCourseMixin(TeacherRequiredMixin):
    """Grupos activos del docente en la organización activa (los archivados son de solo lectura)."""

    def courses(self):
        return Course.objects.for_organization(self.request.organization).filter(
            professor=self.request.user, status=Course.Status.ACTIVE,
        )

    def activities(self):
        return Activity.objects.for_organization(self.request.organization).filter(
            course__in=self.courses(),
        ).select_related('course', 'criterion__period')


class ActivityCreateView(OwnActiveCourseMixin, CreateView):
    model = Activity
    form_class = ActivityForm
    template_name = 'activity_form.html'

    @cached_property
    def course(self):
        return get_object_or_404(self.courses(), pk=self.kwargs['course_pk'])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['course'] = self.course
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(course=self.course, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Se creó "{self.object.title}" como borrador. Publícala cuando esté lista.')
        return response


class ActivityUpdateView(OwnActiveCourseMixin, UpdateView):
    form_class = ActivityForm
    template_name = 'activity_form.html'

    def get_queryset(self):
        return self.activities()

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['course'] = self.object.course
        return kwargs

    def get_context_data(self, **kwargs):
        return super().get_context_data(course=self.object.course, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Se guardaron los cambios de la actividad.')
        return response


class ActivityPublishView(OwnActiveCourseMixin, View):
    """Publica un borrador o lo regresa a borrador."""

    def post(self, request, pk):
        activity = get_object_or_404(self.activities(), pk=pk)
        activity.published = not activity.published
        activity.save()
        if activity.published:
            messages.success(request, f'"{activity.title}" ya la ven los alumnos y cuenta para las calificaciones.')
        else:
            messages.success(request, f'"{activity.title}" volvió a borrador: los alumnos ya no la ven y no cuenta.')
        return redirect(activity)


class ActivityDeleteView(OwnActiveCourseMixin, View):
    def post(self, request, pk):
        activity = get_object_or_404(self.activities(), pk=pk)
        if activity.grades.exists():
            messages.error(
                request, 'No se puede eliminar: ya tiene calificaciones. Pásala a borrador o elimina sus calificaciones primero.',
            )
            return redirect(activity)
        course = activity.course
        activity.delete()
        messages.success(request, f'Se eliminó "{activity.title}".')
        return redirect(course)


class ActivityDetailView(OrganizationMemberMixin, View):
    """El docente ve la actividad con sus alumnos; el alumno, la actividad publicada con su nota."""

    def get_activity(self, request, pk):
        activities = Activity.objects.for_organization(request.organization).select_related('course', 'criterion__period')
        if request.membership.is_teacher:
            return get_object_or_404(activities.filter(course__professor=request.user), pk=pk)
        return get_object_or_404(
            activities.filter(published=True, course__enrollments__student__user=request.user).distinct(), pk=pk,
        )

    def get(self, request, pk):
        activity = self.get_activity(request, pk)
        context = {'activity': activity, 'course': activity.course}
        if request.membership.is_teacher:
            grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
            enrollments = list(activity.course.enrollments.select_related('student'))
            for enrollment in enrollments:
                enrollment.grade = grades.get(enrollment.student_id)
            context['enrollments'] = enrollments
            context['graded_count'] = len(grades)
        else:
            context['grade'] = Grade.objects.filter(activity=activity, student__user=request.user).first()
        return render(request, 'activity_detail.html', context)
