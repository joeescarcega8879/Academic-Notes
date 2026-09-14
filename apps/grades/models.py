from django.db import models
from django.conf import settings

class Evaluation(models.Model):
    class Type(models.TextChoices):
        QUIZ = 'quiz', 'Quiz'
        EXAM = 'exam', 'Examen'
        HOMEWORK = 'homework', 'Tarea'
        PROJECT = 'project', 'Proyecto'

    subject = models.ForeignKey("subjects.Subject", on_delete=models.CASCADE, related_name="evaluations")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    type = models.CharField(max_length=20, choices=Type.choices, default=Type.QUIZ)
    max_score = models.FloatField(default=10.0)
    weight = models.FloatField(default=1.0)
    date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['-date', 'title']

    def __str__(self):
        return f"{self.title} · {self.subject.name}"

    
class Grade(models.Model):
    evaluation = models.ForeignKey(Evaluation, on_delete=models.CASCADE, related_name='grades')
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='grades',
        limit_choices_to={'role': 'student'},
    )
    score = models.FloatField()
    feedback = models.TextField(blank=True)
    graded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('evaluation', 'student')
        ordering = ['-graded_at']

    def __str__(self):
        return f'{self.student.get_full_name() or self.student.username} — {self.evaluation.title}: {self.score}'