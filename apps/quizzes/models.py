from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.organizations.models import Organization, TenantModel


class Question(TenantModel):
    """Pregunta del banco, de un grupo o general, reutilizable en varios quizzes.

    Al agregarla a un quiz se **copia**: editar o borrar la del banco después no altera quizzes ya armados
    ni respuestas ya dadas.

    ``course`` la liga al banco de un grupo: solo se ofrece en los quizzes de ese grupo. Sin grupo es una pregunta
    **general**, disponible en todos los grupos de quien la creó.
    """

    class Kind(models.TextChoices):
        MULTIPLE_CHOICE = 'multiple_choice', 'Opción múltiple'
        TRUE_FALSE = 'true_false', 'Verdadero o falso'

    # Como el grupo, la pregunta pertenece a la organización y la elige quien la crea.
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    # Si el grupo desaparece, sus preguntas no: pasan a ser generales.
    course = models.ForeignKey(
        'courses.Course', null=True, blank=True, on_delete=models.SET_NULL, related_name='bank_questions',
        verbose_name='grupo', help_text='Vacío = pregunta general: sirve en todos tus grupos.',
    )
    kind = models.CharField('tipo', max_length=20, choices=Kind.choices)
    text = models.TextField('pregunta')
    points = models.DecimalField('puntos', max_digits=6, decimal_places=2, default=1, validators=[MinValueValidator(0.01)])
    explanation = models.TextField('explicación', blank=True, help_text='Se muestra al alumno junto a la respuesta correcta.')
    topic = models.CharField('tema', max_length=80, blank=True)
    is_archived = models.BooleanField('archivada', default=False)
    # La propuso la IA y el docente la aprobó (``AIDraft`` guarda quién y cuándo).
    ai_generated = models.BooleanField('hecha con IA', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return self.text[:60]

    @property
    def correct_choices(self):
        return [c for c in self.choices.all() if c.is_correct]


class Choice(TenantModel):
    organization_source = 'question'

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField('opción', max_length=500)
    is_correct = models.BooleanField('correcta', default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.text


# ── Quiz: configuración, preguntas copiadas, intentos y respuestas ───

class QuizConfig(TenantModel):
    """Reglas de un quiz. Cuelga de una actividad de tipo quiz (se crea sola al crearla)."""

    class Feedback(models.TextChoices):
        NONE = 'none', 'Solo la calificación'
        AFTER_SUBMIT = 'after_submit', 'Respuestas correctas y explicaciones al terminar'
        AFTER_CLOSE = 'after_close', 'Respuestas correctas y explicaciones cuando cierre el quiz'

    class Policy(models.TextChoices):
        HIGHEST = 'highest', 'La mejor calificación'
        LAST = 'last', 'La del último intento'
        AVERAGE = 'average', 'El promedio de los intentos'

    organization_source = 'activity'

    activity = models.OneToOneField('grades.Activity', on_delete=models.CASCADE, related_name='quiz')
    attempts_allowed = models.PositiveSmallIntegerField(
        'intentos permitidos', default=1, validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    time_limit_minutes = models.PositiveSmallIntegerField(
        'tiempo límite (minutos)', null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(600)],
        help_text='Vacío = sin límite. El tiempo lo mide el servidor desde que el alumno empieza.',
    )
    shuffle_questions = models.BooleanField('orden aleatorio de las preguntas', default=False)
    shuffle_choices = models.BooleanField('orden aleatorio de las opciones', default=False)
    feedback_mode = models.CharField('retroalimentación', max_length=15, choices=Feedback.choices, default=Feedback.AFTER_SUBMIT)
    attempt_policy = models.CharField(
        'calificación con varios intentos', max_length=10, choices=Policy.choices, default=Policy.HIGHEST,
    )

    def __str__(self):
        return f'Quiz de {self.activity}'

    @property
    def is_locked(self):
        """Con intentos ya hechos, las preguntas y sus puntos dejan de poder cambiar."""
        return self.attempts.exists()


class QuizQuestion(TenantModel):
    """Copia de una pregunta dentro de un quiz: editar o borrar la del banco no la altera."""

    organization_source = 'quiz'

    quiz = models.ForeignKey(QuizConfig, on_delete=models.CASCADE, related_name='questions')
    source = models.ForeignKey(Question, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField(max_length=20, choices=Question.Kind.choices)
    text = models.TextField()
    points = models.DecimalField(max_digits=6, decimal_places=2, default=1, validators=[MinValueValidator(0.01)])
    explanation = models.TextField(blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    ai_generated = models.BooleanField('hecha con IA', default=False)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.text[:60]


class QuizChoice(TenantModel):
    organization_source = 'question'

    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='choices')
    text = models.CharField(max_length=500)
    is_correct = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.text


class QuizAttempt(TenantModel):
    """Un intento de un alumno. El plazo lo fija y lo vigila el servidor."""

    class Status(models.TextChoices):
        IN_PROGRESS = 'in_progress', 'En curso'
        SUBMITTED = 'submitted', 'Enviado'
        EXPIRED = 'expired', 'Cerrado por tiempo'

    organization_source = 'quiz'

    quiz = models.ForeignKey(QuizConfig, on_delete=models.CASCADE, related_name='attempts')
    student = models.ForeignKey('courses.Student', on_delete=models.CASCADE, related_name='quiz_attempts')
    number = models.PositiveSmallIntegerField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField()
    deadline = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    # Orden en que el alumno ve las preguntas y sus opciones: {"questions": [ids], "choices": {id: [ids]}}.
    layout = models.JSONField(default=dict)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    max_points = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ['-started_at', '-id']
        unique_together = ('quiz', 'student', 'number')
        constraints = [
            # Un alumno no puede tener dos intentos abiertos a la vez en el mismo quiz.
            models.UniqueConstraint(
                fields=['quiz', 'student'], condition=models.Q(status='in_progress'), name='one_open_quiz_attempt_per_student',
            ),
        ]

    def __str__(self):
        return f'{self.student} · intento {self.number}'

    @property
    def is_finished(self):
        return self.status != self.Status.IN_PROGRESS


class Answer(TenantModel):
    organization_source = 'attempt'

    attempt = models.ForeignKey(QuizAttempt, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(QuizQuestion, on_delete=models.CASCADE, related_name='answers')
    choice = models.ForeignKey(QuizChoice, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    is_correct = models.BooleanField(null=True)
    points_awarded = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    saved_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('attempt', 'question')

    def __str__(self):
        return f'{self.attempt} → {self.question}'
