from django.conf import settings
from django.db import models

from apps.organizations.models import TenantModel


class AIRequest(TenantModel):
    """Registro de cada solicitud a un proveedor de IA: quién, para qué, cuánto costó y cómo terminó.

    Es la cuenta de usos de la cuota mensual del plan y la bitácora de auditoría. **No guarda lo que se envió ni lo
    que se recibió**: solo su tamaño y una huella (hash), que permite saber si dos solicitudes fueron la misma sin
    conservar datos de alumnos.
    """

    class Kind(models.TextChoices):
        PROBE = 'probe', 'Prueba'
        SYLLABUS_SPLIT = 'syllabus_split', 'División del temario'
        QUIZ = 'quiz', 'Preguntas de quiz'
        ASSIGNMENT = 'assignment', 'Tarea'
        EXAM = 'exam', 'Examen'
        GRADE_REVIEW = 'grade_review', 'Revisión de una tarea'

    class Status(models.TextChoices):
        OK = 'ok', 'Correcta'
        ERROR = 'error', 'Con error'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField('tipo', max_length=20, choices=Kind.choices)
    provider = models.CharField('proveedor', max_length=20)
    model = models.CharField('modelo', max_length=80, blank=True)
    status = models.CharField('estado', max_length=10, choices=Status.choices)
    error = models.CharField('error', max_length=200, blank=True)  # código y motivo, nunca el contenido
    tokens_in = models.PositiveIntegerField('tokens de entrada', default=0)
    tokens_out = models.PositiveIntegerField('tokens de salida', default=0)
    cost_usd = models.DecimalField('costo estimado (USD)', max_digits=10, decimal_places=6, null=True, blank=True)
    duration_ms = models.PositiveIntegerField('duración (ms)', default=0)
    input_chars = models.PositiveIntegerField('caracteres enviados', default=0)
    input_hash = models.CharField('huella de lo enviado', max_length=64, blank=True)
    contains_student_data = models.BooleanField('llevaba datos de alumnos', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['organization', 'status', 'created_at'], name='ai_request_org_month')]
        verbose_name = 'solicitud de IA'
        verbose_name_plural = 'solicitudes de IA'

    def __str__(self):
        return f'{self.get_kind_display()} · {self.get_status_display()} · {self.created_at:%Y-%m-%d %H:%M}'


class AIDraft(TenantModel):
    """Lo que la IA propone y el docente todavía no aprueba: no es una pregunta ni una semana hasta que lo apruebe.

    ``items`` guarda las propuestas ya validadas. En un quiz cada una es
    ``{kind, text, choices: [{text, correct}], true_is_correct, explanation, citation, week, topic, points,
    state, edited, similar, question_id}``; ``state`` es ``pending`` (por revisar), ``approved``, ``discarded`` o
    ``regenerating``. En una división del temario cada una es una semana
    ``{title, topics, objectives, assessment, source}`` lista para ``replace_weeks``. En tareas y proyectos cada una
    es ``{title, description, deliverable, criteria: [{name, description, points}], points, type, citation, week,
    state, edited, activity_id}``; ``state`` ``created`` dice que ya se creó la actividad (``activity_id``).
    """

    organization_source = 'course'

    class Kind(models.TextChoices):
        QUIZ_QUESTIONS = 'quiz_questions', 'Preguntas de quiz'
        SYLLABUS_SPLIT = 'syllabus_split', 'División del temario'
        ASSIGNMENTS = 'assignments', 'Tareas y proyectos'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Generando'
        READY = 'ready', 'Por revisar'
        FAILED = 'failed', 'No se pudo generar'
        APPLIED = 'applied', 'Aplicada'
        DISCARDED = 'discarded', 'Descartada'

    course = models.ForeignKey('courses.Course', on_delete=models.CASCADE, related_name='ai_drafts')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField('tipo', max_length=20, choices=Kind.choices)
    status = models.CharField('estado', max_length=10, choices=Status.choices, default=Status.PENDING)
    # Quiz al que van las preguntas. Sin él (se pidió desde una semana) se crea un quiz en borrador al aprobar.
    activity = models.ForeignKey('grades.Activity', null=True, blank=True, on_delete=models.SET_NULL, related_name='ai_drafts')
    new_activity_title = models.CharField(max_length=255, blank=True)
    params = models.JSONField('lo que se pidió', default=dict)
    items = models.JSONField('propuestas', default=list)
    error = models.CharField('motivo del fallo', max_length=300, blank=True)  # ya listo para mostrarse al docente
    dropped = models.PositiveSmallIntegerField('propuestas descartadas por inválidas', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = 'propuesta de IA'
        verbose_name_plural = 'propuestas de IA'

    def __str__(self):
        return f'{self.get_kind_display()} · {self.get_status_display()} · {self.created_at:%Y-%m-%d %H:%M}'

    @property
    def is_open(self):
        """Todavía hay algo que hacer con ella: esperar, reintentar o revisar."""
        return self.status in (self.Status.PENDING, self.Status.READY, self.Status.FAILED)

    def count(self, state):
        return sum(1 for item in self.items if item.get('state') == state)

    @property
    def pending_count(self):
        """Propuestas que el docente aún no decide (para las plantillas, que no pueden llamar ``count('pending')``)."""
        return self.count('pending')
