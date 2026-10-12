import os
import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models

from apps.organizations.models import TenantModel

from .hooks import activity_publishing


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
        if self.published:
            # Otras apps pueden vetar la publicación (un quiz sin preguntas, por ejemplo).
            activity_publishing.send(sender=Activity, activity=self)

    def save(self, *args, **kwargs):
        from .services.schemes import default_criterion

        self.course.ensure_editable()
        if self.criterion_id is None:
            self.criterion = default_criterion(self.course, self.type)
        self.clean()
        super().save(*args, **kwargs)

    
def apply_late_penalty(raw_score, penalty_percent):
    """Calificación tras la penalización por entrega tardía, redondeada a 2 decimales (mitad hacia arriba)."""
    factor = 1 - Decimal(str(penalty_percent)) / 100
    return float((Decimal(str(raw_score)) * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


class Grade(TenantModel):
    """Calificación de un alumno en una actividad.

    ``raw_score`` es lo que escribió el docente; ``score`` es la calificación efectiva, ya con la penalización
    por entrega tardía (``late_penalty``, en %), y la que usa todo el cálculo. Al editar se cambia ``raw_score``:
    ``score`` se recalcula al guardar, de modo que la penalización nunca se aplica dos veces.
    """

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Docente'
        QUIZ = 'quiz', 'Quiz (automática)'

    organization_source = 'activity'

    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='grades')
    # De dónde viene: lo que el docente fija a mano manda sobre la calificación automática de un quiz.
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    score = models.FloatField(validators=[MinValueValidator(0)])
    raw_score = models.FloatField(validators=[MinValueValidator(0)])
    late_penalty = models.DecimalField(max_digits=5, decimal_places=2, default=0)
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
        if self.raw_score is None:
            self.raw_score = self.score  # creada sin pasar por el servicio: sin penalización
        else:
            self.score = apply_late_penalty(self.raw_score, self.late_penalty)
        super().save(*args, **kwargs)


class GradeHistory(TenantModel):
    """Bitácora de cambios en las calificaciones: quién, qué y cuándo.

    Se llena con señales, así que cubre cualquier alta, cambio o baja (vistas, admin o scripts), salvo las
    operaciones masivas de consulta (``update()``). Guarda copias del nombre del alumno y de la actividad
    para que el historial sobreviva si se borran.
    """

    class Action(models.TextChoices):
        CREATED = 'created', 'Calificó'
        UPDATED = 'updated', 'Cambió la calificación'
        DELETED = 'deleted', 'Eliminó la calificación'

    organization_source = None
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, related_name='+')

    grade = models.ForeignKey(Grade, null=True, on_delete=models.SET_NULL, related_name='history')
    activity = models.ForeignKey(Activity, null=True, on_delete=models.SET_NULL, related_name='grade_history')
    student = models.ForeignKey('courses.Student', null=True, on_delete=models.SET_NULL, related_name='grade_history')
    activity_title = models.CharField(max_length=255)
    student_name = models.CharField(max_length=300)
    action = models.CharField(max_length=10, choices=Action.choices)
    old_score = models.FloatField(null=True, blank=True)
    new_score = models.FloatField(null=True, blank=True)
    old_feedback = models.TextField(blank=True)
    new_feedback = models.TextField(blank=True)
    late_penalty = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at', '-id']
        verbose_name_plural = 'grade history'

    def __str__(self):
        return f'{self.get_action_display()}: {self.student_name} — {self.activity_title}'


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
