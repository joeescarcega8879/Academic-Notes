from celery import shared_task

from .services import batch


@shared_task(name='apps.batches.tasks.read_batch_file')
def read_batch_file(batch_file_id):
    """Lee un PDF del lote (portada escaneada y cuerpo, con OCR). Puede tardar: corre fuera de la petición del docente."""
    batch.process_file(batch_file_id)
