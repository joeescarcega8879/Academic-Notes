"""Configuración de Celery para GradeLink.

El worker se levanta con: ``celery -A core worker -l info``
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.local")

app = Celery("gradelink")

# Toda la configuración de Celery vive en los settings de Django con el
# prefijo CELERY_, para tener un solo lugar de verdad.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Descubre automáticamente los `tasks.py` de cada app instalada.
app.autodiscover_tasks()
