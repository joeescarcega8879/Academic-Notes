"""La libreta del grupo: alumnos × actividades, editable celda por celda."""

from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.models import Course, Student
from core.utils import parse_id

from .models import Activity
from .services.gradesheet import build_gradesheet, describe_cell, set_cell


class OwnCourseGradesheetMixin(TeacherRequiredMixin):
    """Libreta de un grupo del docente en la organización activa (un grupo archivado se ve, no se edita)."""

    def get_course(self, pk):
        return get_object_or_404(
            Course.objects.for_organization(self.request.organization).filter(professor=self.request.user), pk=pk,
        )


class GradesheetView(OwnCourseGradesheetMixin, View):
    def get(self, request, course_pk):
        course = self.get_course(course_pk)
        return render(request, 'gradesheet.html', {
            'course': course, 'sheet': build_gradesheet(course), 'editable': not course.is_archived,
        })


class GradesheetCellView(OwnCourseGradesheetMixin, View):
    """Guarda una celda y devuelve lo que cambia en pantalla: la celda, la final del alumno y los promedios."""

    http_method_names = ['post']

    def post(self, request, course_pk):
        course = self.get_course(course_pk)
        activity_id = parse_id(request.POST.get('activity', ''))
        student_id = parse_id(request.POST.get('student', ''))
        if activity_id is None or student_id is None:
            return JsonResponse({'ok': False, 'error': 'Petición inválida.'}, status=400)
        organization = request.organization
        activity = get_object_or_404(Activity.objects.for_organization(organization).filter(course=course), pk=activity_id)
        student = get_object_or_404(
            Student.objects.for_organization(organization).filter(enrollments__course=course), pk=student_id,
        )

        try:
            grade = set_cell(activity, student, request.POST.get('score', ''), by=request.user)
        except ValidationError as error:
            return JsonResponse({'ok': False, 'error': ' '.join(error.messages)}, status=400)

        sheet = build_gradesheet(course)
        column = sheet.column_for(activity.pk)
        return JsonResponse({
            'ok': True,
            'cell': describe_cell(grade),
            'final': sheet.row_for(student.pk).final,
            'column': {'graded': column.graded, 'average': column.average},
            'group': sheet.group,
        })
