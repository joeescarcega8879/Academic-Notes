from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


def _input(**attrs):
    return forms.TextInput(attrs={'class': 'input', **attrs})


class RegisterForm(forms.Form):
    """Alta de cuenta. ``website`` es una trampa para robots: una persona no lo ve ni lo llena."""

    first_name = forms.CharField(label='Nombre(s)', max_length=150, widget=_input(autocomplete='given-name', autofocus=True))
    last_name = forms.CharField(label='Apellidos', max_length=150, widget=_input(autocomplete='family-name'))
    email = forms.EmailField(
        label='Correo', max_length=254,
        widget=forms.EmailInput(attrs={'class': 'input', 'autocomplete': 'email'}),
    )
    password1 = forms.CharField(
        label='Contraseña', strip=False,
        widget=forms.PasswordInput(attrs={'class': 'input', 'autocomplete': 'new-password'}),
    )
    password2 = forms.CharField(
        label='Repite la contraseña', strip=False,
        widget=forms.PasswordInput(attrs={'class': 'input', 'autocomplete': 'new-password'}),
    )
    accept_terms = forms.BooleanField(
        label='Acepto los términos de uso y el aviso de privacidad',
        error_messages={'required': 'Para crear tu cuenta tienes que aceptar los términos y el aviso de privacidad.'},
    )
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise ValidationError('Ya existe una cuenta con este correo. Inicia sesión o restablece tu contraseña.')
        return email

    def clean(self):
        cleaned = super().clean()
        first, second = cleaned.get('password1'), cleaned.get('password2')
        if first and second and first != second:
            self.add_error('password2', 'Las contraseñas no coinciden.')
        elif first:
            candidate = get_user_model()(
                first_name=cleaned.get('first_name', ''), last_name=cleaned.get('last_name', ''), email=cleaned.get('email', ''),
            )
            try:
                validate_password(first, candidate)
            except ValidationError as error:
                self.add_error('password1', error)
        return cleaned

    @property
    def is_bot(self):
        return bool(self.cleaned_data.get('website'))


class TeacherRegisterForm(RegisterForm):
    school_name = forms.CharField(
        label='Escuela o institución (opcional)', max_length=150, required=False, widget=_input(autocomplete='organization'),
        help_text='Aparece en el encabezado de tus boletas. Si la dejas vacía, se usa tu nombre.',
    )
    field_order = ['first_name', 'last_name', 'email', 'school_name', 'password1', 'password2', 'accept_terms', 'website']
