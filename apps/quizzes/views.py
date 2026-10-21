"""Banco de preguntas: por grupo, más las generales (sin grupo)."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin

from apps.grades.models import Activity
from apps.organizations import limits
from apps.organizations.limits import PlanLimitError
from core.utils import parse_id

from .forms import BankFilterForm, QuestionForm, TrueFalseForm, choice_formset
from .models import Question, QuizConfig
from .services import builder
from .services.bank import (
    TRUE_FALSE_LABELS, UNSET, bank_courses, can_edit_question, duplicate_question, save_question, teaching_courses,
    visible_questions,
)

PAGE_SIZE = 20


class BankMixin(TeacherRequiredMixin):
    """El banco de la organización activa, por grupo: cada docente ve el de sus grupos y las preguntas generales."""

    def questions(self):
        return (
            visible_questions(self.request.organization, self.request.user)
            .select_related('author', 'course').prefetch_related('choices')
        )

    def get_question(self, pk):
        return get_object_or_404(self.questions(), pk=pk)

    def get_editable_question(self, pk):
        question = self.get_question(pk)
        if not can_edit_question(self.request.user, self.request.membership, question):
            raise Http404  # a la pregunta de otro docente se llega a leerla y duplicarla, no a editarla
        return question


class BankView(BankMixin, View):
    def get(self, request):
        form = BankFilterForm(request.GET, groups=bank_courses(request.user, request.organization))
        data = form.cleaned_data if form.is_valid() else {}
        questions = self.questions().filter(is_archived=bool(data.get('archived')))
        group = data.get('grupo', '')
        if group == 'sin':
            questions = questions.filter(course__isnull=True)
        elif group:
            questions = questions.filter(course_id=int(group))
        if data.get('q'):
            questions = questions.filter(Q(text__icontains=data['q']) | Q(topic__icontains=data['q']))
        if data.get('topic'):
            questions = questions.filter(topic__iexact=data['topic'])
        if data.get('kind'):
            questions = questions.filter(kind=data['kind'])
        topics = (
            visible_questions(request.organization, request.user).exclude(topic='')
            .order_by('topic').values_list('topic', flat=True).distinct()
        )
        page = Paginator(questions, PAGE_SIZE).get_page(request.GET.get('page'))
        query = request.GET.copy()
        query.pop('page', None)
        return render(request, 'bank.html', {
            'form': form, 'page': page, 'topics': topics, 'querystring': query.urlencode(),
            'showing_archived': bool(data.get('archived')),
            # Las preguntas nuevas se proponen en el grupo que se está viendo.
            'group_query': f'?grupo={group}' if group.isdigit() else '',
        })


class QuestionFormMixin(BankMixin):
    template_name = 'question_form.html'

    def initial_course(self):
        """El grupo con el que se abre el formulario de una pregunta nueva: el que se estaba viendo, el del quiz o el único."""
        groups = teaching_courses(self.request.user, self.request.organization)
        wanted = parse_id(self.request.GET.get('grupo', ''))
        if wanted is not None and groups.filter(pk=wanted).exists():
            return wanted
        target = self.quiz_to_add_to(self.request)
        if target is not None:
            return target.activity.course_id
        only = list(groups.values_list('pk', flat=True)[:2])
        return only[0] if len(only) == 1 else None

    def forms_for(self, kind, data=None, question=None):
        who = {'user': self.request.user, 'organization': self.request.organization}
        initial = {'course': self.initial_course()} if question is None and data is None else {}
        if kind == Question.Kind.TRUE_FALSE:
            if question is not None:
                verdadero = next(c for c in question.choices.all() if c.text == TRUE_FALSE_LABELS[0])
                initial['correct'] = 'true' if verdadero.is_correct else 'false'
            return TrueFalseForm(data, instance=question, initial=initial, **who), None
        return QuestionForm(data, instance=question, initial=initial, **who), choice_formset(data, question=question)

    def render_page(self, request, kind, form, formset, question=None):
        return render(request, self.template_name, {
            'form': form, 'formset': formset, 'kind': kind, 'kind_label': Question.Kind(kind).label, 'question': question,
        })

    def process(self, request, kind, question=None):
        form, formset = self.forms_for(kind, request.POST, question)
        valid = form.is_valid() and (formset is None or formset.is_valid())
        if valid:
            try:
                saved = save_question(
                    organization=request.organization, author=request.user, kind=kind,
                    text=form.cleaned_data['text'], points=form.cleaned_data['points'],
                    explanation=form.cleaned_data['explanation'], topic=form.cleaned_data['topic'],
                    choices=formset.cleaned_choices if formset is not None else None,
                    true_is_correct=(form.cleaned_data['correct'] == 'true') if formset is None else None,
                    question=question, course=form.cleaned_data['course'],
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Se guardó la pregunta.')
                if question is None:
                    target = self.quiz_to_add_to(request)
                    if target is not None:
                        try:
                            builder.add_questions(target, [saved])
                        except ValidationError as error:
                            messages.error(request, ' '.join(error.messages))
                        else:
                            messages.success(request, 'La pregunta también quedó en el quiz.')
                        return redirect('quizzes:builder', pk=target.activity_id)
                return redirect('quizzes:question_detail', pk=saved.pk)
        return self.render_page(request, kind, form, formset, question)

    def quiz_to_add_to(self, request):
        """El quiz (propio y de un grupo activo) al que se agrega la pregunta nueva, si se llegó desde su constructor."""
        activity_id = parse_id(request.GET.get('add_to', ''))
        if activity_id is None:
            return None
        return QuizConfig.objects.filter(
            activity_id=activity_id, activity__course__professor=request.user, organization=request.organization,
            activity__course__status='active',
        ).first()


class QuestionCreateView(QuestionFormMixin, View):
    def kind(self, kind):
        if kind not in Question.Kind.values:
            raise Http404
        return kind

    def get(self, request, kind):
        kind = self.kind(kind)
        try:
            limits.check_limit(request.organization, 'questions')
        except PlanLimitError as error:
            limits.flash_limit_error(request, error)  # antes de llenar un formulario que no se podría guardar
            return redirect('quizzes:bank')
        form, formset = self.forms_for(kind)
        return self.render_page(request, kind, form, formset)

    def post(self, request, kind):
        return self.process(request, self.kind(kind))


class QuestionUpdateView(QuestionFormMixin, View):
    def get(self, request, pk):
        question = self.get_editable_question(pk)
        form, formset = self.forms_for(question.kind, question=question)
        return self.render_page(request, question.kind, form, formset, question)

    def post(self, request, pk):
        question = self.get_editable_question(pk)
        return self.process(request, question.kind, question)


class QuestionDetailView(BankMixin, View):
    def get(self, request, pk):
        question = self.get_question(pk)
        return render(request, 'question_detail.html', {
            'question': question, 'can_edit': can_edit_question(request.user, request.membership, question),
            'duplicate_groups': teaching_courses(request.user, request.organization),
        })


class QuestionDuplicateView(BankMixin, View):
    def post(self, request, pk):
        question = self.get_question(pk)
        # ``grupo`` vacío: en el mismo grupo; «sin»: general; un número: en el banco de ese grupo (uno suyo y activo).
        raw, course = request.POST.get('grupo', ''), UNSET
        if raw == 'sin':
            course = None
        elif raw:
            course = teaching_courses(request.user, request.organization).filter(pk=parse_id(raw) or 0).first()
            if course is None:
                messages.error(request, 'Elige uno de tus grupos activos para la copia.')
                return redirect('quizzes:question_detail', pk=question.pk)
        try:
            copy = duplicate_question(question, by=request.user, course=course)
        except PlanLimitError as error:
            limits.flash_limit_error(request, error)
            return redirect('quizzes:bank')
        messages.success(request, 'Se duplicó la pregunta: ya puedes editar tu copia.')
        return redirect('quizzes:question_update', pk=copy.pk)


class QuestionArchiveView(BankMixin, View):
    def post(self, request, pk):
        question = self.get_editable_question(pk)
        if question.is_archived:  # volver al banco la hace contar otra vez contra el plan
            try:
                limits.check_limit(request.organization, 'questions')
            except PlanLimitError as error:
                limits.flash_limit_error(request, error)
                return redirect('quizzes:bank')
        question.is_archived = not question.is_archived
        question.save(update_fields=['is_archived', 'updated_at'])
        messages.success(request, 'La pregunta se archivó.' if question.is_archived else 'La pregunta volvió al banco.')
        return redirect('quizzes:bank')


class QuestionDeleteView(BankMixin, View):
    def post(self, request, pk):
        question = self.get_editable_question(pk)
        question.delete()
        messages.success(request, 'Se eliminó la pregunta. Los quizzes que ya la usan conservan su copia.')
        return redirect('quizzes:bank')
