"""Importar preguntas al banco desde Excel o CSV: subir, revisar y confirmar."""

import csv

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.services import importing as file_reader

from .services import question_import

SESSION_KEY = 'question_import'
PREVIEW_ROWS = 200


class QuestionImportView(TeacherRequiredMixin, View):
    """Paso 1: subir el archivo."""

    template_name = 'question_import.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        upload = request.FILES.get('file')
        if upload is None:
            return self.fail(request, 'Elige un archivo .xlsx o .csv.')
        if upload.size > file_reader.MAX_BYTES:
            return self.fail(request, 'El archivo pesa más de 2 MB. Divide la lista en varios archivos.')
        try:
            headers, rows = file_reader.read_table(upload.name, upload.read())
        except file_reader.ImportFileError as error:
            return self.fail(request, str(error))
        request.session[SESSION_KEY] = {'filename': upload.name, 'headers': headers, 'rows': rows}
        return redirect('quizzes:import_preview')

    def fail(self, request, message):
        return render(request, self.template_name, {'error': message})


class QuestionImportPreviewView(TeacherRequiredMixin, View):
    """Paso 2: ver qué pasará con cada fila y confirmar."""

    template_name = 'question_import_preview.html'

    def load(self, request):
        return request.session.get(SESSION_KEY)

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
        # Se vuelve a analizar al confirmar: el banco pudo cambiar desde la vista previa.
        plan = question_import.analyze(request.organization, data['headers'], data['rows'])
        if plan.header_errors:
            return self.render_preview(request, data)
        summary = question_import.apply_import(request.organization, request.user, plan)
        del request.session[SESSION_KEY]
        text = f'Importación lista: {summary["created"]} preguntas nuevas.'
        if summary['duplicates']:
            text += f' {summary["duplicates"]} ya estaban en el banco y se omitieron.'
        if summary['errors']:
            text += f' Se omitieron {summary["errors"]} filas con errores.'
        messages.success(request, text)
        return redirect('quizzes:bank')

    def render_preview(self, request, data):
        plan = question_import.analyze(request.organization, data['headers'], data['rows'])
        return render(request, self.template_name, {
            'filename': data['filename'], 'plan': plan, 'preview': plan.items[:PREVIEW_ROWS],
            'hidden': max(len(plan.items) - PREVIEW_ROWS, 0), 'can_confirm': plan.count_new > 0,
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
