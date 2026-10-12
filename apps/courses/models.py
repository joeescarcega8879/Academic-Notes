from django.core.exceptions import ValidationError
from django.db import models
from django.conf import settings

from apps.organizations.models import Organization, TenantModel
from apps.organizations.services import ensure_individual_organization, ensure_student_membership


class Course(TenantModel):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)
    schedule = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=7, default='#1e3a5f')  # Hex color code

    # A diferencia de sus hijos, la materia sí elige su organización (en el admin).
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')

    professor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='courses', limit_choices_to={'role': 'professor'})

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        # Sin organización explícita, la materia pertenece a donde da clase su profesor.
        if self.organization_id is None:
            self.organization = ensure_individual_organization(self.professor)
        super().save(*args, **kwargs)


class Student(TenantModel):
    """Alumno de la lista de una organización.

    Es distinto de la cuenta (``User``): quien se importa desde Excel aún no tiene
    usuario, y muchos docentes usan GradeLink solo como libreta. ``user`` se enlaza
    cuando el alumno usa el código de invitación.
    """

    # Como la materia, el alumno sí elige su organización.
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')

    # Matrícula: texto, nunca entero (ceros a la izquierda y letras). Vacía = sin matrícula.
    student_number = models.CharField('matrícula', max_length=30, blank=True)
    first_name = models.CharField('nombre(s)', max_length=150)
    last_name = models.CharField('apellidos', max_length=150, blank=True)
    email = models.EmailField('correo', blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='student_records',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        constraints = [
            # La matrícula pertenece a la institución: única dentro de ella, no global.
            models.UniqueConstraint(
                fields=['organization', 'student_number'],
                condition=~models.Q(student_number=''),
                name='unique_student_number_per_organization',
            ),
            models.UniqueConstraint(
                fields=['organization', 'user'],
                condition=models.Q(user__isnull=False),
                name='unique_student_user_per_organization',
            ),
        ]

    def __str__(self):
        return self.get_full_name() or self.email or f'Alumno {self.pk}'

    def get_full_name(self):
        return f'{self.first_name} {self.last_name}'.strip()

    def save(self, *args, **kwargs):
        self.student_number = self.student_number.strip()
        super().save(*args, **kwargs)
        # Estar en la lista con una cuenta enlazada hace al usuario miembro de la organización.
        if self.user_id:
            ensure_student_membership(self.user, self.organization)


class Enrollment(TenantModel):
    organization_source = 'course'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='enrollments')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']

    def __str__(self):
        return f"{self.student} enrolled in {self.course.name}"

    def clean(self):
        if self.student_id and self.course_id and self.student.organization_id != self.course.organization_id:
            raise ValidationError('El alumno y el grupo deben pertenecer a la misma organización.')

    def save(self, *args, **kwargs):
        # El alumno y el grupo comparten organización; la inscripción la hereda del grupo.
        self.clean()
        super().save(*args, **kwargs)
