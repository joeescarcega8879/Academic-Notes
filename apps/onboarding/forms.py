from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.organizations.models import Organization


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


class WaitlistForm(forms.Form):
    """«Avísame cuando el plan de pago esté disponible». ``website`` es la trampa para robots, como en el registro."""

    email = forms.EmailField(
        label='Tu correo', max_length=254,
        widget=forms.EmailInput(attrs={'class': 'input', 'autocomplete': 'email', 'placeholder': 'tucorreo@ejemplo.com'}),
    )
    accept = forms.BooleanField(
        label='Acepto que guarden mi correo para avisarme (aviso de privacidad)',
        error_messages={'required': 'Marca la casilla para que podamos guardar tu correo y avisarte.'},
    )
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))
    # Plan por el que se apunta; sin valor es Pro (la lista de espera de siempre).
    plan = forms.ChoiceField(
        required=False, widget=forms.HiddenInput,
        choices=[(Organization.Plan.TEACHER, 'Pro'), (Organization.Plan.TEACHER_PLUS, 'Plus')],
    )

    def clean_email(self):
        return self.cleaned_data['email'].strip().lower()

    def clean_plan(self):
        return self.cleaned_data['plan'] or Organization.Plan.TEACHER

    @property
    def is_bot(self):
        return bool(self.cleaned_data.get('website'))


class TeacherRegisterForm(RegisterForm):
    school_name = forms.CharField(
        label='Escuela o institución (opcional)', max_length=150, required=False, widget=_input(autocomplete='organization'),
        help_text='Aparece en el encabezado de tus boletas. Si la dejas vacía, se usa tu nombre.',
    )
    field_order = ['first_name', 'last_name', 'email', 'school_name', 'password1', 'password2', 'accept_terms', 'website']
