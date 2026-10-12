"""Renombra la app ``subjects`` a ``courses`` en una base que ya existía.

Django no renombra apps: las tablas conservan el prefijo ``subjects_`` y
``django_migrations`` sigue registrando las migraciones bajo ``subjects``, así que
``migrate`` intentaría crear de nuevo las tablas. Este comando corrige ambas cosas
y debe ejecutarse **una vez, antes de ``migrate``**. En una base nueva no hace nada.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

TABLAS = {'subjects_subject': 'courses_subject', 'subjects_enrollment': 'courses_enrollment'}


class Command(BaseCommand):
    help = 'Renombra la app subjects a courses (tablas, migraciones aplicadas y tipos de contenido).'

    def handle(self, *args, **options):
        existentes = set(connection.introspection.table_names())
        if not existentes & set(TABLAS):
            self.stdout.write('No hay tablas "subjects_*": nada que hacer.')
            return
        choques = existentes & set(TABLAS.values())
        if choques:
            raise CommandError('Ya existen tablas de destino: %s. Revisa la base a mano.' % ', '.join(sorted(choques)))

        quote = connection.ops.quote_name
        with transaction.atomic(), connection.cursor() as cursor:
            for origen, destino in TABLAS.items():
                if origen in existentes:
                    cursor.execute('ALTER TABLE %s RENAME TO %s' % (quote(origen), quote(destino)))
            cursor.execute("UPDATE django_migrations SET app = 'courses' WHERE app = 'subjects'")
            migraciones = cursor.rowcount
            if 'django_content_type' in existentes:
                cursor.execute("UPDATE django_content_type SET app_label = 'courses' WHERE app_label = 'subjects'")

        self.stdout.write(self.style.SUCCESS(
            'Listo: tablas renombradas y %d migraciones reasignadas a "courses". Ahora ejecuta migrate.' % migraciones
        ))
