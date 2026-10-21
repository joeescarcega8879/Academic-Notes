"""Formularios de la pantalla del temario."""

from django import forms

from .models import SyllabusWeek, validate_syllabus_file
from .services.extraction import MAX_PASTED_CHARS


class UploadForm(forms.Form):
    file = forms.FileField(label='Archivo', validators=[validate_syllabus_file], widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx,.txt'}))


class PasteForm(forms.Form):
    text = forms.CharField(
        label='Texto del temario', max_length=MAX_PASTED_CHARS, strip=False,
        widget=forms.Textarea(attrs={'class': 'input', 'rows': 4, 'placeholder': 'Semana 1: Números reales…'}),
    )

    def clean_text(self):
        text = self.cleaned_data['text'].strip()
        if not text:
            raise forms.ValidationError('Escribe o pega el texto del temario.')
        return text


class StartDateForm(forms.Form):
    start_date = forms.DateField(label='Inicio de clases', widget=forms.DateInput(attrs={'type': 'date', 'class': 'input'}, format='%Y-%m-%d'))


class WeekForm(forms.ModelForm):
    class Meta:
        model = SyllabusWeek
        fields = ['title', 'topics', 'objectives', 'no_class']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'input', 'placeholder': 'Título de la semana'}),
            'topics': forms.Textarea(attrs={'class': 'input', 'rows': 5}),
            'objectives': forms.Textarea(attrs={'class': 'input', 'rows': 5}),
        }
        labels = {'title': 'Título', 'topics': 'Temas', 'objectives': 'Objetivos'}
