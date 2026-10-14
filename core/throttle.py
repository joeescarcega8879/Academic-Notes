"""Límite de intentos sencillo sobre la caché de Django (Redis en producción, memoria en local).

Sirve para frenar el abuso de las pantallas públicas (registro, «olvidé mi contraseña», reenvío de
correos) sin depender de otro paquete. Cuenta por ventana fija: el primer intento abre la ventana y
los siguientes la consumen hasta ``limit``.
"""

import hashlib

from django.core.cache import cache


def client_ip(request):
    """Dirección de quien llama. Detrás de un proxy hay que configurarlo para que ``REMOTE_ADDR`` sea la real."""
    return request.META.get('REMOTE_ADDR', '')


def allow(scope, identity, *, limit, window):
    """Cuenta un intento de ``identity`` en ``scope``; ``False`` si ya superó ``limit`` en ``window`` segundos."""
    digest = hashlib.sha256(str(identity).strip().lower().encode()).hexdigest()[:32]
    key = f'throttle:{scope}:{digest}'
    cache.add(key, 0, window)
    try:
        attempts = cache.incr(key)
    except ValueError:  # la clave venció entre add() e incr()
        cache.set(key, 1, window)
        attempts = 1
    return attempts <= limit
