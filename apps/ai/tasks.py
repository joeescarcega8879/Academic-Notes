from celery import shared_task

from . import drafts


@shared_task(name='apps.ai.tasks.run_draft')
def run_draft(draft_id):
    """Genera una propuesta de IA. Es lenta y puede fallar: corre fuera de la petición del docente."""
    drafts.run(draft_id)


@shared_task(name='apps.ai.tasks.regenerate_item')
def regenerate_item(draft_id, index):
    """Cambia una pregunta de una propuesta por otra nueva."""
    drafts.regenerate(draft_id, index)
