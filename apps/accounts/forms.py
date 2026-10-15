from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
from django.core.files.uploadedfile import UploadedFile

from .avatars import process_avatar
from .models import User, StudentProfile, ProfessorProfile

class LoginForm(AuthenticationForm):
    username = forms.CharField(
        label='Email or Username',
        widget=forms.TextInput(attrs={
          'class':'input with-icon',
          'placeholder':'Email or Username',
          'id':'li-user'
        })
    )
    
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'input with-icon',
            'placeholder': '••••••••',
            'id': 'li-pass',
        })
    )
    
class ProfileForm(forms.ModelForm):
    # La foto no se guarda como llega: ``process_avatar`` la valida y la deja cuadrada y ligera.
    avatar = forms.FileField(
        required=False, label='Foto de perfil',
        widget=forms.FileInput(attrs={'accept': 'image/jpeg,image/png,image/webp', 'class': 'sr-only'}),
    )
    remove_avatar = forms.BooleanField(required=False, label='Quitar mi foto')

    class Meta:
        model = User
        fields = [
            'first_name', 'last_name', 'email', 'phone',      
            'birth_date', 'avatar',
            'notify_grades', 'notify_weekly', 'notify_sms', 'show_average',
            ]
        widgets = {
            'birth_date': forms.DateInput(attrs={'type': 'date', 'class': 'input'}),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'input')
        self._old_avatar = self.instance.avatar.name if self.instance.pk else ''

    def clean_avatar(self):
        foto = self.cleaned_data.get('avatar')
        if isinstance(foto, UploadedFile):
            return process_avatar(foto)
        return foto

    def save(self, commit=True):
        subio_foto = isinstance(self.files.get('avatar'), UploadedFile) and self.cleaned_data.get('avatar')
        if self.cleaned_data.get('remove_avatar') and not subio_foto:
            self.instance.avatar = ''
        user = super().save(commit)
        if commit and self._old_avatar and user.avatar.name != self._old_avatar:
            # La foto anterior ya no se usa: no se deja archivo huérfano de una persona.
            user.avatar.storage.delete(self._old_avatar)
        return user

class StudentProfileForm(forms.ModelForm):
    """Datos académicos. Quien se registró con solo nombre y correo aún no tiene perfil: se puede dejar vacío."""

    class Meta:
        model = StudentProfile
        fields = ['program', 'semester']
        labels = {'program': 'Programa', 'semester': 'Semestre'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.required = False
            f.widget.attrs.setdefault('class', 'input')

    def clean(self):
        cleaned = super().clean()
        # Un perfil existente o uno que se empieza a llenar necesita las dos cosas; uno vacío simplemente no se crea.
        if self.instance.pk or self.has_changed():
            for name in self.fields:
                if cleaned.get(name) in (None, ''):
                    self.add_error(name, 'Completa este dato.')
        return cleaned


class ProfessorProfileForm(forms.ModelForm):
    class Meta:
        model = ProfessorProfile
        fields = ['department']
        labels = {'department': 'Departamento'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.required = False
            f.widget.attrs.setdefault('class', 'input')


def _style_inputs(form):
    for field in form.fields.values():
        field.widget.attrs.setdefault('class', 'input')


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(
        label='Correo', max_length=254,
        widget=forms.EmailInput(attrs={'class': 'input', 'autocomplete': 'email', 'autofocus': True}),
    )


class NewPasswordForm(SetPasswordForm):
    """Elegir contraseña nueva (tras el enlace del correo), con los estilos del sitio."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_inputs(self)


class ChangePasswordForm(PasswordChangeForm):
    """Cambiar la contraseña estando dentro."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _style_inputs(self)
