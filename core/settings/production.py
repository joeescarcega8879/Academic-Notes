"""Entorno de producción (Railway/Render primero, AWS cuando la carga lo pida)."""

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False

# ── Validaciones: en producción no se arranca con valores de desarrollo ──
if SECRET_KEY.startswith("django-insecure"):  # noqa: F405
    raise ImproperlyConfigured("Define DJANGO_SECRET_KEY con un valor real en producción.")

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Define DJANGO_ALLOWED_HOSTS en producción.")

if not env("DATABASE_URL", default=""):
    raise ImproperlyConfigured("Define DATABASE_URL en producción.")

CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])

# ── Endurecimiento HTTP ───────────────────────────────────────────────
SECURE_SSL_REDIRECT = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ── Archivos estáticos: WhiteNoise sirve lo que collectstatic recopila ──
MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")  # noqa: F405

STATIC_ROOT = BASE_DIR / "staticfiles"  # noqa: F405

STORAGES = {
    # Fase 1: cuando existan entregas de alumnos, el `default` pasa a S3/MinIO.
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# ── Correo real ───────────────────────────────────────────────────────
EMAIL_BACKEND = env("DJANGO_EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")

# ── Celery síncrono solo en desarrollo ────────────────────────────────
CELERY_TASK_ALWAYS_EAGER = False

# ── Observabilidad ────────────────────────────────────────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
        send_default_pii=False,
    )
