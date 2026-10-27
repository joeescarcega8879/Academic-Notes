"""Pantallas de la IA asistida: pedir preguntas de quiz o examen y revisar las propuestas. Solo para el docente que las pidió."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.models import Course
from apps.grades.models import Activity
from apps.organizations import limits
from apps.quizzes.models import Question, QuizConfig
from apps.quizzes.services import builder, exams
from apps.syllabus.models import Syllabus
from core.utils import parse_id

from . import assignment_generation as task_gen
from . import drafts, quiz_generation as quiz_gen, services, split_generation as split_gen
from .models import AIDraft

REVIEW_ACTIONS = {'save', 'discard', 'restore', 'edit', 'save_edit', 'regen', 'discard_all', 'apply'}


def _course(request, pk):
    return get_object_or_404(
        Course.objects.for_organization(request.organization).filter(professor=request.user, status=Course.Status.ACTIVE), pk=pk,
    )


def _flash_errors(request, error):
    if isinstance(error, limits.PlanLimitError):
        limits.flash_limit_error(request, error)
    else:
        messages.error(request, ' '.join(error.messages))


class QuizGenerateView(TeacherRequiredMixin, View):
    """Recibe el panel «Generar preguntas con IA» y deja la propuesta en marcha."""

    def post(self, request, pk):
        course = _course(request, pk)
        activity = None
        activity_id = parse_id(request.POST.get('activity', ''))
        if activity_id is not None:
            activity = get_object_or_404(
                Activity.objects.for_organization(request.organization).filter(
                    course=course, type__in=(Activity.Type.QUIZ, Activity.Type.EXAM),
                ),
                pk=activity_id,
            )
        back = reverse('quizzes:builder', args=[activity.pk]) if activity else reverse('syllabus:index', args=[course.pk])
        # Desde una semana (sin actividad) el docente elige si quiere un quiz o un examen.
        exam = activity.type == Activity.Type.EXAM if activity is not None else request.POST.get('kind') == 'exam'
        try:
            if activity is not None:
                if exam and not exams.uses_quiz_engine(activity):
                    raise ValidationError('Aplica el examen en línea antes de generarle preguntas con IA.')
                builder.ensure_editable(QuizConfig.objects.get_or_create(activity=activity)[0])
            params = quiz_gen.clean_params(request.POST, course, exam=exam)
            draft = drafts.request_quiz(
                user=request.user, organization=request.organization, course=course, params=params, activity=activity,
                title=request.POST.get('title', ''),
            )
        except ValidationError as error:
            _flash_errors(request, error)
            return redirect(back)
        return redirect('ai:draft', pk=draft.pk)


class AssignmentGenerateView(TeacherRequiredMixin, View):
    """Recibe el panel «Redactar una tarea con IA» y deja la propuesta en marcha."""

    def post(self, request, pk):
        course = _course(request, pk)
        try:
            params = task_gen.clean_params(request.POST, course)
            draft = drafts.request_assignments(user=request.user, organization=request.organization, course=course, params=params)
        except ValidationError as error:
            _flash_errors(request, error)
            back = reverse('grades:activity_create', args=[course.pk]) if request.POST.get('origin') == 'form' else reverse('syllabus:index', args=[course.pk])
            return redirect(back)
        return redirect('ai:assignment_draft', pk=draft.pk)


class SplitGenerateView(TeacherRequiredMixin, View):
    """«Proponer semanas con IA»: deja la propuesta en marcha y vuelve al temario a esperarla."""

    def post(self, request, pk):
        course = _course(request, pk)
        syllabus = get_object_or_404(Syllabus, course=course)
        try:
            params = split_gen.clean_params(request.POST, syllabus)
            draft = drafts.request_split(user=request.user, organization=request.organization, course=course, params=params)
        except ValidationError as error:
            _flash_errors(request, error)
            return redirect('syllabus:index', pk=course.pk)
        return redirect(f'{reverse("syllabus:index", args=[course.pk])}?ia={draft.pk}')


class DraftMixin(TeacherRequiredMixin):
    kind = AIDraft.Kind.QUIZ_QUESTIONS

    def get_draft(self, pk):
        return get_object_or_404(
            drafts.queryset_for(self.request.user, self.request.organization).select_related('course', 'activity'),
            pk=pk, **({'kind': self.kind} if self.kind else {}),
        )


class DraftStatusView(DraftMixin, View):
    """Lo consulta la página mientras espera: cuándo recargar. Sirve para cualquier tipo de propuesta."""

    kind = None

    def get(self, request, pk):
        draft = drafts.expire_if_stale(self.get_draft(pk))
        busy = draft.status == AIDraft.Status.PENDING or any(item.get('state') == drafts.REGENERATING for item in draft.items)
        return JsonResponse({'busy': busy})


class DraftView(DraftMixin, View):
    template_name = 'ai_draft.html'

    def get(self, request, pk):
        draft = drafts.expire_if_stale(self.get_draft(pk))
        return self.render_page(request, draft)

    @staticmethod
    def back_url(draft):
        if draft.activity_id:
            return reverse('quizzes:builder', args=[draft.activity_id])
        return reverse('syllabus:index', args=[draft.course_id])

    def render_page(self, request, draft):
        editing = parse_id(request.GET.get('editar', '')) if draft.status == AIDraft.Status.READY else None
        weeks = {week.position: week for week in quiz_gen.course_weeks(draft.course)}
        rows = []
        for index, item in enumerate(draft.items):
            week = weeks.get(item['week'])
            rows.append({
                'i': index, 'n': index + 1, 'item': item, 'editing': editing == index and item['state'] != drafts.REGENERATING,
                'kind_label': dict(Question.Kind.choices).get(item['kind'], ''),
                'letters': [(chr(65 + position), choice) for position, choice in enumerate(item['choices'])],
                'week_label': f'Semana {item["week"]}' + (f' · {week.title}' if week and week.title else ''),
            })
        approved = draft.count(drafts.APPROVED)
        busy = draft.status == AIDraft.Status.PENDING or any(row['item']['state'] == drafts.REGENERATING for row in rows)
        quiz_count = None
        if draft.activity_id and draft.status == AIDraft.Status.READY:
            quiz_count = builder.totals(QuizConfig.objects.get_or_create(activity=draft.activity)[0])[0]
        context = {
            'draft': draft, 'course': draft.course, 'rows': rows, 'approved': approved, 'busy': busy, 'quiz_count': quiz_count,
            'discarded': draft.count(drafts.DISCARDED), 'total': len(rows), 'back_url': self.back_url(draft),
            'noun': drafts.noun(draft),
            'week_names': ', '.join(
                str(week.position) for week in weeks.values() if week.pk in draft.params.get('week_ids', [])
            ),
            'usage': services.usage_summary(request.organization),
        }
        return render(request, self.template_name, context)

    def post(self, request, pk):
        draft = self.get_draft(pk)
        action, _, argument = request.POST.get('action', '').partition(':')
        index = parse_id(argument) if argument else None
        here = reverse('ai:draft', args=[draft.pk])
        if action == 'retry':
            try:
                drafts.retry(draft)
            except ValidationError as error:
                _flash_errors(request, error)
            return redirect(here)
        if action not in REVIEW_ACTIONS:
            messages.error(request, 'Acción desconocida.')
            return redirect(here)
        target = here
        try:
            with drafts.locked(draft.pk) as current:
                if current.status != AIDraft.Status.READY:
                    raise ValidationError('Esta propuesta ya no se puede modificar.')
                drafts.save_review_state(current, request.POST)
                if action == 'discard':
                    drafts.set_state(current, index, drafts.DISCARDED)
                elif action == 'restore':
                    drafts.set_state(current, index, drafts.PENDING)
                elif action == 'edit':
                    drafts.item_at(current, index)
                    target = f'{here}?editar={index}#p{index + 1}'
                elif action == 'save_edit':
                    target = f'{here}?editar={index}#p{index + 1}'
                    drafts.edit_item(current, index, request.POST)
                    target = f'{here}#p{index + 1}'
                    messages.success(request, 'Se guardaron tus cambios. Revisa que la respuesta marcada sea la correcta.')
                current.save()
            if action == 'regen':
                drafts.request_regeneration(draft, index, request.user)
            elif action == 'discard_all':
                with drafts.locked(draft.pk) as current:
                    drafts.discard_all(current)
                messages.success(request, f'Se descartaron todas las propuestas. No se agregó nada al {drafts.noun(draft)}.')
                return redirect(self.back_url(draft))
            elif action == 'apply':
                activity = drafts.apply_quiz(draft.pk, request.user)
                draft.refresh_from_db()
                count = draft.count(drafts.APPROVED)
                noun = drafts.noun(draft)
                messages.success(request, f'Se agregaron {count} pregunta{"s" if count != 1 else ""} al banco y al {noun}. Revisa el {noun} antes de publicarlo.')
                return redirect('quizzes:builder', pk=activity.pk)
        except ValidationError as error:
            _flash_errors(request, error)
        return redirect(target)


class AssignmentDraftView(DraftMixin, View):
    """Las alternativas de tarea: revisarlas, editarlas, regenerarlas y crear la que sirva."""

    template_name = 'ai_assignment_draft.html'
    kind = AIDraft.Kind.ASSIGNMENTS
    actions = {'save', 'discard', 'restore', 'edit', 'save_edit', 'regen', 'create', 'finish'}

    def get(self, request, pk):
        draft = drafts.expire_if_stale(self.get_draft(pk))
        editing = parse_id(request.GET.get('editar', '')) if draft.status == AIDraft.Status.READY else None
        weeks = {week.position: week for week in quiz_gen.course_weeks(draft.course)}
        rows = []
        for index, item in enumerate(draft.items):
            week = weeks.get(item['week'])
            rows.append({
                'i': index, 'n': index + 1, 'item': item, 'editing': editing == index and item['state'] == drafts.PENDING,
                'week_label': f'Semana {item["week"]}' + (f' · {week.title}' if week and week.title else ''),
                'type_label': dict(task_gen.TYPES).get(item['type'], 'Tarea'),
            })
        busy = draft.status == AIDraft.Status.PENDING or any(row['item']['state'] == drafts.REGENERATING for row in rows)
        week_names = ', '.join(str(week.position) for week in weeks.values() if week.pk in draft.params.get('week_ids', []))
        return render(request, self.template_name, {
            'draft': draft, 'course': draft.course, 'rows': rows, 'busy': busy, 'week_names': week_names,
            'back_url': reverse('syllabus:index', args=[draft.course_id]), 'usage': services.usage_summary(request.organization),
            'params_type': dict(task_gen.TYPES).get(draft.params.get('type'), 'Tarea'),
            'open_count': draft.count(drafts.PENDING),
        })

    def post(self, request, pk):
        draft = self.get_draft(pk)
        action, _, argument = request.POST.get('action', '').partition(':')
        index = parse_id(argument) if argument else None
        here = reverse('ai:assignment_draft', args=[draft.pk])
        if action == 'retry':
            try:
                drafts.retry(draft)
            except ValidationError as error:
                _flash_errors(request, error)
            return redirect(here)
        if action not in self.actions:
            messages.error(request, 'Acción desconocida.')
            return redirect(here)
        target = here
        try:
            if action == 'create':
                activity = drafts.create_assignment(draft.pk, index, request.user)
                messages.success(request, f'Se creó «{activity.title}» como borrador. Revísala y publícala cuando esté lista.')
                return redirect(activity.get_absolute_url())
            with drafts.locked(draft.pk) as current:
                if current.status != AIDraft.Status.READY:
                    raise ValidationError('Esta propuesta ya no se puede modificar.')
                if action in ('discard', 'restore'):
                    drafts.set_state(current, index, drafts.DISCARDED if action == 'discard' else drafts.PENDING)
                    drafts.settle_assignments(current)
                elif action == 'edit':
                    drafts.item_at(current, index)
                    target = f'{here}?editar={index}#p{index + 1}'
                elif action == 'save_edit':
                    target = f'{here}?editar={index}#p{index + 1}'
                    drafts.edit_assignment(current, index, request.POST)
                    target = f'{here}#p{index + 1}'
                    messages.success(request, 'Se guardaron tus cambios.')
                elif action == 'finish':
                    drafts.close_assignments(current)
                current.save()
            if action == 'regen':
                drafts.request_regeneration(draft, index, request.user)
            elif action == 'finish':
                messages.success(request, 'Listo. Las alternativas que no creaste se descartaron.')
                return redirect(self.back_url(draft))
        except ValidationError as error:
            _flash_errors(request, error)
        return redirect(target)

    @staticmethod
    def back_url(draft):
        return reverse('syllabus:index', args=[draft.course_id])
