"""Los proveedores: el de mentira y Gemini (con el cliente de Google simulado, sin red)."""

from types import SimpleNamespace

import pytest
from google.genai import errors

from apps.ai.providers import ProviderError, fake, get_provider
from apps.ai.providers.gemini import GeminiProvider


class TestProveedorDeMentira:
    def test_es_el_proveedor_por_omision(self, settings):
        assert settings.AI_PROVIDER == 'fake' and get_provider() is fake.PROVIDER

    def test_un_proveedor_desconocido_se_rechaza(self, settings):
        settings.AI_PROVIDER = 'inventado'
        with pytest.raises(ProviderError) as error:
            get_provider()
        assert error.value.configuration

    def test_sin_respuestas_programadas_inventa_un_ejemplo_del_esquema(self):
        esquema = {
            'type': 'object',
            'properties': {
                'titulo': {'type': 'string'}, 'puntos': {'type': 'integer'}, 'nota': {'type': 'number'}, 'ok': {'type': 'boolean'},
                'tipo': {'enum': ['quiz', 'tarea']}, 'preguntas': {'type': 'array', 'items': {'type': 'object', 'properties': {'texto': {'type': 'string'}}}},
            },
        }
        assert fake.sample_from_schema(esquema) == {
            'titulo': 'texto de prueba', 'puntos': 1, 'nota': 1.0, 'ok': True, 'tipo': 'quiz', 'preguntas': [{'texto': 'texto de prueba'}],
        }

    def test_usa_las_respuestas_programadas_en_orden(self):
        proveedor = fake.FakeProvider()
        proveedor.responses = [{'a': 1}, {'a': 2}]
        assert [proveedor.generate_json(prompt='x', schema={}).data for _ in range(2)] == [{'a': 1}, {'a': 2}]

    def test_recuerda_lo_que_recibe_y_puede_fallar_a_pedido(self):
        proveedor = fake.FakeProvider()
        proveedor.error = 'se cayó'
        with pytest.raises(ProviderError):
            proveedor.generate_json(prompt='hola', schema={})
        assert proveedor.calls[0]['prompt'] == 'hola'


class FakeModels:
    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.llamadas = respuesta, error, []

    def generate_content(self, **kwargs):
        self.llamadas.append(kwargs)
        if self.error:
            raise self.error
        return self.respuesta


@pytest.fixture
def gemini(monkeypatch):
    """Un GeminiProvider cuyo cliente de Google es de mentira; devuelve (proveedor, modelos simulados)."""

    def armar(respuesta=None, error=None):
        proveedor = GeminiProvider(api_key='clave-de-prueba', model='modelo-de-prueba', tier='free', timeout=5)
        proveedor._client = SimpleNamespace(models=FakeModels(respuesta, error))
        return proveedor, proveedor._client.models

    return armar


def respuesta(texto, entrada=10, salida=20, pensamiento=0):
    return SimpleNamespace(
        text=texto, usage_metadata=SimpleNamespace(prompt_token_count=entrada, candidates_token_count=salida, thoughts_token_count=pensamiento),
    )


class TestGemini:
    def test_faltan_la_clave_o_el_modelo(self):
        with pytest.raises(ProviderError) as sin_clave:
            GeminiProvider(api_key='', model='m')
        with pytest.raises(ProviderError) as sin_modelo:
            GeminiProvider(api_key='k', model='')
        assert sin_clave.value.configuration and sin_modelo.value.configuration

    def test_se_arma_desde_la_configuracion(self, settings):
        settings.AI_PROVIDER, settings.GEMINI_API_KEY, settings.GEMINI_MODEL = 'gemini', 'clave', 'modelo-x'
        settings.GEMINI_KEY_TIER = 'paid'
        proveedor = get_provider()
        assert (proveedor.name, proveedor.model, proveedor.tier) == ('gemini', 'modelo-x', 'paid')

    def test_pide_json_con_el_esquema_y_las_instrucciones(self, gemini):
        proveedor, modelos = gemini(respuesta('{"titulo": "Álgebra"}', 7, 11, 3))
        resultado = proveedor.generate_json(prompt='Genera un título', schema={'type': 'object'}, system='Sé breve')
        llamada = modelos.llamadas[0]
        assert llamada['model'] == 'modelo-de-prueba' and llamada['contents'] == 'Genera un título'
        config = llamada['config']
        assert config.response_mime_type == 'application/json' and config.response_json_schema == {'type': 'object'}
        assert config.system_instruction == 'Sé breve'
        assert resultado.data == {'titulo': 'Álgebra'} and resultado.tokens_in == 7 and resultado.tokens_out == 14  # salida + razonamiento
        assert resultado.model == 'modelo-de-prueba'

    @pytest.mark.parametrize('codigo, reintentar', [(429, True), (503, True), (500, True), (400, False), (401, False), (403, False)])
    def test_los_errores_de_la_api_dicen_si_conviene_reintentar(self, gemini, codigo, reintentar):
        clase = errors.ClientError if codigo < 500 else errors.ServerError
        proveedor, _ = gemini(error=clase(codigo, {'error': {'code': codigo, 'message': 'SECRETO: texto del alumno', 'status': 'X'}}, None))
        with pytest.raises(ProviderError) as error:
            proveedor.generate_json(prompt='p', schema={})
        assert error.value.retryable is reintentar
        assert str(codigo) in str(error.value) and 'SECRETO' not in str(error.value)  # nunca el mensaje del servidor

    def test_un_fallo_de_red_se_puede_reintentar(self, gemini):
        proveedor, _ = gemini(error=TimeoutError('se agotó el tiempo'))
        with pytest.raises(ProviderError) as error:
            proveedor.generate_json(prompt='p', schema={})
        assert error.value.retryable and 'TimeoutError' in str(error.value)

    @pytest.mark.parametrize('texto', [None, '', '   '])
    def test_una_respuesta_vacia_es_un_error(self, gemini, texto):
        proveedor, _ = gemini(respuesta(texto))
        with pytest.raises(ProviderError):
            proveedor.generate_json(prompt='p', schema={})

    def test_algo_que_no_es_json_es_un_error(self, gemini):
        proveedor, _ = gemini(respuesta('esto no es json'))
        with pytest.raises(ProviderError) as error:
            proveedor.generate_json(prompt='p', schema={})
        assert 'JSON' in str(error.value) and 'esto no es' not in str(error.value)

    def test_sin_conteo_de_tokens_no_falla(self, gemini):
        proveedor, _ = gemini(SimpleNamespace(text='{"a": 1}', usage_metadata=None))
        resultado = proveedor.generate_json(prompt='p', schema={})
        assert (resultado.tokens_in, resultado.tokens_out) == (0, 0)
