"""Actividades: el docente las crea y publica; el alumno las consulta."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404
from django.utils.functional import cached_property
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, UpdateView

from apps.accounts.mixins import OrganizationMemberMixin, TeacherRequiredMixin
from apps.ai import ui as ai_ui
from apps.courses.models import Course, Student
from core.utils import parse_id

from .activity_forms import ActivityForm
from .models import Activity, Grade, GradeHistory, Submission
from .services.gradebook import grade_activity
from .services.gradesheet import parse_score
from .services.submissions import submission_state, submit
from .submission_forms import SubmissionForm


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


class ActivityListView(OwnActiveCourseMixin, View):
    """Pestaña «Actividades» del grupo: la tabla de actividades con su botón «Nueva actividad»."""

    def get(self, request, course_pk):
        course = get_object_or_404(self.courses(), pk=course_pk)
        activities = list(course.activities.select_related('criterion').annotate(graded=Count('grades')))
        return render(request, 'activity_list.html', {
            'course': course, 'activities': activities, 'enrollment_count': course.enrollments.count(),
        })


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

    def get_initial(self):
        # Desde el temario: «+ Crear actividad» llega con ?semana=<id> y la semana ya elegida (el formulario la valida).
        initial = super().get_initial()
        week = parse_id(self.request.GET.get('semana', ''))
        if week is not None:
            initial['syllabus_week'] = week
        return initial

    def get_context_data(self, **kwargs):
        week_id = parse_id(self.request.GET.get('semana', ''))
        panel = ai_ui.assignment_panel(self.request.organization, self.course, week_id=week_id, origin='form')
        return super().get_context_data(course=self.course, ai_task=panel, **kwargs)

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
        try:
            activity.save()
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return redirect(activity)
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
    """El docente ve la actividad con sus alumnos; el alumno, la actividad publicada con su entrega y su nota."""

    def get_activity(self, request, pk):
        activities = Activity.objects.for_organization(request.organization).select_related(
            'course', 'criterion__period', 'syllabus_week',
        )
        if request.membership.is_teacher:
            return get_object_or_404(activities.filter(course__professor=request.user), pk=pk)
        return get_object_or_404(
            activities.filter(published=True, course__enrollments__student__user=request.user).distinct(), pk=pk,
        )

    def get(self, request, pk):
        return self.render_page(request, self.get_activity(request, pk))

    def render_page(self, request, activity, form=None):
        context = {'activity': activity, 'course': activity.course}
        if request.membership.is_teacher:
            grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
            submissions = {s.student_id: s for s in Submission.objects.filter(activity=activity)}
            enrollments = list(activity.course.enrollments.select_related('student__user'))
            for enrollment in enrollments:
                enrollment.grade = grades.get(enrollment.student_id)
                enrollment.submission = submissions.get(enrollment.student_id)
            context.update(
                enrollments=enrollments, graded_count=len(grades), submitted_count=len(submissions),
                late_count=sum(1 for s in submissions.values() if s.is_late),
            )
        else:
            grade = Grade.objects.filter(activity=activity, student__user=request.user).first()
            submission = Submission.objects.filter(activity=activity, student__user=request.user).first()
            state = submission_state(activity)
            context.update(
                grade=grade, submission=submission, submission_state=state,
                # Una entrega calificada ya no se cambia; fuera de la ventana tampoco se puede entregar.
                can_submit=activity.accepts_submissions and grade is None and state in ('open', 'late')
                and not activity.course.is_archived,
                submission_form=form or SubmissionForm(existing=submission),
            )
        return render(request, 'activity_detail.html', context)


class SubmitActivityView(ActivityDetailView):
    """El alumno entrega o actualiza su entrega."""

    def get(self, request, pk):
        return redirect('grades:activity_detail', pk=pk)

    def post(self, request, pk):
        activity = self.get_activity(request, pk)
        if not request.membership.is_student:
            raise Http404
        student = get_object_or_404(
            Student.objects.for_organization(request.organization), user=request.user, enrollments__course=activity.course,
        )
        existing = Submission.objects.filter(activity=activity, student=student).first()
        form = SubmissionForm(request.POST, request.FILES, existing=existing)
        if form.is_valid():
            try:
                submission = submit(
                    activity, student, text=form.cleaned_data['text'], link=form.cleaned_data['link'],
                    file=form.cleaned_data['file'],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                if submission.is_late:
                    messages.success(request, 'Tu entrega quedó registrada, pero fuera de la fecha límite.')
                else:
                    messages.success(request, 'Tu entrega quedó registrada.')
                return redirect(activity)
        return self.render_page(request, activity, form=form)


class SubmissionAccessMixin(OrganizationMemberMixin):
    def get_submission(self, request, pk):
        submissions = Submission.objects.for_organization(request.organization).select_related(
            'activity__course', 'activity__criterion__period', 'student',
        )
        if request.membership.is_teacher:
            return get_object_or_404(submissions.filter(activity__course__professor=request.user), pk=pk)
        return get_object_or_404(submissions.filter(student__user=request.user, activity__published=True), pk=pk)


class SubmissionDetailView(SubmissionAccessMixin, View):
    """El docente revisa una entrega."""

    def get(self, request, pk):
        if not request.membership.is_teacher:
            raise Http404
        submission = self.get_submission(request, pk)
        return render(request, 'submission_detail.html', {
            'submission': submission, 'activity': submission.activity, 'course': submission.activity.course,
        })


class SubmissionFileView(SubmissionAccessMixin, View):
    """Descarga del archivo de una entrega: solo el docente del grupo y el propio alumno."""

    def get(self, request, pk):
        submission = self.get_submission(request, pk)
        if not submission.file:
            raise Http404
        response = FileResponse(
            submission.file.open('rb'), as_attachment=True,
            filename=submission.original_name or 'entrega', content_type='application/octet-stream',
        )
        # Lo subido por un alumno nunca se interpreta en el navegador ni se guarda en cachés compartidas.
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response


class GradingView(OwnActiveCourseMixin, View):
    """Calificar a todo el grupo en una sola tabla: nota y comentario por alumno.

    Sirve para tareas (con su entrega a la vista) y para la calificación rápida de participación. Una fila
    sin nota no se toca; si alguna fila es inválida no se guarda ninguna.
    """

    template_name = 'grading.html'

    def get_activity(self, pk):
        return get_object_or_404(self.activities(), pk=pk)

    def rows(self, activity):
        grades = {g.student_id: g for g in Grade.objects.filter(activity=activity)}
        submissions = {s.student_id: s for s in Submission.objects.filter(activity=activity)}
        rows = []
        for enrollment in activity.course.enrollments.select_related('student__user').order_by(
            'student__last_name', 'student__first_name',
        ):
            submission = submissions.get(enrollment.student_id)
            rows.append({
                'student': enrollment.student, 'grade': grades.get(enrollment.student_id), 'submission': submission,
                'penalizable': bool(submission and submission.is_late and activity.allow_late and activity.late_penalty),
            })
        return rows

    def get(self, request, pk):
        activity = self.get_activity(pk)
        return render(request, self.template_name, {'activity': activity, 'course': activity.course, 'rows': self.rows(activity)})

    def post(self, request, pk):
        activity = self.get_activity(pk)
        rows, entries, errors = self.rows(activity), [], {}

        for row in rows:
            sid = row['student'].pk
            row['input'] = {
                'score': request.POST.get(f'score_{sid}', ''), 'feedback': request.POST.get(f'feedback_{sid}', ''),
                'waive': request.POST.get(f'waive_{sid}') == 'on',
            }
            try:
                score = parse_score(request.POST.get(f'score_{sid}', ''), activity.max_score)
            except ValidationError as error:
                errors[sid] = error.messages[0]
                continue
            if score is None:
                continue  # sin nota no se toca (ni se borra la que hubiera)
            entries.append((row['student'], score, row['input']))

        if errors:
            for row in rows:
                row['error'] = errors.get(row['student'].pk)
            messages.error(request, 'Corrige las filas marcadas: no se guardó nada.')
            return render(request, self.template_name, {'activity': activity, 'course': activity.course, 'rows': rows})

        try:
            with transaction.atomic():
                for student, score, data in entries:
                    grade_activity(
                        activity, student, score=score, feedback=data['feedback'], by=request.user,
                        waive_penalty=data['waive'],
                    )
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return render(request, self.template_name, {'activity': activity, 'course': activity.course, 'rows': rows})

        messages.success(request, f'Se guardaron {len(entries)} calificaciones.' if entries else 'No había notas que guardar.')
        return redirect(activity)


class GradeHistoryView(TeacherRequiredMixin, View):
    """Bitácora de calificaciones de una actividad: quién cambió qué y cuándo."""

    def get(self, request, pk):
        activity = get_object_or_404(
            Activity.objects.for_organization(request.organization).filter(course__professor=request.user)
            .select_related('course'),
            pk=pk,
        )
        history = GradeHistory.objects.for_organization(request.organization).filter(activity=activity).select_related('changed_by')
        return render(request, 'grade_history.html', {'activity': activity, 'course': activity.course, 'history': history})
