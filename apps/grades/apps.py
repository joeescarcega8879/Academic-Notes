from django.apps import AppConfig


class GradesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.grades'

    def ready(self):
        from . import signals  # noqa: F401
