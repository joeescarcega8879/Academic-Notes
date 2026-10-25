"""Resolver un quiz o un examen en línea: el alumno empieza, responde, guarda y envía."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from apps.accounts.mixins import OrganizationMemberMixin
from apps.courses.models import Student
from apps.grades.models import Activity, Grade
from core.utils import parse_id

from .models import Question, QuizAttempt, QuizConfig
from .services import attempts as service
from .services import exams, results


def parse_selections(post):
    """Respuestas del formulario: ``q_<pregunta>`` = id de la opción o texto escrito, ``o_<pregunta>`` = el orden de los
    elementos («3,1,2»). Lo que no viene, no se toca.

    Un valor vacío borra la respuesta. Qué hacer con el valor (un id de opción, un texto) depende del tipo de
    pregunta y lo decide el servicio; aquí solo se separan las respuestas por pregunta.
    """
    selections = {}
    for name, value in post.items():
        question_id = parse_id(name[2:]) if name.startswith(('q_', 'o_')) else None
        if question_id is None:
            continue
        selections[question_id] = None if value == '' else value
    return selections


class StudentQuizMixin(OrganizationMemberMixin):
    def student_only(self, request):
        if not request.membership.is_student:
            raise Http404

    def load_quiz(self, request, pk):
        """(actividad, configuración, ficha del alumno) de un quiz o examen en línea publicado en el que el usuario está inscrito."""
        self.student_only(request)
        activity = get_object_or_404(
            Activity.objects.for_organization(request.organization).filter(
                type__in=(Activity.Type.QUIZ, Activity.Type.EXAM), published=True, course__enrollments__student__user=request.user,
            ).select_related('course', 'criterion__period').distinct(),
            pk=pk,
        )
        quiz = get_object_or_404(QuizConfig.objects.for_organization(request.organization), activity=activity)
        student = get_object_or_404(
            Student.objects.for_organization(request.organization), user=request.user, enrollments__course=activity.course,
        )
        return activity, quiz, student

    def load_attempt(self, request, pk):
        """Un intento del propio alumno, ya puesto al día (si se le acabó el tiempo, queda cerrado)."""
        self.student_only(request)
        attempt = get_object_or_404(
            QuizAttempt.objects.for_organization(request.organization).filter(
                student__user=request.user, quiz__activity__published=True,  # un quiz despublicado deja de verse
            ).select_related(
                'quiz__activity__course', 'student',
            ),
            pk=pk,
        )
        return service.expire_if_overdue(attempt)


class QuizOverviewView(StudentQuizMixin, View):
    """Antes de empezar: reglas del quiz, intentos usados y botón para comenzar o continuar."""

    template_name = 'quiz_overview.html'

    def get(self, request, pk):
        activity, quiz, student = self.load_quiz(request, pk)
        return self.render_page(request, activity, quiz, student)

    def render_page(self, request, activity, quiz, student):
        attempts = [service.expire_if_overdue(a) for a in quiz.attempts.filter(student=student)]
        open_attempt = next((a for a in attempts if a.status == QuizAttempt.Status.IN_PROGRESS), None)
        state = service.window_state(activity)
        used = len(attempts)
        blocked = None
        if open_attempt is None:
            if state == 'not_open':
                blocked = f'El {exams.noun(activity)} todavía no abre.'
            elif state == 'closed':
                blocked = f'El {exams.noun(activity)} ya cerró.'
            elif used >= quiz.attempts_allowed:
                blocked = 'Ya usaste todos tus intentos.'
            elif activity.course.is_archived:
                blocked = 'El grupo está archivado.'
        return render(request, self.template_name, {
            'activity': activity, 'course': activity.course, 'quiz': quiz, 'attempts': attempts,
            'open_attempt': open_attempt, 'attempts_used': used, 'blocked': blocked,
            'question_count': quiz.questions.count(), 'window_state': state,
        })

    def post(self, request, pk):
        activity, quiz, student = self.load_quiz(request, pk)
        try:
            attempt = service.start_attempt(quiz, student)
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return redirect('quizzes:overview', pk=pk)
        return redirect('quizzes:take', pk=attempt.pk)


class QuizTakeView(StudentQuizMixin, View):
    template_name = 'quiz_take.html'

    def get(self, request, pk):
        attempt = self.load_attempt(request, pk)
        if attempt.is_finished:
            return redirect('quizzes:result', pk=attempt.pk)
        quiz = attempt.quiz
        questions = {q.pk: q for q in quiz.questions.prefetch_related('choices')}
        choices = attempt.layout.get('choices', {})
        saved = {
            question_id: (choice_id, text, response)
            for question_id, choice_id, text, response in attempt.answers.values_list('question_id', 'choice_id', 'text', 'response')
        }
        rows = []
        for question_id in attempt.layout.get('questions', []):
            question = questions.get(question_id)
            if question is None:
                continue
            by_id = {c.pk: c for c in question.choices.all()}
            choice_id, text, response = saved.get(question_id, (None, '', None))
            shown = choices.get(str(question_id), [])
            if question.kind == Question.Kind.ORDERING and response:
                shown = response  # el orden que ya le había dado el alumno
            rows.append({
                'question': question,
                'choices': [by_id[c] for c in shown if c in by_id],
                'selected': choice_id,
                'text': text,
                # En las de ordenar, vacío hasta que el alumno mueve algo: sin mover cuenta como sin responder.
                'order_value': ','.join(str(i) for i in response) if question.kind == Question.Kind.ORDERING and response else '',
            })
        return render(request, self.template_name, {
            'attempt': attempt, 'activity': quiz.activity, 'course': quiz.activity.course, 'rows': rows,
            'remaining': service.remaining_seconds(attempt),
        })

    def post(self, request, pk):
        attempt = self.load_attempt(request, pk)
        if attempt.is_finished:
            return redirect('quizzes:result', pk=attempt.pk)
        try:
            attempt = service.submit_attempt(attempt, parse_selections(request.POST))
        except ValidationError as error:
            messages.error(request, ' '.join(error.messages))
            return redirect('quizzes:take', pk=pk)
        if attempt.status == QuizAttempt.Status.EXPIRED:
            messages.error(request, 'Se acabó el tiempo: se guardó lo que alcanzaste a responder.')
        return redirect('quizzes:result', pk=attempt.pk)


class QuizAutosaveView(StudentQuizMixin, View):
    """Guardado periódico (lo llama el navegador). Responde JSON con los segundos que le quedan al intento."""

    def post(self, request, pk):
        attempt = self.load_attempt(request, pk)
        result_url = reverse('quizzes:result', args=[attempt.pk])
        if attempt.is_finished:
            return JsonResponse({'expired': True, 'url': result_url}, status=409)
        try:
            remaining = service.save_answers(attempt, parse_selections(request.POST))
        except service.AttemptExpired:
            return JsonResponse({'expired': True, 'url': result_url}, status=409)
        except ValidationError as error:
            return JsonResponse({'error': ' '.join(error.messages)}, status=400)
        return JsonResponse({'ok': True, 'remaining': remaining})


class QuizResultView(StudentQuizMixin, View):
    template_name = 'quiz_result.html'

    def get(self, request, pk):
        attempt = self.load_attempt(request, pk)
        if not attempt.is_finished:
            return redirect('quizzes:take', pk=attempt.pk)
        activity = attempt.quiz.activity
        review_available = results.can_review(attempt)
        pending = results.pending_count(attempt)
        return render(request, self.template_name, {
            'attempt': attempt, 'quiz': attempt.quiz, 'activity': activity, 'course': activity.course, 'pending': pending,
            'percent': round(float(attempt.score) * 100 / float(attempt.max_points)) if attempt.max_points else 0,
            'grade': Grade.objects.filter(activity=activity, student=attempt.student).first(),
            'review_available': review_available,
            'review': results.review_rows(attempt) if review_available else None,
        })
