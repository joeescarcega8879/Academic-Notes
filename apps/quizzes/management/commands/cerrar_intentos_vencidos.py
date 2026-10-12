"""Cierra los intentos de quiz cuyo plazo ya pasó (alternativa a Celery beat, por ejemplo desde un cron)."""

from django.core.management.base import BaseCommand

from apps.quizzes.services.attempts import close_overdue_attempts


class Command(BaseCommand):
    help = 'Cierra y califica los intentos de quiz que se quedaron abiertos después de su plazo.'

    def handle(self, *args, **options):
        closed = close_overdue_attempts()
        self.stdout.write(self.style.SUCCESS(f'Intentos cerrados por tiempo: {closed}.'))
