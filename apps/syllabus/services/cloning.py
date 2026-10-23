"""Copiar el temario de un grupo al duplicarlo para un nuevo ciclo (sin fechas, como las actividades)."""

from django.core.files.base import ContentFile
from django.db import transaction

from ..models import Syllabus


def clone_syllabus(source, clone):
    """Copia el temario de ``source`` (un grupo) a ``clone``: texto, archivo y semanas, sin fecha de inicio.

    Es idempotente: si ``clone`` ya tiene temario lo devuelve tal cual. Así la pueden llamar, en cualquier orden,
    el aviso de duplicado del grupo y el de cada actividad copiada. Devuelve el temario de ``clone`` o ``None``.
    """
    origin = Syllabus.objects.filter(course=source).first()
    if origin is None:
        return None
    existing = Syllabus.objects.filter(course=clone).first()
    if existing is not None:
        return existing
    copy = Syllabus(course=clone, text=origin.text, original_name=origin.original_name, status=origin.status)
    if origin.file:
        with origin.file.open('rb') as handle:
            copy.file.save(origin.original_name or 'temario', ContentFile(handle.read()), save=False)
    copy.save()
    for week in origin.weeks.all():
        copy.weeks.create(
            position=week.position, title=week.title, topics=week.topics, objectives=week.objectives,
            assessment=week.assessment, no_class=week.no_class,
        )
    if copy.status == Syllabus.Status.PENDING:
        from ..tasks import extract_syllabus_text

        transaction.on_commit(lambda: extract_syllabus_text.delay(copy.pk))
    return copy
