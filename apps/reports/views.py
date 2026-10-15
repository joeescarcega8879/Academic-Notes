"""Reportes del grupo: boletas en PDF, concentrado en Excel y alumnos en riesgo. Solo para quien da el grupo."""

from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.text import slugify
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.models import Course, Student
from apps.organizations import limits

from .services import pdf, risk, workbook
from .services.transcript import build_transcripts

SESSION_KEY = 'report_columns'


class OwnCourseReportMixin(TeacherRequiredMixin):
    """Grupo del docente en la organización activa. Un grupo archivado también se reporta: es de solo lectura."""

    def get_course(self, pk):
        return get_object_or_404(
            Course.objects.for_organization(self.request.organization).filter(professor=self.request.user)
            .select_related('academic_year', 'professor', 'organization'),
            pk=pk,
        )


def _download(content, content_type, filename):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = content_disposition_header(True, filename)
    # Datos de alumnos: ni cachés compartidas ni interpretación del navegador.
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _filename(prefix, course, extension):
    label = slugify(course.code or course.name) or f'grupo-{course.pk}'
    return f'{prefix}-{label}-{timezone.localdate().isoformat()}.{extension}'


class TranscriptsView(OwnCourseReportMixin, View):
    """Una sola boleta (``student_pk``) o la de todo el grupo, una por página."""

    def get(self, request, course_pk, student_pk=None):
        course = self.get_course(course_pk)
        if student_pk is None:
            transcripts = build_transcripts(course)
            filename = _filename('boletas', course, 'pdf')
        else:
            student = get_object_or_404(
                Student.objects.for_organization(request.organization).filter(enrollments__course=course), pk=student_pk,
            )
            transcripts = build_transcripts(course, [student])
            filename = _filename(f'boleta-{slugify(student.student_number or student.last_name) or student.pk}', course, 'pdf')
        # Con el plan Gratis la boleta sale bien hecha pero con marca de agua; el plan Docente la quita.
        watermark = not limits.has_feature(request.organization, 'clean_transcripts')
        return _download(pdf.render_transcripts(transcripts, watermark=watermark), 'application/pdf', filename)


class WorkbookConfigView(OwnCourseReportMixin, View):
    """Elegir y ordenar las columnas del concentrado. Se recuerda la última elección de cada grupo."""

    def get(self, request, course_pk):
        course = self.get_course(course_pk)
        if not limits.has_feature(request.organization, 'custom_workbook'):
            # Plan Gratis: columnas fijas, sin elegir ni ordenar.
            rows = [{'column': workbook.BY_KEY[key], 'checked': True} for key in workbook.DEFAULT_KEYS]
            return render(request, 'reports_workbook.html', {'course': course, 'rows': rows, 'locked': True})
        chosen = workbook.parse_columns(request.session.get(SESSION_KEY, {}).get(str(course.pk), [])) or list(workbook.DEFAULT_KEYS)
        # Primero las elegidas, en su orden; luego las demás sin marcar.
        ordered = [workbook.BY_KEY[key] for key in chosen] + [c for c in workbook.COLUMNS if c.key not in chosen]
        rows = [{'column': column, 'checked': column.key in chosen} for column in ordered]
        return render(request, 'reports_workbook.html', {'course': course, 'rows': rows, 'locked': False})


class WorkbookDownloadView(OwnCourseReportMixin, View):
    def get(self, request, course_pk):
        course = self.get_course(course_pk)
        if not limits.has_feature(request.organization, 'custom_workbook'):
            # Plan Gratis: siempre las columnas fijas, pidan lo que pidan en la dirección.
            return _download(
                workbook.build_workbook(course, list(workbook.DEFAULT_KEYS)), workbook.XLSX_TYPE, _filename('concentrado', course, 'xlsx'),
            )
        requested = request.GET.getlist('cols')
        keys = workbook.parse_columns(requested)
        if requested and not keys:
            return HttpResponseBadRequest('Ninguna de las columnas pedidas existe.')
        if not keys:
            keys = workbook.parse_columns(request.session.get(SESSION_KEY, {}).get(str(course.pk), [])) or list(workbook.DEFAULT_KEYS)
        else:
            saved = request.session.get(SESSION_KEY, {})
            saved[str(course.pk)] = keys
            request.session[SESSION_KEY] = saved
        return _download(workbook.build_workbook(course, keys), workbook.XLSX_TYPE, _filename('concentrado', course, 'xlsx'))


class RiskView(OwnCourseReportMixin, View):
    def get(self, request, course_pk):
        course = self.get_course(course_pk)
        assessments = risk.assess_course(course)
        counts = risk.risk_counts(assessments)
        return render(request, 'reports_risk.html', {
            'course': course, 'assessments': assessments, 'counts': counts,
            'attention': [a for a in assessments if a.needs_attention], 'rest': [a for a in assessments if not a.needs_attention],
            'margin_points': risk.MARGIN, 'missing_limit': risk.MISSING_LIMIT,
        })
