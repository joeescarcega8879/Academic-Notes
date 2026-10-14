from django import forms
from apps.courses.models import Course, Enrollment, Student

from .models import Grade, Activity

class GradeForm(forms.ModelForm):
    class Meta:
        model = Grade
        fields = ['activity', 'student', 'score', 'feedback']
        widgets = {
            'feedback': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Comentario del profesor (opcional)'}),
        }

    def __init__(self, *args, **kwargs):
        # Ambos son obligatorios: el formulario solo ofrece datos de los grupos del docente
        # en su organización activa (sin organización, no ofrece nada).
        self.user = kwargs.pop('user')
        self.organization = kwargs.pop('organization')
        super().__init__(*args, **kwargs)

        # Aplicar los estilos del front-end a cada widget (igual que ProfileForm)
        for field in self.fields.values():
            css = 'select' if isinstance(field.widget, forms.Select) else 'input'
            field.widget.attrs.setdefault('class', css)

        # Etiquetas legibles en los selects
        self.fields['student'].label_from_instance = str
        if self.instance.pk:
            # Editar una calificación no la mueve a otro alumno ni a otra actividad.
            self.fields['activity'].disabled = True
            self.fields['student'].disabled = True
        self.fields['activity'].label_from_instance = lambda e: e.title

        courses = Course.objects.for_organization(self.organization).filter(
            professor=self.user, status=Course.Status.ACTIVE,  # un grupo archivado es de solo lectura
        )
        # Solo las evaluaciones de los grupos del profesor
        self.fields['activity'].queryset = (
            Activity.objects.for_organization(self.organization).filter(course__in=courses).select_related('course')
        )
        # Solo alumnos inscritos en algún grupo del profesor
        self.fields['student'].queryset = (
            Student.objects.for_organization(self.organization).filter(enrollments__course__in=courses).distinct()
        )

    def clean(self):
        cleaned = super().clean()
        activity = cleaned.get('activity')
        student = cleaned.get('student')
        score = cleaned.get('score')

        if activity and student:
            if not Enrollment.objects.for_organization(self.organization).filter(
                student=student, course=activity.course,
            ).exists():
                raise forms.ValidationError('El alumno no está inscrito en el grupo de esta evaluación.')
        if activity and score is not None and score > activity.max_score:
            raise forms.ValidationError(f'La calificación no puede superar el máximo de {activity.max_score}.')
        return cleaned