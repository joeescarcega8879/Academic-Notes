"""Operaciones sobre las semanas de un temario: agregar, mover, dividir, unir, quitar y detectar desde el texto.

Los números de semana (``position``) son siempre 1..n sin huecos; cada operación los deja así.
"""

import datetime
import re

from django.db import transaction
from django.db.models import F

from ..models import SyllabusWeek

MAX_WEEKS = 60
TITLE_MAX = SyllabusWeek._meta.get_field('title').max_length


class WeekError(Exception):
    """Una operación sobre semanas que no se puede hacer; el mensaje es para el docente."""


def renumber(syllabus):
    weeks = list(syllabus.weeks.order_by('position', 'pk'))
    changed = []
    for index, week in enumerate(weeks, start=1):
        if week.position != index:
            week.position = index
            changed.append(week)
    if changed:
        SyllabusWeek.objects.bulk_update(changed, ['position'])


@transaction.atomic
def add_week(syllabus, title='', topics='', objectives=''):
    if syllabus.weeks.count() >= MAX_WEEKS:
        raise WeekError(f'Un temario puede tener hasta {MAX_WEEKS} semanas.')
    return syllabus.weeks.create(position=syllabus.weeks.count() + 1, title=title[:TITLE_MAX], topics=topics, objectives=objectives)


@transaction.atomic
def move_week(week, delta):
    """Sube (``delta=-1``) o baja (``+1``) una semana intercambiándola con su vecina. En los extremos no hace nada."""
    neighbour = week.syllabus.weeks.filter(position=week.position + delta).first()
    if neighbour is None:
        return week
    week.position, neighbour.position = neighbour.position, week.position
    SyllabusWeek.objects.bulk_update([week, neighbour], ['position'])
    return week


@transaction.atomic
def split_week(week):
    """Reparte los temas de una semana en dos: la primera mitad se queda y el resto pasa a una semana nueva a continuación."""
    syllabus = week.syllabus
    topics = week.topic_list
    if len(topics) < 2:
        raise WeekError('Para dividir una semana necesita al menos dos temas (uno por línea).')
    if syllabus.weeks.count() >= MAX_WEEKS:
        raise WeekError(f'Un temario puede tener hasta {MAX_WEEKS} semanas.')
    keep = (len(topics) + 1) // 2
    syllabus.weeks.filter(position__gt=week.position).update(position=F('position') + 1)
    new = syllabus.weeks.create(
        position=week.position + 1, title=f'{week.title} (continuación)'[:TITLE_MAX] if week.title else '',
        topics='\n'.join(topics[keep:]),
    )
    week.topics = '\n'.join(topics[:keep])
    week.save(update_fields=['topics'])
    return new


@transaction.atomic
def merge_with_next(week):
    """Junta una semana con la siguiente: concatena temas y objetivos y quita la siguiente."""
    following = week.syllabus.weeks.filter(position__gt=week.position).order_by('position').first()
    if following is None:
        raise WeekError('Esta es la última semana: no hay otra con la que unirla.')
    week.topics = '\n'.join(part for part in (week.topics.strip(), following.topics.strip()) if part)
    week.objectives = '\n'.join(part for part in (week.objectives.strip(), following.objectives.strip()) if part)
    week.title = week.title or following.title
    week.no_class = week.no_class and following.no_class
    week.save(update_fields=['topics', 'objectives', 'title', 'no_class'])
    following.delete()
    renumber(week.syllabus)
    return week


@transaction.atomic
def delete_week(week):
    syllabus = week.syllabus
    week.delete()
    renumber(syllabus)


# ── Fechas ────────────────────────────────────────────────────────────

def week_dates(syllabus, week):
    """(lunes, viernes) de la semana, o ``None`` si el temario no tiene fecha de inicio."""
    if syllabus.start_date is None:
        return None
    monday = syllabus.start_date - datetime.timedelta(days=syllabus.start_date.weekday())
    monday += datetime.timedelta(weeks=week.position - 1)
    return monday, monday + datetime.timedelta(days=4)


def current_week(syllabus, today):
    """La semana que contiene ``today`` (el fin de semana cuenta para la semana que termina), o ``None``."""
    if syllabus.start_date is None:
        return None
    for week in syllabus.weeks.all():
        monday, _ = week_dates(syllabus, week)
        if monday <= today <= monday + datetime.timedelta(days=6):
            return week
    return None


# ── Detectar semanas en el texto ──────────────────────────────────────

HEADING = re.compile(r'^\s*semana\s+(\d{1,3})\s*[:.\-–—)]?\s*(.*)$', re.IGNORECASE)
LABEL = re.compile(r'^\s*(temas?|contenidos?|objetivos?|prop[oó]sitos?)\s*[:.\-–—]\s*(.*)$', re.IGNORECASE)
BULLET = re.compile(r'^\s*(?:[-•*·▪●○]|\d{1,2}[.)])\s+')


def _items(text):
    """Un fragmento «a, b; c.» pasa a ['a', 'b', 'c']."""
    return [part.strip(' .') for part in re.split(r'[;,]', text) if part.strip(' .')]


def detect_weeks(text):
    """Propone semanas a partir de encabezados «Semana N» en el texto: ``[{'title', 'topics', 'objectives'}, …]``.

    Es una ayuda sin IA: si el temario no trae ese formato devuelve ``[]`` y el docente arma las semanas a mano.
    El texto anterior al primer encabezado (portada, datos del curso) se ignora.
    """
    blocks, current = [], None
    for line in text.splitlines():
        heading = HEADING.match(line)
        if heading:
            current = {'title': heading.group(2).strip(' .:'), 'topics': [], 'objectives': [], 'mode': 'topics'}
            blocks.append(current)
            continue
        if current is None or not line.strip():
            continue
        label = LABEL.match(line)
        if label:
            current['mode'] = 'objectives' if label.group(1).lower().startswith(('obj', 'prop')) else 'topics'
            rest = label.group(2).strip()
            if rest:
                current[current['mode']].extend(_items(rest) if current['mode'] == 'topics' else [rest])
            continue
        item = BULLET.sub('', line).strip()
        if item:
            current[current['mode']].append(item)
    return [
        {'title': block['title'][:TITLE_MAX], 'topics': '\n'.join(block['topics']), 'objectives': '\n'.join(block['objectives'])}
        for block in blocks[:MAX_WEEKS]
    ]


@transaction.atomic
def replace_weeks(syllabus, proposals):
    """Cambia todas las semanas por ``proposals``. Las actividades que apuntaban a una semana quedan sin semana."""
    syllabus.weeks.all().delete()
    for index, proposal in enumerate(proposals[:MAX_WEEKS], start=1):
        syllabus.weeks.create(position=index, **proposal)
