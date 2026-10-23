"""Proveedor de mentira: sin red, sin costo y determinista. Es el de desarrollo y el de las pruebas."""

from .base import AIProvider, AIResult, ProviderError


def sample_from_schema(schema):
    """Un valor que cumple un esquema JSON sencillo (objeto, lista, texto, número, booleano, enum)."""
    if 'enum' in schema:
        return schema['enum'][0]
    kind = schema.get('type')
    if kind == 'object':
        return {name: sample_from_schema(sub) for name, sub in schema.get('properties', {}).items()}
    if kind == 'array':
        return [sample_from_schema(schema.get('items', {}))]
    if kind == 'integer':
        return schema.get('minimum', 1)
    if kind == 'number':
        return float(schema.get('minimum', 1))
    if kind == 'boolean':
        return True
    return 'texto de prueba'


class FakeProvider(AIProvider):
    """Responde lo que se le programe (``responses``, una por llamada) o, si no hay nada, un ejemplo del esquema.

    Guarda en ``calls`` lo que recibe: las pruebas de privacidad lo revisan para comprobar que no se fuga ningún dato.
    """

    name = 'fake'
    model = 'fake-1'
    tier = 'fake'

    def __init__(self):
        self.reset()

    def reset(self):
        self.responses = []
        self.calls = []
        self.error = None

    def generate_json(self, *, prompt, schema, system=''):
        self.calls.append({'prompt': prompt, 'schema': schema, 'system': system})
        if self.error is not None:
            raise self.error if isinstance(self.error, ProviderError) else ProviderError(str(self.error))
        data = self.responses.pop(0) if self.responses else sample_from_schema(schema)
        return AIResult(data=data, tokens_in=max(1, len(prompt + system) // 4), tokens_out=max(1, len(str(data)) // 4), model=self.model)


PROVIDER = FakeProvider()
