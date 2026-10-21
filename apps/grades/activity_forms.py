"""Formulario de actividades."""

from django import forms

from .models import Activity

DATETIME_LOCAL = '%Y-%m-%dT%H:%M'


class ActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = [
            'title', 'type', 'criterion', 'syllabus_week', 'max_score', 'weight', 'instructions', 'date',
            'opens_at', 'due_at', 'allow_late', 'late_penalty', 'published',
        ]
        widgets = {
            'instructions': forms.Textarea(attrs={'rows': 4}),
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'opens_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
            'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
        }
        help_texts = {
            'weight': 'Peso relativo dentro de su criterio.',
            'date': 'Para actividades sin entrega: el día del examen, de la participación…',
            'published': 'Mientras sea un borrador, los alumnos no la ven y no cuenta para ninguna calificación.',
        }

    def __init__(self, *args, course, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        for name in ('opens_at', 'due_at'):
            self.fields[name].input_formats = [DATETIME_LOCAL, '%Y-%m-%dT%H:%M:%S']
        quiz = getattr(self.instance, 'quiz', None) if self.instance.pk else None
        if quiz is not None and self.instance.type == Activity.Type.QUIZ and quiz.questions.exists():
            # Cambiar el tipo de un quiz armado dejaría preguntas e intentos huérfanos.
            self.fields['type'].disabled = True
            self.fields['type'].help_text = 'Un quiz con preguntas no puede cambiar de tipo.'
        criterion = self.fields['criterion']
        criterion.queryset = course.scheme.criteria()
        criterion.required = False
        criterion.empty_label = 'Automático según el tipo'
        criterion.label_from_instance = lambda c: f'{c.name} · {c.period.name}'
        weeks = getattr(getattr(course, 'syllabus', None), 'weeks', None)
        if weeks is None or not weeks.exists():
            del self.fields['syllabus_week']  # sin temario o sin semanas no hay nada que elegir
        else:
            week = self.fields['syllabus_week']
            week.queryset = weeks.all()
            week.empty_label = 'Ninguna'
            week.label_from_instance = lambda w: f'Semana {w.position}' + (f' · {w.title}' if w.title else '')
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                continue
            field.widget.attrs.setdefault('class', 'select' if isinstance(field.widget, forms.Select) else 'input')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('late_penalty') and not cleaned.get('allow_late'):
            cleaned['late_penalty'] = 0  # sin entregas tardías no hay nada que penalizar
        return cleaned

    def save(self, commit=True):
        activity = super().save(commit=False)
        activity.course = self.course
        if commit:
            activity.save()
        return activity
