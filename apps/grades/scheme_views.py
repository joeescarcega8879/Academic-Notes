"""Editor del esquema de evaluación de un grupo."""

from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.accounts.mixins import TeacherRequiredMixin
from apps.courses.models import Course

from .models import EvaluationPeriod
from .scheme_forms import (
    SchemeSettingsForm, assignment_formset, criterion_formset, period_formset,
)
from .services.schemes import ensure_scheme

PROTECTED_MESSAGE = (
    'No se puede borrar: todavía tiene actividades asignadas. Reasígnalas a otro criterio en '
    '"Actividades del grupo" y vuelve a intentarlo.'
)


class SchemeView(TeacherRequiredMixin, View):
    """Cada sección (ajustes, periodos, criterios, evaluaciones) se guarda por separado."""

    template_name = 'scheme.html'

    def get_course(self, pk):
        # Un grupo archivado es de solo lectura: no se edita su esquema.
        return get_object_or_404(
            Course.objects.for_organization(self.request.organization).filter(
                professor=self.request.user, status=Course.Status.ACTIVE,
            ),
            pk=pk,
        )

    def get(self, request, pk):
        course = self.get_course(pk)
        return self.render_page(request, course, ensure_scheme(course))

    def post(self, request, pk):
        course = self.get_course(pk)
        scheme = ensure_scheme(course)
        action = request.POST.get('action')
        bound = {}

        if action == 'settings':
            form = SchemeSettingsForm(request.POST, instance=scheme)
            if form.is_valid():
                form.save()
                return self.saved(request, course, 'Se guardaron los ajustes del esquema.')
            bound['settings_form'] = form
        elif action == 'periods':
            formset = period_formset(scheme=scheme, data=request.POST)
            if formset.is_valid():
                return self.save_formset(request, course, formset, 'Se guardaron los periodos.', scheme=scheme)
            bound['period_formset'] = formset
        elif action == 'criteria':
            formset = criterion_formset(scheme=scheme, data=request.POST)
            if formset.is_valid():
                return self.save_formset(request, course, formset, 'Se guardaron los criterios.')
            bound['criterion_formset'] = formset
        elif action == 'evals':
            formset = assignment_formset(scheme=scheme, data=request.POST)
            if formset.is_valid():
                return self.save_formset(request, course, formset, 'Se reasignaron las actividades.')
            bound['assignment_formset'] = formset
        else:
            messages.error(request, 'Acción desconocida.')
            return redirect('grades:scheme', pk=course.pk)

        return self.render_page(request, course, scheme, **bound)

    def saved(self, request, course, message):
        messages.success(request, message)
        return redirect('grades:scheme', pk=course.pk)

    def save_formset(self, request, course, formset, message, **parent):
        """Guarda altas, cambios y bajas; una baja con actividades asignadas se rechaza con un aviso."""
        try:
            with transaction.atomic():
                instances = formset.save(commit=False)
                for obj in formset.deleted_objects:
                    obj.delete()
                for obj in instances:
                    for name, value in parent.items():
                        setattr(obj, name, value)
                    if obj.pk is None and hasattr(obj, 'position'):
                        siblings = obj.scheme.periods if isinstance(obj, EvaluationPeriod) else obj.period.criteria
                        obj.position = siblings.count()
                    obj.save()
        except ProtectedError:
            messages.error(request, PROTECTED_MESSAGE)
            return redirect('grades:scheme', pk=course.pk)
        return self.saved(request, course, message)

    def render_page(self, request, course, scheme, **bound):
        periods = list(scheme.periods.prefetch_related('criteria'))
        return render(request, self.template_name, {
            'course': course,
            'scheme': scheme,
            'settings_form': bound.get('settings_form') or SchemeSettingsForm(instance=scheme),
            'period_formset': bound.get('period_formset') or period_formset(scheme=scheme),
            'criterion_formset': bound.get('criterion_formset') or criterion_formset(scheme=scheme),
            'assignment_formset': bound.get('assignment_formset') or assignment_formset(scheme=scheme),
            # Los pesos son relativos, pero lo habitual es que sumen 100: se avisa si no.
            'periods_total': sum((p.weight for p in periods), Decimal(0)),
            'period_totals': [(p, sum((c.weight for c in p.criteria.all()), Decimal(0))) for p in periods],
        })
