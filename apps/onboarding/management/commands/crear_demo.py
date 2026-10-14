"""Crea (o recrea) una escuela de ejemplo para probar la aplicación a mano."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.onboarding import demo


class Command(BaseCommand):
    help = (
        'Crea una escuela de ejemplo (docente, tres grupos, alumnos, actividades, notas, quizzes y mensajes) '
        'para probar la aplicación. Usa cuentas @demo.test con una contraseña conocida: no es para producción.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Borra la escuela de ejemplo que ya exista y la crea de nuevo.')
        parser.add_argument('--delete', action='store_true', help='Solo borra la escuela de ejemplo y sus cuentas.')
        parser.add_argument('--force', action='store_true', help='Permite correrlo con DEBUG apagado (por ejemplo, en un servidor de pruebas).')

    def handle(self, *args, **options):
        if not settings.DEBUG and not options['force']:
            raise CommandError(
                'Este comando crea cuentas con una contraseña conocida y solo corre con DEBUG activo. '
                'Si de verdad es un servidor de pruebas, agrega --force.'
            )
        try:
            if options['delete'] or options['reset']:
                removed = demo.delete_demo()
                self.stdout.write('Escuela de ejemplo borrada.' if removed else 'No había escuela de ejemplo.')
                if options['delete']:
                    return
            summary = demo.build_demo()
        except demo.DemoExists:
            raise CommandError('Ya existe una escuela de ejemplo. Usa --reset para borrarla y crearla de nuevo.') from None
        except ValidationError as error:
            raise CommandError(' '.join(error.messages)) from None
        self.report(summary)

    def report(self, summary):
        write, ok = self.stdout.write, self.style.SUCCESS
        write(ok('Escuela de ejemplo lista.'))
        write('')
        write(f'  Escuela:  {summary.organization.name}')
        write('  Cuentas (todas con la contraseña indicada):')
        write(f'    Docente   {demo.TEACHER_EMAIL}')
        for student, email in zip(summary.students, demo.STUDENT_EMAILS):
            write(f'    Alumno    {email}   ({student})')
        write(f'    Contraseña: {demo.PASSWORD}')
        write('')
        write('  Grupos:')
        for course in summary.courses:
            estado = ' [archivado]' if course.is_archived else f'  código de invitación {course.invite_code}'
            write(f'    {course.name} ({course.code}), {course.enrollments.count()} alumnos{estado}')
        counts = summary.counts
        write('')
        write(
            f'  {counts["students"]} alumnos, {counts["activities"]} actividades, {counts["grades"]} calificaciones, '
            f'{counts["submissions"]} entregas, {counts["attempts"]} intentos de quiz, {counts["questions"]} preguntas en el banco.'
        )
        write('')
        write('  Para entrar: python manage.py runserver  y abre http://localhost:8000/login/')
