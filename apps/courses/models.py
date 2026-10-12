import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.organizations.models import Organization, TenantModel
from apps.organizations.services import ensure_individual_organization, ensure_student_membership


class AcademicYear(TenantModel):
    """Ciclo escolar de una organización (el año o el semestre; los periodos viven dentro de él).

    Los grupos se archivan y se duplican al cambiar de ciclo, nunca se renombran.
    """

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')
    name = models.CharField('nombre', max_length=60)
    start_date = models.DateField('inicio')
    end_date = models.DateField('fin')
    is_current = models.BooleanField('ciclo actual', default=False)

    class Meta:
        ordering = ['-start_date', 'name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'name'], name='unique_academic_year_name_per_organization'),
            # A lo sumo un ciclo actual por organización.
            models.UniqueConstraint(
                fields=['organization'], condition=models.Q(is_current=True),
                name='unique_current_academic_year_per_organization',
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__gte=models.F('start_date')), name='academic_year_end_not_before_start',
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError('El ciclo no puede terminar antes de empezar.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.is_current:
            # Marcar éste como actual desmarca el anterior.
            AcademicYear.objects.filter(organization_id=self.organization_id, is_current=True).exclude(
                pk=self.pk,
            ).update(is_current=False)
        super().save(*args, **kwargs)

    @staticmethod
    def default_period(today):
        """(nombre, inicio, fin) del ciclo agosto–julio que contiene ``today``."""
        start_year = today.year if today.month >= 8 else today.year - 1
        return (
            f'{start_year}–{start_year + 1}',
            datetime.date(start_year, 8, 1),
            datetime.date(start_year + 1, 7, 31),
        )

    @classmethod
    def current_for(cls, organization):
        """Ciclo actual de ``organization``; si no tiene, crea el agosto–julio en curso y lo marca actual."""
        current = cls.objects.filter(organization=organization, is_current=True).first()
        if current is not None:
            return current
        name, start, end = cls.default_period(timezone.localdate())
        year, _ = cls.objects.get_or_create(
            organization=organization, name=name, defaults={'start_date': start, 'end_date': end},
        )
        year.is_current = True
        year.save()
        return year


class Course(TenantModel):
    name = models.CharField(max_length=100)
    # El código es único dentro del ciclo de una organización, para poder duplicar el grupo al siguiente ciclo.
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    schedule = models.CharField(max_length=200, blank=True)
    color = models.CharField(max_length=7, default='#1e3a5f')  # Hex color code

    # A diferencia de sus hijos, la materia sí elige su organización (en el admin).
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')

    professor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='courses', limit_choices_to={'role': 'professor'})

    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name='courses', verbose_name='ciclo')

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Activo'
        ARCHIVED = 'archived', 'Archivado'

    # Un grupo archivado es de solo lectura: sigue siendo consultable y exportable.
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['organization', 'academic_year', 'code'], name='unique_course_code_per_year'),
        ]

    @property
    def is_archived(self):
        return self.status == self.Status.ARCHIVED

    def ensure_editable(self):
        """Un grupo archivado no admite cambios en sus alumnos, evaluaciones ni notas."""
        if self.is_archived:
            raise ValidationError('El grupo está archivado y es de solo lectura.')

    def __str__(self):
        return f"{self.name} ({self.code})"

    def save(self, *args, **kwargs):
        # Sin organización explícita, la materia pertenece a donde da clase su profesor.
        if self.organization_id is None:
            self.organization = ensure_individual_organization(self.professor)
        if self.academic_year_id is None:
            self.academic_year = AcademicYear.current_for(self.organization)
        elif self.academic_year.organization_id != self.organization_id:
            raise ValidationError('El ciclo y el grupo deben pertenecer a la misma organización.')
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
        self.course.ensure_editable()
        super().save(*args, **kwargs)
