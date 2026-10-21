from celery import shared_task

from .services.extraction import extract_syllabus


@shared_task(name='apps.syllabus.tasks.extract_syllabus_text')
def extract_syllabus_text(syllabus_id):
    """Saca el texto del archivo de un temario. Se encola al subirlo: puede tardar con un PDF grande."""
    return extract_syllabus(syllabus_id)
