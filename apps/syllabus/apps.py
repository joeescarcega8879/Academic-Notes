from django.apps import AppConfig


class SyllabusConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.syllabus'

    def ready(self):
        from . import signals  # noqa: F401
