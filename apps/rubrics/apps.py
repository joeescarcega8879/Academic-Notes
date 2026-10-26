from django.apps import AppConfig


class RubricsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.rubrics'

    def ready(self):
        from . import signals  # noqa: F401
