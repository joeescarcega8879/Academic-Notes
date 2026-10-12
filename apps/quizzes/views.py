"""Banco de preguntas de la organización."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin

from .forms import BankFilterForm, QuestionForm, TrueFalseForm, choice_formset
from .models import Question
from .services.bank import TRUE_FALSE_LABELS, can_edit_question, duplicate_question, save_question

PAGE_SIZE = 20


class BankMixin(TeacherRequiredMixin):
    """El banco es de la organización activa: lo ven y lo reutilizan todos sus docentes."""

    def questions(self):
        return Question.objects.for_organization(self.request.organization).select_related('author').prefetch_related('choices')

    def get_question(self, pk):
        return get_object_or_404(self.questions(), pk=pk)

    def get_editable_question(self, pk):
        question = self.get_question(pk)
        if not can_edit_question(self.request.user, self.request.membership, question):
            raise Http404  # a la pregunta de otro docente se llega a leerla y duplicarla, no a editarla
        return question


class BankView(BankMixin, View):
    def get(self, request):
        form = BankFilterForm(request.GET)
        data = form.cleaned_data if form.is_valid() else {}
        questions = self.questions().filter(is_archived=bool(data.get('archived')))
        if data.get('q'):
            questions = questions.filter(Q(text__icontains=data['q']) | Q(topic__icontains=data['q']))
        if data.get('topic'):
            questions = questions.filter(topic__iexact=data['topic'])
        if data.get('kind'):
            questions = questions.filter(kind=data['kind'])
        topics = (
            Question.objects.for_organization(request.organization).exclude(topic='')
            .order_by('topic').values_list('topic', flat=True).distinct()
        )
        page = Paginator(questions, PAGE_SIZE).get_page(request.GET.get('page'))
        query = request.GET.copy()
        query.pop('page', None)
        return render(request, 'bank.html', {
            'form': form, 'page': page, 'topics': topics, 'querystring': query.urlencode(),
            'showing_archived': bool(data.get('archived')),
        })


class QuestionFormMixin(BankMixin):
    template_name = 'question_form.html'

    def forms_for(self, kind, data=None, question=None):
        if kind == Question.Kind.TRUE_FALSE:
            initial = {}
            if question is not None:
                verdadero = next(c for c in question.choices.all() if c.text == TRUE_FALSE_LABELS[0])
                initial['correct'] = 'true' if verdadero.is_correct else 'false'
            return TrueFalseForm(data, instance=question, initial=initial), None
        return QuestionForm(data, instance=question), choice_formset(data, question=question)

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
                    question=question,
                )
            except ValidationError as error:
                form.add_error(None, error)
            else:
                messages.success(request, 'Se guardó la pregunta.')
                return redirect('quizzes:question_detail', pk=saved.pk)
        return self.render_page(request, kind, form, formset, question)


class QuestionCreateView(QuestionFormMixin, View):
    def kind(self, kind):
        if kind not in Question.Kind.values:
            raise Http404
        return kind

    def get(self, request, kind):
        kind = self.kind(kind)
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
        })


class QuestionDuplicateView(BankMixin, View):
    def post(self, request, pk):
        copy = duplicate_question(self.get_question(pk), by=request.user)
        messages.success(request, 'Se duplicó la pregunta: ya puedes editar tu copia.')
        return redirect('quizzes:question_update', pk=copy.pk)


class QuestionArchiveView(BankMixin, View):
    def post(self, request, pk):
        question = self.get_editable_question(pk)
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
