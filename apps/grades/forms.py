from django import forms
from django.contrib.auth import get_user_model
from apps.subjects.models import Enrollment, Subject

from .models import Grade, Evaluation

User = get_user_model()

class GradeForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ['evaluation', 'student', 'score', 'feedback']
        widgets = {
            'feedback': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Comentario del profesor (opcional)'}),
        }

    def __init__(self, *args, **kwargs):
        # Ambos son obligatorios: el formulario solo ofrece datos de las materias del docente
        # en su organización activa (sin organización, no ofrece nada).
        self.user = kwargs.pop('user')
        self.organization = kwargs.pop('organization')
        super().__init__(*args, **kwargs)

        # Aplicar los estilos del front-end a cada widget (igual que ProfileForm)
        for field in self.fields.values():
            css = 'select' if isinstance(field.widget, forms.Select) else 'input'
            field.widget.attrs.setdefault('class', css)

        # Etiquetas legibles en los selects
        self.fields['student'].label_from_instance = lambda u: u.get_full_name() or u.email
        self.fields['evaluation'].label_from_instance = lambda e: e.title

        subjects = Subject.objects.for_organization(self.organization).filter(professor=self.user)
        # Solo las evaluaciones de las materias del profesor
        self.fields['evaluation'].queryset = (
            Evaluation.objects.for_organization(self.organization).filter(subject__in=subjects).select_related('subject')
        )
        # Solo alumnos inscritos en alguna materia del profesor
        self.fields['student'].queryset = User.objects.filter(enrollments__subject__in=subjects).distinct()

    def clean(self):
        cleaned = super().clean()
        evaluation = cleaned.get('evaluation')
        student = cleaned.get('student')
        score = cleaned.get('score')

        if evaluation and student:
            if not Enrollment.objects.for_organization(self.organization).filter(
                student=student, subject=evaluation.subject,
            ).exists():
                raise forms.ValidationError('El alumno no está inscrito en la materia de esta evaluación.')
        if evaluation and score is not None and score > evaluation.max_score:
            raise forms.ValidationError(f'La calificación no puede superar el máximo de {evaluation.max_score}.')
        return cleaned