"""Lista editable: agregar, inscribir, editar, quitar alumnos y desvincular cuentas."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.accounts.factories import StudentFactory
from apps.grades.factories import GradeFactory
from apps.grades.models import Grade
from apps.messaging.models import Conversation
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership

from .factories import CourseFactory, EnrollmentFactory, StudentRecordFactory
from .models import Enrollment, Student
from .services import roster
from .services.courses import archive_course
from .services.invitations import redeem_invitation

pytestmark = pytest.mark.django_db

NUEVO = {"action": "new", "student_number": "00777", "first_name": "Rosa", "last_name": "Vega", "email": "rosa@x.test"}


@pytest.fixture
def alumno(course):
    """Alumno de la lista inscrito en el grupo, con matrícula y sin cuenta."""
    ficha = StudentRecordFactory(
        organization=course.organization, user=None, student_number="00123", first_name="Ana", last_name="Pérez",
    )
    EnrollmentFactory(course=course, student=ficha)
    return ficha


# ── Servicios ─────────────────────────────────────────────────────────

class TestServicios:
    def test_agregar_crea_e_inscribe(self, course):
        ficha = roster.add_student(course, first_name="Rosa", last_name="Vega", student_number="1", email="")
        assert (ficha.organization, ficha.user) == (course.organization, None)
        assert course.enrollments.filter(student=ficha).exists()

    def test_agregar_con_matricula_repetida_no_deja_nada_a_medias(self, course, alumno):
        with pytest.raises(IntegrityError):
            roster.add_student(course, first_name="Otra", last_name="X", student_number="00123", email="")
        assert Student.objects.count() == 1

    def test_inscribir_existente_es_idempotente(self, course):
        ficha = StudentRecordFactory(organization=course.organization)
        roster.enroll_existing(course, ficha)
        roster.enroll_existing(course, ficha)
        assert Enrollment.objects.filter(student=ficha, course=course).count() == 1

    def test_inscribir_a_alguien_de_otra_organizacion_falla(self, course):
        with pytest.raises(ValidationError):
            roster.enroll_existing(course, StudentRecordFactory())

    def test_quitar_borra_la_inscripcion_no_al_alumno(self, course, alumno):
        roster.remove_from_course(course, alumno)
        assert not course.enrollments.exists()
        assert Student.objects.filter(pk=alumno.pk).exists()

    def test_quitar_con_calificaciones_no_se_permite(self, course, alumno, activity):
        GradeFactory(activity=activity, student=alumno)
        with pytest.raises(ValidationError, match="calificaciones"):
            roster.remove_from_course(course, alumno)
        assert course.enrollments.count() == 1 and Grade.objects.count() == 1

    def test_quitar_a_alguien_con_cuenta_borra_su_conversacion(self, course):
        cuenta = StudentFactory()
        ficha = StudentRecordFactory(organization=course.organization, user=cuenta)
        EnrollmentFactory(course=course, student=ficha)
        assert Conversation.objects.filter(course=course, student=cuenta).exists()
        roster.remove_from_course(course, ficha)
        assert not Conversation.objects.filter(course=course, student=cuenta).exists()

    def test_quitar_de_un_grupo_archivado_no_se_permite(self, course, alumno):
        archive_course(course)
        with pytest.raises(ValidationError):
            roster.remove_from_course(course, alumno)
        assert course.enrollments.count() == 1


class TestDesvincular:
    @pytest.fixture
    def vinculado(self, course, alumno):
        cuenta = StudentFactory()
        redeem_invitation(cuenta, course.invite_code, "00123", "Pérez")
        alumno.refresh_from_db()
        return alumno

    def test_separa_la_cuenta_y_conserva_al_alumno_y_sus_notas(self, course, vinculado, activity):
        GradeFactory(activity=activity, student=vinculado, score=9)
        roster.unlink_student(vinculado)
        vinculado.refresh_from_db()
        assert vinculado.user is None
        assert Grade.objects.get(student=vinculado).score == 9
        assert course.enrollments.filter(student=vinculado).exists()

    def test_la_cuenta_pierde_membresia_y_conversaciones(self, course, vinculado):
        cuenta = vinculado.user
        roster.unlink_student(vinculado)
        assert not Membership.objects.filter(user=cuenta, organization=course.organization).exists()
        assert not Conversation.objects.filter(student=cuenta).exists()

    def test_conserva_el_rol_de_docente_de_la_cuenta(self, course, alumno):
        docente = course.professor  # también dará clase en la organización de otro
        Membership.objects.filter(user=docente, organization=course.organization).update(role=Membership.Role.TEACHER)
        alumno.user = docente
        alumno.save()  # ensure_student_membership no degrada el rol existente
        roster.unlink_student(alumno)
        assert Membership.objects.get(user=docente, organization=course.organization).role == Membership.Role.TEACHER

    def test_puede_volver_a_enlazarse_con_el_codigo(self, course, vinculado):
        roster.unlink_student(vinculado)
        otra = StudentFactory()
        assert redeem_invitation(otra, course.invite_code, "00123", "Pérez") == vinculado

    def test_sin_cuenta_no_hace_nada(self, alumno):
        assert roster.unlink_student(alumno) == alumno


# ── Pantallas ─────────────────────────────────────────────────────────

class TestAgregar:
    def url(self, course):
        return reverse("student_add", args=[course.pk])

    def test_agrega_un_alumno_nuevo(self, professor_client, course):
        response = professor_client.post(self.url(course), NUEVO, follow=True)
        ficha = Student.objects.get(student_number="00777")
        assert response.redirect_chain[-1][0] == reverse("course_detail", args=[course.pk])
        assert (ficha.organization, ficha.user, ficha.email) == (course.organization, None, "rosa@x.test")
        assert course.enrollments.filter(student=ficha).exists()
        assert any("se agregó" in str(m) for m in response.context["messages"])

    def test_matricula_repetida_en_la_organizacion_se_rechaza_con_el_nombre(self, professor_client, course, alumno):
        response = professor_client.post(self.url(course), {**NUEVO, "student_number": "00123"})
        assert response.status_code == 200
        assert "Ana Pérez" in str(response.context["new_form"].errors["student_number"])
        assert Student.objects.count() == 1

    def test_la_misma_matricula_de_otra_organizacion_es_valida(self, professor_client, course):
        StudentRecordFactory(student_number="00777")
        assert professor_client.post(self.url(course), NUEVO).status_code == 302

    def test_nombre_obligatorio_y_correo_valido(self, professor_client, course):
        response = professor_client.post(self.url(course), {**NUEVO, "first_name": "", "email": "no"})
        assert set(response.context["new_form"].errors) == {"first_name", "email"}

    def test_inscribe_a_uno_existente_de_la_organizacion(self, professor_client, course):
        existente = StudentRecordFactory(organization=course.organization)
        response = professor_client.post(self.url(course), {"action": "existing", "student": existente.pk})
        assert response.status_code == 302 and course.enrollments.filter(student=existente).exists()

    def test_no_ofrece_alumnos_ya_inscritos_ni_de_otra_organizacion(self, professor_client, course, alumno):
        libre = StudentRecordFactory(organization=course.organization)
        StudentRecordFactory()  # otra organización
        form = professor_client.get(self.url(course)).context["existing_form"]
        assert list(form.fields["student"].queryset) == [libre]

    def test_no_se_puede_forzar_a_un_alumno_de_otra_organizacion(self, professor_client, course):
        ajeno = StudentRecordFactory()
        response = professor_client.post(self.url(course), {"action": "existing", "student": ajeno.pk})
        assert response.status_code == 200 and "student" in response.context["existing_form"].errors
        assert not course.enrollments.exists()


class TestEditar:
    def url(self, course, student):
        return reverse("student_edit", args=[course.pk, student.pk])

    def test_edita_los_datos(self, professor_client, course, alumno):
        datos = {"student_number": "00999", "first_name": "Ana María", "last_name": "Pérez", "email": "nueva@x.test"}
        assert professor_client.post(self.url(course, alumno), datos).status_code == 302
        alumno.refresh_from_db()
        assert (alumno.student_number, alumno.first_name, alumno.email) == ("00999", "Ana María", "nueva@x.test")

    def test_conservar_su_propia_matricula_es_valido(self, professor_client, course, alumno):
        datos = {"student_number": "00123", "first_name": "Ana", "last_name": "Pérez", "email": ""}
        assert professor_client.post(self.url(course, alumno), datos).status_code == 302

    def test_no_permite_la_matricula_de_otro_alumno(self, professor_client, course, alumno):
        StudentRecordFactory(organization=course.organization, student_number="00500", first_name="Beto", last_name="Ruiz")
        datos = {"student_number": "00500", "first_name": "Ana", "last_name": "Pérez", "email": ""}
        response = professor_client.post(self.url(course, alumno), datos)
        assert "Beto Ruiz" in str(response.context["form"].errors["student_number"])
        alumno.refresh_from_db()
        assert alumno.student_number == "00123"

    def test_un_alumno_que_no_esta_en_el_grupo_es_404(self, professor_client, course):
        otro = StudentRecordFactory(organization=course.organization)
        assert professor_client.get(self.url(course, otro)).status_code == 404

    def test_alumno_de_otra_organizacion_es_404(self, professor_client, course):
        assert professor_client.get(self.url(course, EnrollmentFactory().student)).status_code == 404


class TestQuitarYDesvincular:
    def test_quitar(self, professor_client, course, alumno):
        response = professor_client.post(reverse("student_remove", args=[course.pk, alumno.pk]), follow=True)
        assert not course.enrollments.exists()
        assert any("se quitó" in str(m) for m in response.context["messages"])

    def test_quitar_con_calificaciones_avisa_y_no_quita(self, professor_client, course, alumno, activity):
        GradeFactory(activity=activity, student=alumno)
        response = professor_client.post(reverse("student_remove", args=[course.pk, alumno.pk]), follow=True)
        assert course.enrollments.count() == 1
        assert any("calificaciones" in str(m) for m in response.context["messages"])

    def test_quitar_solo_acepta_post(self, professor_client, course, alumno):
        assert professor_client.get(reverse("student_remove", args=[course.pk, alumno.pk])).status_code == 405

    def test_desvincular(self, professor_client, course, alumno):
        cuenta = StudentFactory()
        redeem_invitation(cuenta, course.invite_code, "00123", "Pérez")
        professor_client.post(reverse("student_unlink", args=[course.pk, alumno.pk]))
        alumno.refresh_from_db()
        assert alumno.user is None

    def test_desvincular_sin_cuenta_avisa(self, professor_client, course, alumno):
        response = professor_client.post(reverse("student_unlink", args=[course.pk, alumno.pk]), follow=True)
        assert any("no tiene una cuenta" in str(m) for m in response.context["messages"])


class TestPermisosDeLaLista:
    NOMBRES = ["student_add", "student_edit", "student_remove", "student_unlink"]

    def args(self, name, course, student):
        return [course.pk] if name == "student_add" else [course.pk, student.pk]

    @pytest.mark.parametrize("name", NOMBRES)
    def test_grupo_de_otro_docente_es_404(self, professor_client, alumno, name):
        ajeno = CourseFactory()
        otro_alumno = EnrollmentFactory(course=ajeno).student
        assert professor_client.get(reverse(name, args=self.args(name, ajeno, otro_alumno))).status_code in (404, 405)
        assert professor_client.post(reverse(name, args=self.args(name, ajeno, otro_alumno)), NUEVO).status_code == 404

    @pytest.mark.parametrize("name", NOMBRES)
    def test_grupo_archivado_es_404(self, professor_client, course, alumno, name):
        archive_course(course)
        assert professor_client.post(reverse(name, args=self.args(name, course, alumno)), NUEVO).status_code == 404
        assert course.enrollments.count() == 1

    @pytest.mark.parametrize("name", NOMBRES)
    def test_el_alumno_no_puede(self, student_client, course, enrollment, name):
        response = student_client.post(reverse(name, args=self.args(name, course, enrollment.student)), NUEVO)
        assert response.status_code == 302 and response.url == reverse("student_dashboard")

    def test_otra_organizacion_activa_es_404(self, professor_client, professor, course, alumno):
        otra = CourseFactory(professor=professor, organization=MembershipFactory(user=professor, role=Membership.Role.TEACHER).organization)
        assert professor_client.get(reverse("student_add", args=[otra.pk])).status_code == 404

    def test_el_detalle_ofrece_las_acciones_solo_en_grupos_activos(self, professor_client, course, alumno):
        editar = reverse("student_edit", args=[course.pk, alumno.pk])
        assert editar in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
        archive_course(course)
        assert editar not in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
