"""Las vistas filtran por la organización activa, no solo por dueño.

Un usuario con membresías en dos organizaciones es el caso que el filtro por
profesor/alumno no cubre: todo lo suyo es "suyo", pero solo lo de la organización
activa debe verse. Aquí se prueba cada vista en ambas organizaciones.
"""

from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD, ProfessorFactory, StudentFactory
from apps.grades.tests.factories import ActivityFactory, GradeFactory
from apps.grades.models import Grade
from apps.messaging.tests.factories import MessageFactory
from apps.messaging.models import Conversation, Message
from apps.courses.tests.factories import EnrollmentFactory, CourseFactory

from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY

pytestmark = pytest.mark.django_db


def _clase(profesor, organizacion, alumno):
    """Materia de ``profesor`` en ``organizacion`` con evaluación, nota del alumno y un mensaje de él."""
    materia = CourseFactory(professor=profesor, organization=organizacion)
    EnrollmentFactory(course=materia, student=alumno)
    evaluacion = ActivityFactory(course=materia)
    nota = GradeFactory(activity=evaluacion, student=alumno)
    conversacion = Conversation.objects.get(course=materia, student=alumno)
    mensaje = MessageFactory(conversation=conversacion, sender=alumno)
    return SimpleNamespace(
        materia=materia, evaluacion=evaluacion, nota=nota, conversacion=conversacion, mensaje=mensaje,
        organizacion=organizacion,
    )


@pytest.fixture
def docente_en_dos():
    """Profesor que da clase en dos organizaciones; un alumno distinto en cada una."""
    profesor = ProfessorFactory()
    a = Membership.objects.get(user=profesor).organization
    b = OrganizationFactory()
    MembershipFactory(user=profesor, organization=b, role=Membership.Role.TEACHER)
    alumno_a, alumno_b = StudentFactory(), StudentFactory()
    return SimpleNamespace(
        profesor=profesor, alumno_a=alumno_a, alumno_b=alumno_b,
        a=_clase(profesor, a, alumno_a), b=_clase(profesor, b, alumno_b),
    )


@pytest.fixture
def alumno_en_dos():
    """Alumno inscrito con dos profesores distintos, cada uno en su organización."""
    alumno = StudentFactory()
    return SimpleNamespace(
        alumno=alumno,
        a=_clase(profesor_a := ProfessorFactory(), Membership.objects.get(user=profesor_a).organization, alumno),
        b=_clase(profesor_b := ProfessorFactory(), Membership.objects.get(user=profesor_b).organization, alumno),
    )


def _client(user, organizacion=None):
    client = Client()
    client.force_login(user)
    if organizacion is not None:
        session = client.session
        session[SESSION_KEY] = organizacion.pk
        session.save()
    return client


# ── Docente ───────────────────────────────────────────────────────────

class TestDocenteConDosOrganizaciones:
    @pytest.mark.parametrize("lado", ["a", "b"])
    def test_dashboard_solo_cuenta_la_organizacion_activa(self, docente_en_dos, lado):
        d = docente_en_dos
        activa = getattr(d, lado)
        context = _client(d.profesor, activa.organizacion).get(reverse("professor_dashboard")).context
        assert [s.pk for s in context["courses"]] == [activa.materia.pk]
        assert context["total_students"] == 1
        assert context["total_activities"] == 1
        assert context["graded_count"] == 1

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_materia_de_la_otra_organizacion_es_404(self, docente_en_dos, lado, otro):
        activa, ajena = getattr(docente_en_dos, lado), getattr(docente_en_dos, otro)
        client = _client(docente_en_dos.profesor, activa.organizacion)
        assert client.get(reverse("course_detail", args=[activa.materia.pk])).status_code == 200
        assert client.get(reverse("course_detail", args=[ajena.materia.pk])).status_code == 404

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_lista_y_exportacion_de_notas(self, docente_en_dos, lado, otro):
        activa, ajena = getattr(docente_en_dos, lado), getattr(docente_en_dos, otro)
        client = _client(docente_en_dos.profesor, activa.organizacion)

        assert [g.pk for g in client.get(reverse("grades:list")).context["grades"]] == [activa.nota.pk]
        assert [s.pk for s in client.get(reverse("grades:list")).context["courses"]] == [activa.materia.pk]

        csv_texto = client.get(reverse("grades:export")).content.decode("utf-8-sig")
        assert activa.nota.student.email in csv_texto
        assert ajena.nota.student.email not in csv_texto
        # Pedir la materia de la otra organización por parámetro tampoco la filtra
        csv_ajeno = client.get(reverse("grades:export"), {"materia": ajena.materia.pk}).content.decode("utf-8-sig")
        assert ajena.nota.student.email not in csv_ajeno

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_editar_y_eliminar_notas_de_la_otra_organizacion_es_404(self, docente_en_dos, lado, otro):
        activa, ajena = getattr(docente_en_dos, lado), getattr(docente_en_dos, otro)
        client = _client(docente_en_dos.profesor, activa.organizacion)
        for name in ("grades:update", "grades:delete"):
            url = reverse(name, args=[ajena.nota.pk])
            assert client.get(url).status_code == 404
            assert client.post(url, {"score": 1}).status_code == 404
        ajena.nota.refresh_from_db()
        assert Grade.objects.filter(pk=ajena.nota.pk).exists()

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_formulario_de_nota_solo_ofrece_datos_de_la_organizacion_activa(self, docente_en_dos, lado, otro):
        activa = getattr(docente_en_dos, lado)
        form = _client(docente_en_dos.profesor, activa.organizacion).get(reverse("grades:create")).context["form"]
        assert list(form.fields["activity"].queryset) == [activa.evaluacion]
        assert list(form.fields["student"].queryset) == [activa.nota.student]

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_no_se_puede_calificar_una_evaluacion_de_la_otra_organizacion(self, docente_en_dos, lado, otro):
        activa, ajena = getattr(docente_en_dos, lado), getattr(docente_en_dos, otro)
        total = Grade.objects.count()
        response = _client(docente_en_dos.profesor, activa.organizacion).post(
            reverse("grades:create"),
            {"activity": ajena.evaluacion.pk, "student": ajena.nota.student.pk, "score": 5},
        )
        assert response.status_code == 200  # el formulario rechaza la elección
        assert response.context["form"].errors
        assert Grade.objects.count() == total

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_mensajeria(self, docente_en_dos, lado, otro):
        activa, ajena = getattr(docente_en_dos, lado), getattr(docente_en_dos, otro)
        client = _client(docente_en_dos.profesor, activa.organizacion)

        lista = client.get(reverse("messaging:list")).context
        assert [c.pk for c in lista["conversations"]] == [activa.conversacion.pk]
        assert lista["unread_count"] == 1  # el mensaje del alumno de la organización activa, no el otro

        assert client.get(reverse("messaging:detail", args=[ajena.conversacion.pk])).status_code == 404
        enviados = Message.objects.count()
        assert client.post(reverse("messaging:send", args=[ajena.conversacion.pk]), {"body": "hola"}).status_code == 404
        assert Message.objects.count() == enviados

    def test_abrir_un_hilo_no_marca_leidos_los_de_la_otra_organizacion(self, docente_en_dos):
        d = docente_en_dos
        _client(d.profesor, d.a.organizacion).get(reverse("messaging:detail", args=[d.a.conversacion.pk]))
        d.a.mensaje.refresh_from_db()
        d.b.mensaje.refresh_from_db()
        assert d.a.mensaje.read_at is not None
        assert d.b.mensaje.read_at is None

    def test_marcar_notificaciones_leidas_solo_afecta_a_la_organizacion_activa(self, docente_en_dos):
        d = docente_en_dos
        response = _client(d.profesor, d.a.organizacion).post(reverse("notifications_read"))
        assert response.status_code == 302
        d.a.mensaje.refresh_from_db()
        d.b.mensaje.refresh_from_db()
        assert d.a.mensaje.read_at is not None
        assert d.b.mensaje.read_at is None


# ── Alumno ────────────────────────────────────────────────────────────

class TestAlumnoConDosOrganizaciones:
    @pytest.mark.parametrize("lado", ["a", "b"])
    def test_dashboard_muestra_solo_la_organizacion_activa(self, alumno_en_dos, lado):
        activa = getattr(alumno_en_dos, lado)
        context = _client(alumno_en_dos.alumno, activa.organizacion).get(reverse("student_dashboard")).context
        assert [e.course_id for e in context["enrollments"]] == [activa.materia.pk]

    @pytest.mark.parametrize("lado, otro", [("a", "b"), ("b", "a")])
    def test_materia_notas_y_mensajes_de_la_otra_organizacion(self, alumno_en_dos, lado, otro):
        activa, ajena = getattr(alumno_en_dos, lado), getattr(alumno_en_dos, otro)
        client = _client(alumno_en_dos.alumno, activa.organizacion)

        assert client.get(reverse("course_detail", args=[activa.materia.pk])).status_code == 200
        assert client.get(reverse("course_detail", args=[ajena.materia.pk])).status_code == 404
        assert [g.pk for g in client.get(reverse("grades:list")).context["grades"]] == [activa.nota.pk]
        assert [c.pk for c in client.get(reverse("messaging:list")).context["conversations"]] == [activa.conversacion.pk]
        assert client.get(reverse("messaging:detail", args=[ajena.conversacion.pk])).status_code == 404

    def test_notificaciones_de_notas_solo_de_la_organizacion_activa(self, alumno_en_dos):
        a = alumno_en_dos.a
        context = _client(alumno_en_dos.alumno, a.organizacion).get(reverse("grades:list")).context
        titulos = [n["title"] for n in context["notifications"] if n["type"] == "grade"]
        assert titulos == [a.evaluacion.title]

    def test_un_alumno_no_puede_usar_vistas_de_docente_en_ninguna_organizacion(self, alumno_en_dos):
        for lado in (alumno_en_dos.a, alumno_en_dos.b):
            client = _client(alumno_en_dos.alumno, lado.organizacion)
            response = client.get(reverse("grades:create"))
            assert response.status_code == 302
            assert response.url == reverse("student_dashboard")


# ── Rol por organización ──────────────────────────────────────────────

class TestRolPorOrganizacion:
    def test_el_mismo_usuario_es_docente_en_una_y_alumno_en_otra(self, docente_en_dos):
        d = docente_en_dos
        Membership.objects.filter(user=d.profesor, organization=d.b.organizacion).update(role=Membership.Role.STUDENT)

        como_docente = _client(d.profesor, d.a.organizacion)
        como_alumno = _client(d.profesor, d.b.organizacion)
        assert como_docente.get(reverse("professor_dashboard")).status_code == 200
        assert como_docente.get(reverse("student_dashboard")).url == reverse("professor_dashboard")
        assert como_alumno.get(reverse("student_dashboard")).status_code == 200
        assert como_alumno.get(reverse("professor_dashboard")).url == reverse("student_dashboard")

    def test_roles_sin_vistas_aun_van_al_perfil(self):
        usuario = StudentFactory()
        MembershipFactory(user=usuario, role=Membership.Role.PARENT)
        client = _client(usuario)
        for name in ("professor_dashboard", "student_dashboard", "grades:list", "messaging:list"):
            response = client.get(reverse(name))
            assert response.status_code == 302 and response.url == reverse("profile"), name

    @pytest.mark.parametrize("rol", [Membership.Role.ADMIN, Membership.Role.COORDINATOR])
    def test_la_direccion_sin_clases_va_a_su_escuela(self, rol):
        usuario = StudentFactory()
        MembershipFactory(user=usuario, role=rol)
        client = _client(usuario)
        for name in ("professor_dashboard", "student_dashboard", "grades:list", "messaging:list"):
            response = client.get(reverse(name))
            assert response.status_code == 302 and response.url == reverse("organizations:school"), name
        assert client.get(reverse("organizations:school")).status_code == 200

    def test_sin_membresias_no_hay_acceso_a_datos(self):
        client = _client(StudentFactory())
        for name in ("professor_dashboard", "student_dashboard", "grades:list", "messaging:list", "grades:create"):
            assert client.get(reverse(name)).url == reverse("profile"), name


# ── Selector de organización ──────────────────────────────────────────

class TestCambiarOrganizacion:
    def test_cambia_la_organizacion_activa(self, docente_en_dos):
        d = docente_en_dos
        client = _client(d.profesor, d.a.organizacion)
        response = client.post(reverse("organizations:switch"), {"organization": d.b.organizacion.pk})
        assert response.status_code == 302 and response.url == reverse("professor_dashboard")
        assert client.session[SESSION_KEY] == d.b.organizacion.pk
        context = client.get(reverse("professor_dashboard")).context
        assert [s.pk for s in context["courses"]] == [d.b.materia.pk]

    def test_redirige_al_inicio_del_rol_en_la_organizacion_elegida(self, docente_en_dos):
        d = docente_en_dos
        Membership.objects.filter(user=d.profesor, organization=d.b.organizacion).update(role=Membership.Role.STUDENT)
        client = _client(d.profesor, d.a.organizacion)
        response = client.post(reverse("organizations:switch"), {"organization": d.b.organizacion.pk})
        assert response.url == reverse("student_dashboard")

    def test_no_se_puede_activar_una_organizacion_ajena(self, docente_en_dos):
        d = docente_en_dos
        ajena = OrganizationFactory()
        client = _client(d.profesor, d.a.organizacion)
        assert client.post(reverse("organizations:switch"), {"organization": ajena.pk}).status_code == 404
        assert client.session[SESSION_KEY] == d.a.organizacion.pk

    @pytest.mark.parametrize("valor", ["", "abc", "0", "-1"])
    def test_valores_invalidos_son_404(self, docente_en_dos, valor):
        client = _client(docente_en_dos.profesor)
        assert client.post(reverse("organizations:switch"), {"organization": valor}).status_code == 404

    def test_solo_acepta_post(self, docente_en_dos):
        assert _client(docente_en_dos.profesor).get(reverse("organizations:switch")).status_code == 405

    def test_anonimo_va_al_login(self, client):
        response = client.post(reverse("organizations:switch"), {"organization": 1})
        assert response.status_code == 302 and response.url.startswith("/login/")

    def test_no_se_puede_activar_una_organizacion_inactiva(self, docente_en_dos):
        d = docente_en_dos
        d.b.organizacion.is_active = False
        d.b.organizacion.save()
        client = _client(d.profesor, d.a.organizacion)
        assert client.post(reverse("organizations:switch"), {"organization": d.b.organizacion.pk}).status_code == 404

    def test_el_selector_solo_aparece_con_varias_organizaciones(self, docente_en_dos, professor):
        con_dos = _client(docente_en_dos.profesor).get(reverse("professor_dashboard")).content.decode()
        con_una = _client(professor).get(reverse("professor_dashboard")).content.decode()
        assert 'class="org-switch"' in con_dos
        assert 'class="org-switch"' not in con_una
