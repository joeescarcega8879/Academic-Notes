"""Entregas de los alumnos: reglas, archivos privados y permisos."""

import datetime

import pytest
from django.conf import settings
from django.test import Client
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.factories import CourseFactory, EnrollmentFactory, StudentRecordFactory
from apps.courses.services.courses import archive_course
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY

from .factories import ActivityFactory, GradeFactory
from .models import MAX_SUBMISSION_BYTES, Activity, Submission
from .services.submissions import clean_filename, submission_state, submit

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


def archivo(nombre="tarea.pdf", contenido=b"%PDF-1.4 contenido"):
    return SimpleUploadedFile(nombre, contenido)


@pytest.fixture
def tarea(course):
    return ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=True, due_at=AHORA + UN_DIA)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


# ── Ventana de entrega ────────────────────────────────────────────────

class TestVentana:
    @pytest.mark.parametrize("opens, due, allow_late, esperado", [
        (None, None, True, "open"),
        (-1, 1, True, "open"),
        (1, 2, True, "not_open"),
        (-2, -1, True, "late"),
        (-2, -1, False, "closed"),
        (None, -1, False, "closed"),
    ])
    def test_estados(self, course, opens, due, allow_late, esperado):
        dia = lambda n: None if n is None else AHORA + n * UN_DIA  # noqa: E731
        actividad = ActivityFactory(course=course, opens_at=dia(opens), due_at=dia(due), allow_late=allow_late)
        assert submission_state(actividad, AHORA) == esperado

    def test_justo_en_la_fecha_limite_no_es_tardia(self, course):
        actividad = ActivityFactory(course=course, due_at=AHORA)
        assert submission_state(actividad, AHORA) == "open"
        assert submission_state(actividad, AHORA + datetime.timedelta(seconds=1)) == "late"


# ── Servicio de entrega ───────────────────────────────────────────────

class TestEntregar:
    def test_texto(self, tarea, alumno):
        entrega = submit(tarea, alumno, text="  Mi respuesta  ", now=AHORA)
        assert (entrega.text, entrega.is_late, entrega.submitted_at) == ("Mi respuesta", False, AHORA)
        assert (entrega.organization, entrega.activity, entrega.student) == (tarea.organization, tarea, alumno)

    def test_enlace_y_archivo(self, tarea, alumno):
        assert submit(tarea, alumno, link="https://ejemplo.com/trabajo", now=AHORA).link == "https://ejemplo.com/trabajo"

    def test_archivo(self, tarea, alumno):
        entrega = submit(tarea, alumno, file=archivo("Mi Tarea Final.pdf"), now=AHORA)
        assert entrega.original_name == "Mi Tarea Final.pdf"
        assert entrega.file.read() == b"%PDF-1.4 contenido"

    def test_sin_nada_que_entregar(self, tarea, alumno):
        with pytest.raises(ValidationError, match="respuesta, un enlace o un archivo"):
            submit(tarea, alumno, text="   ", now=AHORA)
        assert not Submission.objects.exists()

    def test_fuera_de_fecha_se_marca_tardia(self, course, alumno):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=True)
        assert submit(actividad, alumno, text="tarde", now=AHORA).is_late

    def test_sin_tardias_se_rechaza(self, course, alumno):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=False)
        with pytest.raises(ValidationError, match="no acepta entregas tardías"):
            submit(actividad, alumno, text="tarde", now=AHORA)

    def test_antes_de_abrir_se_rechaza(self, course, alumno):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, opens_at=AHORA + UN_DIA)
        with pytest.raises(ValidationError, match="todavía no abre"):
            submit(actividad, alumno, text="x", now=AHORA)

    def test_un_borrador_no_recibe_entregas(self, course, alumno):
        borrador = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=False)
        with pytest.raises(ValidationError, match="no recibe entregas"):
            submit(borrador, alumno, text="x", now=AHORA)

    @pytest.mark.parametrize("tipo", [Activity.Type.PARTICIPATION, Activity.Type.EXAM, Activity.Type.QUIZ])
    def test_solo_las_tareas_y_proyectos_reciben_entregas(self, course, alumno, tipo):
        with pytest.raises(ValidationError, match="no recibe entregas"):
            submit(ActivityFactory(course=course, type=tipo), alumno, text="x", now=AHORA)

    def test_un_proyecto_si_recibe(self, course, alumno):
        assert submit(ActivityFactory(course=course, type=Activity.Type.PROJECT), alumno, text="x", now=AHORA)

    def test_quien_no_esta_inscrito_no_entrega(self, tarea, course):
        ajeno = StudentRecordFactory(organization=course.organization)
        with pytest.raises(ValidationError, match="No estás inscrito"):
            submit(tarea, ajeno, text="x", now=AHORA)

    def test_un_grupo_archivado_no_recibe_entregas(self, tarea, alumno, course):
        archive_course(course)
        with pytest.raises(ValidationError, match="archivado"):
            submit(tarea, alumno, text="x", now=AHORA)

    def test_reentregar_actualiza_la_misma_entrega(self, tarea, alumno):
        submit(tarea, alumno, text="v1", now=AHORA)
        entrega = submit(tarea, alumno, text="v2", now=AHORA + datetime.timedelta(hours=1))
        assert Submission.objects.count() == 1
        assert (entrega.text, entrega.submitted_at) == ("v2", AHORA + datetime.timedelta(hours=1))

    def test_reentregar_sin_archivo_conserva_el_anterior(self, tarea, alumno):
        primera = submit(tarea, alumno, file=archivo(), now=AHORA)
        segunda = submit(tarea, alumno, text="añado un comentario", now=AHORA)
        assert segunda.file.name == primera.file.name and segunda.file.storage.exists(segunda.file.name)

    def test_reentregar_con_archivo_nuevo_borra_el_viejo(self, tarea, alumno):
        primera = submit(tarea, alumno, file=archivo("a.pdf", b"AAA"), now=AHORA)
        ruta_vieja, almacen = primera.file.name, primera.file.storage
        segunda = submit(tarea, alumno, file=archivo("b.pdf", b"BBB"), now=AHORA)
        assert not almacen.exists(ruta_vieja)
        assert segunda.file.read() == b"BBB" and segunda.original_name == "b.pdf"

    def test_reentregar_despues_del_limite_la_marca_tardia(self, course, alumno):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA + UN_DIA)
        submit(actividad, alumno, text="a tiempo", now=AHORA)
        assert submit(actividad, alumno, text="cambio", now=AHORA + 2 * UN_DIA).is_late

    def test_una_entrega_calificada_no_se_cambia(self, tarea, alumno):
        submit(tarea, alumno, text="v1", now=AHORA)
        GradeFactory(activity=tarea, student=alumno)
        with pytest.raises(ValidationError, match="ya fue calificada"):
            submit(tarea, alumno, text="v2", now=AHORA)
        assert Submission.objects.get().text == "v1"


# ── Archivos y enlaces ────────────────────────────────────────────────

class TestArchivos:
    @pytest.mark.parametrize("nombre", [
        "x.html", "x.htm", "x.svg", "x.js", "x.exe", "x.php", "x.sh", "x.bat", "x.xhtml", "sin_extension", "x.pdf.exe",
    ])
    def test_extensiones_peligrosas_se_rechazan(self, tarea, alumno, nombre):
        with pytest.raises(ValidationError):
            submit(tarea, alumno, file=archivo(nombre), now=AHORA)
        assert not Submission.objects.exists()

    @pytest.mark.parametrize("nombre", ["a.pdf", "a.DOCX", "a.png", "a.jpeg", "a.zip", "a.txt", "a.xlsx"])
    def test_extensiones_permitidas(self, tarea, alumno, nombre):
        assert submit(tarea, alumno, file=archivo(nombre), now=AHORA).file

    def test_el_tamano_maximo(self, tarea, alumno):
        justo = SimpleUploadedFile("a.pdf", b"0" * MAX_SUBMISSION_BYTES)
        assert submit(tarea, alumno, file=justo, now=AHORA).file
        demasiado = SimpleUploadedFile("b.pdf", b"0" * (MAX_SUBMISSION_BYTES + 1))
        with pytest.raises(ValidationError, match="10 MB"):
            submit(tarea, EnrollmentFactory(course=tarea.course).student, file=demasiado, now=AHORA)

    @pytest.mark.parametrize("enlace", ["javascript:alert(1)", "ftp://x.com/a", "data:text/html,<b>", "no es un enlace", "//x.com"])
    def test_enlaces_que_no_son_http_se_rechazan(self, tarea, alumno, enlace):
        with pytest.raises(ValidationError):
            submit(tarea, alumno, link=enlace, now=AHORA)

    def test_enlace_https_valido(self, tarea, alumno):
        assert submit(tarea, alumno, link="https://drive.example.com/d/123?x=1", now=AHORA)

    @pytest.mark.parametrize("nombre, esperado", [
        ("../../etc/passwd.pdf", "passwd.pdf"), ("C:\\Users\\x\\tarea.pdf", "tarea.pdf"),
        ("tarea\x00.pdf", "tarea.pdf"), ("a" * 400 + ".pdf", ("a" * 400 + ".pdf")[:255]),
    ])
    def test_el_nombre_mostrado_se_limpia(self, nombre, esperado):
        assert clean_filename(nombre) == esperado

    def test_el_archivo_se_guarda_con_nombre_propio_en_una_ruta_ordenada(self, tarea, alumno):
        entrega = submit(tarea, alumno, file=archivo("../../hack.pdf"), now=AHORA)
        ruta = entrega.file.name
        assert "hack" not in ruta and ".." not in ruta
        assert ruta.startswith(f"{tarea.organization_id}/{tarea.course_id}/{tarea.pk}/{alumno.pk}/") and ruta.endswith(".pdf")

    def test_los_archivos_estan_fuera_de_media(self, tarea, alumno):
        entrega = submit(tarea, alumno, file=archivo(), now=AHORA)
        ruta = entrega.file.path
        assert str(settings.MEDIA_ROOT) not in ruta
        assert ruta.startswith(str(entrega.file.storage.location))

    def test_borrar_la_entrega_borra_el_archivo(self, tarea, alumno):
        entrega = submit(tarea, alumno, file=archivo(), now=AHORA)
        ruta, almacen = entrega.file.name, entrega.file.storage
        entrega.delete()
        assert not almacen.exists(ruta)

    def test_borrar_la_actividad_borra_los_archivos(self, tarea, alumno):
        entrega = submit(tarea, alumno, file=archivo(), now=AHORA)
        ruta, almacen = entrega.file.name, entrega.file.storage
        tarea.delete()
        assert not almacen.exists(ruta)


# ── Pantallas del alumno ──────────────────────────────────────────────

class TestPortalDelAlumno:
    def url(self, actividad):
        return reverse("grades:activity_submit", args=[actividad.pk])

    def test_ve_el_formulario_de_entrega(self, student_client, tarea, enrollment):
        response = student_client.get(tarea.get_absolute_url())
        assert response.status_code == 200 and response.context["can_submit"]
        assert 'enctype="multipart/form-data"' in response.content.decode()

    def test_entrega_texto_y_ve_el_resultado(self, student_client, tarea, enrollment):
        response = student_client.post(self.url(tarea), {"text": "Mi respuesta"}, follow=True)
        assert response.redirect_chain[-1][0] == tarea.get_absolute_url()
        assert any("quedó registrada" in str(m) for m in response.context["messages"])
        assert "Mi respuesta" in response.content.decode()

    def test_entrega_un_archivo_y_lo_descarga(self, student_client, tarea, enrollment):
        student_client.post(self.url(tarea), {"file": archivo("tarea.pdf", b"contenido secreto")})
        entrega = Submission.objects.get()
        response = student_client.get(reverse("grades:submission_file", args=[entrega.pk]))
        assert response.status_code == 200 and b"".join(response.streaming_content) == b"contenido secreto"

    def test_formulario_vacio(self, student_client, tarea, enrollment):
        response = student_client.post(self.url(tarea), {})
        assert response.status_code == 200 and response.context["submission_form"].non_field_errors()
        assert not Submission.objects.exists()

    def test_archivo_no_permitido(self, student_client, tarea, enrollment):
        response = student_client.post(self.url(tarea), {"file": archivo("malo.html", b"<script>")})
        assert response.status_code == 200 and "file" in response.context["submission_form"].errors
        assert not Submission.objects.exists()

    def test_enlace_javascript(self, student_client, tarea, enrollment):
        response = student_client.post(self.url(tarea), {"link": "javascript:alert(1)"})
        assert "link" in response.context["submission_form"].errors

    def test_fuera_de_fecha_avisa_y_marca_tardia(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, late_penalty=20)
        html = student_client.get(actividad.get_absolute_url()).content.decode()
        assert "se marcará como tardía" in html and "20 %" in html
        student_client.post(self.url(actividad), {"text": "tarde"})
        assert Submission.objects.get().is_late

    def test_cerrada_no_muestra_el_formulario_ni_acepta_entregas(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=False)
        response = student_client.get(actividad.get_absolute_url())
        assert not response.context["can_submit"] and "no acepta entregas tardías" in response.content.decode()
        post = student_client.post(self.url(actividad), {"text": "x"})
        assert post.status_code == 200 and not Submission.objects.exists()

    def test_calificada_ya_no_se_puede_cambiar(self, student_client, tarea, enrollment):
        student_client.post(self.url(tarea), {"text": "v1"})
        GradeFactory(activity=tarea, student=enrollment.student)
        assert not student_client.get(tarea.get_absolute_url()).context["can_submit"]
        student_client.post(self.url(tarea), {"text": "v2"})
        assert Submission.objects.get().text == "v1"

    def test_las_actividades_sin_entrega_no_ofrecen_formulario(self, student_client, course, enrollment):
        participacion = ActivityFactory(course=course, type=Activity.Type.PARTICIPATION)
        assert "Tu entrega" not in student_client.get(participacion.get_absolute_url()).content.decode()
        assert student_client.post(self.url(participacion), {"text": "x"}).status_code == 200
        assert not Submission.objects.exists()

    def test_un_enlace_se_abre_de_forma_segura(self, student_client, tarea, enrollment):
        student_client.post(self.url(tarea), {"link": "https://ejemplo.com"})
        html = student_client.get(tarea.get_absolute_url()).content.decode()
        assert 'rel="noopener noreferrer nofollow"' in html

    def test_el_texto_entregado_se_escapa(self, student_client, tarea, enrollment):
        student_client.post(self.url(tarea), {"text": "<img src=x onerror=alert(1)>"})
        html = student_client.get(tarea.get_absolute_url()).content.decode()
        assert "<img src=x" not in html and "&lt;img" in html

    def test_no_entrega_en_una_actividad_de_otro_grupo(self, student_client, enrollment):
        ajena = ActivityFactory(type=Activity.Type.HOMEWORK)
        assert student_client.post(self.url(ajena), {"text": "x"}).status_code == 404

    def test_no_entrega_en_un_borrador(self, student_client, course, enrollment):
        borrador = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=False)
        assert student_client.post(self.url(borrador), {"text": "x"}).status_code == 404

    def test_el_docente_no_entrega(self, professor_client, tarea):
        assert professor_client.post(self.url(tarea), {"text": "x"}).status_code == 404

    def test_get_redirige_al_detalle(self, student_client, tarea, enrollment):
        assert student_client.get(self.url(tarea)).url == tarea.get_absolute_url()

    def test_anonimo_va_al_login(self, client, tarea):
        assert client.post(self.url(tarea), {"text": "x"}).url.startswith("/login/")


# ── Permisos de lectura y descarga ────────────────────────────────────

class TestPermisos:
    @pytest.fixture
    def entrega(self, tarea, alumno):
        return submit(tarea, alumno, text="texto", file=archivo("a.pdf", b"PRIVADO"), now=AHORA)

    def descargar(self, client, entrega):
        return client.get(reverse("grades:submission_file", args=[entrega.pk]))

    def test_el_docente_del_grupo_descarga(self, professor_client, entrega):
        assert b"".join(self.descargar(professor_client, entrega).streaming_content) == b"PRIVADO"

    def test_el_dueno_descarga(self, student_client, entrega):
        assert self.descargar(student_client, entrega).status_code == 200

    def test_otro_alumno_no_descarga(self, client, entrega, course):
        otro = StudentFactory()
        EnrollmentFactory(course=course, student=otro)
        client.force_login(otro)
        assert self.descargar(client, entrega).status_code == 404
        assert client.get(reverse("grades:submission_detail", args=[entrega.pk])).status_code == 404

    def test_un_docente_de_otra_organizacion_no_descarga(self, client, entrega):
        client.force_login(ProfessorFactory())
        assert self.descargar(client, entrega).status_code == 404

    def test_el_docente_de_otro_grupo_en_la_misma_organizacion_no_descarga(self, entrega):
        otro = ProfessorFactory()
        MembershipFactory(user=otro, organization=entrega.organization, role=Membership.Role.TEACHER)
        CourseFactory(professor=otro, organization=entrega.organization)
        cliente = Client()
        cliente.force_login(otro)
        sesion = cliente.session
        sesion[SESSION_KEY] = entrega.organization_id  # misma organización activa, pero no es su grupo
        sesion.save()
        assert self.descargar(cliente, entrega).status_code == 404
        assert cliente.get(reverse("grades:submission_detail", args=[entrega.pk])).status_code == 404

    def test_anonimo_va_al_login(self, client, entrega):
        assert self.descargar(client, entrega).url.startswith("/login/")

    def test_cabeceras_de_descarga_seguras(self, professor_client, entrega):
        response = self.descargar(professor_client, entrega)
        assert response["Content-Type"] == "application/octet-stream"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Cache-Control"] == "private, no-store"
        assert response["Content-Disposition"].startswith("attachment") and "a.pdf" in response["Content-Disposition"]

    def test_la_descarga_de_una_actividad_en_borrador_no_es_para_el_alumno(self, student_client, entrega):
        entrega.activity.published = False
        entrega.activity.save()
        assert self.descargar(student_client, entrega).status_code == 404

    def test_entrega_sin_archivo_es_404(self, professor_client, tarea, course):
        sin_archivo = submit(tarea, EnrollmentFactory(course=course).student, text="solo texto", now=AHORA)
        assert self.descargar(professor_client, sin_archivo).status_code == 404

    def test_la_url_publica_de_media_no_expone_el_archivo(self, client, entrega):
        assert not entrega.file.path.startswith(str(settings.MEDIA_ROOT))
        assert client.get(f"/media/{entrega.file.name}").status_code == 404


# ── Pantallas del docente ─────────────────────────────────────────────

class TestBandejaDelDocente:
    def test_la_tabla_muestra_quien_entrego_y_quien_no(self, professor_client, tarea, course, enrollment):
        tardio = EnrollmentFactory(course=course).student
        tarea.due_at = AHORA - UN_DIA
        tarea.save()
        submit(tarea, enrollment.student, text="a", now=AHORA - 2 * UN_DIA)
        submit(tarea, tardio, text="b", now=AHORA)
        context = professor_client.get(tarea.get_absolute_url()).context
        assert (context["submitted_count"], context["late_count"]) == (2, 1)
        html = professor_client.get(tarea.get_absolute_url()).content.decode()
        assert "Ver entrega" in html and "Tardía" in html

    def test_alumno_sin_entrega(self, professor_client, tarea, enrollment):
        assert "Sin entrega" in professor_client.get(tarea.get_absolute_url()).content.decode()

    def test_las_actividades_sin_entrega_no_muestran_la_columna(self, professor_client, course, enrollment):
        participacion = ActivityFactory(course=course, type=Activity.Type.PARTICIPATION)
        html = professor_client.get(participacion.get_absolute_url()).content.decode()
        assert "Sin entrega" not in html and "<th>Entrega</th>" not in html

    def test_revisar_una_entrega(self, professor_client, tarea, alumno):
        entrega = submit(tarea, alumno, text="Mi <b>respuesta</b>", link="https://ejemplo.com", file=archivo("a.pdf"), now=AHORA)
        html = professor_client.get(reverse("grades:submission_detail", args=[entrega.pk])).content.decode()
        assert "&lt;b&gt;respuesta" in html and "https://ejemplo.com" in html and "Descargar a.pdf" in html
        assert "A tiempo" in html

    def test_el_alumno_no_entra_al_detalle_del_docente(self, student_client, tarea, alumno):
        entrega = submit(tarea, alumno, text="x", now=AHORA)
        assert student_client.get(reverse("grades:submission_detail", args=[entrega.pk])).status_code == 404
