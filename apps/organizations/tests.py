"""Pruebas de organizaciones: membresías, derivación del tenant, middleware y aislamiento."""

import pytest
from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.db import IntegrityError, transaction
from django.test import Client, RequestFactory
from django.urls import reverse

from apps.accounts.factories import ProfessorFactory, StudentFactory
from apps.grades.factories import EvaluationFactory, GradeFactory
from apps.grades.models import Evaluation, Grade
from apps.messaging.factories import ConversationFactory, MessageFactory
from apps.messaging.models import Conversation, Message
from apps.subjects.factories import EnrollmentFactory, SubjectFactory
from apps.subjects.models import Enrollment, Subject

from .factories import MembershipFactory, OrganizationFactory
from .managers import OrganizationQuerySet
from .middleware import SESSION_KEY, OrganizationMiddleware
from .models import Membership, Organization
from .services import ensure_individual_organization, ensure_student_membership, teaching_organization

pytestmark = pytest.mark.django_db

TENANT_MODELS = [Subject, Enrollment, Evaluation, Grade, Conversation, Message]


# ── Membresías y organización individual ──────────────────────────────

class TestOrganizacionIndividual:
    def test_profesor_nuevo_nace_con_su_organizacion(self):
        profesor = ProfessorFactory(first_name="Ana", last_name="Pérez")
        membership = Membership.objects.get(user=profesor)
        assert membership.role == Membership.Role.OWNER
        assert membership.organization.type == Organization.Type.INDIVIDUAL
        assert membership.organization.name == "Ana Pérez"
        assert membership.is_teacher

    def test_alumno_nuevo_no_recibe_organizacion(self):
        assert not Membership.objects.filter(user=StudentFactory()).exists()

    def test_ensure_es_idempotente(self):
        profesor = ProfessorFactory()
        primera = ensure_individual_organization(profesor)
        assert ensure_individual_organization(profesor) == primera
        assert Organization.objects.count() == 1

    def test_teaching_organization(self):
        profesor = ProfessorFactory()
        assert teaching_organization(profesor) == Membership.objects.get(user=profesor).organization
        assert teaching_organization(StudentFactory()) is None

    def test_una_sola_membresia_por_usuario_y_organizacion(self):
        membership = MembershipFactory()
        with pytest.raises(IntegrityError), transaction.atomic():
            MembershipFactory(user=membership.user, organization=membership.organization)

    def test_un_usuario_puede_tener_roles_distintos_en_organizaciones_distintas(self):
        usuario = StudentFactory()
        MembershipFactory(user=usuario, role=Membership.Role.STUDENT)
        MembershipFactory(user=usuario, role=Membership.Role.PARENT)
        assert usuario.memberships.count() == 2

    def test_ensure_student_membership_no_degrada_un_rol_existente(self):
        profesor = ProfessorFactory()
        organizacion = teaching_organization(profesor)
        ensure_student_membership(profesor, organizacion)
        assert Membership.objects.get(user=profesor, organization=organizacion).role == Membership.Role.OWNER


# ── Derivación del tenant ─────────────────────────────────────────────

class TestDerivacionDeOrganizacion:
    def test_la_materia_toma_la_organizacion_de_su_profesor(self):
        profesor = ProfessorFactory()
        materia = SubjectFactory(professor=profesor)
        assert materia.organization == teaching_organization(profesor)

    def test_la_materia_respeta_una_organizacion_explicita(self):
        organizacion = OrganizationFactory()
        assert SubjectFactory(organization=organizacion).organization == organizacion

    def test_los_hijos_heredan_la_organizacion_de_la_materia(self):
        inscripcion = EnrollmentFactory()
        materia = inscripcion.subject
        evaluacion = EvaluationFactory(subject=materia)
        nota = GradeFactory(evaluation=evaluacion, student=inscripcion.student)
        conversacion = Conversation.objects.get(subject=materia, student=inscripcion.student)
        mensaje = MessageFactory(conversation=conversacion)

        for objeto in (inscripcion, evaluacion, nota, conversacion, mensaje):
            assert objeto.organization_id == materia.organization_id, type(objeto).__name__

    def test_no_se_puede_forzar_otra_organizacion_en_un_hijo(self):
        materia = SubjectFactory()
        intruso = OrganizationFactory()
        evaluacion = EvaluationFactory.build(subject=materia, organization=intruso)
        evaluacion.save()
        assert evaluacion.organization_id == materia.organization_id

    def test_inscribirse_hace_al_alumno_miembro_de_la_organizacion(self):
        inscripcion = EnrollmentFactory()
        membership = Membership.objects.get(user=inscripcion.student)
        assert membership.organization == inscripcion.subject.organization
        assert membership.role == Membership.Role.STUDENT

    def test_inscribirse_en_dos_materias_de_la_misma_organizacion_no_duplica(self):
        profesor = ProfessorFactory()
        alumno = StudentFactory()
        EnrollmentFactory(student=alumno, subject=SubjectFactory(professor=profesor))
        EnrollmentFactory(student=alumno, subject=SubjectFactory(professor=profesor))
        assert alumno.memberships.count() == 1

    def test_alumno_en_materias_de_dos_organizaciones(self):
        alumno = StudentFactory()
        EnrollmentFactory(student=alumno)
        EnrollmentFactory(student=alumno)
        assert alumno.memberships.count() == 2


# ── for_organization ──────────────────────────────────────────────────

class TestForOrganization:
    def test_filtra_por_organizacion(self):
        a, b = SubjectFactory(), SubjectFactory()
        assert list(Subject.objects.for_organization(a.organization)) == [a]
        assert list(Subject.objects.for_organization(b.organization)) == [b]

    def test_sin_organizacion_no_devuelve_nada(self):
        SubjectFactory()
        assert Subject.objects.for_organization(None).count() == 0

    def test_se_encadena_con_otros_filtros(self):
        materia = SubjectFactory(name="Álgebra")
        SubjectFactory(name="Álgebra", organization=materia.organization)
        assert Subject.objects.for_organization(materia.organization).filter(code=materia.code).count() == 1

    def test_tambien_funciona_en_los_managers_relacionados(self):
        materia = SubjectFactory()
        EnrollmentFactory(subject=materia)
        assert materia.enrollments.for_organization(materia.organization).count() == 1
        assert materia.enrollments.for_organization(OrganizationFactory()).count() == 0


# ── Middleware ────────────────────────────────────────────────────────

class TestMiddleware:
    def run(self, usuario=None, session=None):
        """Pasa una petición por el middleware y devuelve la petición resultante."""
        request = RequestFactory().get("/")
        request.user = usuario if usuario is not None else AnonymousUser()
        request.session = session or {}
        OrganizationMiddleware(lambda r: None)(request)
        return request

    def test_anonimo_no_tiene_organizacion(self):
        request = self.run()
        assert request.organization is None
        assert request.membership is None

    def test_profesor_usa_su_organizacion(self):
        profesor = ProfessorFactory()
        request = self.run(profesor)
        assert request.organization == teaching_organization(profesor)
        assert request.membership.role == Membership.Role.OWNER

    def test_usuario_sin_membresias(self):
        assert self.run(StudentFactory()).organization is None

    def test_sin_sesion_toma_la_primera_membresia(self):
        alumno = StudentFactory()
        primera = MembershipFactory(user=alumno).organization
        MembershipFactory(user=alumno)
        assert self.run(alumno).organization == primera

    def test_respeta_la_organizacion_elegida_en_sesion(self):
        alumno = StudentFactory()
        MembershipFactory(user=alumno)
        elegida = MembershipFactory(user=alumno).organization
        assert self.run(alumno, {SESSION_KEY: elegida.pk}).organization == elegida

    def test_ignora_una_organizacion_en_sesion_de_la_que_no_es_miembro(self):
        alumno = StudentFactory()
        propia = MembershipFactory(user=alumno).organization
        ajena = OrganizationFactory()
        assert self.run(alumno, {SESSION_KEY: ajena.pk}).organization == propia

    def test_ignora_organizaciones_inactivas(self):
        alumno = StudentFactory()
        MembershipFactory(user=alumno, organization=OrganizationFactory(is_active=False))
        activa = MembershipFactory(user=alumno).organization
        assert self.run(alumno).organization == activa

    def test_la_peticion_real_lo_expone(self, professor_client, professor):
        response = professor_client.get(reverse("professor_dashboard"))
        assert response.wsgi_request.organization == teaching_organization(professor)


# ── Aislamiento entre organizaciones ──────────────────────────────────

@pytest.fixture
def dos_organizaciones():
    """Dos organizaciones completas: profesor, alumno, materia, evaluación, nota y mensaje."""
    datos = []
    for _ in range(2):
        profesor = ProfessorFactory()
        materia = SubjectFactory(professor=profesor)
        alumno = EnrollmentFactory(subject=materia).student
        evaluacion = EvaluationFactory(subject=materia)
        GradeFactory(evaluation=evaluacion, student=alumno)
        conversacion = Conversation.objects.get(subject=materia, student=alumno)
        MessageFactory(conversation=conversacion, sender=alumno)
        datos.append({"profesor": profesor, "alumno": alumno, "materia": materia, "org": materia.organization})
    return datos


class TestAislamiento:
    @pytest.mark.parametrize("modelo", TENANT_MODELS, ids=lambda m: m.__name__)
    def test_cada_modelo_solo_devuelve_filas_de_su_organizacion(self, dos_organizaciones, modelo):
        a, b = dos_organizaciones
        filas_a = modelo.objects.for_organization(a["org"])
        filas_b = modelo.objects.for_organization(b["org"])
        assert filas_a.exists() and filas_b.exists()
        assert not set(filas_a.values_list("pk", flat=True)) & set(filas_b.values_list("pk", flat=True))
        assert filas_a.count() + filas_b.count() == modelo.objects.count()

    def test_todo_modelo_con_organizacion_esta_cubierto_y_usa_for_organization(self):
        """Guardia estructural: un modelo nuevo con ``organization`` no puede quedar fuera sin que falle esto."""
        con_organizacion = {
            m for m in apps.get_models()
            if m._meta.app_label != "organizations"
            and any(f.name == "organization" for f in m._meta.get_fields())
        }
        assert con_organizacion == set(TENANT_MODELS)
        for modelo in con_organizacion:
            assert isinstance(modelo.objects.all(), OrganizationQuerySet), modelo.__name__
            assert not modelo._meta.get_field("organization").null, modelo.__name__

    def test_las_vistas_de_una_organizacion_no_muestran_datos_de_la_otra(self, dos_organizaciones):
        a, b = dos_organizaciones
        client = Client()
        client.force_login(a["profesor"])

        assert client.get(reverse("subject_detail", args=[b["materia"].pk])).status_code == 404

        notas = client.get(reverse("grades:list")).context["grades"]
        assert {g.evaluation.subject_id for g in notas} == {a["materia"].pk}

        conversaciones = client.get(reverse("messaging:list")).context["conversations"]
        assert {c.subject_id for c in conversaciones} == {a["materia"].pk}

        csv_texto = client.get(reverse("grades:export")).content.decode("utf-8-sig")
        assert b["alumno"].email not in csv_texto
        assert a["alumno"].email in csv_texto

    def test_el_alumno_de_una_organizacion_no_entra_a_la_otra(self, dos_organizaciones):
        a, b = dos_organizaciones
        client = Client()
        client.force_login(a["alumno"])
        assert client.get(reverse("subject_detail", args=[b["materia"].pk])).status_code == 404
        conversacion_ajena = Conversation.objects.get(subject=b["materia"])
        assert client.get(reverse("messaging:detail", args=[conversacion_ajena.pk])).status_code == 404

    def test_borrar_una_organizacion_con_datos_esta_protegido(self, dos_organizaciones):
        from django.db.models import ProtectedError

        with pytest.raises(ProtectedError):
            dos_organizaciones[0]["org"].delete()
