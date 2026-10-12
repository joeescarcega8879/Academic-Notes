import os
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models

from apps.organizations.models import TenantModel


class EvaluationScheme(TenantModel):
    """Cómo se calcula la calificación final de un grupo: escala, mínimo aprobatorio y redondeo.

    Los periodos y criterios cuelgan de aquí. Los pesos son relativos: solo cuentan los que ya tienen
    calificaciones, así que el promedio no se hunde por lo que aún no se ha evaluado.
    """

    organization_source = 'course'

    ROUNDING_CHOICES = [(0, 'Enteros'), (1, '1 decimal'), (2, '2 decimales')]

    course = models.OneToOneField('courses.Course', on_delete=models.CASCADE, related_name='scheme')
    scale_max = models.PositiveSmallIntegerField(
        'escala máxima', default=10, validators=[MinValueValidator(1)],
        help_text='La calificación máxima posible: 10, 100, 5…',
    )
    pass_mark = models.DecimalField(
        'mínimo aprobatorio', max_digits=6, decimal_places=2, default=6, validators=[MinValueValidator(0)],
        help_text='Se compara con la calificación ya redondeada.',
    )
    rounding_decimals = models.PositiveSmallIntegerField('redondeo', choices=ROUNDING_CHOICES, default=2)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(pass_mark__lte=models.F('scale_max')), name='scheme_pass_mark_within_scale'),
        ]

    def __str__(self):
        return f'Esquema de {self.course}'

    def clean(self):
        if self.pass_mark is not None and self.scale_max is not None and self.pass_mark > self.scale_max:
            raise ValidationError({'pass_mark': 'El mínimo aprobatorio no puede superar la escala máxima.'})

    def criteria(self):
        """Criterios del esquema en orden (periodo y posición)."""
        return EvaluationCriterion.objects.filter(period__scheme=self).select_related('period').order_by(
            'period__position', 'period__id', 'position', 'id',
        )


WEIGHT_VALIDATORS = [MinValueValidator(0), MaxValueValidator(100)]


class EvaluationPeriod(TenantModel):
    """Parcial, bimestre… dentro del ciclo. Un esquema siempre tiene al menos uno."""

    organization_source = 'scheme'

    scheme = models.ForeignKey(EvaluationScheme, on_delete=models.CASCADE, related_name='periods')
    name = models.CharField('nombre', max_length=80)
    weight = models.DecimalField('peso (%)', max_digits=5, decimal_places=2, default=100, validators=WEIGHT_VALIDATORS)
    position = models.PositiveSmallIntegerField('orden', default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name


class EvaluationCriterion(TenantModel):
    """Una categoría con peso dentro de un periodo: Exámenes 40 %, Tareas 30 %…"""

    organization_source = 'period'

    period = models.ForeignKey(EvaluationPeriod, on_delete=models.CASCADE, related_name='criteria')
    name = models.CharField('nombre', max_length=80)
    weight = models.DecimalField('peso (%)', max_digits=5, decimal_places=2, default=100, validators=WEIGHT_VALIDATORS)
    # Las evaluaciones nuevas de este tipo se asignan solas a este criterio.
    default_type = models.CharField('tipo de evaluación', max_length=20, blank=True)
    position = models.PositiveSmallIntegerField('orden', default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.name} ({self.period})'


class Activity(TenantModel):
    """Algo que el docente califica: tarea, quiz, examen, proyecto o participación.

    Una actividad en borrador (``published=False``) no la ven los alumnos ni cuenta para ninguna
    calificación final hasta que se publica.
    """

    organization_source = 'course'

    class Type(models.TextChoices):
        QUIZ = 'quiz', 'Quiz'
        EXAM = 'exam', 'Examen'
        HOMEWORK = 'homework', 'Tarea'
        PROJECT = 'project', 'Proyecto'
        PARTICIPATION = 'participation', 'Participación'

    # Tipos en los que el alumno entrega algo (archivo, texto o enlace).
    SUBMISSION_TYPES = (Type.HOMEWORK, Type.PROJECT)

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="activities")
    title = models.CharField('título', max_length=255)
    instructions = models.TextField('instrucciones', blank=True)
    type = models.CharField('tipo', max_length=20, choices=Type.choices, default=Type.HOMEWORK)
    max_score = models.FloatField('puntos', default=10.0, validators=[MinValueValidator(0.01)])
    weight = models.FloatField('peso', default=1.0, validators=[MinValueValidator(0)])
    # Fecha de realización (examen, participación del día…). La apertura y el límite de entrega son aparte.
    date = models.DateField('fecha', null=True, blank=True)

    published = models.BooleanField('publicada', default=False)
    opens_at = models.DateTimeField('abre', null=True, blank=True)
    due_at = models.DateTimeField('fecha límite de entrega', null=True, blank=True)
    allow_late = models.BooleanField('permite entregas tardías', default=True)
    late_penalty = models.DecimalField(
        'penalización por entrega tardía (%)', max_digits=5, decimal_places=2, default=0,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    # Peso relativo (``weight``) dentro de su criterio. Si no se indica, se asigna según el tipo.
    # PROTECT: no se borra un criterio con actividades; hay que reasignarlas primero.
    criterion = models.ForeignKey(EvaluationCriterion, on_delete=models.PROTECT, related_name='activities', verbose_name='criterio')

    class Meta:
        ordering = ['-date', 'title']
        verbose_name_plural = 'activities'

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse('grades:activity_detail', args=[self.pk])

    @property
    def accepts_submissions(self):
        return self.type in self.SUBMISSION_TYPES

    def __str__(self):
        return f"{self.title} · {self.course.name}"

    def clean(self):
        if self.criterion_id and self.course_id and self.criterion.period.scheme.course_id != self.course_id:
            raise ValidationError({'criterion': 'El criterio debe ser del esquema de este grupo.'})
        if self.opens_at and self.due_at and self.due_at < self.opens_at:
            raise ValidationError({'due_at': 'La fecha límite no puede ser anterior a la apertura.'})

    def save(self, *args, **kwargs):
        from .services.schemes import default_criterion

        self.course.ensure_editable()
        if self.criterion_id is None:
            self.criterion = default_criterion(self.course, self.type)
        self.clean()
        super().save(*args, **kwargs)

    
class Grade(TenantModel):
    organization_source = 'activity'

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='grades')
    score = models.FloatField(validators=[MinValueValidator(0)])
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('activity', 'student')
        ordering = ['-graded_at']

    def __str__(self):
        return f'{self.student} — {self.activity.title}: {self.score}'

    def clean(self):
        if self.student_id and self.activity_id and self.student.organization_id != self.activity.organization_id:
            raise ValidationError('El alumno y la actividad deben pertenecer a la misma organización.')
        if self.activity_id:
            self.activity.course.ensure_editable()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


# ── Entregas ──────────────────────────────────────────────────────────

MAX_SUBMISSION_BYTES = 10 * 1024 * 1024
# Lista blanca: nada que un navegador pueda ejecutar (html, svg, js…) si alguien abre el archivo.
ALLOWED_SUBMISSION_EXTENSIONS = (
    '.pdf', '.doc', '.docx', '.odt', '.rtf', '.txt', '.csv', '.xls', '.xlsx', '.ods', '.ppt', '.pptx', '.odp',
    '.png', '.jpg', '.jpeg', '.gif', '.zip',
)


def get_submission_storage():
    """Almacenamiento privado de entregas (``STORAGES["submissions"]``): disco hoy, S3 mañana."""
    from django.core.files.storage import storages

    return storages['submissions']


def submission_upload_to(instance, filename):
    # El nombre en disco no es el del alumno: evita colisiones y rutas manipuladas.
    extension = os.path.splitext(filename)[1].lower()
    activity = instance.activity
    return f'{activity.organization_id}/{activity.course_id}/{activity.pk}/{instance.student_id}/{uuid.uuid4().hex}{extension}'


def validate_submission_file(file):
    extension = os.path.splitext(file.name)[1].lower()
    if extension not in ALLOWED_SUBMISSION_EXTENSIONS:
        raise ValidationError(
            'Tipo de archivo no permitido. Sube un PDF, documento de Office, imagen, texto o ZIP.', code='extension',
        )
    if file.size > MAX_SUBMISSION_BYTES:
        raise ValidationError('El archivo pesa más de 10 MB.', code='size')


class Submission(TenantModel):
    """Lo que un alumno entrega en una actividad: texto, enlace y/o archivo. Una por alumno y actividad."""

    organization_source = 'activity'

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='submissions')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='submissions')
    text = models.TextField('respuesta', blank=True)
    link = models.CharField('enlace', max_length=500, blank=True, validators=[URLValidator(schemes=['http', 'https'])])
    file = models.FileField(
        'archivo', upload_to=submission_upload_to, storage=get_submission_storage, blank=True, max_length=300,
        validators=[validate_submission_file],
    )
    original_name = models.CharField(max_length=255, blank=True)
    submitted_at = models.DateTimeField()
    is_late = models.BooleanField(default=False)

    class Meta:
        unique_together = ('activity', 'student')
        ordering = ['-submitted_at']

    def __str__(self):
        return f'{self.student} → {self.activity.title}'

    def clean(self):
        if self.student_id and self.activity_id and self.student.organization_id != self.activity.organization_id:
            raise ValidationError('El alumno y la actividad deben pertenecer a la misma organización.')
        if not (self.text.strip() or self.link or self.file):
            raise ValidationError('La entrega necesita una respuesta, un enlace o un archivo.')
        if self.activity_id:
            self.activity.course.ensure_editable()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
