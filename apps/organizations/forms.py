from django import forms

from .models import Organization


class OrganizationNameForm(forms.ModelForm):
    """Nombre de la organización (en el caso individual, el de la escuela del docente)."""

    class Meta:
        model = Organization
        fields = ['name']
        labels = {'name': 'Nombre de tu escuela o institución'}
        widgets = {'name': forms.TextInput(attrs={'class': 'input', 'maxlength': 150})}

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())  # sin espacios de más ni saltos de línea
        if not name:
            raise forms.ValidationError('Escribe un nombre.')
        return name
