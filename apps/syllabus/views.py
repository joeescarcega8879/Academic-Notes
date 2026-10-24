"""Pantalla del temario de un grupo: subir o pegar el texto y editar las semanas. Solo para el docente del grupo."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.ai import drafts as ai_drafts, ui as ai_ui
from apps.ai.models import AIDraft
from apps.courses.models import Course
from core.utils import parse_id

from .forms import PasteForm, StartDateForm, UploadForm, WeekForm
from .models import Syllabus
from .services import extraction, weeks as week_ops
from .tasks import extract_syllabus_text


def range_label(monday, friday):
    """«24–28 ago» o «31 ago–4 sep» cuando la semana cruza de mes."""
    if monday.month == friday.month:
        return f'{monday.day}–{date_format(friday, "j b")}'
    return f'{date_format(monday, "j b")}–{date_format(friday, "j b")}'


class SyllabusAccessMixin(TeacherRequiredMixin):
    """El temario es del docente del grupo; un grupo archivado ya no se edita (igual que el esquema)."""

    def get_course(self, pk):
        return get_object_or_404(
            Course.objects.for_organization(self.request.organization).filter(
                professor=self.request.user, status=Course.Status.ACTIVE,
            ),
            pk=pk,
        )


class SyllabusView(SyllabusAccessMixin, View):
    template_name = 'syllabus.html'

    # ── Armado de la página ───────────────────────────────────────────

    def page(self, request, course, syllabus, week=None, **bound):
        """Contexto y respuesta. ``week`` es la semana abierta en el editor; ``bound`` trae formularios con errores."""
        rows, today = [], timezone.localdate()
        current = None
        if syllabus is not None:
            current = week_ops.current_week(syllabus, today)
            for item in syllabus.weeks.prefetch_related('activities'):
                dates = week_ops.week_dates(syllabus, item)
                rows.append({
                    'week': item, 'dates': range_label(*dates) if dates else '', 'activities': list(item.activities.all()),
                    'is_now': current is not None and item.pk == current.pk,
                })
            if week is None:
                week = self.week_from_query(request, syllabus, current)
        selected = next((row for row in rows if week is not None and row['week'].pk == week.pk), None)
        proposals = []
        if syllabus is not None and request.GET.get('detectar') and syllabus.text:
            proposals = week_ops.detect_weeks(syllabus.text)
            if not proposals:
                messages.info(request, 'No encontramos encabezados como «Semana 1», «Semana 2»… en el texto. Arma las semanas a mano o ajusta el texto.')
        ai_context = {}
        if syllabus is not None:
            ai_context = self.ai_context(request, course, syllabus, selected['week'] if selected else None)
        context = {
            **ai_context,
            'course': course, 'syllabus': syllabus, 'rows': rows, 'selected': selected, 'current': current,
            'week_form': bound.get('week_form') or (WeekForm(instance=week) if week is not None else None),
            'upload_form': bound.get('upload_form') or UploadForm(), 'paste_form': bound.get('paste_form') or PasteForm(),
            'start_form': bound.get('start_form') or StartDateForm(initial={'start_date': syllabus.start_date if syllabus else None}),
            'proposals': proposals, 'show_forms': bool(bound.get('upload_form') or bound.get('paste_form')),
            'week_limit': week_ops.MAX_WEEKS,
        }
        return render(request, self.template_name, context)

    def ai_context(self, request, course, syllabus, week):
        """Lo que la pantalla necesita para ofrecer la IA: el panel de quiz, la división propuesta y las propuestas sin resolver."""
        split = None
        wanted = parse_id(request.GET.get('ia', ''))
        if wanted is not None:
            split = ai_drafts.queryset_for(request.user, request.organization).filter(
                course=course, kind=AIDraft.Kind.SYLLABUS_SPLIT, pk=wanted,
                status__in=(AIDraft.Status.PENDING, AIDraft.Status.READY, AIDraft.Status.FAILED),
            ).first()
            if split is not None:
                split = ai_drafts.expire_if_stale(split)
        return {
            'ai': ai_ui.quiz_panel(request.organization, course, week=week), 'ai_split': split,
            'ai_task': ai_ui.assignment_panel(request.organization, course, week_id=week.pk if week else None),
            'ai_task_drafts': ai_drafts.open_assignment_drafts(request.user, request.organization, course),
            'ai_split_reason': ai_ui.split_reason(request.organization, syllabus),
            'ai_quiz_drafts': ai_drafts.open_quiz_drafts(request.user, request.organization, course),
        }

    @staticmethod
    def week_from_query(request, syllabus, current):
        number = parse_id(request.GET.get('semana', ''))
        if number is not None:
            found = syllabus.weeks.filter(position=number).first()
            if found is not None:
                return found
        return current or syllabus.weeks.first()

    @staticmethod
    def back(course, week=None):
        url = reverse('syllabus:index', args=[course.pk])
        return redirect(f'{url}?semana={week.position}' if week is not None else url)

    # ── Peticiones ────────────────────────────────────────────────────

    def get(self, request, pk):
        course = self.get_course(pk)
        return self.page(request, course, Syllabus.objects.filter(course=course).first())

    def post(self, request, pk):
        course = self.get_course(pk)
        syllabus = Syllabus.objects.filter(course=course).first()
        action = request.POST.get('action', '')
        handler = getattr(self, f'do_{action}', None)
        if action in ('upload', 'paste', 'manual'):
            return handler(request, course, syllabus)
        if syllabus is None or handler is None:
            raise Http404
        return handler(request, course, syllabus)

    # ── Acciones sobre el temario ─────────────────────────────────────

    def do_upload(self, request, course, syllabus):
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.page(request, course, syllabus, upload_form=form)
        saved = extraction.save_uploaded_file(course, form.cleaned_data['file'])
        transaction.on_commit(lambda: extract_syllabus_text.delay(saved.pk))
        messages.success(request, 'Archivo guardado. Estamos sacando el texto; si tarda, vuelve a abrir esta página en un momento.')
        return self.back(course)

    def do_paste(self, request, course, syllabus):
        form = PasteForm(request.POST)
        if not form.is_valid():
            return self.page(request, course, syllabus, paste_form=form)
        extraction.save_pasted_text(course, form.cleaned_data['text'])
        messages.success(request, 'Se guardó el texto del temario.')
        return self.back(course)

    def do_manual(self, request, course, syllabus):
        extraction.get_or_create_syllabus(course)
        return self.back(course)

    def do_delete_syllabus(self, request, course, syllabus):
        extraction.delete_syllabus(syllabus)
        messages.success(request, 'Se eliminó el temario. Tus actividades siguen ahí, solo que sin semana.')
        return self.back(course)

    def do_start_date(self, request, course, syllabus):
        form = StartDateForm(request.POST)
        week = self.posted_week(request, syllabus, required=False)
        if not form.is_valid():
            messages.error(request, 'Escribe una fecha de inicio válida.')
            return self.back(course, week)
        syllabus.start_date = form.cleaned_data['start_date']
        syllabus.save(update_fields=['start_date', 'updated_at'])
        messages.success(request, 'Se actualizaron las fechas de las semanas.')
        return self.back(course, week)

    def do_apply_detected(self, request, course, syllabus):
        proposals = week_ops.detect_weeks(syllabus.text)
        if not proposals:
            messages.error(request, 'Ya no hay semanas que detectar en el texto.')
            return self.back(course)
        week_ops.replace_weeks(syllabus, proposals)
        messages.success(request, f'Se crearon {len(proposals)} semanas a partir del texto.')
        return self.back(course, syllabus.weeks.first())

    def do_ai_split_apply(self, request, course, syllabus):
        draft = get_object_or_404(
            ai_drafts.queryset_for(request.user, request.organization), pk=parse_id(request.POST.get('draft', '')) or 0,
            course=course, kind=AIDraft.Kind.SYLLABUS_SPLIT,
        )
        try:
            count = ai_drafts.apply_split(draft.pk, request.user)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return self.back(course)
        messages.success(request, f'Se crearon {count} semanas con la propuesta de la IA. Revísalas y ajústalas cuando quieras.')
        return self.back(course, syllabus.weeks.first())

    def do_ai_split_discard(self, request, course, syllabus):
        draft = get_object_or_404(
            ai_drafts.queryset_for(request.user, request.organization), pk=parse_id(request.POST.get('draft', '')) or 0,
            course=course, kind=AIDraft.Kind.SYLLABUS_SPLIT,
        )
        if draft.is_open:
            ai_drafts.discard_all(draft)
        return self.back(course)

    def do_ai_split_retry(self, request, course, syllabus):
        draft = get_object_or_404(
            ai_drafts.queryset_for(request.user, request.organization), pk=parse_id(request.POST.get('draft', '')) or 0,
            course=course, kind=AIDraft.Kind.SYLLABUS_SPLIT,
        )
        try:
            ai_drafts.retry(draft)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return self.back(course)
        return redirect(f'{reverse("syllabus:index", args=[course.pk])}?ia={draft.pk}')

    # ── Acciones sobre una semana ─────────────────────────────────────

    def posted_week(self, request, syllabus, required=True):
        week = None
        number = parse_id(request.POST.get('week', ''))
        if number is not None:
            week = syllabus.weeks.filter(pk=number).first()
        if week is None and required:
            raise Http404
        return week

    def do_add_week(self, request, course, syllabus):
        try:
            week = week_ops.add_week(syllabus)
        except week_ops.WeekError as error:
            messages.error(request, str(error))
            return self.back(course)
        return self.back(course, week)

    def do_save_week(self, request, course, syllabus):
        week = self.posted_week(request, syllabus)
        form = WeekForm(request.POST, instance=week)
        if not form.is_valid():
            return self.page(request, course, syllabus, week=week, week_form=form)
        form.save()
        messages.success(request, f'Se guardó la semana {week.position}.')
        return self.back(course, week)

    def save_then(self, request, course, syllabus, operation):
        """Guarda lo escrito en el editor y luego mueve/divide/une, para no perder cambios sin guardar."""
        week = self.posted_week(request, syllabus)
        form = WeekForm(request.POST, instance=week)
        if not form.is_valid():
            return self.page(request, course, syllabus, week=week, week_form=form)
        form.save()
        try:
            result = operation(week)
        except week_ops.WeekError as error:
            messages.error(request, str(error))
            return self.back(course, week)
        return self.back(course, result)

    def do_move_up(self, request, course, syllabus):
        return self.save_then(request, course, syllabus, lambda week: week_ops.move_week(week, -1))

    def do_move_down(self, request, course, syllabus):
        return self.save_then(request, course, syllabus, lambda week: week_ops.move_week(week, +1))

    def do_split(self, request, course, syllabus):
        return self.save_then(request, course, syllabus, week_ops.split_week)

    def do_merge(self, request, course, syllabus):
        return self.save_then(request, course, syllabus, week_ops.merge_with_next)

    def do_delete_all_weeks(self, request, course, syllabus):
        count = week_ops.delete_all_weeks(syllabus)
        if count:
            messages.success(request, f'Se quitaron las {count} semanas. Tus actividades siguen ahí, solo que sin semana.' if count > 1 else 'Se quitó la semana.')
        return self.back(course)

    def do_delete_week(self, request, course, syllabus):
        week = self.posted_week(request, syllabus)
        position = week.position
        week_ops.delete_week(week)
        messages.success(request, f'Se quitó la semana {position}.')
        return self.back(course, syllabus.weeks.filter(position=min(position, syllabus.weeks.count())).first())


class SyllabusFileView(SyllabusAccessMixin, View):
    """Descarga del archivo original del temario: solo el docente del grupo."""

    def get(self, request, pk):
        course = self.get_course(pk)
        syllabus = get_object_or_404(Syllabus, course=course)
        if not syllabus.file:
            raise Http404
        response = FileResponse(
            syllabus.file.open('rb'), as_attachment=True,
            filename=syllabus.original_name or 'temario', content_type='application/octet-stream',
        )
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store'
        return response
