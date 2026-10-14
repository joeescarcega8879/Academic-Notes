import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.accounts.forms import ProfessorProfileForm, ProfileForm, StudentProfileForm
from apps.accounts.mixins import OrganizationMemberMixin, StudentRequiredMixin, TeacherRequiredMixin
from apps.accounts.models import User
from core.utils import parse_id
from apps.grades.services.grading import (
    course_stats, group_results, overall_stats, results_by_course, student_average,
)

from apps.organizations.services import SESSION_KEY

from .forms import (
    AcademicYearForm, CloneCourseForm, CourseForm, EnrollExistingForm, JoinCourseForm, StudentForm,
)
from .models import AcademicYear, Course, Enrollment, Student
from .services import importing, roster
from .services.courses import archive_course, clone_course, unarchive_course
from .services.summary import student_summary
from .services.invitations import (
    InvitationError, disable_invite_code, redeem_invitation, regenerate_invite_code,
)


class ProfessorDashboardView(TeacherRequiredMixin, TemplateView):

    template_name = "dashboard-profesor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Activity, Grade

        user = self.request.user
        organization = self.request.organization
        active = Course.Status.ACTIVE
        own = Course.objects.for_organization(organization).filter(professor=user).select_related('academic_year')
        courses = list(own.filter(status=active).annotate(student_count=Count('enrollments')))
        # La vista principal y sus estadísticas cubren solo los grupos activos.
        grades = list(
            Grade.objects
            .for_organization(organization)
            .filter(activity__course__professor=user, activity__course__status=active)
            .select_related('activity')
        )

        results = group_results(grades)
        per_course = course_stats(results)
        for course in courses:
            stats = per_course.get(course.pk)
            course.average = stats.average if stats else None
            course.pass_rate = stats.pass_rate if stats else None

        overall = overall_stats(results)
        context['courses'] = courses
        context['archived_courses'] = list(own.filter(status=Course.Status.ARCHIVED))
        context['total_activities'] = (
            Activity.objects
            .for_organization(organization)
            .filter(course__professor=user, course__status=active)
            .count()
        )
        context['graded_count'] = len(grades)
        context['group_average'] = overall.average
        context['pass_rate'] = overall.pass_rate

        context['total_students'] = (
            Enrollment.objects
            .for_organization(organization)
            .filter(course__professor=user, course__status=active)
            .values('student')
            .distinct()
            .count()
        )
        return context


class StudentDashboardView(StudentRequiredMixin, TemplateView):

    template_name = 'dashboard-alumno.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Grade

        user = self.request.user
        organization = self.request.organization
        mine = (
            Enrollment.objects
            .for_organization(organization)
            .filter(student__user=user)
            .select_related('course', 'course__professor')
        )
        enrollments = list(mine.filter(course__status=Course.Status.ACTIVE))

        # Promedio ponderado del alumno (general y por grupo)
        grades = list(
            Grade.objects
            .for_organization(organization)
            .filter(student__user=user, activity__course__status=Course.Status.ACTIVE, activity__published=True)
            .select_related('activity')
        )

        results = results_by_course(grades)
        for e in enrollments:
            result = results.get(e.course_id)
            e.course_average = result.final if result else None
            e.result = result

        context['enrollments'] = enrollments
        context['archived_enrollments'] = list(mine.filter(course__status=Course.Status.ARCHIVED))
        context['average'] = student_average(results)
        return context


class CourseDetailView(OrganizationMemberMixin, DetailView):

    model = Course
    template_name = 'course_detail.html'
    context_object_name = 'course'

    def get_queryset(self):
        qs = Course.objects.for_organization(self.request.organization).select_related('academic_year')
        user = self.request.user
        if self.request.membership.is_teacher:
            return qs.filter(professor=user)
        return qs.filter(enrollments__student__user=user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        from apps.grades.models import Grade

        enrollments = list(self.object.enrollments.select_related('student'))
        context['my_enrollment'] = self.object.enrollments.filter(student__user=user).first()

        # Vista docente: calificación final de cada alumno según el esquema del grupo
        if self.request.membership.is_teacher:
            results = group_results(
                Grade.objects.filter(activity__course=self.object).select_related('activity')
            )
            for enrollment in enrollments:
                enrollment.result = results.get((self.object.pk, enrollment.student_id))
        context['enrollments'] = enrollments
        context['activities'] = list(
            self.object.activities.select_related('criterion').annotate(graded=Count('grades'))
        )

        # Vista alumno: evaluaciones del grupo + su calificación
        if self.request.membership.is_student:
            my_grades = {
                g.activity_id: g
                for g in Grade.objects.filter(
                    student__user=user, activity__course=self.object, activity__published=True,
                ).select_related('activity')
            }
            rows = [
                {'activity': activity, 'grade': my_grades.get(activity.id)}
                for activity in self.object.activities.filter(published=True)
            ]

            result = results_by_course(my_grades.values()).get(self.object.pk)
            context['activity_rows'] = rows
            context['course_result'] = result
            context['course_average'] = result.final if result else None
        return context


# ── Grupos: crear, editar, archivar y duplicar ────────────────────────

class OwnCourseMixin(TeacherRequiredMixin):
    """Grupos del docente en la organización activa."""

    def get_queryset(self):
        return Course.objects.for_organization(self.request.organization).filter(professor=self.request.user)


class CourseFormKwargsMixin:
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['organization'] = self.request.organization
        kwargs['professor'] = self.request.user
        return kwargs


class CourseCreateView(CourseFormKwargsMixin, TeacherRequiredMixin, CreateView):
    model = Course
    form_class = CourseForm
    template_name = 'course_form.html'

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Se creó el grupo "{self.object.name}".')
        return response


class CourseUpdateView(CourseFormKwargsMixin, OwnCourseMixin, UpdateView):
    form_class = CourseForm
    template_name = 'course_form.html'

    def get_queryset(self):
        # Un grupo archivado es de solo lectura.
        return super().get_queryset().filter(status=Course.Status.ACTIVE)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Se guardaron los cambios del grupo.')
        return response


class CourseArchiveView(OwnCourseMixin, View):
    def post(self, request, pk):
        course = get_object_or_404(self.get_queryset(), pk=pk)
        archive_course(course)
        messages.success(request, f'"{course.name}" quedó archivado: sigue consultable, pero ya no admite cambios.')
        return redirect('professor_dashboard')


class CourseUnarchiveView(OwnCourseMixin, View):
    def post(self, request, pk):
        course = get_object_or_404(self.get_queryset(), pk=pk)
        unarchive_course(course)
        messages.success(request, f'"{course.name}" volvió a estar activo.')
        return redirect(course)


class CourseCloneView(OwnCourseMixin, View):
    """Duplica un grupo para un nuevo ciclo (copia el grupo y sus evaluaciones; no alumnos ni notas)."""

    template_name = 'course_clone.html'

    def get_course(self, pk):
        return get_object_or_404(self.get_queryset().select_related('academic_year'), pk=pk)

    def get(self, request, pk):
        course = self.get_course(pk)
        return render(request, self.template_name, {'course': course, 'form': CloneCourseForm(course=course)})

    def post(self, request, pk):
        course = self.get_course(pk)
        form = CloneCourseForm(request.POST, course=course)
        if form.is_valid():
            try:
                clone = clone_course(
                    course, form.cleaned_data['academic_year'],
                    code=form.cleaned_data['code'], name=form.cleaned_data['name'],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, f'Se duplicó "{course.name}" en el ciclo {clone.academic_year}.')
                return redirect(clone)
        return render(request, self.template_name, {'course': course, 'form': form})


# ── Ciclos escolares ──────────────────────────────────────────────────

class AcademicYearListView(TeacherRequiredMixin, ListView):
    """Ciclos de la organización, con el formulario para crear uno nuevo."""

    template_name = 'academic_years.html'
    context_object_name = 'years'

    def get_queryset(self):
        return AcademicYear.objects.for_organization(self.request.organization).annotate(course_count=Count('courses'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault('form', AcademicYearForm(organization=self.request.organization))
        return context

    def post(self, request):
        form = AcademicYearForm(request.POST, organization=request.organization)
        if form.is_valid():
            year = form.save()
            messages.success(request, f'Se creó el ciclo {year}.')
            return redirect('academic_years')
        self.object_list = self.get_queryset()
        return self.render_to_response(self.get_context_data(form=form))


class AcademicYearCurrentView(TeacherRequiredMixin, View):
    def post(self, request, pk):
        year = get_object_or_404(AcademicYear.objects.for_organization(request.organization), pk=pk)
        year.is_current = True
        year.save()
        messages.success(request, f'{year} es ahora el ciclo actual.')
        return redirect('academic_years')


# ── Lista editable ────────────────────────────────────────────────────

class RosterMixin(OwnCourseMixin):
    """Editar la lista solo aplica a grupos activos propios; los archivados son de solo lectura."""

    def get_queryset(self):
        return super().get_queryset().filter(status=Course.Status.ACTIVE)

    def get_course(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    def get_student(self, course, student_pk):
        """Alumno inscrito en el grupo (así se acota a la organización y al docente)."""
        return get_object_or_404(Student.objects.for_organization(course.organization), pk=student_pk, enrollments__course=course)


class StudentAddView(RosterMixin, View):
    """Agregar un alumno nuevo a la lista o inscribir uno que ya está en la organización."""

    template_name = 'student_add.html'

    def render_page(self, request, course, new_form=None, existing_form=None):
        return render(request, self.template_name, {
            'course': course,
            'new_form': new_form or StudentForm(organization=course.organization),
            'existing_form': existing_form or EnrollExistingForm(course=course),
        })

    def get(self, request, pk):
        return self.render_page(request, self.get_course(pk))

    def post(self, request, pk):
        course = self.get_course(pk)
        if request.POST.get('action') == 'existing':
            form = EnrollExistingForm(request.POST, course=course)
            if form.is_valid():
                roster.enroll_existing(course, form.cleaned_data['student'])
                messages.success(request, f'{form.cleaned_data["student"]} quedó inscrito en el grupo.')
                return redirect(course)
            return self.render_page(request, course, existing_form=form)

        form = StudentForm(request.POST, organization=course.organization)
        if form.is_valid():
            student = roster.add_student(course, **form.cleaned_data)
            messages.success(request, f'{student} se agregó al grupo.')
            return redirect(course)
        return self.render_page(request, course, new_form=form)


class StudentEditView(RosterMixin, View):
    template_name = 'student_edit.html'

    def get(self, request, pk, student_pk):
        course = self.get_course(pk)
        student = self.get_student(course, student_pk)
        form = StudentForm(instance=student, organization=course.organization)
        return render(request, self.template_name, {'course': course, 'student': student, 'form': form})

    def post(self, request, pk, student_pk):
        course = self.get_course(pk)
        student = self.get_student(course, student_pk)
        form = StudentForm(request.POST, instance=student, organization=course.organization)
        if form.is_valid():
            form.save()
            messages.success(request, f'Se guardaron los datos de {student}.')
            return redirect(course)
        return render(request, self.template_name, {'course': course, 'student': student, 'form': form})


class StudentRemoveView(RosterMixin, View):
    def post(self, request, pk, student_pk):
        course = self.get_course(pk)
        student = self.get_student(course, student_pk)
        try:
            roster.remove_from_course(course, student)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, f'{student} se quitó del grupo.')
        return redirect(course)


class StudentUnlinkView(RosterMixin, View):
    def post(self, request, pk, student_pk):
        course = self.get_course(pk)
        student = self.get_student(course, student_pk)
        if student.user_id is None:
            messages.error(request, f'{student} no tiene una cuenta vinculada.')
        else:
            roster.unlink_student(student)
            messages.success(request, f'Se desvinculó la cuenta de {student}. Puede volver a enlazarse con el código.')
        return redirect(course)


# ── Código de invitación ──────────────────────────────────────────────

class CourseInviteView(OwnCourseMixin, View):
    """El docente regenera, desactiva o activa el código de su grupo."""

    def post(self, request, pk):
        course = get_object_or_404(self.get_queryset().filter(status=Course.Status.ACTIVE), pk=pk)
        action = request.POST.get('action')
        if action == 'disable':
            disable_invite_code(course)
            messages.success(request, 'Se desactivó el código: nadie podrá usarlo hasta que lo actives de nuevo.')
        elif action in ('regenerate', 'enable'):
            regenerate_invite_code(course)
            messages.success(request, f'Nuevo código del grupo: {course.invite_code}. El anterior ya no funciona.')
        return redirect(course)


class JoinCourseView(LoginRequiredMixin, View):
    """El alumno enlaza su cuenta con su lugar en la lista de un grupo."""

    template_name = 'join_course.html'

    def get(self, request):
        return render(request, self.template_name, {'form': JoinCourseForm()})

    def post(self, request):
        form = JoinCourseForm(request.POST)
        if form.is_valid():
            try:
                student = redeem_invitation(request.user, **form.cleaned_data)
            except InvitationError as error:
                form.add_error(None, str(error))
            else:
                # Pasa a ver la organización del grupo al que se unió.
                request.session[SESSION_KEY] = student.organization_id
                messages.success(request, 'Listo: tu cuenta quedó enlazada con tu lugar en la lista.')
                return redirect('student_dashboard')
        return render(request, self.template_name, {'form': form})


# ── Importar la lista de un grupo ─────────────────────────────────────

class ImportMixin(OwnCourseMixin):
    """Importar solo aplica a grupos activos propios; los archivados son de solo lectura."""

    def get_queryset(self):
        return super().get_queryset().filter(status=Course.Status.ACTIVE)

    def get_course(self, pk):
        return get_object_or_404(self.get_queryset(), pk=pk)

    @staticmethod
    def session_key(course):
        return f'import_{course.pk}'


class StudentImportView(ImportMixin, View):
    """Paso 1: subir el archivo."""

    template_name = 'student_import.html'

    def get(self, request, pk):
        return render(request, self.template_name, {'course': self.get_course(pk)})

    def post(self, request, pk):
        course = self.get_course(pk)
        upload = request.FILES.get('file')
        if upload is None:
            return self.fail(request, course, 'Elige un archivo .xlsx o .csv.')
        if upload.size > importing.MAX_BYTES:
            return self.fail(request, course, 'El archivo pesa más de 2 MB. Divide la lista en varios archivos.')
        try:
            headers, rows = importing.read_table(upload.name, upload.read())
        except importing.ImportFileError as error:
            return self.fail(request, course, str(error))
        request.session[self.session_key(course)] = {'filename': upload.name, 'headers': headers, 'rows': rows}
        return redirect('student_import_preview', pk=course.pk)

    def fail(self, request, course, message):
        return render(request, self.template_name, {'course': course, 'error': message})


class StudentImportPreviewView(ImportMixin, View):
    """Paso 2: asociar columnas, ver qué pasará con cada fila y confirmar."""

    template_name = 'student_import_preview.html'
    PREVIEW_ROWS = 200

    def load(self, request, course):
        return request.session.get(self.session_key(course))

    def get(self, request, pk):
        course = self.get_course(pk)
        data = self.load(request, course)
        if data is None:
            messages.error(request, 'Sube primero el archivo con la lista.')
            return redirect('student_import', pk=course.pk)
        return self.render_preview(request, course, data, importing.detect_mapping(data['headers']))

    def post(self, request, pk):
        course = self.get_course(pk)
        data = self.load(request, course)
        if data is None:
            messages.error(request, 'La vista previa expiró. Sube el archivo de nuevo.')
            return redirect('student_import', pk=course.pk)

        mapping = self.read_mapping(request.POST)
        errors = importing.validate_mapping(mapping, len(data['headers']))
        if request.POST.get('action') == 'confirm' and not errors:
            # Se vuelve a analizar al confirmar: la base pudo cambiar desde la vista previa.
            plan = importing.analyze(course, data['rows'], mapping)
            try:
                summary = importing.apply_import(course, plan)
            except ValidationError as error:
                errors = list(error.messages)
            else:
                del request.session[self.session_key(course)]
                messages.success(request, self.summary_message(summary))
                return redirect(course)
        return self.render_preview(request, course, data, mapping, errors)

    @staticmethod
    def read_mapping(post):
        mapping = {}
        for key in importing.FIELDS:
            mapping[key] = parse_id(post.get(f'map_{key}', ''))
        return mapping

    @staticmethod
    def summary_message(summary):
        text = (
            f'Importación lista: {summary["created"]} alumnos nuevos, '
            f'{summary["updated"]} actualizados y {summary["enrolled"]} inscritos.'
        )
        if summary['skipped']:
            text += f' Se omitieron {summary["skipped"]} filas con errores.'
        return text

    def render_preview(self, request, course, data, mapping, errors=None):
        errors = errors if errors is not None else importing.validate_mapping(mapping, len(data['headers']))
        plan = None if errors else importing.analyze(course, data['rows'], mapping)
        return render(request, self.template_name, {
            'course': course,
            'filename': data['filename'],
            'headers': data['headers'],
            'fields': [
                {'key': key, 'label': label, 'selected': mapping.get(key), 'required': key == importing.REQUIRED_FIELD}
                for key, label in importing.FIELDS.items()
            ],
            'mapping_errors': errors,
            'plan': plan,
            'preview_rows': plan.rows[:self.PREVIEW_ROWS] if plan else [],
            'hidden_rows': max(len(plan.rows) - self.PREVIEW_ROWS, 0) if plan else 0,
            'can_confirm': bool(plan) and any(row.action != 'error' for row in plan.rows),
        })


class StudentImportTemplateView(TeacherRequiredMixin, View):
    """Plantilla CSV con los encabezados que la importación reconoce."""

    def get(self, request):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="plantilla-alumnos.csv"'
        response.write('﻿')  # BOM para que Excel respete los acentos
        writer = csv.writer(response)
        writer.writerow(list(importing.FIELDS.values()))
        writer.writerow(['00123', 'Ana María', 'Pérez López', 'ana@ejemplo.com'])
        return response


# ── Perfil ────────────────────────────────────────────────────────────

class ProfileView(LoginRequiredMixin, View):
    """Datos personales y preferencias de la cuenta, con el resumen académico si es alumno."""

    template_name = 'perfil.html'

    @staticmethod
    def forms(request, data=None, files=None):
        user = request.user
        if user.role == User.Role.STUDENT:
            extra = StudentProfileForm(data, instance=getattr(user, 'student_profile', None))
        else:
            extra = ProfessorProfileForm(data, instance=getattr(user, 'professor_profile', None))
        return ProfileForm(data, files, instance=user), extra

    def get(self, request):
        return render(request, self.template_name, self.context(request, *self.forms(request)))

    @staticmethod
    def context(request, profile_form, extra_form):
        # La matrícula pertenece a la organización activa, no a la cuenta.
        student = Student.objects.for_organization(request.organization).filter(user=request.user).first()
        membership = request.membership
        summary = student_summary(request.user, request.organization) if membership and membership.is_student else None
        return {
            'profile_form': profile_form,
            'extra_form': extra_form,
            'student_number': student.student_number if student else '',
            'summary': summary,
        }

    def post(self, request):
        profile_form, extra_form = self.forms(request, request.POST, request.FILES)
        if profile_form.is_valid() and extra_form.is_valid():
            profile_form.save()
            extra = extra_form.save(commit=False)
            extra.user = request.user
            extra.save()
            return redirect('profile')
        return render(request, self.template_name, self.context(request, profile_form, extra_form))
