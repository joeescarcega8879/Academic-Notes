import pytest

from apps.ai import drafts


@pytest.fixture(autouse=True)
def sin_esperas_entre_reintentos(monkeypatch):
    """Los reintentos ante fallos pasajeros esperan segundos de verdad: en las pruebas no."""
    monkeypatch.setattr(drafts, 'RETRY_DELAYS', (0, 0))
