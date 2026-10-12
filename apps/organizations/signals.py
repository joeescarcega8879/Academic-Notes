from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .services import ensure_individual_organization


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_individual_organization(sender, instance, created, **kwargs):
    """Todo profesor nuevo nace con su organización individual."""
    # Transitorio: cuando Membership reemplace a User.role, esto pasa al alta de docentes.
    if created and instance.role == 'professor':
        ensure_individual_organization(instance)
