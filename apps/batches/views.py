from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.courses.services.text import sort_enrollments
from apps.grades.activity_views import OwnActiveCourseMixin
from apps.grades.models import Activity
from core.utils import parse_id

from .models import BatchFile
from .services import batch, ocr
from .services.pdfs import MAX_PAGES


class BatchMixin(OwnActiveCourseMixin):
    """El docente del grupo (activo) y solo para actividades en las que el alumno entrega algo."""

    def get_activity(self, pk):
        activity = get_object_or_404(self.activities(), pk=pk)
        if not activity.accepts_submissions:
            raise Http404
        return activity

    def get_file(self, pk):
        return get_object_or_404(
            BatchFile.objects.for_organization(self.request.organization).filter(
                activity__in=self.activities().filter(type__in=Activity.SUBMISSION_TYPES),
            ).select_related('activity__course', 'student'),
            pk=pk,
        )

    def back(self, activity):
        return redirect('batches:index', activity.pk)


class BatchView(BatchMixin, View):
    """Lista del lote de la actividad: sube PDFs, muestra de quién es cada uno y deja asignar o descartar."""

    template_name = 'batch.html'

    def page(self, request, activity):
        files = list(BatchFile.objects.filter(activity=activity).select_related('student'))
        students = [e.student for e in sort_enrollments(activity.course.enrollments.select_related('student'))]
        counts = {status: sum(1 for f in files if f.status == status) for status in BatchFile.Status.values}
        return render(request, self.template_name, {
            'activity': activity, 'course': activity.course, 'files': files, 'students': students, 'counts': counts,
            'ready_count': counts[BatchFile.Status.READY], 'reading_count': counts[BatchFile.Status.READING],
            'cover_choices': Activity._meta.get_field('cover_pages').choices, 'ocr_available': ocr.available(),
            'limits': {
                'file_mb': batch.MAX_SUBMISSION_BYTES // (1024 * 1024), 'batch_mb': batch.MAX_BATCH_BYTES // (1024 * 1024),
                'files': batch.MAX_BATCH_FILES, 'pages': MAX_PAGES,
            },
        })

    def get(self, request, pk):
        return self.page(request, self.get_activity(pk))

    def post(self, request, pk):
        activity = self.get_activity(pk)
        valid_covers = {value for value, _ in Activity._meta.get_field('cover_pages').choices}
        cover_pages = parse_id(request.POST.get('cover_pages', ''))
        if cover_pages not in valid_covers:
            cover_pages = activity.cover_pages
        try:
            result = batch.upload(
                activity, request.FILES.getlist('files'), cover_pages=cover_pages, user=request.user,
            )
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return self.back(activity)

        if cover_pages != activity.cover_pages:  # la elección queda como la de la actividad
            Activity.objects.filter(pk=activity.pk).update(cover_pages=cover_pages)
        statuses = [f.status for f in result.created]
        ready = statuses.count(BatchFile.Status.READY)
        total = len(result.created)
        if statuses.count(BatchFile.Status.READING):  # Celery todavía los está leyendo: la página se actualiza sola
            messages.success(
                request, 'Se subió 1 archivo y se está leyendo.' if total == 1 else f'Se subieron {total} archivos y se están leyendo.',
            )
        elif total:
            review = total - ready
            text = 'Se leyó 1 archivo' if total == 1 else f'Se leyeron {total} archivos'
            text += ': 1 identificado' if ready == 1 else f': {ready} identificados'
            if review:
                text += f' y {review} que {"necesita" if review == 1 else "necesitan"} tu revisión.'
            messages.success(request, text if review else text + '.')
        for name, reason in result.rejected:
            messages.error(request, f'{name}: {reason}')
        return self.back(activity)


class BatchStatusView(BatchMixin, View):
    """Para la página del lote: ¿siguen leyéndose archivos? Cuando ya no, se recarga sola."""

    def get(self, request, pk):
        activity = self.get_activity(pk)
        return JsonResponse({'busy': BatchFile.objects.filter(activity=activity, status=BatchFile.Status.READING).exists()})


class BatchAssignView(BatchMixin, View):
    """Dice de quién es un archivo (o que reemplace la entrega que el alumno ya hizo en el portal)."""

    def post(self, request, pk):
        batch_file = self.get_file(pk)
        activity = batch_file.activity
        student_id = parse_id(request.POST.get('student', ''))
        student = None
        if student_id is not None:
            enrollment = activity.course.enrollments.select_related('student').filter(student_id=student_id).first()
            student = enrollment.student if enrollment else None
        if student is None:
            messages.error(request, 'Elige a un alumno del grupo.')
            return self.back(activity)
        try:
            batch.assign(batch_file, student, replace=request.POST.get('replace') == '1')
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        return self.back(activity)


class BatchDiscardView(BatchMixin, View):
    def post(self, request, pk):
        batch_file = self.get_file(pk)
        try:
            batch.discard(batch_file)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        else:
            messages.success(request, f'Se quitó {batch_file.original_name} del lote.')
        return self.back(batch_file.activity)


class BatchApplyView(BatchMixin, View):
    """Convierte en entregas los archivos identificados."""

    def post(self, request, pk):
        activity = self.get_activity(pk)
        try:
            result = batch.apply(activity)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return self.back(activity)
        if result.saved:
            messages.success(request, 'Se guardó 1 entrega.' if result.saved == 1 else f'Se guardaron {result.saved} entregas.')
        elif not result.skipped:
            messages.error(request, 'No hay archivos identificados para guardar.')
        for name, reason in result.skipped:
            messages.error(request, f'{name}: {reason}')
        return self.back(activity)


class BatchFileView(BatchMixin, View):
    """Descarga del PDF del lote (solo el docente del grupo), como las entregas: nunca se interpreta en el navegador."""

    def get(self, request, pk):
        batch_file = self.get_file(pk)
        if not batch_file.file:
            raise Http404
        response = FileResponse(
            batch_file.file.open('rb'), as_attachment=True, filename=batch_file.original_name,
            content_type='application/octet-stream',
        )
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response
