"""El borrador de una rúbrica tal como lo manda el editor, su validación y las plantillas de arranque.

Un borrador es un diccionario simple:

    {'name': ..., 'description': ..., 'levels': ['Excelente', ...],
     'criteria': [{'name': ..., 'cells': [{'points': ..., 'text': ...}, ...]}, ...]}

Al leer el formulario, ``points`` queda como el texto escrito (para volver a mostrarlo si hay errores); ``validate``
lo convierte en ``Decimal`` y devuelve el borrador limpio que guarda ``library``.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MIN_LEVELS, MAX_LEVELS = 2, 6
MIN_CRITERIA, MAX_CRITERIA = 1, 12
MAX_POINTS = Decimal(1000)
NAME_MAX, DESCRIPTION_MAX, LEVEL_NAME_MAX, CRITERION_MAX, TEXT_MAX = 150, 200, 60, 150, 1000
# Tope de lo que se lee del formulario, por encima de lo permitido, para que un envío manipulado no genere miles de filas.
READ_LIMIT = 30

DEFAULT_LEVELS = ['Excelente', 'Bueno', 'Regular', 'Insuficiente']
DEFAULT_POINTS = [4, 3, 2, 0]


def _count(raw, default):
    try:
        return max(0, min(int(raw), READ_LIMIT))
    except (TypeError, ValueError):
        return default


def parse_points(raw):
    """``Decimal`` de 0 a 1000 con 2 decimales a partir de lo escrito (acepta coma), o None si no es válido."""
    try:
        value = Decimal(str(raw).strip().replace(',', '.'))
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > MAX_POINTS:
        return None
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def parse_post(post):
    """Lee el formulario del editor: ``levels`` y ``criteria`` dicen cuántos hay; el resto se nombra por posición."""
    levels_count, criteria_count = _count(post.get('levels'), 0), _count(post.get('criteria'), 0)
    return {
        'name': post.get('name', '').strip(), 'description': post.get('description', '').strip(),
        'levels': [post.get(f'level_{j}', '').strip() for j in range(levels_count)],
        'criteria': [
            {
                'name': post.get(f'c{i}_name', '').strip(),
                'cells': [
                    {'points': post.get(f'c{i}_l{j}_points', '').strip(), 'text': post.get(f'c{i}_l{j}_text', '').strip()}
                    for j in range(levels_count)
                ],
            }
            for i in range(criteria_count)
        ],
    }


def validate(draft):
    """``(errores, borrador limpio)``: los errores son mensajes para el docente; el limpio trae ``Decimal`` en los puntos."""
    errors = []
    name = draft['name']
    if not name:
        errors.append('Ponle un nombre a la rúbrica.')
    elif len(name) > NAME_MAX:
        errors.append(f'El nombre no puede pasar de {NAME_MAX} caracteres.')
    if len(draft['description']) > DESCRIPTION_MAX:
        errors.append(f'«Para qué sirve» no puede pasar de {DESCRIPTION_MAX} caracteres.')

    levels, criteria = draft['levels'], draft['criteria']
    if not MIN_LEVELS <= len(levels) <= MAX_LEVELS:
        errors.append(f'La rúbrica necesita entre {MIN_LEVELS} y {MAX_LEVELS} niveles.')
    if not MIN_CRITERIA <= len(criteria) <= MAX_CRITERIA:
        errors.append(f'La rúbrica necesita entre {MIN_CRITERIA} y {MAX_CRITERIA} criterios.')
    if errors and (len(levels) > MAX_LEVELS or len(criteria) > MAX_CRITERIA or not levels or not criteria):
        return errors, None

    if any(not level or len(level) > LEVEL_NAME_MAX for level in levels):
        errors.append(f'Cada nivel necesita un nombre de hasta {LEVEL_NAME_MAX} caracteres.')
    elif len({level.casefold() for level in levels}) != len(levels):
        errors.append('Los nombres de los niveles no se pueden repetir.')

    clean_criteria = []
    for number, criterion in enumerate(criteria, start=1):
        label = f'«{criterion["name"]}»' if criterion['name'] else f'El criterio {number}'
        if not criterion['name']:
            errors.append(f'El criterio {number} necesita un nombre.')
        elif len(criterion['name']) > CRITERION_MAX:
            errors.append(f'El nombre del criterio {number} no puede pasar de {CRITERION_MAX} caracteres.')
        cells = []
        for level, cell in zip(levels, criterion['cells'], strict=True):
            points = parse_points(cell['points'])
            if points is None:
                errors.append(f'{label}, nivel «{level}»: los puntos deben ser un número de 0 a {MAX_POINTS:g}.')
            if len(cell['text']) > TEXT_MAX:
                errors.append(f'{label}, nivel «{level}»: la descripción no puede pasar de {TEXT_MAX} caracteres.')
            cells.append({'points': points, 'text': cell['text']})
        if all(cell['points'] is not None for cell in cells) and max(cell['points'] for cell in cells) <= 0:
            errors.append(f'{label} debe dar puntos en al menos un nivel.')
        clean_criteria.append({'name': criterion['name'], 'cells': cells})

    if errors:
        return errors, None
    return [], {'name': name, 'description': draft['description'], 'levels': levels, 'criteria': clean_criteria}


def draft_from_version(version, *, name=None, description=None):
    """El borrador (con los puntos como texto) de una versión guardada, para volver a editarla o duplicarla."""
    criteria = list(version.criteria.prefetch_related('levels'))
    levels = [level.name for level in criteria[0].levels.all()] if criteria else list(DEFAULT_LEVELS)
    return {
        'name': version.rubric.name if name is None else name,
        'description': version.rubric.description if description is None else description,
        'levels': levels,
        'criteria': [
            {
                'name': criterion.name,
                'cells': [{'points': f'{level.points:g}', 'text': level.description} for level in criterion.levels.all()],
            }
            for criterion in criteria
        ],
    }


def blank_draft(criteria=3):
    return {
        'name': '', 'description': '', 'levels': list(DEFAULT_LEVELS),
        'criteria': [
            {'name': '', 'cells': [{'points': str(points), 'text': ''} for points in DEFAULT_POINTS]} for _ in range(criteria)
        ],
    }


def _criterion(name, points, texts):
    return {'name': name, 'cells': [{'points': str(p), 'text': t} for p, t in zip(points, texts, strict=True)]}


# Plantillas de arranque: criterios y descripciones de ejemplo que el docente edita a su gusto.
TEMPLATES = {
    'ensayo': {
        'title': 'Ensayo',
        'draft': {
            'name': 'Ensayo argumentativo', 'description': 'Ensayos de 2 a 3 cuartillas', 'levels': list(DEFAULT_LEVELS),
            'criteria': [
                _criterion('Tesis', [4, 3, 2, 0], [
                    'Plantea una postura clara, original y la sostiene en todo el texto.', 'Postura clara, con algo de repetición.',
                    'La postura existe pero es vaga o cambia.', 'No hay una postura identificable.']),
                _criterion('Argumentos', [8, 6, 3, 0], [
                    'Tres o más argumentos sólidos con datos y ejemplos.', 'Dos argumentos sólidos y uno débil.',
                    'Argumentos generales, sin datos.', 'Sin argumentos, o sin relación con la tesis.']),
                _criterion('Redacción y ortografía', [4, 3, 2, 0], [
                    'Sin errores; párrafos bien enlazados.', 'Hasta 5 errores que no impiden entender.',
                    'Entre 6 y 12 errores o párrafos desordenados.', 'Más de 12 errores o ideas confusas.']),
                _criterion('Fuentes y formato', [4, 3, 2, 0], [
                    '3 o más fuentes citadas en formato correcto.', '2 fuentes citadas, formato casi correcto.',
                    '1 fuente o citas incompletas.', 'Sin fuentes.']),
            ],
        },
    },
    'exposicion': {
        'title': 'Exposición oral',
        'draft': {
            'name': 'Exposición oral', 'description': 'Presentaciones frente al grupo', 'levels': list(DEFAULT_LEVELS),
            'criteria': [
                _criterion('Dominio del tema', [4, 3, 2, 0], [
                    'Explica con seguridad y responde preguntas con precisión.', 'Explica bien; duda en alguna pregunta.',
                    'Lee gran parte del material; respuestas incompletas.', 'No muestra dominio del tema.']),
                _criterion('Claridad y voz', [4, 3, 2, 0], [
                    'Voz clara, ritmo adecuado, mira al grupo.', 'Se entiende casi todo; algo de lectura.',
                    'Volumen bajo o ritmo irregular.', 'No se le entiende.']),
                _criterion('Apoyo visual y tiempo', [4, 3, 2, 0], [
                    'Material claro y atractivo; respeta el tiempo.', 'Material correcto; se pasa o falta poco tiempo.',
                    'Material confuso o con exceso de texto.', 'Sin material o fuera de tiempo por mucho.']),
            ],
        },
    },
    'proyecto': {
        'title': 'Proyecto en equipo',
        'draft': {
            'name': 'Proyecto en equipo', 'description': 'Proyectos con producto final', 'levels': list(DEFAULT_LEVELS),
            'criteria': [
                _criterion('Investigación', [6, 4, 2, 0], [
                    'Fuentes variadas y confiables, bien usadas.', 'Fuentes suficientes con algún uso débil.',
                    'Pocas fuentes o poco confiables.', 'Sin investigación visible.']),
                _criterion('Producto final', [8, 6, 3, 0], [
                    'Cumple todo lo pedido con calidad destacada.', 'Cumple lo pedido con detalles por mejorar.',
                    'Cumple solo una parte de lo pedido.', 'No se entregó o no corresponde.']),
                _criterion('Trabajo en equipo', [4, 3, 2, 0], [
                    'Todos participaron y se nota la coordinación.', 'Participación pareja con algo de desorden.',
                    'Una o dos personas hicieron casi todo.', 'No hubo trabajo en equipo.']),
                _criterion('Presentación', [4, 3, 2, 0], [
                    'Clara, ordenada y dentro del tiempo.', 'Clara con pequeños tropiezos.',
                    'Desordenada o incompleta.', 'No se presentó.']),
                _criterion('Evidencias del proceso', [4, 3, 2, 0], [
                    'Bitácora o avances completos y a tiempo.', 'Avances casi completos.',
                    'Avances parciales o tardíos.', 'Sin evidencias.']),
            ],
        },
    },
    'portafolio': {
        'title': 'Cuaderno o portafolio',
        'draft': {
            'name': 'Cuaderno o portafolio', 'description': 'Revisión periódica del cuaderno', 'levels': list(DEFAULT_LEVELS),
            'criteria': [
                _criterion('Completo', [4, 3, 2, 0], [
                    'Todas las tareas y apuntes están.', 'Falta una parte pequeña.', 'Falta cerca de la mitad.', 'Falta casi todo.']),
                _criterion('Orden y limpieza', [3, 2, 1, 0], [
                    'Ordenado, con fechas y títulos.', 'Casi siempre ordenado.', 'Desordenado en varias partes.', 'Sin orden.']),
                _criterion('Reflexión', [3, 2, 1, 0], [
                    'Explica con sus palabras lo aprendido.', 'Explica lo aprendido con apoyo del libro.',
                    'Copia más de lo que explica.', 'No hay reflexión.']),
            ],
        },
    },
}


def template_draft(key):
    """Copia del borrador de una plantilla (para que editarlo no toque la plantilla), o None si no existe."""
    template = TEMPLATES.get(key)
    if template is None:
        return None
    draft = template['draft']
    return {
        'name': draft['name'], 'description': draft['description'], 'levels': list(draft['levels']),
        'criteria': [{'name': c['name'], 'cells': [dict(cell) for cell in c['cells']]} for c in draft['criteria']],
    }
