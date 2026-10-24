"""Límite de intentos sencillo sobre la caché de Django (Redis en producción, memoria en local).

Sirve para frenar el abuso de las pantallas públicas (registro, «olvidé mi contraseña», reenvío de
correos, inicio de sesión) sin depender de otro paquete. Cuenta por ventana fija: el primer intento abre
la ventana y los siguientes la consumen hasta ``limit``.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    """Dirección de quien llama.

    Sin proxy (``TRUSTED_PROXY_COUNT = 0``) es ``REMOTE_ADDR``. Con ``n`` proxies de confianza delante, cada uno
    agrega a ``X-Forwarded-For`` la dirección de quien le habló, así que la del cliente real es la ``n``-ésima
    contando desde la derecha: lo que el cliente escriba a la izquierda no cuenta (no se puede falsear).
    """
    remote = request.META.get('REMOTE_ADDR', '')
    proxies = getattr(settings, 'TRUSTED_PROXY_COUNT', 0)
    if proxies <= 0:
        return remote
    forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
    return forwarded[-proxies] if len(forwarded) >= proxies else remote


def _key(scope, identity):
    digest = hashlib.sha256(str(identity).strip().lower().encode()).hexdigest()[:32]
    return f'throttle:{scope}:{digest}'


def hit(scope, identity, *, window):
    """Anota un intento de ``identity`` en ``scope`` y devuelve cuántos van en la ventana de ``window`` segundos."""
    key = _key(scope, identity)
    cache.add(key, 0, window)
    try:
        return cache.incr(key)
    except ValueError:  # la clave venció entre add() e incr()
        cache.set(key, 1, window)
        return 1


def exceeded(scope, identity, *, limit):
    """``True`` si ``identity`` ya acumuló ``limit`` o más intentos en ``scope`` (no anota nada)."""
    return (cache.get(_key(scope, identity)) or 0) >= limit


def reset(scope, identity):
    """Olvida los intentos de ``identity`` en ``scope`` (p. ej. tras un inicio de sesión correcto)."""
    cache.delete(_key(scope, identity))


def allow(scope, identity, *, limit, window):
    """Cuenta un intento de ``identity`` en ``scope``; ``False`` si ya superó ``limit`` en ``window`` segundos."""
    return hit(scope, identity, window=window) <= limit
