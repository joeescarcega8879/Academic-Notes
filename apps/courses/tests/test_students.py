"""Pruebas de ``Student``: alumno de la lista, distinto de la cuenta."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.tests.factories import StudentFactory
from apps.grades.factories import GradeFactory
from apps.grades.models import Grade
from apps.messaging.models import Conversation
from apps.organizations.tests.factories import OrganizationFactory
from apps.organizations.models import Membership

from apps.courses.tests.factories import EnrollmentFactory, StudentRecordFactory
from apps.courses.models import Enrollment, Student
from apps.courses.services.students import student_for_user

pytestmark = pytest.mark.django_db


# ── Matrícula única por organización ──────────────────────────────────

class TestMatricula:
    def test_se_repite_entre_organizaciones(self):
        StudentRecordFactory(student_number="A001")
        StudentRecordFactory(student_number="A001")  # otra organización
        assert Student.objects.filter(student_number="A001").count() == 2

    def test_no_se_repite_dentro_de_una_organizacion(self):
        organizacion = OrganizationFactory()
        StudentRecordFactory(organization=organizacion, student_number="A001")
        with pytest.raises(IntegrityError), transaction.atomic():
            StudentRecordFactory(organization=organizacion, student_number="A001")

    def test_los_espacios_no_la_distinguen(self):
        organizacion = OrganizationFactory()
        StudentRecordFactory(organization=organizacion, student_number="A001")
        with pytest.raises(IntegrityError), transaction.atomic():
            StudentRecordFactory(organization=organizacion, student_number=" A001 ")

    def test_vacia_puede_repetirse(self):
        organizacion = OrganizationFactory()
        StudentRecordFactory(organization=organizacion, student_number="")
        StudentRecordFactory(organization=organizacion, student_number="")
        assert Student.objects.filter(organization=organizacion, student_number="").count() == 2

    def test_es_texto_y_conserva_ceros_a_la_izquierda(self):
        alumno = StudentRecordFactory(student_number="000123")
        alumno.refresh_from_db()
        assert alumno.student_number == "000123"

    def test_una_cuenta_tiene_una_sola_ficha_por_organizacion(self):
        organizacion = OrganizationFactory()
        cuenta = StudentFactory()
        StudentRecordFactory(organization=organizacion, user=cuenta)
        with pytest.raises(IntegrityError), transaction.atomic():
            StudentRecordFactory(organization=organizacion, user=cuenta)
        StudentRecordFactory(user=cuenta)  # en otra organización sí

    def test_student_for_user_es_idempotente_y_copia_los_datos_de_la_cuenta(self):
        organizacion = OrganizationFactory()
        cuenta = StudentFactory(first_name="Sofía", last_name="López")
        ficha = student_for_user(cuenta, organizacion)
        assert student_for_user(cuenta, organizacion) == ficha
        assert (ficha.first_name, ficha.last_name, ficha.email) == ("Sofía", "López", cuenta.email)


# ── Alumno sin cuenta ─────────────────────────────────────────────────

class TestAlumnoSinCuenta:
    @pytest.fixture
    def sin_cuenta(self, course):
        return StudentRecordFactory(organization=course.organization, user=None, first_name="Luis", last_name="Mora")

    def test_se_puede_inscribir_y_calificar(self, course, activity, sin_cuenta):
        EnrollmentFactory(course=course, student=sin_cuenta)
        GradeFactory(activity=activity, student=sin_cuenta, score=9)
        assert Grade.objects.get(student=sin_cuenta).score == 9

    def test_no_tiene_membresia_ni_conversaciones(self, course, sin_cuenta):
        EnrollmentFactory(course=course, student=sin_cuenta)
        assert not Membership.objects.filter(role=Membership.Role.STUDENT).exists()
        assert not Conversation.objects.exists()

    def test_aparece_en_el_dashboard_el_detalle_y_el_csv_del_profesor(
        self, professor_client, course, activity, sin_cuenta,
    ):
        EnrollmentFactory(course=course, student=sin_cuenta)
        GradeFactory(activity=activity, student=sin_cuenta, score=7)

        assert professor_client.get(reverse("professor_dashboard")).context["total_students"] == 1
        detalle = professor_client.get(reverse("course_detail", args=[course.pk]))
        assert "Luis Mora" in detalle.content.decode()
        assert "Luis Mora" in professor_client.get(reverse("grades:export")).content.decode("utf-8-sig")

    def test_el_profesor_puede_calificarlo_desde_el_formulario(self, professor_client, course, activity, sin_cuenta):
        EnrollmentFactory(course=course, student=sin_cuenta)
        response = professor_client.post(
            reverse("grades:create"), {"activity": activity.pk, "student": sin_cuenta.pk, "score": 8},
        )
        assert response.status_code == 302
        assert Grade.objects.get(student=sin_cuenta).score == 8

    def test_enlazar_una_cuenta_lo_hace_miembro_y_crea_sus_conversaciones(self, course, sin_cuenta):
        EnrollmentFactory(course=course, student=sin_cuenta)
        cuenta = StudentFactory()
        sin_cuenta.user = cuenta
        sin_cuenta.save()

        assert Membership.objects.get(user=cuenta).organization == course.organization
        assert Conversation.objects.filter(course=course, student=cuenta).count() == 1

    def test_ya_enlazado_ve_sus_materias_y_notas(self, course, activity, sin_cuenta, client):
        EnrollmentFactory(course=course, student=sin_cuenta)
        GradeFactory(activity=activity, student=sin_cuenta, score=9)
        cuenta = StudentFactory()
        sin_cuenta.user = cuenta
        sin_cuenta.save()

        client.force_login(cuenta)
        context = client.get(reverse("student_dashboard")).context
        assert [e.course for e in context["enrollments"]] == [course]
        assert context["average"] == 9.0

    def test_borrar_la_cuenta_conserva_al_alumno_y_sus_notas(self, course, activity):
        cuenta = StudentFactory()
        ficha = student_for_user(cuenta, course.organization)
        GradeFactory(activity=activity, student=ficha, score=6)
        cuenta.delete()

        ficha.refresh_from_db()
        assert ficha.user is None
        assert Grade.objects.filter(student=ficha).count() == 1


# ── Coherencia de organización ────────────────────────────────────────

class TestMismaOrganizacion:
    def test_no_se_inscribe_a_un_alumno_de_otra_organizacion(self, course):
        ajeno = StudentRecordFactory()  # otra organización
        with pytest.raises(ValidationError):
            Enrollment.objects.create(student=ajeno, course=course)

    def test_no_se_califica_a_un_alumno_de_otra_organizacion(self, activity):
        ajeno = StudentRecordFactory()
        with pytest.raises(ValidationError):
            Grade.objects.create(student=ajeno, activity=activity, score=5)

    def test_el_formulario_no_ofrece_alumnos_de_otra_organizacion(self, professor_client, course, activity):
        propio = EnrollmentFactory(course=course).student
        ajeno = EnrollmentFactory().student
        form = professor_client.get(reverse("grades:create")).context["form"]
        assert list(form.fields["student"].queryset) == [propio]
        assert ajeno not in form.fields["student"].queryset


# ── Presentación ──────────────────────────────────────────────────────

class TestPresentacion:
    def test_nombre_completo(self):
        assert StudentRecordFactory.build(first_name="Ana María", last_name="Ruiz").get_full_name() == "Ana María Ruiz"
        assert str(StudentRecordFactory.build(first_name="Ana", last_name="", user=None)) == "Ana"

    def test_el_perfil_muestra_la_matricula_de_la_organizacion_activa(self, client, course):
        cuenta = StudentFactory()
        ficha = student_for_user(cuenta, course.organization)
        ficha.student_number = "A777"
        ficha.save()
        client.force_login(cuenta)
        assert "Matrícula A777" in client.get(reverse("profile")).content.decode()

    def test_el_detalle_del_profesor_muestra_la_matricula(self, professor_client, course):
        alumno = StudentRecordFactory(organization=course.organization, student_number="B042")
        EnrollmentFactory(course=course, student=alumno)
        assert "B042" in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
