from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.organizations.models import Organization, TenantModel


class Rubric(TenantModel):
    """Plantilla de calificación del docente: criterios con niveles y puntos, reutilizable en cualquier actividad.

    El contenido vive en sus **versiones** (``RubricVersion``): una rúbrica ya usada para calificar no se edita, se
    publica una versión nueva, de modo que ninguna calificación dada cambia después.
    """

    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    name = models.CharField('nombre', max_length=150)
    description = models.CharField('para qué sirve', max_length=200, blank=True)
    is_archived = models.BooleanField('archivada', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        from django.urls import reverse

        return reverse('rubrics:detail', args=[self.pk])

    @property
    def current_version(self):
        """La versión vigente: la que se ofrece al asignar la rúbrica a una actividad."""
        versions = list(self.versions.all())  # con prefetch no cuesta otra consulta
        return max(versions, key=lambda version: version.number) if versions else None


class RubricVersion(TenantModel):
    """Una edición de la rúbrica. Mientras nadie califique con ella se corrige en su lugar; después, se congela."""

    organization_source = 'rubric'

    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name='versions')
    number = models.PositiveSmallIntegerField('versión', default=1)
    # Suma de lo máximo de cada criterio: se guarda para no recalcularla en cada pantalla.
    max_points = models.DecimalField('puntos', max_digits=7, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-number']
        constraints = [models.UniqueConstraint(fields=['rubric', 'number'], name='unique_rubric_version_number')]

    def __str__(self):
        return f'{self.rubric} · versión {self.number}'


class RubricCriterion(TenantModel):
    organization_source = 'version'

    version = models.ForeignKey(RubricVersion, on_delete=models.CASCADE, related_name='criteria')
    position = models.PositiveSmallIntegerField(default=0)
    name = models.CharField('criterio', max_length=150)
    # El nivel más alto de este criterio.
    max_points = models.DecimalField('puntos', max_digits=6, decimal_places=2, default=0)

    class Meta:
        ordering = ['position', 'id']
        verbose_name_plural = 'rubric criteria'

    def __str__(self):
        return self.name


class RubricLevel(TenantModel):
    organization_source = 'criterion'

    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name='levels')
    position = models.PositiveSmallIntegerField(default=0)
    name = models.CharField('nivel', max_length=60)
    points = models.DecimalField('puntos', max_digits=6, decimal_places=2, validators=[MinValueValidator(0)])
    description = models.TextField('descripción', blank=True)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.criterion} · {self.name} ({self.points:g})'


class RubricScore(TenantModel):
    """El nivel que obtuvo un alumno en un criterio, con un comentario opcional. Cuelga de su ``Grade``."""

    organization_source = 'grade'

    grade = models.ForeignKey('grades.Grade', on_delete=models.CASCADE, related_name='rubric_scores')
    # PROTECT: una versión con calificaciones no se modifica ni se borra, así el detalle siempre se puede mostrar.
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.PROTECT, related_name='+')
    level = models.ForeignKey(RubricLevel, on_delete=models.PROTECT, related_name='+')
    points = models.DecimalField(max_digits=6, decimal_places=2)
    comment = models.CharField('comentario', max_length=500, blank=True)

    class Meta:
        ordering = ['criterion__position', 'criterion_id']
        constraints = [models.UniqueConstraint(fields=['grade', 'criterion'], name='unique_rubric_score_per_criterion')]

    def __str__(self):
        return f'{self.criterion}: {self.points:g}'
