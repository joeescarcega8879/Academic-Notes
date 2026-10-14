"""Utilidades pequeñas compartidas por todas las apps."""

from django.utils.http import url_has_allowed_host_and_scheme

# Un identificador de la base de datos cabe en un entero de 64 bits: 19 dígitos como máximo.
MAX_ID_DIGITS = 18


def parse_id(value):
    """Convierte texto de la petición en un identificador entero, o ``None`` si no lo es.

    ``str.isdigit()`` no basta para decidir si ``int()`` funcionará: acepta dígitos como "²" y cadenas de
    miles de cifras, y ``int()`` falla con ``ValueError`` (un error 500) en ambos casos. Aquí solo se
    aceptan de 1 a 18 dígitos ASCII.
    """
    if isinstance(value, str) and value.isascii() and value.isdigit() and len(value) <= MAX_ID_DIGITS:
        return int(value)
    return None


def safe_next_url(request):
    """Destino pedido con ``next`` (en la URL o en el formulario) si es una ruta de este mismo sitio; si no, ''.

    Evita que ``next`` sirva para mandar al usuario a otro sitio (redirección abierta).
    """
    candidate = request.POST.get('next') or request.GET.get('next') or ''
    allowed = url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    )
    return candidate if candidate and allowed else ''


def csv_safe(value):
    """Texto seguro para una celda de CSV: Excel ejecuta como fórmula lo que empiece con =, +, - o @.

    Un alumno (o un docente) puede escribir cualquier cosa en su nombre o en un comentario; al abrir el archivo
    esa celda no debe correr nada. Se antepone una comilla, que Excel muestra pero no interpreta.
    """
    text = str(value)
    return "'" + text if text[:1] in ('=', '+', '-', '@', '\t', '\r') else text
