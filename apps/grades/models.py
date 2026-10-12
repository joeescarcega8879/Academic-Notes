from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
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


class Evaluation(TenantModel):
    organization_source = 'course'

    class Type(models.TextChoices):
        QUIZ = 'quiz', 'Quiz'
        EXAM = 'exam', 'Examen'
        HOMEWORK = 'homework', 'Tarea'
        PROJECT = 'project', 'Proyecto'

    course = models.ForeignKey("courses.Course", on_delete=models.CASCADE, related_name="evaluations")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.QUIZ)
    max_score = models.FloatField(default=10.0, validators=[MinValueValidator(0.01)])
    weight = models.FloatField(default=1.0, validators=[MinValueValidator(0)])
    date = models.DateField(null=True, blank=True)

    # Peso relativo (``weight``) dentro de su criterio. Si no se indica, se asigna según el tipo.
    # PROTECT: no se borra un criterio con evaluaciones; hay que reasignarlas primero.
    criterion = models.ForeignKey(EvaluationCriterion, on_delete=models.PROTECT, related_name='evaluations', verbose_name='criterio')

    class Meta:
        ordering = ['-date', 'title']

    def __str__(self):
        return f"{self.title} · {self.course.name}"

    def clean(self):
        if self.criterion_id and self.course_id and self.criterion.period.scheme.course_id != self.course_id:
            raise ValidationError({'criterion': 'El criterio debe ser del esquema de este grupo.'})

    def save(self, *args, **kwargs):
        from .services.schemes import default_criterion

        self.course.ensure_editable()
        if self.criterion_id is None:
            self.criterion = default_criterion(self.course, self.type)
        self.clean()
        super().save(*args, **kwargs)

    
class Grade(TenantModel):
    organization_source = 'evaluation'

    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='grades')
    score = models.FloatField(validators=[MinValueValidator(0)])
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('evaluation', 'student')
        ordering = ['-graded_at']

    def __str__(self):
        return f'{self.student} — {self.evaluation.title}: {self.score}'

    def clean(self):
        if self.student_id and self.evaluation_id and self.student.organization_id != self.evaluation.organization_id:
            raise ValidationError('El alumno y la evaluación deben pertenecer a la misma organización.')
        if self.evaluation_id:
            self.evaluation.course.ensure_editable()

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)