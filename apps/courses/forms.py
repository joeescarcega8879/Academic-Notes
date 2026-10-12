from django import forms

from .models import AcademicYear, Course


def _style(form):
    """Estilos del front-end en cada widget (igual que el resto de formularios del proyecto)."""
    for field in form.fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            continue
        css = 'select' if isinstance(field.widget, forms.Select) else 'input'
        field.widget.attrs.setdefault('class', css)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['name', 'code', 'academic_year', 'schedule', 'color', 'description']
        labels = {'name': 'Nombre', 'code': 'Código', 'schedule': 'Horario', 'color': 'Color', 'description': 'Descripción'}
        widgets = {
            'color': forms.TextInput(attrs={'type': 'color', 'style': 'height: 38px; padding: 2px'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, organization, professor, **kwargs):
        self.organization = organization
        self.professor = professor
        super().__init__(*args, **kwargs)
        _style(self)
        years = AcademicYear.objects.for_organization(organization)
        self.fields['academic_year'].queryset = years
        self.fields['academic_year'].empty_label = None
        if not self.instance.pk:
            self.fields['academic_year'].initial = years.filter(is_current=True).first()

    def clean(self):
        cleaned = super().clean()
        year, code = cleaned.get('academic_year'), (cleaned.get('code') or '').strip()
        if year and code:
            repeated = Course.objects.for_organization(self.organization).filter(academic_year=year, code=code)
            if repeated.exclude(pk=self.instance.pk).exists():
                self.add_error('code', f'Ya existe un grupo con este código en el ciclo {year}.')
        return cleaned

    def save(self, commit=True):
        course = super().save(commit=False)
        if not course.pk:
            course.professor = self.professor
            course.organization = self.organization
        if commit:
            course.save()
        return course


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ['name', 'start_date', 'end_date', 'is_current']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, organization, **kwargs):
        self.organization = organization
        super().__init__(*args, **kwargs)
        _style(self)

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if AcademicYear.objects.for_organization(self.organization).filter(name=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ya existe un ciclo con este nombre.')
        return name

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get('start_date'), cleaned.get('end_date')
        if start and end and end < start:
            self.add_error('end_date', 'El ciclo no puede terminar antes de empezar.')
        return cleaned

    def save(self, commit=True):
        year = super().save(commit=False)
        year.organization = self.organization
        if commit:
            year.save()
        return year


class CloneCourseForm(forms.Form):
    """Datos del grupo duplicado: el ciclo destino y, si hace falta, otro nombre o código."""

    academic_year = forms.ModelChoiceField(queryset=AcademicYear.objects.none(), label='Ciclo destino', empty_label=None)
    name = forms.CharField(label='Nombre', max_length=100)
    code = forms.CharField(label='Código', max_length=20)

    def __init__(self, *args, course, **kwargs):
        super().__init__(*args, **kwargs)
        years = AcademicYear.objects.for_organization(course.organization).exclude(pk=course.academic_year_id)
        self.fields['academic_year'].queryset = years
        self.fields['name'].initial = course.name
        self.fields['code'].initial = course.code
        _style(self)
