from django.db import models
from django.conf import settings

class Conversation(models.Model):
    subject = models.ForeignKey("subjects.Subject", 
                                on_delete=models.CASCADE, 
                                related_name="conversations"
    )

    student = models.ForeignKey(settings.AUTH_USER_MODEL, 
                                on_delete=models.CASCADE, 
                                related_name="student_conversations", 
                                limit_choices_to={'role': 'student'}
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('subject', 'student')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.get_full_name() or self.student.username} - {self.subject.name}"

    def counterpart(self, user):
        return self.subject.professor if user == self.student else self.student

class Message(models.Model):
    conversation = models.ForeignKey(Conversation,
                                     on_delete=models.CASCADE,
                                     related_name="messages"
    )

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages"
    )

    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
            models.Index(fields=['conversation', 'read_at']),
        ]

    def __str__(self):
        return f"{self.sender.get_full_name() or self.sender.username} — {self.body[:40]}"