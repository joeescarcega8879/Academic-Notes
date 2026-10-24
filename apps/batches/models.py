import os
import uuid

from django.conf import settings
from django.db import models

from apps.grades.models import get_submission_storage
from apps.organizations.models import TenantModel


def batch_upload_to(instance, filename):
    # Como las entregas: el nombre en disco no es el del archivo original.
    activity = instance.activity
    return f'{activity.organization_id}/{activity.course_id}/{activity.pk}/lote/{uuid.uuid4().hex}.pdf'


class BatchFile(TenantModel):
    """Un PDF del lote que sube el docente (tareas en papel digitalizadas, entregas por correo…).

    Espera aquí hasta que el docente lo confirma: solo entonces se vuelve la ``Submission`` del alumno y esta fila
    desaparece. Mientras tanto la portada se lee para saber de quién es (por la matrícula) y el docente corrige lo
    que no se pudo identificar.
    """

    organization_source = 'activity'

    class Status(models.TextChoices):
        READY = 'ready', 'Identificado'
        UNIDENTIFIED = 'unidentified', 'Sin identificar'
        DUPLICATE = 'duplicate', 'Duplicado'
        CONFLICT = 'conflict', 'Ya tiene entrega'
        UNREADABLE = 'unreadable', 'No se pudo leer'

    class IdentifiedBy(models.TextChoices):
        COVER = 'cover', 'Por la portada'
        MANUAL = 'manual', 'A mano'

    activity = models.ForeignKey('grades.Activity', on_delete=models.CASCADE, related_name='batch_files')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    # Vacío solo en los archivos que no se pudieron leer: no vale la pena guardarlos.
    file = models.FileField(upload_to=batch_upload_to, storage=get_submission_storage, blank=True, max_length=300)
    original_name = models.CharField(max_length=255)
    size = models.PositiveIntegerField(default=0)
    pages = models.PositiveIntegerField(default=0)
    # Las páginas de portada que se leyeron (las de la actividad al momento de subir) y su texto, recortado.
    cover_pages = models.PositiveSmallIntegerField(default=1)
    cover_text = models.TextField(blank=True)

    status = models.CharField(max_length=20, choices=Status.choices)
    student = models.ForeignKey('courses.Student', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    identified_by = models.CharField(max_length=10, choices=IdentifiedBy.choices, blank=True)
    # Qué pasó, en una frase para el docente («protegido con contraseña», «varias matrículas en la portada»…).
    problem = models.CharField(max_length=200, blank=True)
    # La portada no menciona el apellido del alumno al que se le asignó: puede ser la matrícula de otro.
    name_mismatch = models.BooleanField(default=False)
    # El alumno ya entregó en el portal y el docente decidió reemplazar ese archivo.
    replace = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        verbose_name = 'archivo del lote'
        verbose_name_plural = 'archivos del lote'

    def __str__(self):
        return f'{self.original_name} → {self.activity.title}'

    @property
    def extension(self):
        return os.path.splitext(self.original_name)[1].lower()
