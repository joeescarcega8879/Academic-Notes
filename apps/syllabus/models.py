"""El temario de un grupo y su división por semanas (sección 13 de ``New_Phases.md``).

Es material de planeación del docente: el alumno no lo ve. Sin IA: el editor manual manda siempre.
"""

import os
import uuid

from django.core.exceptions import ValidationError
from django.db import models

from apps.organizations.models import TenantModel

MAX_SYLLABUS_BYTES = 10 * 1024 * 1024
# Lista blanca: PDF con texto, Word moderno y texto plano. El .doc antiguo no se puede leer sin servicios aparte.
ALLOWED_SYLLABUS_EXTENSIONS = ('.pdf', '.docx', '.txt')


def get_syllabus_storage():
    """Almacenamiento privado de temarios (``STORAGES["syllabi"]``): disco hoy, S3 mañana."""
    from django.core.files.storage import storages

    return storages['syllabi']


def syllabus_upload_to(instance, filename):
    # El nombre en disco no es el del docente: evita colisiones y rutas manipuladas.
    extension = os.path.splitext(filename)[1].lower()
    course = instance.course
    return f'{course.organization_id}/{course.pk}/{uuid.uuid4().hex}{extension}'


def validate_syllabus_file(file):
    extension = os.path.splitext(file.name)[1].lower()
    if extension == '.doc':
        raise ValidationError('Los .doc antiguos no se pueden leer: guárdalo como .docx o pega el texto.', code='extension')
    if extension not in ALLOWED_SYLLABUS_EXTENSIONS:
        raise ValidationError('Sube un PDF, un documento de Word (.docx) o un archivo de texto (.txt).', code='extension')
    if file.size > MAX_SYLLABUS_BYTES:
        raise ValidationError('El archivo pesa más de 10 MB.', code='size')


class Syllabus(TenantModel):
    """El temario de un grupo: archivo original (privado) y texto extraído. Uno por grupo."""

    organization_source = 'course'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Extrayendo texto'
        READY = 'ready', 'Texto listo'
        EMPTY = 'empty', 'Sin texto legible'
        FAILED = 'failed', 'No se pudo leer'

    course = models.OneToOneField('courses.Course', on_delete=models.CASCADE, related_name='syllabus')
    file = models.FileField(
        'archivo', upload_to=syllabus_upload_to, storage=get_syllabus_storage, blank=True, max_length=300,
        validators=[validate_syllabus_file],
    )
    original_name = models.CharField(max_length=255, blank=True)
    text = models.TextField('texto', blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.READY)
    # Primer lunes de clases: de aquí salen las fechas de cada semana.
    start_date = models.DateField('inicio de clases', null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'temario'
        verbose_name_plural = 'temarios'

    def __str__(self):
        return f'Temario de {self.course}'

    @property
    def word_count(self):
        return len(self.text.split())


class SyllabusWeek(TenantModel):
    """Una semana del temario. ``position`` (1, 2, 3…) es su número; siempre contiguo, sin huecos."""

    organization_source = 'syllabus'

    syllabus = models.ForeignKey(Syllabus, on_delete=models.CASCADE, related_name='weeks')
    position = models.PositiveIntegerField('número', default=1)
    title = models.CharField('título', max_length=200, blank=True)
    topics = models.TextField('temas', blank=True, help_text='Un tema por línea.')
    objectives = models.TextField('objetivos', blank=True)
    assessment = models.TextField('actividades y evaluación', blank=True, help_text='Una por línea.')
    no_class = models.BooleanField('sin clase', default=False)

    class Meta:
        ordering = ['position', 'pk']
        verbose_name = 'semana del temario'
        verbose_name_plural = 'semanas del temario'

    def __str__(self):
        return f'Semana {self.position}: {self.title}' if self.title else f'Semana {self.position}'

    @property
    def topic_list(self):
        return [line.strip() for line in self.topics.splitlines() if line.strip()]
