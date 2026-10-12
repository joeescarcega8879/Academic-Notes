"""Constructor de quizzes: configuración y preguntas."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.functional import cached_property
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.grades.models import Activity

from .forms import BankFilterForm, QuizConfigForm
from .models import Question, QuizConfig, QuizQuestion
from .services import builder

PICKER_PAGE_SIZE = 15


class OwnQuizMixin(TeacherRequiredMixin):
    """El quiz de una actividad de un grupo activo del docente, en la organización activa."""

    @cached_property
    def activity(self):
        return get_object_or_404(
            Activity.objects.for_organization(self.request.organization).select_related('course', 'criterion__period'),
            pk=self.kwargs['pk'], type=Activity.Type.QUIZ, course__professor=self.request.user,
        )

    @cached_property
    def quiz(self):
        quiz, _ = QuizConfig.objects.get_or_create(activity=self.activity)
        return quiz


class BuilderView(OwnQuizMixin, View):
    template_name = 'quiz_builder.html'

    def get(self, request, pk):
        return self.render_page(request)

    def render_page(self, request, config_form=None):
        quiz = self.quiz
        count, total = builder.totals(quiz)
        archived_course = self.activity.course.is_archived

        picker = Question.objects.for_organization(request.organization).filter(is_archived=False).exclude(
            pk__in=quiz.questions.exclude(source=None).values_list('source_id', flat=True),
        ).select_related('author').prefetch_related('choices')
        filters = BankFilterForm({'q': request.GET.get('bq', ''), 'topic': request.GET.get('btopic', ''), 'kind': request.GET.get('bkind', '')})
        data = filters.cleaned_data if filters.is_valid() else {}
        if data.get('q'):
            picker = picker.filter(Q(text__icontains=data['q']) | Q(topic__icontains=data['q']))
        if data.get('topic'):
            picker = picker.filter(topic__iexact=data['topic'])
        if data.get('kind'):
            picker = picker.filter(kind=data['kind'])
        page = Paginator(picker, PICKER_PAGE_SIZE).get_page(request.GET.get('bp'))
        query = request.GET.copy()
        query.pop('bp', None)

        return render(request, self.template_name, {
            'activity': self.activity, 'course': self.activity.course, 'quiz': quiz,
            'config_form': config_form or QuizConfigForm(instance=quiz),
            'questions': quiz.questions.prefetch_related('choices'),
            'question_count': count, 'total_points': total,
            'points_match': float(total) == float(self.activity.max_score),
            'locked': quiz.is_locked, 'read_only': archived_course,
            'picker': page, 'picker_querystring': query.urlencode(),
            'picker_filters': {'q': data.get('q', ''), 'topic': data.get('topic', ''), 'kind': data.get('kind', '')},
            'kinds': Question.Kind.choices,
        })

    def post(self, request, pk):
        if self.activity.course.is_archived:
            messages.error(request, 'El grupo está archivado y es de solo lectura.')
            return redirect('quizzes:builder', pk=pk)

        action = request.POST.get('action')
        try:
            if action == 'settings':
                form = QuizConfigForm(request.POST, instance=self.quiz)
                if not form.is_valid():
                    return self.render_page(request, config_form=form)
                form.save()
                messages.success(request, 'Se guardó la configuración del quiz.')
            elif action == 'add':
                ids = [int(i) for i in request.POST.getlist('question') if i.isdigit()]
                questions = Question.objects.for_organization(request.organization).filter(pk__in=ids)
                added = builder.add_questions(self.quiz, questions)
                messages.success(request, f'Se agregaron {len(added)} preguntas.' if added else 'No había preguntas nuevas que agregar.')
            elif action in ('remove', 'up', 'down', 'points'):
                question = get_object_or_404(QuizQuestion.objects.filter(quiz=self.quiz), pk=request.POST.get('question_id') or 0)
                if action == 'remove':
                    builder.remove_question(question)
                    messages.success(request, 'Se quitó la pregunta del quiz.')
                elif action == 'points':
                    builder.set_points(question, request.POST.get('points', ''))
                    messages.success(request, 'Se actualizaron los puntos.')
                else:
                    builder.move_question(question, -1 if action == 'up' else 1)
            elif action == 'sync':
                builder.sync_activity_points(self.quiz)
                messages.success(request, 'Los puntos de la actividad ahora son el total de las preguntas.')
            else:
                messages.error(request, 'Acción desconocida.')
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
        return redirect('quizzes:builder', pk=pk)
