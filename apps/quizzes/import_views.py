"""Importar preguntas al banco desde Excel o CSV: subir, revisar y confirmar."""

import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.services import importing as file_reader
from apps.organizations import limits
from apps.organizations.limits import PlanLimitError

from core.utils import parse_id

from .services import question_import
from .services.bank import teaching_courses

SESSION_KEY = 'question_import'
PREVIEW_ROWS = 200
GENERAL = 'sin'


def destination(request, raw):
    """El grupo de destino que eligió el docente: ``(True, grupo)``, ``(True, None)`` si es general, o ``(False, None)``."""
    if raw in ('', GENERAL):
        return True, None
    course = teaching_courses(request.user, request.organization).filter(pk=parse_id(raw) or 0).first()
    return (course is not None), course


def import_form_context(request, **extra):
    """Los grupos entre los que se elige el destino y cuál viene marcado (el que se veía en el banco, o el único)."""
    groups = list(teaching_courses(request.user, request.organization))
    wanted = parse_id(request.POST.get('grupo') or request.GET.get('grupo') or '')
    selected = wanted if wanted in {course.pk for course in groups} else (groups[0].pk if len(groups) == 1 else None)
    return {'groups': groups, 'selected_group': selected, 'general_selected': request.POST.get('grupo') == GENERAL, **extra}


class QuestionImportView(TeacherRequiredMixin, View):
    """Paso 1: subir el archivo."""

    template_name = 'question_import.html'

    def get(self, request):
        return render(request, self.template_name, import_form_context(request))

    def post(self, request):
        valid, course = destination(request, request.POST.get('grupo', ''))
        if not valid:
            return self.fail(request, 'Elige uno de tus grupos activos, o «Sin grupo».')
        upload = request.FILES.get('file')
        if upload is None:
            return self.fail(request, 'Elige un archivo .xlsx o .csv.')
        if upload.size > file_reader.MAX_BYTES:
            return self.fail(request, 'El archivo pesa más de 2 MB. Divide la lista en varios archivos.')
        try:
            headers, rows = file_reader.read_table(upload.name, upload.read())
        except file_reader.ImportFileError as error:
            return self.fail(request, str(error))
        request.session[SESSION_KEY] = {
            'filename': upload.name, 'headers': headers, 'rows': rows, 'course_id': course.pk if course else None,
        }
        return redirect('quizzes:import_preview')

    def fail(self, request, message):
        return render(request, self.template_name, import_form_context(request, error=message))


class QuestionImportPreviewView(TeacherRequiredMixin, View):
    """Paso 2: ver qué pasará con cada fila y confirmar."""

    template_name = 'question_import_preview.html'

    def load(self, request):
        return request.session.get(SESSION_KEY)

    def course(self, request, data):
        """El grupo de destino guardado al subir el archivo; ``(False, None)`` si dejó de ser uno suyo y activo."""
        raw = data.get('course_id')
        return destination(request, str(raw) if raw else GENERAL)

    def get(self, request):
        data = self.load(request)
        if data is None:
            messages.error(request, 'Sube primero el archivo con las preguntas.')
            return redirect('quizzes:import')
        return self.render_preview(request, data)

    def post(self, request):
        data = self.load(request)
        if data is None:
            messages.error(request, 'La vista previa expiró. Sube el archivo de nuevo.')
            return redirect('quizzes:import')
        valid, course = self.course(request, data)
        if not valid:
            messages.error(request, 'El grupo de destino ya no está disponible. Sube el archivo de nuevo.')
            return redirect('quizzes:import')
        # Se vuelve a analizar al confirmar: el banco pudo cambiar desde la vista previa.
        plan = question_import.analyze(request.organization, data['headers'], data['rows'], course)
        if plan.header_errors:
            return self.render_preview(request, data)
        try:
            summary = question_import.apply_import(request.organization, request.user, plan, course)
        except PlanLimitError as error:
            limits.flash_limit_error(request, error)
            return self.render_preview(request, data)
        del request.session[SESSION_KEY]
        text = f'Importación lista: {summary["created"]} preguntas nuevas.'
        if summary['duplicates']:
            text += f' {summary["duplicates"]} ya estaban en el banco y se omitieron.'
        if summary['errors']:
            text += f' Se omitieron {summary["errors"]} filas con errores.'
        messages.success(request, text)
        return redirect('quizzes:bank')

    def render_preview(self, request, data):
        _, course = self.course(request, data)
        plan = question_import.analyze(request.organization, data['headers'], data['rows'], course)
        limit_error = ''
        try:
            limits.check_limit(request.organization, 'questions', adding=plan.count_new)
        except PlanLimitError as error:
            limit_error = ' '.join(error.messages)
        return render(request, self.template_name, {
            'filename': data['filename'], 'plan': plan, 'preview': plan.items[:PREVIEW_ROWS],
            'hidden': max(len(plan.items) - PREVIEW_ROWS, 0), 'can_confirm': plan.count_new > 0 and not limit_error,
            'limit_error': limit_error, 'course': course,
        })


class QuestionImportTemplateView(TeacherRequiredMixin, View):
    """Plantilla CSV con el formato que entiende la importación."""

    def get(self, request):
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = 'attachment; filename="plantilla-preguntas.csv"'
        response.write('﻿')  # BOM para que Excel respete los acentos
        writer = csv.writer(response)
        writer.writerow(question_import.TEMPLATE_HEADERS)
        writer.writerows(question_import.TEMPLATE_ROWS)
        return response
