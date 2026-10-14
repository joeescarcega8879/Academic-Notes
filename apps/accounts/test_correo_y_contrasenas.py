"""Correos transaccionales, confirmación de correo y contraseñas (restablecer y cambiar)."""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services, tasks
from apps.accounts.factories import PASSWORD, ProfessorFactory, StudentFactory

pytestmark = pytest.mark.django_db

User = get_user_model()
NUEVA = "Otra-clave-segura-4417"


def enlace(correo, fragmento):
    """El primer enlace del correo que contiene ``fragmento``, como ruta."""
    encontrado = re.search(r"https?://[^\s\"<>]+" + re.escape(fragmento) + r"[^\s\"<>]*", correo.body)
    assert encontrado, f"sin enlace con {fragmento}"
    return "/" + encontrado.group(0).split("/", 3)[3]


# ── Tokens de confirmación ────────────────────────────────────────────

class TestConfirmarCorreo:
    def test_un_enlace_valido_confirma(self, professor):
        usuario = services.confirm_email(services.verification_token(professor))
        assert usuario == professor
        professor.refresh_from_db()
        assert professor.email_verified_at is not None

    def test_confirmar_dos_veces_conserva_la_primera_fecha(self, professor):
        token = services.verification_token(professor)
        services.confirm_email(token)
        professor.refresh_from_db()
        primera = professor.email_verified_at
        services.confirm_email(token)
        professor.refresh_from_db()
        assert professor.email_verified_at == primera

    @pytest.mark.parametrize("token", ["", "abc", "x" * 200, "a:b:c"])
    def test_tokens_basura(self, db, token):
        assert services.confirm_email(token) is None

    def test_un_token_alterado_no_sirve(self, professor):
        token = services.verification_token(professor)
        assert services.confirm_email(token[:-2] + ("AA" if token[-2:] != "AA" else "BB")) is None
        professor.refresh_from_db()
        assert professor.email_verified_at is None

    def test_un_token_vencido_no_sirve(self, professor, monkeypatch):
        token = services.verification_token(professor)
        monkeypatch.setattr(services, "VERIFY_MAX_AGE", -1)
        assert services.confirm_email(token) is None

    def test_si_cambio_el_correo_el_enlace_viejo_no_sirve(self, professor):
        token = services.verification_token(professor)
        professor.email = "nuevo@prueba.test"
        professor.save()
        assert services.confirm_email(token) is None

    def test_el_usuario_borrado(self, professor):
        token = services.verification_token(professor)
        professor.delete()
        assert services.confirm_email(token) is None

    def test_un_token_de_otro_proposito_no_sirve(self, professor):
        from django.core import signing

        assert services.confirm_email(signing.dumps({"u": professor.pk, "e": professor.email}, salt="otra-cosa")) is None


# ── Tareas de correo ──────────────────────────────────────────────────

class TestTareas:
    def test_bienvenida_de_docente(self, professor, settings):
        settings.SITE_URL = "https://app.ejemplo.mx"
        tasks.send_welcome_email(professor.pk)
        (correo,) = mail.outbox
        assert correo.to == [professor.email] and "bienvenida" in correo.subject
        assert "docente" in correo.body and "https://app.ejemplo.mx/correo/confirmar/" in correo.body
        html, tipo = correo.alternatives[0]
        assert tipo == "text/html" and "Confirmar mi correo" in html

    def test_bienvenida_de_alumno(self, student):
        tasks.send_welcome_email(student.pk)
        assert "Unirme a un grupo" in mail.outbox[0].body

    def test_si_ya_confirmo_la_bienvenida_no_trae_enlace(self, professor):
        professor.email_verified_at = timezone.now()
        professor.save()
        tasks.send_welcome_email(professor.pk)
        assert "/correo/confirmar/" not in mail.outbox[0].body

    def test_el_texto_plano_no_escapa_apostrofes_pero_el_html_si(self):
        usuario = ProfessorFactory(first_name="D'Arcy <b>")
        tasks.send_welcome_email(usuario.pk)
        correo = mail.outbox[0]
        assert "D'Arcy <b>" in correo.body
        assert "<b>" not in correo.alternatives[0][0].split("Hola", 1)[1].split("</p>", 1)[0]

    def test_verificacion_no_se_manda_si_ya_esta_confirmado_ni_a_cuentas_inactivas(self, professor):
        professor.email_verified_at = timezone.now()
        professor.save()
        tasks.send_verification_email(professor.pk)
        otro = ProfessorFactory(is_active=False)
        tasks.send_verification_email(otro.pk)
        tasks.send_welcome_email(otro.pk)
        assert mail.outbox == []

    def test_usuario_inexistente_no_falla(self, db):
        tasks.send_welcome_email(987654)
        tasks.send_password_reset_email(987654)
        assert mail.outbox == []

    def test_cuenta_sin_contrasena_no_recibe_enlace_de_restablecer(self, professor):
        professor.set_unusable_password()
        professor.save()
        tasks.send_password_reset_email(professor.pk)
        assert mail.outbox == []

    def test_las_tareas_reintentan_si_el_proveedor_falla(self):
        assert tasks.send_welcome_email.max_retries == 3
        assert Exception in tasks.send_welcome_email.autoretry_for


class TestVistasDeConfirmacion:
    def test_el_enlace_confirma_y_avisa(self, professor_client, professor):
        response = professor_client.get(reverse("verify_email", args=[services.verification_token(professor)]), follow=True)
        professor.refresh_from_db()
        assert professor.email_verified_at is not None and "confirmamos tu correo" in response.content.decode()

    def test_el_enlace_sirve_sin_sesion(self, client, professor):
        response = client.get(reverse("verify_email", args=[services.verification_token(professor)]))
        assert response.url == reverse("login")
        professor.refresh_from_db()
        assert professor.email_verified_at is not None

    def test_enlace_invalido_avisa_sin_romper(self, client):
        response = client.get(reverse("verify_email", args=["basura"]), follow=True)
        assert "no es válido" in response.content.decode()

    def test_reenviar_manda_un_correo_nuevo(self, professor_client, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            response = professor_client.post(reverse("resend_verification"), {"next": reverse("professor_dashboard")})
        assert response.url == reverse("professor_dashboard") and len(mail.outbox) == 1
        assert "/correo/confirmar/" in mail.outbox[0].body

    def test_reenviar_tiene_limite(self, professor_client, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            for _ in range(5):
                professor_client.post(reverse("resend_verification"))
        assert len(mail.outbox) == 3

    def test_reenviar_a_un_next_externo_se_ignora(self, professor_client):
        assert professor_client.post(reverse("resend_verification"), {"next": "https://malicioso.example/"}).url == reverse("home")

    def test_reenviar_exige_sesion_y_post(self, client, professor_client):
        assert client.post(reverse("resend_verification")).url.startswith("/login/")
        assert professor_client.get(reverse("resend_verification")).status_code == 405

    def test_quien_ya_confirmo_no_recibe_mas(self, professor_client, professor, django_capture_on_commit_callbacks):
        professor.email_verified_at = timezone.now()
        professor.save()
        with django_capture_on_commit_callbacks(execute=True):
            professor_client.post(reverse("resend_verification"))
        assert mail.outbox == []


class TestAvisoDeCorreo:
    def test_el_docente_sin_confirmar_lo_ve(self, professor_client, course):
        html = professor_client.get(reverse("professor_dashboard")).content.decode()
        assert "Confirma tu correo" in html and reverse("resend_verification") in html

    def test_confirmado_no_lo_ve(self, professor_client, professor, course):
        professor.email_verified_at = timezone.now()
        professor.save()
        assert "Confirma tu correo" not in professor_client.get(reverse("professor_dashboard")).content.decode()

    def test_el_alumno_no_lo_ve(self, student_client, enrollment):
        assert "Confirma tu correo" not in student_client.get(reverse("student_dashboard")).content.decode()

    def test_cambiar_el_correo_en_el_perfil_pide_confirmarlo_otra_vez(self, professor_client, professor, django_capture_on_commit_callbacks):
        professor.email_verified_at = timezone.now()
        professor.save()
        data = {
            "first_name": professor.first_name, "last_name": professor.last_name, "email": "cambio@prueba.test",
            "phone": "", "birth_date": "", "notify_grades": "on", "show_average": "on", "department": "Mate",
        }
        with django_capture_on_commit_callbacks(execute=True):
            response = professor_client.post(reverse("profile"), data)
        professor.refresh_from_db()
        assert response.status_code == 302 and professor.email == "cambio@prueba.test" and professor.email_verified_at is None
        assert mail.outbox[0].to == ["cambio@prueba.test"]

    def test_guardar_el_perfil_sin_cambiar_el_correo_no_lo_desconfirma(self, professor_client, professor, django_capture_on_commit_callbacks):
        professor.email_verified_at = timezone.now()
        professor.save()
        data = {
            "first_name": "Otro", "last_name": professor.last_name, "email": professor.email,
            "phone": "", "birth_date": "", "notify_grades": "on", "show_average": "on", "department": "Mate",
        }
        with django_capture_on_commit_callbacks(execute=True):
            professor_client.post(reverse("profile"), data)
        professor.refresh_from_db()
        assert professor.email_verified_at is not None and mail.outbox == []


# ── Olvidé mi contraseña ──────────────────────────────────────────────

class TestRestablecer:
    def pedir(self, client, correo):
        return client.post(reverse("password_reset"), {"email": correo})

    def test_la_respuesta_es_la_misma_exista_o_no_la_cuenta(self, client, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            existe = self.pedir(client, professor.email)
            no_existe = self.pedir(Client(), "nadie@prueba.test")
        assert existe.status_code == no_existe.status_code == 302 and existe.url == no_existe.url == reverse("password_reset_sent")
        assert len(mail.outbox) == 1

    def test_ignora_mayusculas_y_espacios(self, client, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, f"  {professor.email.upper()} ")
        assert len(mail.outbox) == 1

    def test_cuentas_inactivas_no_reciben(self, client, django_capture_on_commit_callbacks):
        usuario = ProfessorFactory(is_active=False)
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, usuario.email)
        assert mail.outbox == []

    def test_correo_invalido_es_error_del_formulario(self, client):
        response = self.pedir(client, "no-es-correo")
        assert response.status_code == 200 and not mail.outbox

    def test_limite_por_correo(self, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            for _ in range(6):
                assert self.pedir(Client(), professor.email).status_code == 302
        assert len(mail.outbox) == 3

    def test_limite_por_conexion(self, client, django_capture_on_commit_callbacks):
        for n in range(10):
            assert self.pedir(client, f"x{n}@prueba.test").status_code == 302
        assert self.pedir(client, "otro@prueba.test").status_code == 429

    def test_flujo_completo(self, client, professor, django_capture_on_commit_callbacks, settings):
        settings.SITE_URL = "https://app.ejemplo.mx"
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, professor.email)
        ruta = enlace(mail.outbox[0], "/contrasena/restablecer/")
        pagina = client.get(ruta, follow=True)
        assert pagina.status_code == 200 and "Elige tu nueva contraseña" in pagina.content.decode()
        formulario = pagina.redirect_chain[-1][0]
        respuesta = client.post(formulario, {"new_password1": NUEVA, "new_password2": NUEVA})
        assert respuesta.url == reverse("password_reset_complete")
        assert client.post(reverse("login"), {"username": professor.email, "password": NUEVA}).status_code == 302
        assert Client().post(reverse("login"), {"username": professor.email, "password": PASSWORD}).status_code == 200

    def test_el_enlace_solo_sirve_una_vez(self, client, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, professor.email)
        ruta = enlace(mail.outbox[0], "/contrasena/restablecer/")
        pagina = client.get(ruta, follow=True)
        client.post(pagina.redirect_chain[-1][0], {"new_password1": NUEVA, "new_password2": NUEVA})
        viejo = Client().get(ruta, follow=True)
        assert "Este enlace ya no sirve" in viejo.content.decode()

    def test_un_enlace_manipulado_no_sirve(self, client):
        respuesta = client.get(reverse("password_reset_confirm", args=["MQ", "no-es-un-token"]), follow=True)
        assert "Este enlace ya no sirve" in respuesta.content.decode()

    def test_la_contrasena_nueva_pasa_por_los_validadores(self, client, professor, django_capture_on_commit_callbacks):
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, professor.email)
        pagina = client.get(enlace(mail.outbox[0], "/contrasena/restablecer/"), follow=True)
        respuesta = client.post(pagina.redirect_chain[-1][0], {"new_password1": "123", "new_password2": "123"})
        assert respuesta.status_code == 200
        professor.refresh_from_db()
        assert professor.check_password(PASSWORD)

    def test_el_enlace_del_correo_usa_la_direccion_configurada(self, client, professor, django_capture_on_commit_callbacks, settings):
        settings.SITE_URL = "https://libreta.escuela.mx"
        with django_capture_on_commit_callbacks(execute=True):
            self.pedir(client, professor.email)
        assert "https://libreta.escuela.mx/contrasena/restablecer/" in mail.outbox[0].body

    def test_el_login_enlaza_a_restablecer_y_al_registro(self, client):
        html = client.get(reverse("login")).content.decode()
        assert reverse("password_reset") in html and reverse("register") in html and reverse("register_student") in html


# ── Cambiar contraseña ────────────────────────────────────────────────

class TestCambiarContrasena:
    url = "password_change"

    def test_exige_sesion(self, client):
        assert client.get(reverse(self.url)).url.startswith("/login/")

    def test_cambia_y_conserva_la_sesion(self, professor_client, professor):
        response = professor_client.post(reverse(self.url), {"old_password": PASSWORD, "new_password1": NUEVA, "new_password2": NUEVA})
        assert response.url == reverse("profile")
        professor.refresh_from_db()
        assert professor.check_password(NUEVA)
        assert professor_client.get(reverse("profile")).status_code == 200

    def test_contrasena_actual_incorrecta(self, professor_client, professor):
        response = professor_client.post(reverse(self.url), {"old_password": "mala", "new_password1": NUEVA, "new_password2": NUEVA})
        assert response.status_code == 200
        professor.refresh_from_db()
        assert professor.check_password(PASSWORD)

    def test_el_perfil_enlaza_al_cambio(self, professor_client):
        assert reverse(self.url) in professor_client.get(reverse("profile")).content.decode()

    def test_alumno_tambien(self, student_client, student):
        response = student_client.post(reverse(self.url), {"old_password": PASSWORD, "new_password1": NUEVA, "new_password2": NUEVA})
        assert response.status_code == 302
        student.refresh_from_db()
        assert student.check_password(NUEVA)


def test_throttle_ventana_y_aislamiento():
    from core import throttle

    assert [throttle.allow("t", "a", limit=2, window=60) for _ in range(3)] == [True, True, False]
    assert throttle.allow("t", "b", limit=2, window=60) is True  # otra identidad
    assert throttle.allow("otro", "a", limit=2, window=60) is True  # otro ámbito
    assert throttle.allow("t", " A ", limit=2, window=60) is False  # misma identidad sin importar mayúsculas ni espacios
