"""Entorno para la suite de pruebas (pytest-django y CI).

Busca ser rápido y determinista: hashing barato de contraseñas, correo en
memoria y tareas síncronas. La base de datos es la que indique DATABASE_URL
(PostgreSQL en CI, SQLite en local).
"""

import tempfile
from pathlib import Path

from .base import *  # noqa: F401,F403

DEBUG = False

# Hashes rápidos: las pruebas no necesitan seguridad, sí velocidad.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Los archivos subidos en pruebas no deben ensuciar el `media/` del proyecto.
MEDIA_ROOT = Path(tempfile.gettempdir()) / "gradelink-test-media"

# Silencia el ruido de las migraciones durante los tests.
LOGGING["root"]["level"] = "ERROR"  # noqa: F405
