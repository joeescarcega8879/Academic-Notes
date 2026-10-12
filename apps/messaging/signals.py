from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from apps.courses.models import Enrollment, Student

from .models import Conversation

# Un hilo necesita a alguien con quien hablar: solo existe para alumnos con cuenta enlazada.

@receiver(post_save, sender=Enrollment)
def create_conversation(sender, instance, created, **kwargs):
    if created and instance.student.user_id:
        Conversation.objects.get_or_create(course=instance.course, student_id=instance.student.user_id)


@receiver(post_save, sender=Student)
def create_conversations_on_link(sender, instance, **kwargs):
    """Al enlazar una cuenta a un alumno ya inscrito, aparecen los hilos de sus grupos."""
    if instance.user_id:
        for enrollment in instance.enrollments.select_related('course'):
            Conversation.objects.get_or_create(course=enrollment.course, student_id=instance.user_id)


@receiver(post_delete, sender=Enrollment)
def delete_conversation(sender, instance, **kwargs):
    if instance.student.user_id:
        Conversation.objects.filter(course=instance.course, student_id=instance.student.user_id).delete()
