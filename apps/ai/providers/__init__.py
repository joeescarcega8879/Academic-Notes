"""Proveedores de IA intercambiables. El resto del código solo usa ``get_provider()`` y ``apps.ai.services``."""

from django.conf import settings

from .base import AIProvider, AIResult, ProviderError  # noqa: F401


def get_provider():
    """El proveedor que indica ``settings.AI_PROVIDER`` (``fake`` por omisión: sin red y sin costo)."""
    name = settings.AI_PROVIDER
    if name == 'fake':
        from .fake import PROVIDER

        return PROVIDER
    if name == 'gemini':
        from .gemini import GeminiProvider

        return GeminiProvider.from_settings()
    raise ProviderError(f'Proveedor de IA desconocido: {name!r}', configuration=True)
