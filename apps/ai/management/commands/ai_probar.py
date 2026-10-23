import time

from django.core.management.base import BaseCommand, CommandError

from apps.ai.providers import ProviderError, get_provider

SCHEMA = {
    'type': 'object',
    'properties': {'respuesta': {'type': 'string'}},
    'required': ['respuesta'],
}


class Command(BaseCommand):
    help = (
        'Prueba el proveedor de IA configurado (AI_PROVIDER) con un texto corto, sin pasar por planes ni cuotas. '
        'Úsalo con datos inventados: con una clave gratuita Google puede usar lo que envías.'
    )

    def add_arguments(self, parser):
        parser.add_argument('texto', nargs='?', default='Responde con una frase corta en español: ¿para qué sirve un temario?')

    def handle(self, *args, **options):
        try:
            provider = get_provider()
        except ProviderError as error:
            raise CommandError(f'Configuración: {error}') from error
        self.stdout.write(f'Proveedor: {provider.name} | modelo: {provider.model or "-"} | clave: {provider.tier}')
        started = time.monotonic()
        try:
            result = provider.generate_json(prompt=options['texto'], schema=SCHEMA)
        except ProviderError as error:
            raise CommandError(f'Falló: {error}') from error
        self.stdout.write(f'Respuesta ({int((time.monotonic() - started) * 1000)} ms, {result.tokens_in} tokens de entrada, {result.tokens_out} de salida):')
        self.stdout.write(str(result.data))
