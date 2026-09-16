from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from apps.subjects.models import Enrollment

from .models import Conversation

@receiver(post_save, sender=Enrollment)
def create_conversation(sender, instance, created, **kwargs):
    if created:
        Conversation.objects.get_or_create(subject=instance.subject, student=instance.student)


@receiver(post_delete, sender=Enrollment)
def delete_conversation(sender, instance, **kwargs):
    Conversation.objects.filter(subject=instance.subject, student=instance.student).delete()
