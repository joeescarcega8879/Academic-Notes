"""Gemini (Google), con la biblioteca oficial ``google-genai``.

La clave vive solo en el servidor (``GEMINI_API_KEY``). Con una clave gratuita Google puede usar lo que recibe para
mejorar sus productos, así que el servicio nunca le manda datos de alumnos (ver ``GEMINI_KEY_TIER``).
"""

from django.conf import settings

from .base import AIProvider, AIResult, ProviderError, loads_lenient

RETRYABLE_CODES = {408, 429, 500, 502, 503, 504}


class GeminiProvider(AIProvider):
    name = 'gemini'

    def __init__(self, *, api_key, model, tier='free', timeout=60):
        if not api_key:
            raise ProviderError('Falta GEMINI_API_KEY en el servidor.', configuration=True)
        if not model:
            raise ProviderError('Falta GEMINI_MODEL en el servidor.', configuration=True)
        from google import genai
        from google.genai import types

        self.model = model
        self.tier = tier
        self._types = types
        self._client = genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout * 1000)))

    @classmethod
    def from_settings(cls):
        return cls(
            api_key=settings.GEMINI_API_KEY, model=settings.GEMINI_MODEL, tier=settings.GEMINI_KEY_TIER,
            timeout=settings.AI_TIMEOUT_SECONDS,
        )

    def generate_json(self, *, prompt, schema, system=''):
        from google.genai import errors

        config = self._types.GenerateContentConfig(
            system_instruction=system or None, response_mime_type='application/json', response_json_schema=schema,
            temperature=0.4,
        )
        try:
            response = self._client.models.generate_content(model=self.model, contents=prompt, config=config)
        except errors.APIError as error:
            # Solo el código y el estado: el mensaje del servidor podría citar la solicitud.
            code = getattr(error, 'code', None)
            raise ProviderError(f'Gemini respondió {code} {getattr(error, "status", "") or ""}'.strip(), retryable=code in RETRYABLE_CODES) from None
        except Exception as error:  # red caída, tiempo agotado, etc.
            raise ProviderError(f'No se pudo contactar a Gemini ({type(error).__name__}).', retryable=True) from None
        text = (response.text or '').strip()
        if not text:
            raise ProviderError('Gemini no devolvió contenido (posible bloqueo de seguridad).')
        try:
            data = loads_lenient(text)
        except ValueError:
            raise ProviderError('Gemini devolvió algo que no es JSON válido.') from None
        usage = response.usage_metadata
        return AIResult(
            data=data,
            tokens_in=(getattr(usage, 'prompt_token_count', 0) or 0) if usage else 0,
            tokens_out=((getattr(usage, 'candidates_token_count', 0) or 0) + (getattr(usage, 'thoughts_token_count', 0) or 0)) if usage else 0,
            model=self.model,
        )
