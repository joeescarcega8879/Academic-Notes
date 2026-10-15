from django.conf import settings
from django.db import models

from apps.organizations.models import Organization


class WaitlistEntry(models.Model):
    """Alguien que pidió que le avisemos cuando el plan de pago esté disponible (página de Precios).

    Sirve para medir interés real por plan antes de cobrar. Solo se guarda el correo, para avisar una vez
    (ver el aviso de privacidad). El correo no se verifica: nadie recibe nada más que ese aviso.
    """

    email = models.EmailField()
    plan = models.CharField(max_length=20, choices=Organization.Plan.choices, default=Organization.Plan.TEACHER)
    # Si pidió el aviso con la sesión iniciada.
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'lista de espera'
        verbose_name_plural = 'lista de espera'
        constraints = [models.UniqueConstraint(fields=['email', 'plan'], name='unique_waitlist_email_per_plan')]

    def __str__(self):
        return f'{self.email} · {self.get_plan_display()}'
