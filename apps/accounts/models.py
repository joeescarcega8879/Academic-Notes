from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager


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
    dni = models.CharField(max_length=20, unique=True, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True)

    # Preferencias (del perfil.html)
    notify_grades = models.BooleanField(default=True)
    notify_weekly = models.BooleanField(default=False)
    notify_sms = models.BooleanField(default=False)
    show_average = models.BooleanField(default=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['role', 'dni']
    

class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    program = models.CharField(max_length=100)
    semester = models.IntegerField()
    tutor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='tutor_students')
    enrollment_number = models.CharField(max_length=20, unique=True)
    
class ProfessorProfile(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, related_name='professor_profile'
    )
    department = models.CharField(max_length=100)