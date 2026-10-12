"""Entorno de desarrollo local: ``runserver`` directo o vía Docker Compose."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)

ALLOWED_HOSTS = env.list(
    "DJANGO_ALLOWED_HOSTS",
    default=["localhost", "127.0.0.1", "0.0.0.0", "[::1]"],
)

CSRF_TRUSTED_ORIGINS = env.list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    default=["http://localhost:8000", "http://127.0.0.1:8000"],
)

# En local los correos se imprimen en consola en vez de enviarse.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Sin un worker de Celery corriendo, las tareas se ejecutan en el proceso.
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=True)

INTERNAL_IPS = ["127.0.0.1"]