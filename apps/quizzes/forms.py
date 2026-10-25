from django import forms

from apps.courses.models import Course

from .models import Question, QuizConfig
from .services.bank import MAX_CHOICES, teaching_courses, validate_choices


def _style(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            continue
        css = 'select' if isinstance(field.widget, forms.Select) else 'input'
        field.widget.attrs.setdefault('class', css)


class QuestionForm(forms.ModelForm):
    class Meta:
        model = Question
        fields = ['course', 'text', 'points', 'topic', 'explanation']
        widgets = {
            'text': forms.Textarea(attrs={'rows': 3}),
            'explanation': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, user=None, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
        # Solo se ofrecen los grupos activos del docente; al editar se conserva el actual aunque ya esté archivado.
        groups = Course.objects.none()
        if user is not None and organization is not None:
            groups = teaching_courses(user, organization)
        if self.instance.course_id:
            groups = groups | Course.objects.filter(pk=self.instance.course_id)
        field = self.fields['course']
        field.queryset = groups
        field.empty_label = 'Sin grupo (general: sirve en todos mis grupos)'
        field.label = 'Grupo'


class TrueFalseForm(QuestionForm):
    correct = forms.ChoiceField(
        label='Respuesta correcta', choices=[('true', 'Verdadero'), ('false', 'Falso')], widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['correct'].widget.attrs.pop('class', None)


class ChoiceForm(forms.Form):
    text = forms.CharField(label='Opción', required=False, max_length=500)
    is_correct = forms.BooleanField(label='Correcta', required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['text'].widget.attrs['class'] = 'input'


class BaseChoiceFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        rows = [(f.cleaned_data.get('text', ''), f.cleaned_data.get('is_correct', False)) for f in self.forms]
        self.cleaned_choices = validate_choices(rows)  # lanza ValidationError con el mensaje para el docente


ChoiceFormSet = forms.formset_factory(ChoiceForm, formset=BaseChoiceFormSet, extra=0, max_num=MAX_CHOICES, validate_max=True)


def choice_formset(data=None, *, question=None):
    """Formset de opciones: con las de ``question`` al editar, o cuatro filas vacías al crear."""
    if data is None and question is not None:
        initial = [{'text': c.text, 'is_correct': c.is_correct} for c in question.choices.all()]
        initial += [{}] * max(0, 4 - len(initial))
        return ChoiceFormSet(initial=initial, prefix='choices')
    if data is None:
        return ChoiceFormSet(initial=[{}] * 4, prefix='choices')
    return ChoiceFormSet(data, prefix='choices')


class QuizConfigForm(forms.ModelForm):
    class Meta:
        model = QuizConfig
        fields = [
            'attempts_allowed', 'time_limit_minutes', 'shuffle_questions', 'shuffle_choices', 'feedback_mode', 'attempt_policy',
        ]

    def __init__(self, *args, allow_time_limit=True, **kwargs):
        super().__init__(*args, **kwargs)
        _style(self)
        noun = self.instance.activity.get_type_display().lower() if self.instance.activity_id else 'quiz'
        # Las opciones nombran lo que se está armando: no se tocan en el modelo para no cambiar su migración.
        self.fields['feedback_mode'].choices = [(value, label.replace('el quiz', f'el {noun}')) for value, label in QuizConfig.Feedback.choices]
        if not allow_time_limit:
            # Deshabilitado: lo que llegue en la petición se ignora y se conserva el valor actual (si lo hay).
            field = self.fields['time_limit_minutes']
            field.disabled = True
            field.help_text = 'Los quizzes y exámenes con tiempo límite son del plan Pro.'


class BankFilterForm(forms.Form):
    q = forms.CharField(label='Buscar', required=False)
    topic = forms.CharField(label='Tema', required=False)
    kind = forms.ChoiceField(label='Tipo', required=False, choices=[('', 'Todos')] + list(Question.Kind.choices))
    grupo = forms.ChoiceField(label='Grupo', required=False, choices=[('', 'Todos los grupos'), ('sin', 'Sin grupo (generales)')])
    archived = forms.BooleanField(label='Ver archivadas', required=False)

    def __init__(self, *args, groups=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['grupo'].choices = (
            [('', 'Todos los grupos')]
            + [(str(course.pk), f'{course.name} (archivado)' if course.is_archived else course.name) for course in groups]
            + [('sin', 'Sin grupo (generales)')]
        )
        for name, field in self.fields.items():
            if name != 'archived':
                field.widget.attrs['class'] = 'select' if isinstance(field.widget, forms.Select) else 'input'
