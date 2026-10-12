from celery import shared_task

from .services.attempts import close_overdue_attempts


@shared_task(name='apps.quizzes.tasks.close_overdue_attempts')
def close_overdue_attempts_task():
    """Cierra y califica los intentos cuyo plazo ya pasó. Corre cada minuto (ver CELERY_BEAT_SCHEDULE)."""
    return close_overdue_attempts()
