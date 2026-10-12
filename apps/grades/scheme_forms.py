"""Formularios del editor del esquema de evaluación."""

from django import forms
from django.core.exceptions import ValidationError

from .models import Evaluation, EvaluationCriterion, EvaluationPeriod, EvaluationScheme


def _style(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            continue
        css = 'select' if isinstance(field.widget, forms.Select) else 'input'
        field.widget.attrs.setdefault('class', css)


class SchemeSettingsForm(forms.ModelForm):
    class Meta:
        model = EvaluationScheme
        fields = ['scale_max', 'pass_mark', 'rounding_decimals']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class PeriodForm(forms.ModelForm):
    class Meta:
        model = EvaluationPeriod
        fields = ['name', 'weight']

    def __init__(self, *args, scheme, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)


class CriterionForm(forms.ModelForm):
    default_type = forms.ChoiceField(
        label='Evaluaciones nuevas de tipo', required=False,
        choices=[('', '— ninguno —')] + list(Evaluation.Type.choices),
    )

    class Meta:
        model = EvaluationCriterion
        fields = ['period', 'name', 'weight', 'default_type']

    def __init__(self, *args, scheme, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['period'].queryset = scheme.periods.all()
        self.fields['period'].empty_label = None
        _style(self)


class EvaluationAssignForm(forms.ModelForm):
    """Cambia solo el criterio de una evaluación."""

    class Meta:
        model = Evaluation
        fields = ['criterion']

    def __init__(self, *args, scheme, **kwargs):
        super().__init__(*args, **kwargs)
        field = self.fields['criterion']
        field.queryset = scheme.criteria()
        field.empty_label = None
        field.label_from_instance = lambda c: f'{c.name} · {c.period.name}'
        _style(self)


class AtLeastOneFormSet(forms.BaseModelFormSet):
    """Formset que no permite quedarse sin filas (sin contar las marcadas para borrar)."""

    minimum_message = 'Debe quedar al menos una fila.'

    def clean(self):
        super().clean()
        if any(self.errors):
            return
        remaining = [f for f in self.forms if f.cleaned_data and not f.cleaned_data.get('DELETE')]
        if not remaining:
            raise ValidationError(self.minimum_message)


class PeriodFormSet(AtLeastOneFormSet):
    minimum_message = 'El esquema necesita al menos un periodo.'


class CriterionFormSet(AtLeastOneFormSet):
    minimum_message = 'El esquema necesita al menos un criterio.'


def period_formset(*, scheme, data=None):
    factory = forms.modelformset_factory(
        EvaluationPeriod, form=PeriodForm, formset=PeriodFormSet, extra=1, can_delete=True,
    )
    return factory(data, queryset=scheme.periods.all(), prefix='periods', form_kwargs={'scheme': scheme})


def criterion_formset(*, scheme, data=None):
    factory = forms.modelformset_factory(
        EvaluationCriterion, form=CriterionForm, formset=CriterionFormSet, extra=1, can_delete=True,
    )
    return factory(data, queryset=scheme.criteria(), prefix='criteria', form_kwargs={'scheme': scheme})


def assignment_formset(*, scheme, data=None):
    factory = forms.modelformset_factory(Evaluation, form=EvaluationAssignForm, extra=0)
    queryset = scheme.course.evaluations.select_related('criterion__period').order_by('title', 'id')
    return factory(data, queryset=queryset, prefix='evals', form_kwargs={'scheme': scheme})
