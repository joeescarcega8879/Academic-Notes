"""«Revisar con IA»: la bandeja de calificaciones sugeridas de una actividad. Solo para el docente del grupo."""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.courses.services.text import student_sort_key
from apps.grades.activity_views import OwnActiveCourseMixin
from apps.grades.models import Activity
from apps.organizations import limits

from . import reviews, services, ui
from .models import AIReview


class ReviewMixin(OwnActiveCourseMixin):
    def get_activity(self, pk):
        activity = get_object_or_404(self.activities(), pk=pk)
        if not activity.accepts_submissions:
            raise Http404
        return activity

    def get_review(self, pk):
        return get_object_or_404(
            AIReview.objects.for_organization(self.request.organization).filter(
                submission__activity__in=self.activities().filter(type__in=Activity.SUBMISSION_TYPES),
            ).select_related('submission__student', 'submission__activity__course'),
            pk=pk,
        )

    def back(self, activity):
        return redirect('ai:review', activity.pk)

    def fail(self, request, error):
        if isinstance(error, limits.PlanLimitError):
            limits.flash_limit_error(request, error)
        else:
            messages.error(request, ' '.join(error.messages))


class ReviewView(ReviewMixin, View):
    """La bandeja: pedir sugerencias y ver, corregir, confirmar o descartar cada una."""

    def get(self, request, pk):
        activity = self.get_activity(pk)
        reviews.expire_stale(activity)
        ready, skipped = reviews.overview(activity)
        rows = sorted(reviews.reviews_of(activity), key=lambda review: student_sort_key(review.submission.student))
        counts = {status: sum(1 for r in rows if r.status == status) for status in AIReview.Status.values}
        candidates = reviews.bulk_candidates(activity)
        confirming = bool(candidates) and request.GET.get('confirmar') == '1'
        return render(request, 'ai_review.html', {
            'activity': activity, 'course': activity.course, 'rows': rows, 'counts': counts, 'ready_count': len(ready),
            'skipped': sorted(skipped.items()), 'bulk_count': len(candidates), 'confirming': confirming,
            'summary': reviews.bulk_summary(candidates, activity.max_score) if confirming else None,
            'reason': ui.unavailable_reason(request.organization), 'usage': services.usage_summary(request.organization),
            'asking': min(len(ready), reviews.MAX_PER_REQUEST), 'busy': counts[AIReview.Status.QUEUED] > 0,
        })

    def post(self, request, pk):
        activity = self.get_activity(pk)
        try:
            created, left_out = reviews.request_reviews(activity, request.user)
        except ValidationError as error:
            self.fail(request, error)
            return self.back(activity)
        total = len(created)
        text = 'Se pidió la sugerencia de 1 trabajo.' if total == 1 else f'Se pidieron las sugerencias de {total} trabajos.'
        if left_out:
            text += f' Quedan {left_out} para pedir después (por el tope por solicitud o por tus usos del mes).'
        messages.success(request, text)
        return self.back(activity)


class ReviewStatusView(ReviewMixin, View):
    """Para la bandeja: ¿siguen revisándose trabajos? Cuando ya no, se recarga sola."""

    def get(self, request, pk):
        activity = self.get_activity(pk)
        reviews.expire_stale(activity)
        return JsonResponse({'busy': AIReview.objects.filter(submission__activity=activity, status=AIReview.Status.QUEUED).exists()})


class ReviewActionView(ReviewMixin, View):
    """Confirmar (con lo que el docente corrigió), descartar o volver a pedir UNA sugerencia."""

    action = None

    def post(self, request, pk):
        review = self.get_review(pk)
        activity = review.submission.activity
        student = review.submission.student
        try:
            if self.action == 'confirm':
                score = reviews.parse_score(request.POST.get('score', ''))
                reviews.confirm(review, user=request.user, score=score, feedback=request.POST.get('feedback', ''))
                messages.success(request, f'Se guardó la calificación de {student}.')
            elif self.action == 'discard':
                reviews.discard(review)
                messages.success(request, f'Se descartó la sugerencia para {student}. Califícala a mano cuando quieras.')
            elif self.action == 'retry':
                reviews.retry(review, user=request.user)
                messages.success(request, f'Se volvió a pedir la sugerencia para {student}.')
        except ValidationError as error:
            self.fail(request, error)
        return self.back(activity)


class ReviewBulkView(ReviewMixin, View):
    """Confirma sin cambios las sugerencias con evidencia en todos los puntos (el resumen se vio antes)."""

    def post(self, request, pk):
        activity = self.get_activity(pk)
        saved, skipped = reviews.confirm_bulk(activity, request.user)
        if saved:
            messages.success(request, 'Se confirmó 1 calificación.' if saved == 1 else f'Se confirmaron {saved} calificaciones.')
        elif not skipped:
            messages.error(request, 'No había sugerencias para confirmar sin cambios.')
        for name, reason in skipped:
            messages.error(request, f'{name}: {reason}')
        return self.back(activity)
