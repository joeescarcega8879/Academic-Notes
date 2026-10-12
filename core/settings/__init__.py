"""Configuración de Django dividida por entorno.

- ``core.settings.base``       → común a todos los entornos.
- ``core.settings.local``      → desarrollo (lo que usa ``manage.py`` por defecto).
- ``core.settings.test``       → suite de pruebas y CI.
- ``core.settings.production`` → producción.
"""
