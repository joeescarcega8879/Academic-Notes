from celery import shared_task

from . import drafts, reviews


@shared_task(name='apps.ai.tasks.run_draft')
def run_draft(draft_id):
    """Genera una propuesta de IA. Es lenta y puede fallar: corre fuera de la petición del docente."""
    drafts.run(draft_id)


@shared_task(name='apps.ai.tasks.regenerate_item')
def regenerate_item(draft_id, index):
    """Cambia una pregunta de una propuesta por otra nueva."""
    drafts.regenerate(draft_id, index)


@shared_task(name='apps.ai.tasks.run_review')
def run_review(review_id):
    """Pide a la IA la calificación sugerida de una entrega."""
    reviews.run(review_id)
