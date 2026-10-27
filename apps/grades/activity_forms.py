"""Formulario de actividades."""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.rubrics.models import Rubric
from apps.rubrics.services.library import resolve_version

from .models import Activity

DATETIME_LOCAL = '%Y-%m-%dT%H:%M'


class ActivityForm(forms.ModelForm):
    # La rúbrica elegida de la biblioteca; al guardar, la actividad queda con una versión concreta de ella.
    rubric = forms.ModelChoiceField(
        queryset=Rubric.objects.none(), required=False, label='Rúbrica', empty_label='Sin rúbrica (calificar con un número)',
    )
    field_order = [
        'title', 'type', 'criterion', 'syllabus_week', 'max_score', 'rubric', 'weight', 'instructions', 'date',
        'opens_at', 'due_at', 'allow_late', 'late_penalty', 'by_teams', 'published',
    ]

    class Meta:
        model = Activity
        fields = [
            'title', 'type', 'criterion', 'syllabus_week', 'max_score', 'weight', 'instructions', 'date',
            'opens_at', 'due_at', 'allow_late', 'late_penalty', 'by_teams', 'published',
        ]
        widgets = {
            'instructions': forms.Textarea(attrs={'rows': 4}),
            'date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'opens_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
            'due_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format=DATETIME_LOCAL),
        }
        help_texts = {
            'weight': 'Peso relativo dentro de su criterio.',
            'by_teams': 'Solo proyectos. Una entrega y una calificación por equipo; los equipos se arman al guardar, en «Equipos».',
            'date': 'Para actividades sin entrega: el día del examen, de la participación…',
            'published': 'Mientras sea un borrador, los alumnos no la ven y no cuenta para ninguna calificación.',
        }

    def _setup_rubric(self, course):
        field = self.fields['rubric']
        in_use = self.instance.rubric_version.rubric_id if self.instance.pk and self.instance.rubric_version_id else None
        field.queryset = Rubric.objects.for_organization(course.organization).filter(
            Q(author=course.professor, is_archived=False) | Q(pk=in_use),
        ).prefetch_related('versions')
        field.help_text = 'Se califica eligiendo un nivel por criterio, y el alumno la ve antes de entregar.'
        # Cuánto vale cada rúbrica: la versión que esta actividad ya usa, o la vigente. Lo lee el aviso de puntos.
        self.rubric_points = {}
        for rubric in field.queryset:
            version = self.instance.rubric_version if rubric.pk == in_use else rubric.current_version
            self.rubric_points[rubric.pk] = float(version.max_points)
        field.label_from_instance = lambda r: f'{r.name} · {self.rubric_points[r.pk]:g} pts'
        if in_use:
            self.initial['rubric'] = in_use

    def __init__(self, *args, course, **kwargs):
        self.course = course
        super().__init__(*args, **kwargs)
        self._setup_rubric(course)
        for name in ('opens_at', 'due_at'):
            self.fields[name].input_formats = [DATETIME_LOCAL, '%Y-%m-%dT%H:%M:%S']
        quiz = getattr(self.instance, 'quiz', None) if self.instance.pk else None
        if quiz is not None and quiz.questions.exists():
            # Cambiar el tipo de un quiz (o de un examen en línea) armado dejaría preguntas e intentos huérfanos.
            self.fields['type'].disabled = True
            self.fields['type'].help_text = f'Un {self.instance.get_type_display().lower()} con preguntas no puede cambiar de tipo.'
        if self.instance.pk and (
            self.instance.submissions.exists() or self.instance.grades.exists() or self.instance.teams.exists()
        ):
            # Cambiarlo con trabajo ya hecho dejaría entregas y notas sin dueño.
            self.fields['by_teams'].disabled = True
            self.fields['by_teams'].help_text = (
                'Ya no se puede cambiar: el proyecto tiene entregas, calificaciones o equipos.' if not self.instance.by_teams
                else 'Ya no se puede cambiar: el proyecto tiene entregas, calificaciones o equipos armados.'
            )
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
        self._clean_rubric(cleaned)
        return cleaned

    def _clean_rubric(self, cleaned):
        rubric, kind = cleaned.get('rubric'), cleaned.get('type')
        self.rubric_version = None
        if rubric is not None and (kind == Activity.Type.QUIZ or getattr(self.instance, 'quiz', None) is not None):
            self.add_error('rubric', 'Un quiz o un examen en línea se califica solo: no lleva rúbrica.')
            return
        if rubric is None and kind == Activity.Type.PROJECT:
            self.add_error('rubric', 'Un proyecto se califica con rúbrica. Crea una en «Rúbricas» y elígela aquí.')
            return
        try:
            self.rubric_version = resolve_version(self.instance, rubric)
        except ValidationError as error:
            self.add_error('rubric', error)

    def save(self, commit=True):
        activity = super().save(commit=False)
        activity.course = self.course
        activity.rubric_version = self.rubric_version
        if commit:
            activity.save()
        return activity
