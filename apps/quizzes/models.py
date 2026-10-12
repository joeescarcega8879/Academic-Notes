from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.organizations.models import Organization, TenantModel


class Question(TenantModel):
    """Pregunta del banco de la organización, reutilizable en varios quizzes.

    Al agregarla a un quiz se **copia**: editar o borrar la del banco después no altera quizzes ya armados
    ni respuestas ya dadas.
    """

    class Kind(models.TextChoices):
        MULTIPLE_CHOICE = 'multiple_choice', 'Opción múltiple'
        TRUE_FALSE = 'true_false', 'Verdadero o falso'

    # Como el grupo, la pregunta pertenece a la organización y la elige quien la crea.
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='+')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    kind = models.CharField('tipo', max_length=20, choices=Kind.choices)
    text = models.TextField('pregunta')
    points = models.DecimalField('puntos', max_digits=6, decimal_places=2, default=1, validators=[MinValueValidator(0.01)])
    explanation = models.TextField('explicación', blank=True, help_text='Se muestra al alumno junto a la respuesta correcta.')
    topic = models.CharField('tema', max_length=80, blank=True)
    is_archived = models.BooleanField('archivada', default=False)
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
