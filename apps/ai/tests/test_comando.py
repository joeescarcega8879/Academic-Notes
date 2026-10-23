"""El comando ``ai_probar``: comprueba el proveedor configurado sin pasar por planes ni cuotas."""

from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ai.providers import fake


@pytest.fixture(autouse=True)
def limpio():
    fake.PROVIDER.reset()
    yield
    fake.PROVIDER.reset()


def correr(*args):
    salida = StringIO()
    call_command('ai_probar', *args, stdout=salida)
    return salida.getvalue()


def test_muestra_el_proveedor_el_modelo_y_la_respuesta():
    fake.PROVIDER.responses = [{'respuesta': 'Sirve para planear.'}]
    texto = correr('¿Para qué sirve un temario?')
    assert 'Proveedor: fake' in texto and 'modelo: fake-1' in texto and 'Sirve para planear.' in texto
    assert fake.PROVIDER.calls[0]['prompt'] == '¿Para qué sirve un temario?'


def test_tiene_un_texto_por_omision():
    correr()
    assert fake.PROVIDER.calls[0]['prompt']


def test_un_proveedor_mal_configurado_da_un_error_claro(settings):
    settings.AI_PROVIDER, settings.GEMINI_API_KEY = 'gemini', ''
    with pytest.raises(CommandError, match='Configuración'):
        correr()


def test_si_el_proveedor_falla_lo_dice():
    fake.PROVIDER.error = 'sin conexión'
    with pytest.raises(CommandError, match='Falló'):
        correr()
