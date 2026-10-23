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
