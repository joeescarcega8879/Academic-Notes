"""Formulario de entrega del alumno."""

from django import forms
from django.core.validators import URLValidator

from .models import validate_submission_file


class SubmissionForm(forms.Form):
    text = forms.CharField(label='Respuesta', required=False, max_length=20000, widget=forms.Textarea(attrs={'rows': 6}))
    link = forms.CharField(
        label='Enlace', required=False, max_length=500, validators=[URLValidator(schemes=['http', 'https'])],
        help_text='Opcional: un enlace a tu trabajo (http o https).',
    )
    file = forms.FileField(
        label='Archivo', required=False, validators=[validate_submission_file],
        help_text='PDF, documento de Office, imagen, texto o ZIP. Máximo 10 MB.',
    )

    def __init__(self, *args, existing=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.existing = existing  # entrega previa del alumno, si la hay
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'input')

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        keeps_file = bool(self.existing and self.existing.file)
        if not (cleaned.get('text', '').strip() or cleaned.get('link') or cleaned.get('file') or keeps_file):
            raise forms.ValidationError('Escribe una respuesta, agrega un enlace o sube un archivo.')
        return cleaned
