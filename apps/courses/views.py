import csv

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.accounts.mixins import OrganizationMemberMixin, StudentRequiredMixin, TeacherRequiredMixin
from apps.grades.services.grading import grade_stats, stats_by_course

from .forms import AcademicYearForm, CloneCourseForm, CourseForm
from .models import AcademicYear, Course, Enrollment
from .services import importing
from .services.courses import archive_course, clone_course, unarchive_course


class ProfessorDashboardView(TeacherRequiredMixin, TemplateView):

    template_name = "dashboard-profesor.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.grades.models import Evaluation, Grade

        user = self.request.user
        organization = self.request.organization
        active = Course.Status.ACTIVE
        own = Course.objects.for_organization(organization).filter(professor=user).select_related('academic_year')
        courses = list(own.filter(status=active).annotate(student_count=Count('enrollments')))
        # La vista principal y sus estadísticas cubren solo los grupos activos.
        grades = list(
            Grade.objects
            .for_organization(organization)
            .filter(evaluation__course__professor=user, evaluation__course__status=active)
            .select_related('evaluation')
        )

        per_course = stats_by_course(grades)
        for course in courses:
            stats = per_course.get(course.pk)
            course.average = stats.average if stats else None
            course.pass_rate = stats.pass_rate if stats else None

        overall = grade_stats(grades)
        context['courses'] = courses
        context['archived_courses'] = list(own.filter(status=Course.Status.ARCHIVED))
        context['total_evaluations'] = (
            Evaluation.objects
            .for_organization(organization)
            .filter(course__professor=user, course__status=active)
            .count()
        )
        context['graded_count'] = overall.count
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

        # Promedio ponderado del alumno (general y por materia)
        grades = list(
            Grade.objects.for_organization(organization).filter(student__user=user).select_related('evaluation')
        )

        per_course = stats_by_course(grades)
        for e in enrollments:
            stats = per_course.get(e.course_id)
            e.course_average = stats.average if stats else None

        context['enrollments'] = enrollments
        context['archived_enrollments'] = list(mine.filter(course__status=Course.Status.ARCHIVED))
        context['average'] = grade_stats(grades).average
        return context


class CourseDetailView(OrganizationMemberMixin, DetailView):

    model = Course
    template_name = 'materia.html'
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
        context['enrollments'] = self.object.enrollments.select_related('student')
        context['my_enrollment'] = self.object.enrollments.filter(student__user=user).first()

        # Vista alumno: evaluaciones de la materia + su calificación
        if self.request.membership.is_student:
            from apps.grades.models import Grade

            my_grades = {
                g.evaluation_id: g
                for g in Grade.objects.filter(student__user=user, evaluation__course=self.object).select_related('evaluation')
            }
            rows = [
                {'evaluation': evaluation, 'grade': my_grades.get(evaluation.id)}
                for evaluation in self.object.evaluations.all()
            ]

            context['evaluation_rows'] = rows
            context['course_average'] = grade_stats(my_grades.values()).average
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
            raw = post.get(f'map_{key}', '')
            mapping[key] = int(raw) if raw.isdigit() else None
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
