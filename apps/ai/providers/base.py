"""El contrato de un proveedor de IA."""

import json
import re
from dataclasses import dataclass

# Una barra invertida que no forma una secuencia de escape válida de JSON (la «\(» de una fórmula LaTeX sin duplicar).
_JSON_ESCAPE_OR_STRAY = re.compile(r'(\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))|\\')


def loads_lenient(text):
    r"""``json.loads``; si falla por barras sueltas (``\(``, ``\alpha``), las duplica y vuelve a intentar. Lanza ``ValueError``."""
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(_JSON_ESCAPE_OR_STRAY.sub(lambda match: match.group(1) or '\\\\', text))


@dataclass(frozen=True)
class AIResult:
    data: object          # el JSON ya interpretado (dict o lista)
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ''


class ProviderError(Exception):
    """Falló el proveedor. El texto es para el registro: no debe llevar nada de lo que se envió.

    ``retryable``: conviene reintentar (límite de uso, servidor ocupado). ``configuration``: falta o está mal
    configurado el proveedor en el servidor (no es culpa de la solicitud).
    """

    def __init__(self, message, *, retryable=False, configuration=False):
        super().__init__(message)
        self.retryable = retryable
        self.configuration = configuration


class AIProvider:
    """Interfaz: «dame un JSON que cumpla este esquema»."""

    name = ''
    model = ''
    #: ``free`` (el proveedor puede usar lo que recibe para mejorar sus productos), ``paid`` o ``fake`` (sin red).
    tier = 'paid'

    def generate_json(self, *, prompt, schema, system=''):
        raise NotImplementedError
