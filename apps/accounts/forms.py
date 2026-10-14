from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, SetPasswordForm
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
            
class StudentProfileForm(forms.ModelForm):
    class Meta:
        model = StudentProfile
        fields = ['program', 'semester']
        labels = {'program': 'Programa', 'semester': 'Semestre'}
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.widget.attrs.setdefault('class', 'input')
            
class ProfessorProfileForm(forms.ModelForm):
    class Meta:
        model = ProfessorProfile
        fields = ['department']
        labels = {'department': 'Departamento'}
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
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
