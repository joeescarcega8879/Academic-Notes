import uuid
from pathlib import PurePosixPath

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.urls import reverse


def get_avatar_storage():
    """Almacenamiento privado de las fotos de perfil (``STORAGES["avatars"]``): disco hoy, S3 mañana."""
    from django.core.files.storage import storages

    return storages['avatars']


def avatar_upload_to(instance, filename):
    # Nombre al azar: no revela nada y cada foto nueva cambia la dirección (así el navegador no muestra la vieja).
    return f'{instance.pk}/{uuid.uuid4().hex}.jpg'


class UserManager(BaseUserManager):
    def create_user(self, username=None, email=None, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio')
        email = self.normalize_email(email)
        username = username or email.split('@')[0]
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username=None, email=None, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        STUDENT = 'student', 'Alumno'
        PROFESSOR = 'professor', 'Profesor'

    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices)
    phone = models.CharField(max_length=15, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    dni = models.CharField(max_length=20, unique=True, null=True, blank=True)
    avatar = models.ImageField(upload_to=avatar_upload_to, storage=get_avatar_storage, blank=True)

    # Preferencias (del perfil.html)
    notify_grades = models.BooleanField(default=True)
    notify_weekly = models.BooleanField(default=False)
    notify_sms = models.BooleanField(default=False)
    show_average = models.BooleanField(default=True)

    # Marca de tiempo de la ultima vez que el usuario leyo sus notificaciones.
    notifications_read_at = models.DateTimeField(null=True, blank=True)

    # Cuándo confirmó que el correo es suyo (con el enlace que se le envía). Vacío = sin confirmar.
    email_verified_at = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['role', 'dni']

    @property
    def initials(self):
        """Iniciales para el círculo sin foto; si no hay nombre, la primera letra del correo."""
        letters = f'{self.first_name[:1]}{self.last_name[:1]}'.upper()
        return letters or (self.email[:1].upper() if self.email else '?')

    @property
    def avatar_url(self):
        """Dirección de la foto (la sirve una vista con permisos), o ``''`` si no tiene."""
        if not self.avatar:
            return ''
        return f'{reverse("avatar", args=[self.pk])}?v={PurePosixPath(self.avatar.name).stem}'
    

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    program = models.CharField(max_length=100)
    semester = models.IntegerField()
    tutor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tutor_students')
    # Deprecado: la matrícula pertenece a la organización (courses.Student.student_number).
    enrollment_number = models.CharField(
        max_length=20, blank=True, default='',
        help_text='Deprecado: la matrícula vive en courses.Student.student_number.',
    )

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.program} ({self.semester}º sem)'
    
class ProfessorProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='professor_profile'
    )
    department = models.CharField(max_length=100)

    def __str__(self):
        return f'{self.user.get_full_name()} — {self.department}'