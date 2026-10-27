"""Entrega de un proyecto por equipos: cualquier integrante la envía y todo el equipo queda con la misma.

Cada integrante tiene su propia fila de ``Submission`` (así la libreta, el panel del alumno y la rúbrica siguen
viendo «una entrega por alumno»), pero todas comparten texto, enlace y el mismo archivo en el almacenamiento.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.grades.models import Grade, Submission
from apps.grades.services.submissions import clean_filename

from .teams import members_of, team_of


def submit_team(activity, student, *, text='', link='', file=None, now, late):
    """Registra o actualiza la entrega del equipo de ``student``; devuelve la fila de ``student``.

    Las reglas de la ventana (abierta, tardía, cerrada) y de inscripción ya las revisó ``submit``.
    """
    team = team_of(activity, student)
    if team is None:
        raise ValidationError('Tu docente todavía no te asignó a un equipo: aún no puedes entregar.')
    members = members_of(team)
    if Grade.objects.filter(activity=activity, student__in=members).exists():
        raise ValidationError('La entrega de tu equipo ya fue calificada y no se puede cambiar.')

    with transaction.atomic():
        rows = {s.student_id: s for s in Submission.objects.select_for_update().filter(activity=activity, student__in=members)}
        previous = max(rows.values(), key=lambda s: (s.submitted_at, s.pk), default=None)
        old_names = {row.file.name for row in rows.values() if row.file}
        kept_name = previous.file.name if previous is not None and previous.file else ''
        kept_original = previous.original_name if kept_name else ''

        saved = []
        for member in members:
            row = rows.get(member.pk) or Submission(activity=activity, student=member)
            row.team, row.submitted_by = team, student
            row.text, row.link = text.strip(), link.strip()
            row.submitted_at, row.is_late = now, late
            if file is not None:
                if saved:
                    row.file.name = saved[0].file.name  # el mismo archivo en el almacenamiento: no se copia
                else:
                    row.file = file
                row.original_name = clean_filename(file.name)
            elif kept_name:
                row.file.name, row.original_name = kept_name, kept_original
            row.full_clean()
            row.save()
            saved.append(row)

    storage = Submission._meta.get_field('file').storage
    for name in old_names - {row.file.name for row in saved if row.file}:
        storage.delete(name)  # ya con la entrega confirmada en la base: el archivo anterior no hace falta
    return next(row for row in saved if row.student_id == student.pk)
