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
    following.activities.update(syllabus_week=week)  # las actividades de la semana que desaparece pasan a la unida
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

HEADING = re.compile(r'^\s*semana\s+(\d{1,3})\s*[:.\-–—|)]?\s*(.*)$', re.IGNORECASE)
# Etiquetas de sección, solas en su línea («Objetivo de la semana») o con contenido («Temas: a, b»).
LABEL = re.compile(
    r'^\s*(temas?|contenidos?|temario|objetivos?(?:\s+de\s+(?:la\s+)?semana)?|prop[oó]sitos?)\s*(?:[:.\-–—]\s*(.*))?$', re.IGNORECASE,
)
SESSION = re.compile(r'^\s*sesi[oó]n\s+(\d{1,2})\s*[:.\-–—]?\s*(.*)$', re.IGNORECASE)
TABLE_HEAD = re.compile(r'^\s*sesi[oó]n\s*$', re.IGNORECASE)  # encabezado de la tabla «Sesión | Contenidos»
# Secciones de la semana que no son temas ni objetivos: se saltan (siguen en el texto extraído).
SKIPPED = re.compile(
    r'^\s*(actividades(?:\s+de\s+aprendizaje)?|entregables?(?:\s*/\s*evaluaci[oó]n)?|evaluaci[oó]n|tareas?|recursos|materiales)\s*:?\s*$',
    re.IGNORECASE,
)
# Secciones del documento que vienen después de la última semana: cortan la semana en curso.
CLOSING = re.compile(
    r'^\s*(evaluaci[oó]n\s+(?:sugerida|del\s+curso)|criterios\s+de\s+evaluaci[oó]n|bibliograf[ií]a.*|referencias.*|fuentes.*|anexos?)\s*:?\s*$',
    re.IGNORECASE,
)
PAGE = re.compile(r'^\s*p[aá]gina\s+\d+(\s+de\s+\d+)?\s*$', re.IGNORECASE)
BULLET = re.compile(r'^\s*(?:[-•*·▪●○\x7f\uf0b7\uf0a7]|\d{1,2}[.)])\s+')
SENTENCE_END = ('.', '!', '?', ':', ';')
MAX_TITLE_LINE = 120
WRAPPED_MIN = 60  # una línea así de larga sin punto final seguramente continúa en la siguiente


def _items(text):
    """Un fragmento «a, b; c.» pasa a ['a', 'b', 'c']."""
    return [part.strip(' .') for part in re.split(r'[;,]', text) if part.strip(' .')]


def _drop_running_headers(lines):
    """Quita «Página N» y el encabezado que se repite justo antes de cada uno (el título del documento en cada hoja)."""
    headers = set()
    for index, line in enumerate(lines):
        if PAGE.match(line) and index > 0 and lines[index - 1].strip():
            before = lines[index - 1].strip()
            if sum(1 for other in lines if other.strip() == before) >= 2:
                headers.add(before)
    return [line for line in lines if not PAGE.match(line) and line.strip() not in headers]


def _new_block(title):
    return {'title': title, 'pending_title': not title, 'topics': [], 'objectives': [], 'mode': 'topics', 'in_session': False, 'open': False, 'gap': False}


def _add(block, text, bulleted):
    """Agrega una línea a la sección en curso; une las líneas que el PDF cortó a media frase."""
    items = block[block['mode']]
    joins = bool(items) and not bulleted and (
        block['in_session'] or block['open']
        or (not block['gap'] and not items[-1].rstrip().endswith(SENTENCE_END)
            and (text[:1].islower() or len(items[-1]) >= WRAPPED_MIN))
    )
    if joins:
        items[-1] += ' ' + text
    else:
        items.append(text)
    block['open'] = block['gap'] = False


def detect_weeks(text):
    """Propone semanas a partir de encabezados «Semana N» en el texto: ``[{'title', 'topics', 'objectives'}, …]``.

    Es una ayuda sin IA que entiende estos formatos: ``Semana 1: Título`` y ``SEMANA 1`` con el título en la línea
    siguiente; ``Temas:`` y ``Objetivos:`` con o sin dos puntos; y sesiones («Sesión 1» + contenido), una por tema.
    Se salta las actividades y entregables de la semana, los encabezados de página y lo que sigue a la última
    semana (evaluación, bibliografía). Si el temario no trae encabezados «Semana N» devuelve ``[]`` y el docente
    arma las semanas a mano. Lo anterior al primer encabezado (portada, datos del curso) se ignora.
    """
    blocks, current = [], None
    for raw in _drop_running_headers(text.splitlines()):
        line = raw.strip()
        if not line:
            if current is not None:
                current['gap'] = True
            continue
        if CLOSING.match(line):
            current = None
            continue
        heading = HEADING.match(line)
        if heading and len(heading.group(2)) <= MAX_TITLE_LINE:
            current = _new_block(heading.group(2).strip(' .:|'))
            blocks.append(current)
            continue
        if current is None or TABLE_HEAD.match(line):
            continue
        if SKIPPED.match(line):
            current.update(mode='skip', in_session=False, pending_title=False)
            continue
        label = LABEL.match(line)
        if label:
            current.update(mode='objectives' if label.group(1).lower().startswith(('obj', 'prop')) else 'topics',
                           in_session=False, pending_title=False, open=False)
            rest = (label.group(2) or '').strip()
            if rest:
                current[current['mode']].extend(_items(rest) if current['mode'] == 'topics' else [rest])
            continue
        session = SESSION.match(line)
        if session:
            current.update(mode='topics', in_session=True, pending_title=False, open=not session.group(2))
            current['topics'].append(f'Sesión {session.group(1)}:' + (f' {session.group(2).strip()}' if session.group(2) else ''))
            continue
        bulleted = bool(BULLET.match(line))
        content = BULLET.sub('', line).strip()
        if current['mode'] == 'skip' or not content:
            continue
        if current['pending_title'] and not bulleted:
            current['pending_title'] = False
            if len(content) <= MAX_TITLE_LINE:
                current['title'] = content.strip(' .:')
                continue
        current['pending_title'] = False
        _add(current, content, bulleted)
    return [
        {'title': block['title'][:TITLE_MAX], 'topics': '\n'.join(block['topics']), 'objectives': '\n'.join(block['objectives'])}
        for block in blocks[:MAX_WEEKS]
    ]


@transaction.atomic
def delete_all_weeks(syllabus):
    """Quita todas las semanas de una vez (sus actividades quedan sin semana). Devuelve cuántas había."""
    count = syllabus.weeks.count()
    syllabus.weeks.all().delete()
    return count


@transaction.atomic
def replace_weeks(syllabus, proposals):
    """Cambia todas las semanas por ``proposals``. Las actividades que apuntaban a una semana quedan sin semana."""
    syllabus.weeks.all().delete()
    for index, proposal in enumerate(proposals[:MAX_WEEKS], start=1):
        syllabus.weeks.create(position=index, **proposal)
