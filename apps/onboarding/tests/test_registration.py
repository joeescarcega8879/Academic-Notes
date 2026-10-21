"""Alta de docentes y alumnos por cuenta propia, portada, páginas legales y primeros pasos."""

import datetime
import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import PASSWORD, ProfessorFactory, StudentFactory
from apps.courses.models import AcademicYear, Course
from apps.organizations import plans
from apps.organizations.models import Membership, Organization

from apps.onboarding import services
from apps.onboarding.services import default_cycle, register_student, register_teacher, unique_username

pytestmark = pytest.mark.django_db

User = get_user_model()
CLAVE = "Clave-segura-9271"


def datos(**extra):
    return {
        "first_name": "Ana", "last_name": "López Ruiz", "email": "ana@escuela.mx", "password1": CLAVE, "password2": CLAVE,
        "accept_terms": "on", **extra,
    }


# ── Ciclo escolar y nombre de usuario ─────────────────────────────────

class TestCicloYUsuario:
    @pytest.mark.parametrize("hoy, nombre, inicio, fin", [
        (datetime.date(2026, 10, 14), "2026–2027", datetime.date(2026, 8, 1), datetime.date(2027, 7, 31)),
        (datetime.date(2026, 8, 1), "2026–2027", datetime.date(2026, 8, 1), datetime.date(2027, 7, 31)),
        (datetime.date(2026, 7, 31), "2025–2026", datetime.date(2025, 8, 1), datetime.date(2026, 7, 31)),
        (datetime.date(2027, 1, 5), "2026–2027", datetime.date(2026, 8, 1), datetime.date(2027, 7, 31)),
        (datetime.date(2026, 12, 31), "2026–2027", datetime.date(2026, 8, 1), datetime.date(2027, 7, 31)),
    ])
    def test_ciclo_de_agosto_a_julio(self, hoy, nombre, inicio, fin):
        assert default_cycle(hoy) == (nombre, inicio, fin)

    def test_usuario_unico(self):
        assert unique_username("ana@a.com") == "ana"
        User.objects.create_user(username="ana", email="ana@a.com", password="x")
        assert unique_username("ana@b.com") == "ana2"
        User.objects.create_user(username="ana2", email="ana@c.com", password="x")
        assert unique_username("ANA@d.com") == "ana3"

    @pytest.mark.parametrize("correo", ["@raro.com", "ñ.ü@x.com", "a" * 300 + "@x.com", "...@x.com"])
    def test_usuario_con_correos_raros(self, correo):
        assert 0 < len(unique_username(correo)) <= 150


# ── Servicio ──────────────────────────────────────────────────────────

class TestRegistrarDocente:
    def test_crea_cuenta_organizacion_membresia_y_ciclo(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            user = register_teacher(
                first_name="Ana", last_name="López", email="Ana@Escuela.MX ", password=CLAVE, today=datetime.date(2026, 10, 14),
            )
        assert (user.email, user.role, user.email_verified_at) == ("ana@escuela.mx", "professor", None)
        assert user.check_password(CLAVE)
        organization = Organization.objects.get()
        assert (organization.name, organization.type) == ("Ana López", Organization.Type.INDIVIDUAL)
        assert Membership.objects.get().role == Membership.Role.OWNER
        year = AcademicYear.objects.get()
        assert (year.name, year.is_current, year.organization) == ("2026–2027", True, organization)
        assert len(mail.outbox) == 1 and mail.outbox[0].to == ["ana@escuela.mx"]

    def test_el_nombre_de_la_escuela_nombra_la_organizacion(self):
        register_teacher(first_name="Ana", last_name="L", email="a@a.com", password=CLAVE, school_name="  Prepa Norte ")
        assert Organization.objects.get().name == "Prepa Norte"

    def test_correo_repetido_sin_importar_mayusculas(self):
        register_teacher(first_name="A", last_name="B", email="ana@x.com", password=CLAVE)
        with pytest.raises(Exception, match="Ya existe una cuenta"):
            register_teacher(first_name="A", last_name="B", email="ANA@X.COM", password=CLAVE)
        assert User.objects.count() == 1 and Organization.objects.count() == 1

    def test_si_algo_falla_no_queda_nada_a_medias(self, monkeypatch):
        def falla(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(services.AcademicYear.objects, "create", falla)
        with pytest.raises(RuntimeError):
            register_teacher(first_name="A", last_name="B", email="x@x.com", password=CLAVE)
        assert not User.objects.exists() and not Organization.objects.exists()

    def test_dos_docentes_con_el_mismo_nombre_tienen_cuentas_distintas(self):
        a = register_teacher(first_name="Ana", last_name="L", email="ana@a.com", password=CLAVE)
        b = register_teacher(first_name="Ana", last_name="L", email="ana@b.com", password=CLAVE)
        assert a.username != b.username and Organization.objects.count() == 2


class TestRegistrarAlumno:
    def test_sin_organizacion_hasta_que_se_una(self, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            user = register_student(first_name="Luis", last_name="Gómez", email="luis@x.com", password=CLAVE)
        assert user.role == "student" and not Membership.objects.exists() and not Organization.objects.exists()
        assert "código" in mail.outbox[0].body


# ── Vistas de registro ────────────────────────────────────────────────

class TestRegistroDeDocente:
    url = "register"

    def test_la_pagina(self, client):
        response = client.get(reverse(self.url))
        html = response.content.decode()
        assert response.status_code == 200 and "Crea tu cuenta de docente" in html and 'name="school_name"' in html

    def test_alta_completa_inicia_sesion_y_lleva_al_inicio(self, client):
        response = client.post(reverse(self.url), datos(school_name="Prepa Norte"))
        assert response.status_code == 302 and response.url == reverse("professor_dashboard")
        user = User.objects.get(email="ana@escuela.mx")
        assert int(client.session["_auth_user_id"]) == user.pk
        assert client.session["organization_id"] == Organization.objects.get().pk
        assert client.get(response.url).status_code == 200

    def test_el_docente_nuevo_puede_crear_su_primer_grupo_sin_configurar_nada(self, client):
        client.post(reverse(self.url), datos())
        formulario = client.get(reverse("course_create"))
        assert formulario.status_code == 200
        ciclo = AcademicYear.objects.get()
        response = client.post(reverse("course_create"), {
            "name": "Matemáticas I", "code": "MAT1", "academic_year": ciclo.pk, "schedule": "", "color": "#336699", "description": "",
        })
        assert response.status_code == 302 and Course.objects.get().name == "Matemáticas I"

    def test_correo_repetido_es_un_error_del_formulario_no_un_500(self, client):
        ProfessorFactory(email="ana@escuela.mx")
        response = client.post(reverse(self.url), datos(email="ANA@escuela.mx"))
        assert response.status_code == 200 and "Ya existe una cuenta" in response.content.decode()
        assert User.objects.count() == 1

    @pytest.mark.parametrize("cambio, mensaje", [
        ({"password1": "corta1", "password2": "corta1"}, "demasiado corta"),
        ({"password1": "password", "password2": "password"}, "muy común"),
        ({"password1": "12345678901", "password2": "12345678901"}, "totalmente numérica"),
        ({"password2": "Otra-clave-9271"}, "no coinciden"),
        ({"password1": "ana@escuela.mx", "password2": "ana@escuela.mx"}, "muy similar"),
    ])
    def test_contrasenas_rechazadas(self, client, cambio, mensaje):
        response = client.post(reverse(self.url), datos(**cambio))
        assert response.status_code == 200 and mensaje in response.content.decode()
        assert not User.objects.exists()

    def test_hay_que_aceptar_los_terminos(self, client):
        data = datos()
        del data["accept_terms"]
        response = client.post(reverse(self.url), data)
        assert response.status_code == 200 and "tienes que aceptar" in response.content.decode() and not User.objects.exists()

    @pytest.mark.parametrize("campo", ["first_name", "last_name", "email"])
    def test_campos_obligatorios(self, client, campo):
        data = datos()
        data[campo] = ""
        assert client.post(reverse(self.url), data).status_code == 200 and not User.objects.exists()

    def test_correo_invalido(self, client):
        assert client.post(reverse(self.url), datos(email="no-es-correo")).status_code == 200 and not User.objects.exists()

    def test_la_trampa_para_robots_no_crea_nada_ni_da_pistas(self, client):
        response = client.post(reverse(self.url), datos(website="http://spam.example"))
        assert response.status_code == 302 and not User.objects.exists() and "_auth_user_id" not in client.session

    def test_limite_de_altas_por_conexion(self, client):
        for n in range(5):
            Client().post(reverse(self.url), datos(email=f"u{n}@x.com"))
        response = client.post(reverse(self.url), datos(email="otro@x.com"))
        assert response.status_code == 429 and "Intenta de nuevo" in response.content.decode()
        assert User.objects.count() == 5

    def test_quien_ya_tiene_sesion_no_se_registra_otra_vez(self, professor_client):
        assert professor_client.get(reverse(self.url)).url == reverse("professor_dashboard")
        assert professor_client.post(reverse(self.url), datos()).url == reverse("professor_dashboard")
        assert not User.objects.filter(email="ana@escuela.mx").exists()

    def test_los_nombres_se_escapan(self, client):
        client.post(reverse(self.url), datos(first_name="<script>alert(1)</script>"))
        html = client.get(reverse("professor_dashboard")).content.decode()
        assert "<script>alert(1)</script>" not in html

    def test_la_contrasena_no_se_guarda_en_claro(self, client):
        client.post(reverse(self.url), datos())
        assert CLAVE not in User.objects.get().password

    def test_el_alta_llega_al_correo_con_enlace_de_confirmacion(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse(self.url), datos())
        (correo,) = mail.outbox
        assert "/correo/confirmar/" in correo.body and correo.alternatives


class TestRegistroDeAlumno:
    def test_la_pagina_y_el_alta(self, client):
        assert "cuenta de alumno" in client.get(reverse("register_student")).content.decode()
        data = datos()
        response = client.post(reverse("register_student"), data)
        assert response.url == reverse("join_course")
        user = User.objects.get()
        assert user.role == "student" and not Membership.objects.exists()
        assert client.get(response.url).status_code == 200

    def test_el_alumno_nuevo_se_une_a_un_grupo_con_el_codigo(self, client, course):
        from apps.courses.tests.factories import StudentRecordFactory

        ficha = StudentRecordFactory(organization=course.organization, user=None, student_number="00123", last_name="Gómez")
        from apps.courses.tests.factories import EnrollmentFactory

        EnrollmentFactory(course=course, student=ficha)
        client.post(reverse("register_student"), datos(email="luis@x.com"))
        response = client.post(reverse("join_course"), {"code": course.invite_code, "student_number": "00123", "last_name": "Gómez"})
        assert response.status_code == 302
        ficha.refresh_from_db()
        assert ficha.user == User.objects.get(email="luis@x.com")
        assert Membership.objects.get(user=ficha.user).role == Membership.Role.STUDENT

    def test_no_se_puede_usar_el_alta_de_alumno_para_escoger_ser_docente(self, client):
        client.post(reverse("register_student"), datos(role="professor", school_name="X"))
        assert User.objects.get().role == "student" and not Organization.objects.exists()


# ── Portada y páginas legales ─────────────────────────────────────────

class TestPortada:
    def test_anonimo(self, client):
        response = client.get("/")
        html = response.content.decode()
        assert response.status_code == 200
        for enlace in (reverse("register"), reverse("register_student"), reverse("login"), reverse("terms"), reverse("privacy")):
            assert enlace in html

    def test_no_dice_ningun_precio_que_no_este_en_la_tabla_de_planes(self, client):
        html = client.get("/").content.decode().lower()
        precios = {int(p.replace(",", "")) for p in re.findall(r"\$([\d,]+)", html)}
        assert precios == {0, plans.TEACHER.monthly_price, plans.TEACHER.annual_price, plans.PLUS.monthly_price, plans.PLUS.annual_price}

    def test_con_sesion_cada_rol_va_a_su_inicio(self, professor_client, student_client, enrollment):
        assert professor_client.get("/").url == reverse("professor_dashboard")
        assert student_client.get("/").url == reverse("student_dashboard")

    def test_el_nombre_del_sitio_sale_de_la_configuracion(self, client, settings):
        settings.SITE_NAME = "MiLibreta"
        assert "MiLibreta" in client.get("/").content.decode()

    @pytest.mark.parametrize("nombre, texto", [("terms", "Términos de uso"), ("privacy", "Aviso de privacidad")])
    def test_paginas_legales_publicas_y_marcadas_como_borrador(self, client, nombre, texto):
        response = client.get(reverse(nombre))
        html = response.content.decode()
        assert response.status_code == 200 and texto in html and "pendiente de revisión legal" in html


# ── Primeros pasos ────────────────────────────────────────────────────

class TestPrimerosPasos:
    def test_docente_nuevo_ve_los_cuatro_pasos_pendientes(self, client):
        client.post(reverse("register"), datos())
        response = client.get(reverse("professor_dashboard"))
        pasos = response.context["onboarding"]
        assert (pasos["done"], pasos["total"]) == (0, 4) and "Primeros pasos" in response.content.decode()
        assert pasos["steps"][0].url == reverse("course_create")

    def test_los_pasos_se_marcan_con_lo_que_ya_hizo(self, professor_client, professor, course):
        from apps.courses.tests.factories import EnrollmentFactory
        from apps.grades.tests.factories import ActivityFactory
        from apps.grades.services.gradebook import grade_activity

        def hechos():
            return [s.done for s in professor_client.get(reverse("professor_dashboard")).context["onboarding"]["steps"]]

        assert hechos() == [True, False, False, False]
        alumno = EnrollmentFactory(course=course).student
        assert hechos() == [True, True, False, False]
        actividad = ActivityFactory(course=course)
        assert hechos() == [True, True, True, False]
        grade_activity(actividad, alumno, score=8)
        assert "onboarding" not in professor_client.get(reverse("professor_dashboard")).context  # todo listo: desaparece

    def test_los_enlaces_apuntan_al_primer_grupo(self, professor_client, course):
        pasos = professor_client.get(reverse("professor_dashboard")).context["onboarding"]["steps"]
        assert pasos[1].url == reverse("student_import", args=[course.pk])
        assert pasos[2].url == reverse("grades:activity_create", args=[course.pk])
        assert pasos[3].url == reverse("grades:gradesheet", args=[course.pk])

    def test_se_puede_ocultar_y_se_recuerda(self, professor_client, course):
        response = professor_client.post(reverse("onboarding_dismiss"))
        assert response.url == reverse("professor_dashboard")
        assert "onboarding" not in professor_client.get(reverse("professor_dashboard")).context

    def test_ocultar_exige_ser_docente(self, student_client, client):
        assert student_client.post(reverse("onboarding_dismiss")).status_code == 302
        assert client.post(reverse("onboarding_dismiss")).url.startswith("/login/")

    def test_solo_cuenta_lo_del_propio_docente(self, professor_client, course):
        from apps.courses.tests.factories import EnrollmentFactory

        EnrollmentFactory()  # alumno en el grupo de otro docente
        pasos = professor_client.get(reverse("professor_dashboard")).context["onboarding"]["steps"]
        assert [s.done for s in pasos] == [True, False, False, False]

    def test_el_trabajo_de_un_colega_de_la_misma_organizacion_no_cuenta(self, professor_client, course):
        from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
        from apps.grades.tests.factories import ActivityFactory
        from apps.organizations.tests.factories import MembershipFactory

        colega = ProfessorFactory()
        MembershipFactory(user=colega, organization=course.organization, role=Membership.Role.TEACHER)
        ajeno = CourseFactory(professor=colega, organization=course.organization)
        EnrollmentFactory(course=ajeno)
        ActivityFactory(course=ajeno)
        pasos = professor_client.get(reverse("professor_dashboard")).context["onboarding"]["steps"]
        assert [s.done for s in pasos] == [True, False, False, False]

    def test_el_correo_de_bienvenida_sale_solo_cuando_la_transaccion_se_confirma(self, client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=False) as pendientes:
            client.post(reverse("register"), datos())
            assert mail.outbox == []
        assert len(pendientes) == 1
        pendientes[0]()
        assert len(mail.outbox) == 1

    def test_no_se_calcula_en_otras_pantallas(self, professor_client, course):
        respuesta = professor_client.get(reverse("grades:list"))
        assert "onboarding" not in respuesta.context

    def test_servicio(self, professor, course):
        pasos = services.teacher_steps(professor, course.organization)
        assert [s.key for s in pasos] == ["group", "students", "activity", "grade"]


def test_el_alumno_no_ve_los_primeros_pasos(student_client, enrollment):
    assert "onboarding" not in student_client.get(reverse("student_dashboard")).context
