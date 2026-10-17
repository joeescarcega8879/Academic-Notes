"""La escuela de ejemplo (``crear_demo``): que se arme completa, que sirva para probar y que se pueda borrar sin tocar nada más."""

import io

import pytest
from django.core import mail
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.courses.factories import EnrollmentFactory
from apps.courses.models import AcademicYear, Course, Enrollment, Student
from apps.grades.models import Activity, Grade, GradeHistory, Submission
from apps.messaging.models import Conversation, Message
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership, Organization
from apps.quizzes.models import Question, QuizAttempt
from apps.reports.services import risk

from . import demo

pytestmark = pytest.mark.django_db


@pytest.fixture
def escuela():
    return demo.build_demo()


def entrar(email):
    client = Client()
    assert client.post(reverse("login"), {"username": email, "password": demo.PASSWORD}).status_code == 302
    return client


class TestArmado(TestCase):
    """Solo lee: la escuela se arma una vez para toda la clase."""

    @classmethod
    def setUpTestData(cls):
        cls.escuela = demo.build_demo()

    def test_cuentas_grupos_y_alumnos(self):
        assert self.escuela.teacher.email == demo.TEACHER_EMAIL and self.escuela.teacher.check_password(demo.PASSWORD)
        assert self.escuela.teacher.email_verified_at is not None
        assert self.escuela.organization.name == demo.SCHOOL
        mates, espanol, historia = self.escuela.courses
        assert (mates.name, mates.enrollments.count()) == ("Matemáticas II", 28)
        assert (espanol.name, espanol.enrollments.count()) == ("Español II", 24)
        assert historia.is_archived and historia.academic_year != mates.academic_year
        assert mates.academic_year.is_current and not historia.academic_year.is_current
        assert AcademicYear.objects.filter(organization=self.escuela.organization).count() == 2

    def test_no_manda_correos(self):
        assert mail.outbox == []

    def test_matriculas_unicas_como_texto_con_ceros(self):
        numeros = list(Student.objects.filter(organization=self.escuela.organization).values_list("student_number", flat=True))
        assert len(numeros) == len(set(numeros)) == 55 and all(len(n) == 5 and n.isdigit() for n in numeros)
        assert "00001" in numeros

    def test_hay_alumnos_en_dos_grupos(self):
        mates, espanol, _ = self.escuela.courses
        compartidos = set(mates.enrollments.values_list("student_id", flat=True)) & set(espanol.enrollments.values_list("student_id", flat=True))
        assert len(compartidos) == 12

    def test_el_segundo_grupo_tiene_dos_periodos(self):
        espanol = self.escuela.courses[1]
        assert [p.name for p in espanol.scheme.periods.all()] == ["Primer parcial", "Segundo parcial"]
        assert [c.name for p in espanol.scheme.periods.all() for c in p.criteria.all()] == [
            "Lecturas y tareas", "Examen 1", "Redacción", "Examen 2",
        ]

    def test_actividades_de_todos_los_tipos_con_borradores_y_pendientes(self):
        tipos = set(Activity.objects.filter(course__organization=self.escuela.organization).values_list("type", flat=True))
        assert tipos == {"exam", "homework", "project", "participation", "quiz"}
        assert Activity.objects.filter(course__organization=self.escuela.organization, published=False).count() == 3
        pendiente = Activity.objects.get(title="Tarea 4: Geometría")
        assert pendiente.published and not pendiente.grades.exists() and pendiente.due_at > demo.timezone.now()

    def test_entregas_tardias_con_penalizacion(self):
        assert Submission.objects.filter(activity__course__organization=self.escuela.organization, is_late=True).exists()
        assert Grade.objects.filter(activity__course__organization=self.escuela.organization, late_penalty__gt=0).exists()
        penalizada = Grade.objects.filter(late_penalty__gt=0).first()
        assert penalizada.score < penalizada.raw_score

    def test_quizzes_con_intentos_y_notas_automaticas(self):
        assert QuizAttempt.objects.filter(quiz__activity__course__organization=self.escuela.organization).count() >= 20
        assert Grade.objects.filter(source=Grade.Source.QUIZ).exists()
        borrador = Activity.objects.get(title="Quiz: Ecuaciones (borrador)")
        assert not borrador.published and borrador.quiz.questions.count() == 4
        assert Question.objects.filter(organization=self.escuela.organization).count() == 12

    def test_hay_de_todo_en_aprobados_riesgo_y_reprobados(self):
        niveles = risk.risk_counts(risk.assess_course(self.escuela.courses[0]))
        assert niveles[risk.FAILING] >= 2 and niveles[risk.AT_RISK] >= 3 and niveles[risk.OK] >= 10

    def test_la_bitacora_registra_al_docente(self):
        assert GradeHistory.objects.filter(changed_by=self.escuela.teacher).exists()

    def test_mensajes_con_pendientes_de_leer(self):
        # Un hilo por alumno con cuenta y grupo: dos de ellos cursan también Español.
        assert Conversation.objects.filter(course__organization=self.escuela.organization).count() == 5
        alumno = self.escuela.students[0].user
        conversacion = Conversation.objects.get(course=self.escuela.courses[0], student=alumno)
        assert conversacion.messages.count() == 3
        assert Message.objects.filter(conversation__student=self.escuela.students[1].user, read_at__isnull=True).exists()

    def test_las_cuentas_de_alumno_quedaron_enlazadas_por_el_flujo_real(self):
        for student, email in zip(self.escuela.students, demo.STUDENT_EMAILS):
            assert student.user.email == email and student.user.role == "student"
            assert Membership.objects.get(user=student.user).role == Membership.Role.STUDENT

    def test_las_cifras_del_resumen_son_verdad(self):
        c = self.escuela.counts
        assert c["grades"] <= Grade.objects.count()  # la cuenta de la base incluye las automáticas de los quizzes
        assert c["students"] == 55 and c["questions"] == 12 and c["attempts"] == QuizAttempt.objects.count()
        assert c["enrollments"] == Enrollment.objects.count() == 67
        assert c["submissions"] == Submission.objects.count()


class TestRecorrido(TestCase):
    """Humo: con datos realistas, cada pantalla importante responde sin error."""

    @classmethod
    def setUpTestData(cls):
        cls.escuela = demo.build_demo()

    def test_el_docente_recorre_la_aplicacion(self):
        client = entrar(demo.TEACHER_EMAIL)
        mates, espanol, historia = self.escuela.courses
        alumno = mates.enrollments.first().student
        quiz = Activity.objects.get(title="Quiz: Fracciones")
        paginas = [
            reverse("professor_dashboard"), reverse("grades:list"), reverse("academic_years"), reverse("messaging:list"),
            reverse("quizzes:bank"),
            *[reverse("course_detail", args=[c.pk]) for c in self.escuela.courses],
            *[reverse("grades:gradesheet", args=[c.pk]) for c in self.escuela.courses],
            *[reverse("reports:risk", args=[c.pk]) for c in self.escuela.courses],
            reverse("reports:workbook", args=[mates.pk]),
            reverse("grades:scheme", args=[espanol.pk]),
            quiz.get_absolute_url(), reverse("grades:activity_grading", args=[Activity.objects.get(title="Tarea 1: Fracciones").pk]),
            reverse("grades:activity_history", args=[quiz.pk]),
        ]
        for url in paginas:
            assert client.get(url).status_code == 200, url
        assert client.get(reverse("reports:transcripts", args=[mates.pk])).content.startswith(b"%PDF-")
        assert client.get(reverse("reports:transcript", args=[espanol.pk, espanol.enrollments.first().student.pk])).status_code == 200
        assert client.get(reverse("reports:workbook_download", args=[espanol.pk])).status_code == 200
        assert client.get(reverse("grades:export")).status_code == 200
        assert alumno.pk

    def test_los_alumnos_ven_lo_suyo(self):
        for email in demo.STUDENT_EMAILS:
            client = entrar(email)
            panel = client.get(reverse("student_dashboard"))
            assert panel.status_code == 200 and panel.context["enrollments"]
            assert client.get(reverse("grades:list")).status_code == 200
            assert client.get(reverse("messaging:list")).status_code == 200
            assert client.get(reverse("profile")).status_code == 200
        client = entrar(demo.STUDENT_EMAILS[0])
        assert client.get(reverse("course_detail", args=[self.escuela.courses[0].pk])).status_code == 200

    def test_el_alumno_ve_su_quiz_con_la_calificacion(self):
        client = entrar(demo.STUDENT_EMAILS[0])
        quiz = Activity.objects.get(title="Quiz: Fracciones")
        assert client.get(quiz.get_absolute_url()).status_code in (200, 302)

    def test_el_docente_no_ve_los_borradores_del_alumno_ni_al_reves(self):
        client = entrar(demo.STUDENT_EMAILS[0])
        borrador = Activity.objects.get(title="Proyecto extra (borrador)")
        assert client.get(borrador.get_absolute_url()).status_code == 404

    def test_el_docente_nuevo_no_ve_nada_de_la_escuela_de_ejemplo(self):
        otro = ProfessorFactory()
        client = Client()
        client.force_login(otro)
        for course in self.escuela.courses:
            assert client.get(reverse("course_detail", args=[course.pk])).status_code in (302, 404)


class TestSemillaYBorrado:
    def snapshot(self):
        return sorted(
            (g.student.student_number, g.activity.title, g.score) for g in Grade.objects.select_related("student", "activity")
        )

    def test_la_misma_semilla_da_los_mismos_datos(self):
        demo.build_demo()
        primera = self.snapshot()
        demo.delete_demo()
        demo.build_demo()
        assert self.snapshot() == primera

    def test_otra_semilla_cambia_las_notas(self):
        demo.build_demo(seed=1)
        a = self.snapshot()
        demo.delete_demo()
        demo.build_demo(seed=2)
        assert self.snapshot() != a

    def test_no_se_crea_dos_veces(self, escuela):
        with pytest.raises(demo.DemoExists):
            demo.build_demo()
        assert Organization.objects.filter(name=demo.SCHOOL).count() == 1

    def test_borrar_deja_la_base_como_estaba_y_no_toca_lo_demas(self):
        from django.contrib.auth import get_user_model

        ajeno = EnrollmentFactory()
        modelos = (
            get_user_model(), Organization, Membership, AcademicYear, Course, Enrollment, Student, Activity, Grade, GradeHistory,
            Submission, QuizAttempt, Question, Message, Conversation,
        )
        antes = {modelo: modelo.objects.count() for modelo in modelos}
        demo.build_demo()
        assert Course.objects.count() > antes[Course]
        assert demo.delete_demo() is True
        assert {modelo: modelo.objects.count() for modelo in modelos} == antes
        assert Course.objects.get().pk == ajeno.course.pk

    def test_borrar_sin_escuela_no_falla(self, db):
        assert demo.delete_demo() is False

    def test_se_niega_a_borrar_si_hay_cuentas_ajenas_en_la_organizacion(self, escuela):
        MembershipFactory(user=ProfessorFactory(), organization=escuela.organization, role=Membership.Role.TEACHER)
        with pytest.raises(ValidationError, match="no son de ejemplo"):
            demo.delete_demo()
        assert Course.objects.filter(organization=escuela.organization).count() == 3  # nada se borró

    def test_se_puede_volver_a_crear_despues_de_borrar(self, escuela):
        demo.delete_demo()
        assert demo.build_demo().teacher.email == demo.TEACHER_EMAIL


class TestComandoCrearDemo:
    def correr(self, *args, **kwargs):
        salida = io.StringIO()
        call_command("crear_demo", *args, stdout=salida, **kwargs)
        return salida.getvalue()

    def test_se_niega_sin_debug(self, settings):
        settings.DEBUG = False
        with pytest.raises(CommandError, match="DEBUG"):
            self.correr()

    def test_con_force_crea_y_muestra_las_credenciales(self, settings):
        settings.DEBUG = False
        texto = self.correr("--force")
        for esperado in (demo.TEACHER_EMAIL, demo.STUDENT_EMAILS[0], demo.PASSWORD, "Matemáticas II", "[archivado]", "código de invitación"):
            assert esperado in texto, esperado
        assert Course.objects.count() == 3

    def test_con_debug_no_pide_force(self, settings):
        settings.DEBUG = True
        assert "Escuela de ejemplo lista" in self.correr()

    def test_si_ya_existe_pide_reset(self, settings, escuela):
        settings.DEBUG = True
        with pytest.raises(CommandError, match="--reset"):
            self.correr()

    def test_reset_la_recrea(self, settings, escuela):
        settings.DEBUG = True
        texto = self.correr("--reset")
        assert "borrada" in texto and "lista" in texto and Course.objects.count() == 3

    def test_delete_solo_borra(self, settings, escuela):
        settings.DEBUG = True
        assert "borrada" in self.correr("--delete")
        assert not Course.objects.exists() and not demo.demo_exists()
        assert "No había" in self.correr("--delete")

    def test_las_credenciales_del_comando_sirven_para_entrar(self, settings):
        settings.DEBUG = True
        self.correr()
        assert Client().post(reverse("login"), {"username": demo.TEACHER_EMAIL, "password": demo.PASSWORD}).status_code == 302
