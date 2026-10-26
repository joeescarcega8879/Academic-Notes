"""Escuela de ejemplo para probar la aplicación a mano (``manage.py crear_demo``).

Arma, por los mismos servicios que usa la aplicación, un docente con tres grupos (uno con el esquema por defecto,
uno con dos periodos y uno archivado de un ciclo anterior), alumnos, actividades de todos los tipos, entregas
tardías, quizzes con intentos, calificaciones con aprobados, riesgos y faltantes, y mensajes. Todo sale de una
semilla fija: dos corridas dan los mismos alumnos y las mismas notas.

Las cuentas de ejemplo usan el dominio ``@demo.test`` y una contraseña conocida: **no es para producción**.
"""

import datetime
import random
from dataclasses import dataclass, field

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.courses.models import AcademicYear, Course, Enrollment, Student
from apps.courses.services.courses import archive_course
from apps.courses.services.invitations import redeem_invitation
from apps.courses.services.roster import add_student, enroll_existing
from apps.grades.models import Activity, EvaluationCriterion, EvaluationPeriod, Grade, GradeHistory, Submission
from apps.grades.services.gradebook import grade_activity
from apps.grades.services.schemes import ensure_scheme
from apps.grades.services.submissions import submit
from apps.messaging.models import Conversation, Message
from apps.organizations.models import Membership, Organization
from apps.quizzes.models import Choice, Question, QuizAttempt
from apps.quizzes.services import attempts as quiz_attempts
from apps.quizzes.services.bank import save_question
from apps.quizzes.services.builder import add_questions
from apps.rubrics.models import Rubric
from apps.rubrics.services import editor as rubric_editor
from apps.rubrics.services import library as rubric_library

from .services import register_student, register_teacher

DEMO_DOMAIN = '@demo.test'
TEACHER_EMAIL = f'docente{DEMO_DOMAIN}'
STUDENT_EMAILS = [f'alumno{n}{DEMO_DOMAIN}' for n in (1, 2, 3)]
PASSWORD = 'Demo-Clave-2026'
SCHOOL = 'Secundaria Técnica Demo'
SEED = 2026

FIRST_NAMES = [
    'Ana', 'Luis', 'María', 'Carlos', 'Sofía', 'Diego', 'Valeria', 'Jorge', 'Camila', 'Miguel', 'Daniela', 'Andrés', 'Fernanda',
    'Ricardo', 'Paola', 'Emilio', 'Regina', 'Hugo', 'Ximena', 'Iván', 'Renata', 'Óscar', 'Mariana', 'Pablo', 'Lucía', 'Adrián',
    'Julieta', 'Rodrigo', 'Natalia', 'Sebastián', 'Abril', 'Tomás', 'Itzel', 'Mateo', 'Frida', 'Bruno',
]
LAST_NAMES = [
    'García', 'Hernández', 'López', 'Martínez', 'González', 'Pérez', 'Rodríguez', 'Sánchez', 'Ramírez', 'Cruz', 'Flores', 'Gómez',
    'Morales', 'Vázquez', 'Jiménez', 'Reyes', 'Díaz', 'Torres', 'Gutiérrez', 'Ruiz', 'Mendoza', 'Aguilar', 'Ortiz', 'Castillo',
    'Núñez', 'Romero', 'Herrera', 'Medina', 'Rojas', 'Salazar', 'Ávila', 'Guerrero', 'Pineda', 'Cortés', 'Soto', 'Vargas',
]

BANK = [
    ('mc', '¿Cuánto es 3/4 + 1/4?', [('1', True), ('4/8', False), ('3/16', False), ('1/2', False)], 'Fracciones'),
    ('mc', '¿Cuál fracción es equivalente a 2/3?', [('4/6', True), ('3/2', False), ('2/6', False), ('6/4', False)], 'Fracciones'),
    ('mc', '¿Cuánto es 1/2 de 18?', [('9', True), ('8', False), ('36', False), ('6', False)], 'Fracciones'),
    ('tf', '2/5 es mayor que 1/2.', False, 'Fracciones'),
    ('mc', '¿Cuál es el resultado de 5/6 − 1/3?', [('1/2', True), ('4/3', False), ('4/6 de 1/3', False), ('1/6', False)], 'Fracciones'),
    ('mc', 'Resuelve: x + 7 = 15', [('x = 8', True), ('x = 22', False), ('x = 7', False), ('x = −8', False)], 'Ecuaciones'),
    ('mc', 'Resuelve: 3x = 24', [('x = 8', True), ('x = 21', False), ('x = 72', False), ('x = 12', False)], 'Ecuaciones'),
    ('tf', 'Si 2x + 1 = 9, entonces x = 4.', True, 'Ecuaciones'),
    ('mc', 'Resuelve: 5x − 10 = 20', [('x = 6', True), ('x = 2', False), ('x = 30', False), ('x = 5', False)], 'Ecuaciones'),
    ('mc', '¿Cuál es el área de un rectángulo de 6 por 4?', [('24', True), ('20', False), ('10', False), ('48', False)], 'Geometría'),
    ('tf', 'Un triángulo puede tener dos ángulos rectos.', False, 'Geometría'),
    ('mc', '¿Cuántos grados suman los ángulos interiores de un triángulo?', [('180', True), ('90', False), ('360', False), ('270', False)], 'Geometría'),
]

# Banco de Español II y preguntas generales (sin grupo, sirven en todos los grupos).
BANK_SPANISH = [
    ('mc', '¿Cuál de estas palabras lleva tilde?', [('canción', True), ('camion', False), ('lapiz', False), ('arbol', False)], 'Ortografía'),
    ('mc', '¿Qué tipo de texto cuenta una historia con personajes y un final?', [('Narrativo', True), ('Instructivo', False), ('Informativo', False), ('Publicitario', False)], 'Lectura'),
    ('tf', 'El sujeto de una oración siempre aparece al inicio.', False, 'Gramática'),
    ('mc', '¿Cuál es un sinónimo de «rápido»?', [('Veloz', True), ('Lento', False), ('Pesado', False), ('Quieto', False)], 'Vocabulario'),
    ('tf', 'Un párrafo debe tener una idea principal.', True, 'Redacción'),
    ('mc', '¿Qué signo cierra una pregunta en español?', [('?', True), ('!', False), ('.', False), (',', False)], 'Ortografía'),
]
BANK_GENERAL = [
    ('tf', 'Repasar un poco cada día ayuda más que estudiar todo la noche anterior.', True, 'Hábitos de estudio'),
    ('mc', '¿Qué conviene hacer antes de entregar una tarea?', [('Revisarla', True), ('Copiarla', False), ('Dejarla para después', False), ('Borrar el nombre', False)], 'Hábitos de estudio'),
]

CONVERSATIONS = [
    ('¿Maestra, puedo entregar la Tarea 2 mañana? Tuve un problema con mi internet.', 'student'),
    ('Claro, te la recibo con la penalización normal. Que no se repita, por favor.', 'teacher'),
    ('Muchas gracias maestra, la entrego mañana temprano.', 'student'),
]


@dataclass
class DemoSummary:
    organization: object
    teacher: object
    students: list
    courses: list
    counts: dict = field(default_factory=dict)


class DemoExists(Exception):
    """Ya hay una escuela de ejemplo: hay que borrarla antes (``--reset``)."""


def demo_exists():
    return get_user_model().objects.filter(email=TEACHER_EMAIL).exists()


# ── Armado ────────────────────────────────────────────────────────────

class Builder:
    def __init__(self, seed=SEED, now=None):
        self.rng = random.Random(seed)
        self.now = now or timezone.now()
        self.number = 0
        self.names = set()
        self.ability = {}  # id de alumno → nivel de 0 a 10
        self.counts = {'grades': 0, 'submissions': 0, 'attempts': 0, 'activities': 0}

    # personas
    def person(self):
        while True:
            name = (self.rng.choice(FIRST_NAMES), f'{self.rng.choice(LAST_NAMES)} {self.rng.choice(LAST_NAMES)}')
            if name not in self.names:
                self.names.add(name)
                return name

    def new_student(self, course, *, level=None):
        first, last = self.person()
        self.number += 1
        student = add_student(
            course, student_number=f'{self.number:05d}', first_name=first, last_name=last,
            email=f'{first}.{last.split()[0]}{self.number}@alumnos.demo.test'.lower().replace(' ', '').replace('á', 'a')
            .replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n'),
        )
        self.ability[student.pk] = level if level is not None else self.draw_level()
        return student

    def draw_level(self):
        return min(max(self.rng.gauss(8.0, 0.9), 6.6), 9.9)

    # notas
    def score(self, student, top):
        raw = self.rng.gauss(self.ability[student.pk], 1.0) / 10 * top
        raw = min(max(raw, 0), top)
        return round(raw * 2) / 2 if top <= 20 else float(round(raw))

    def activity(self, course, title, type_, *, top=10, criterion=None, published=True, days=None, due=None, **extra):
        date = (self.now + datetime.timedelta(days=days)).date() if days is not None else None
        activity = Activity(
            course=course, title=title, type=type_, max_score=top, published=published, date=date,
            due_at=self.now + datetime.timedelta(days=due) if due is not None else None, **extra,
        )
        if criterion is not None:
            activity.criterion = criterion
        activity.save()
        self.counts['activities'] += 1
        return activity

    def grade(self, activity, student, teacher, score=None, feedback=''):
        value = self.score(student, activity.max_score) if score is None else score
        grade_activity(activity, student, score=value, by=teacher, feedback=feedback)
        self.counts['grades'] += 1

    def grade_all(self, activity, students, teacher, *, skip=0.0, skip_students=()):
        for student in students:
            if student.pk in skip_students or self.rng.random() < skip:
                continue
            self.grade(activity, student, teacher)

    def homework(self, activity, students, teacher, *, skip_students=(), late_share=0.25):
        """Entregas (algunas tardías) y su calificación. Quien está en ``skip_students`` no entrega ni se califica."""
        for student in students:
            if student.pk in skip_students:
                continue
            late = self.rng.random() < late_share and activity.allow_late
            when = activity.due_at + datetime.timedelta(days=self.rng.randint(1, 2)) if late else (
                activity.due_at - datetime.timedelta(days=self.rng.randint(1, 4))
            )
            link = f'https://drive.ejemplo.mx/{activity.pk}/{student.pk}' if self.rng.random() < 0.3 else ''
            submit(activity, student, text='' if link else f'Entrega de {student.first_name}.', link=link, now=when)
            self.counts['submissions'] += 1
            self.grade(activity, student, teacher, feedback='Buen trabajo.' if self.ability[student.pk] > 8.5 else '')

    # quizzes
    def quiz_attempts(self, quiz, students):
        for student in students:
            for number in range(self.rng.choice([1, 1, 2])):
                started = self.now - datetime.timedelta(days=3, minutes=-number * 30)
                attempt = quiz_attempts.start_attempt(quiz, student, now=started)
                chance = min(max(self.ability[student.pk] / 10 + 0.05 * number, 0.2), 0.97)
                picks = {}
                for question in quiz.questions.prefetch_related('choices'):
                    choices = list(question.choices.all())
                    right = next(c for c in choices if c.is_correct)
                    picks[question.pk] = (right if self.rng.random() < chance else self.rng.choice(choices)).pk
                quiz_attempts.submit_attempt(attempt, picks, now=started + datetime.timedelta(minutes=9))
                self.counts['attempts'] += 1


def _make_bank(teacher, organization, rows, course=None):
    """Crea las preguntas de ``rows`` en el banco de ``course`` (sin grupo: generales)."""
    questions = []
    for kind, text, options, topic in rows:
        if kind == 'tf':
            questions.append(save_question(
                organization=organization, author=teacher, kind=Question.Kind.TRUE_FALSE, text=text, points=1,
                true_is_correct=options, topic=topic, explanation='Revisa el tema en tu cuaderno.', course=course,
            ))
        else:
            questions.append(save_question(
                organization=organization, author=teacher, kind=Question.Kind.MULTIPLE_CHOICE, text=text, points=1,
                choices=options, topic=topic, course=course,
            ))
    return questions


def _make_rubric(teacher, organization, template):
    """Rúbrica de ejemplo a partir de una plantilla del editor."""
    _, draft = rubric_editor.validate(rubric_editor.template_draft(template))
    return rubric_library.create_rubric(organization=organization, author=teacher, draft=draft)


@transaction.atomic
def build_demo(*, seed=SEED, now=None):
    """Crea la escuela de ejemplo y devuelve un ``DemoSummary``. Lanza ``DemoExists`` si ya hay una."""
    if demo_exists():
        raise DemoExists
    b = Builder(seed, now)
    today = b.now.date()

    teacher = register_teacher(
        first_name='Laura', last_name='Mendoza Ríos', email=TEACHER_EMAIL, password=PASSWORD, school_name=SCHOOL,
        today=today, notify=False,
    )
    teacher.email_verified_at = b.now
    teacher.save(update_fields=['email_verified_at'])
    organization = Membership.objects.get(user=teacher).organization
    # La escuela de ejemplo usa el plan Pro: así se ve todo (sin topes, quizzes con tiempo, boletas sin marca).
    organization.plan = Organization.Plan.TEACHER
    organization.save(update_fields=['plan'])
    # Las rúbricas de ejemplo: los proyectos se califican siempre con una.
    project_rubric = _make_rubric(teacher, organization, 'proyecto')
    essay_rubric = _make_rubric(teacher, organization, 'ensayo')
    current = AcademicYear.current_for(organization)
    previous = AcademicYear.objects.create(
        organization=organization, name=f'{current.start_date.year - 1}–{current.start_date.year}',
        start_date=current.start_date.replace(year=current.start_date.year - 1),
        end_date=current.end_date.replace(year=current.end_date.year - 1),
    )

    # ── Matemáticas II: esquema por defecto ──
    maths = Course.objects.create(
        name='Matemáticas II', code='MAT2-A', professor=teacher, organization=organization, academic_year=current,
        schedule='Lun, Mié y Vie 8:00–9:00', color='#2563eb', description='Fracciones, ecuaciones y geometría.',
    )
    bank = _make_bank(teacher, organization, BANK, maths)
    general = _make_bank(teacher, organization, BANK_GENERAL)
    levels = [4.2, 4.8, 5.1] + [6.1, 6.4, 6.7, 6.9] + [None] * 21
    maths_students = [b.new_student(maths, level=lvl) for lvl in levels]
    weak = {s.pk for s in maths_students[:3]}

    exam1 = b.activity(maths, 'Examen parcial 1', Activity.Type.EXAM, top=10, days=-40)
    b.grade_all(exam1, maths_students, teacher)
    exam2 = b.activity(maths, 'Examen parcial 2', Activity.Type.EXAM, top=100, days=-12, weight=2)
    b.grade_all(exam2, maths_students, teacher, skip=0.05)
    hw1 = b.activity(maths, 'Tarea 1: Fracciones', Activity.Type.HOMEWORK, days=-35, due=-34, allow_late=True, late_penalty=10)
    b.homework(hw1, maths_students, teacher)
    hw2 = b.activity(maths, 'Tarea 2: Ecuaciones', Activity.Type.HOMEWORK, days=-20, due=-19, allow_late=True, late_penalty=10)
    b.homework(hw2, maths_students, teacher, skip_students=weak)
    hw3 = b.activity(maths, 'Tarea 3: Problemas', Activity.Type.HOMEWORK, days=-8, due=-7, allow_late=False)
    b.homework(hw3, maths_students, teacher, skip_students=weak | {s.pk for s in maths_students[3:5]}, late_share=0)
    b.activity(maths, 'Tarea 4: Geometría', Activity.Type.HOMEWORK, days=2, due=5, allow_late=True, late_penalty=20)
    b.activity(maths, 'Proyecto final: Maqueta', Activity.Type.PROJECT, top=100, days=10, due=21, weight=3, rubric_version=project_rubric.current_version)
    b.activity(maths, 'Proyecto extra (borrador)', Activity.Type.PROJECT, top=100, published=False)
    part = b.activity(maths, 'Participación de octubre', Activity.Type.PARTICIPATION, days=-3)
    b.grade_all(part, maths_students, teacher, skip=0.1)

    quiz_activity = b.activity(maths, 'Quiz: Fracciones', Activity.Type.QUIZ, top=5, published=False, days=-25)
    quiz = quiz_activity.quiz
    quiz.attempts_allowed, quiz.time_limit_minutes = 2, 15
    quiz.save()
    add_questions(quiz, bank[:5])
    quiz_activity.published = True
    quiz_activity.save()
    b.quiz_attempts(quiz, [s for s in maths_students if s.pk not in weak or b.rng.random() < 0.5])
    draft_quiz = b.activity(maths, 'Quiz: Ecuaciones (borrador)', Activity.Type.QUIZ, top=4, published=False)
    add_questions(draft_quiz.quiz, bank[5:9])

    # ── Español II: dos periodos ──
    spanish = Course.objects.create(
        name='Español II', code='ESP2-B', professor=teacher, organization=organization, academic_year=current,
        schedule='Mar y Jue 10:00–11:00', color='#7c3aed', description='Lectura, redacción y comunicación.',
    )
    spanish_bank = _make_bank(teacher, organization, BANK_SPANISH, spanish)
    scheme = ensure_scheme(spanish)
    first = scheme.periods.get()
    first.name, first.weight = 'Primer parcial', 50
    first.save()
    first.criteria.all().delete()
    reading = EvaluationCriterion.objects.create(period=first, name='Lecturas y tareas', weight=40, default_type=Activity.Type.HOMEWORK, position=0)
    exam_a = EvaluationCriterion.objects.create(period=first, name='Examen 1', weight=60, default_type=Activity.Type.EXAM, position=1)
    second = EvaluationPeriod.objects.create(scheme=scheme, name='Segundo parcial', weight=50, position=1)
    writing = EvaluationCriterion.objects.create(period=second, name='Redacción', weight=50, default_type=Activity.Type.PROJECT, position=0)
    exam_b = EvaluationCriterion.objects.create(period=second, name='Examen 2', weight=50, default_type=Activity.Type.EXAM, position=1)

    spanish_students = []
    for student in maths_students[7:19]:  # alumnos que cursan ambas materias
        enroll_existing(spanish, student)
        spanish_students.append(student)
    spanish_students += [b.new_student(spanish) for _ in range(12)]
    for activity_args in (
        ('Lectura 1: El principito', Activity.Type.HOMEWORK, reading, -45, -44),
        ('Lectura 2: Cuentos de Rulfo', Activity.Type.HOMEWORK, reading, -38, -37),
    ):
        activity = b.activity(spanish, activity_args[0], activity_args[1], criterion=activity_args[2], days=activity_args[3], due=activity_args[4], late_penalty=10)
        b.homework(activity, spanish_students, teacher)
    e1 = b.activity(spanish, 'Examen del primer parcial', Activity.Type.EXAM, criterion=exam_a, days=-30)
    b.grade_all(e1, spanish_students, teacher)
    essay = b.activity(
        spanish, 'Ensayo argumentativo', Activity.Type.PROJECT, top=100, criterion=writing, days=-10, due=-9, late_penalty=15,
        rubric_version=essay_rubric.current_version,
    )
    b.homework(essay, spanish_students, teacher, late_share=0.4)
    b.activity(spanish, 'Examen del segundo parcial', Activity.Type.EXAM, criterion=exam_b, days=14)
    b.activity(spanish, 'Antología (borrador)', Activity.Type.HOMEWORK, criterion=reading, published=False)

    # ── Historia III: grupo archivado del ciclo anterior ──
    history = Course.objects.create(
        name='Historia III', code='HIS3-C', professor=teacher, organization=organization, academic_year=previous,
        schedule='Vie 12:00–14:00', color='#b45309', description='Grupo del ciclo anterior, ya archivado.',
    )
    history_students = [b.new_student(history) for _ in range(15)]
    for title, type_, top in (('Examen 1', Activity.Type.EXAM, 10), ('Examen final', Activity.Type.EXAM, 10), ('Tarea de cierre', Activity.Type.HOMEWORK, 10)):
        activity = b.activity(history, title, type_, top=top, days=-300)
        b.grade_all(activity, history_students, teacher)
    archive_course(history)

    # ── Cuentas de alumno enlazadas por el código de invitación (el flujo real) ──
    linked = []
    for email, student in zip(STUDENT_EMAILS, [maths_students[7], maths_students[8], maths_students[20]]):
        user = register_student(
            first_name=student.first_name, last_name=student.last_name, email=email, password=PASSWORD, notify=False,
        )
        user.email_verified_at = b.now
        user.save(update_fields=['email_verified_at'])
        redeem_invitation(user, maths.invite_code, student.student_number, student.last_name)
        student.refresh_from_db()  # ya trae su cuenta enlazada
        linked.append(student)

    # ── Mensajes ──
    conversation = Conversation.objects.get(course=maths, student=linked[0].user)
    for body, who in CONVERSATIONS:
        sender = linked[0].user if who == 'student' else teacher
        message = Message.objects.create(conversation=conversation, sender=sender, body=body)
        if who == 'student' and body is not CONVERSATIONS[-1][0]:
            Message.objects.filter(pk=message.pk).update(read_at=b.now)  # la maestra ya leyó la primera
    other = Conversation.objects.get(course=maths, student=linked[1].user)
    Message.objects.create(conversation=other, sender=linked[1].user, body='Maestra, ¿cuándo sale la calificación del proyecto?')

    counts = {
        **b.counts, 'courses': 3, 'students': Student.objects.filter(organization=organization).count(),
        'enrollments': Enrollment.objects.filter(course__organization=organization).count(),
        'questions': len(bank) + len(spanish_bank) + len(general),
    }
    return DemoSummary(
        organization=organization, teacher=teacher, students=linked, courses=[maths, spanish, history], counts=counts,
    )


# ── Borrado ───────────────────────────────────────────────────────────

@transaction.atomic
def delete_demo():
    """Borra la escuela de ejemplo y sus cuentas. Se niega si la organización tiene a alguien que no sea de ejemplo."""
    User = get_user_model()
    teacher = User.objects.filter(email=TEACHER_EMAIL).first()
    if teacher is None:
        return False
    organizations = list(Organization.objects.filter(memberships__user=teacher, name=SCHOOL).distinct())
    for organization in organizations:
        outsiders = Membership.objects.filter(organization=organization).exclude(user__email__endswith=DEMO_DOMAIN)
        if outsiders.exists():
            raise ValidationError(f'La organización «{organization}» tiene cuentas que no son de ejemplo; no se borra.')
    for organization in organizations:
        # Las actividades primero: protegen a sus criterios, y borrar el grupo no sabe resolver ese orden.
        Activity.objects.filter(course__organization=organization).delete()
        Course.objects.filter(organization=organization).delete()
        Question.objects.filter(organization=organization).delete()
        Rubric.objects.filter(organization=organization).delete()  # tras las actividades: ellas protegen a sus versiones
        Student.objects.filter(organization=organization).delete()
        # La bitácora va al final: borrar notas también escribe en ella.
        GradeHistory.objects.filter(organization=organization).delete()
        AcademicYear.objects.filter(organization=organization).delete()
        organization.delete()
    User.objects.filter(email__endswith=DEMO_DOMAIN).delete()
    return True
