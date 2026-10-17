"""Pantallas de importación de lista: subir, revisar y confirmar."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from apps.courses.tests.factories import CourseFactory
from apps.courses.models import Enrollment, Student
from apps.courses.services.courses import archive_course

pytestmark = pytest.mark.django_db

CSV = "Matrícula,Nombre,Apellidos,Correo\n00123,Ana,Pérez,ana@x.test\n00124,Luis,Mora,\n,,Sin nombre,\n"


def archivo(nombre="lista.csv", contenido=CSV):
    datos = contenido if isinstance(contenido, bytes) else contenido.encode("utf-8")
    return SimpleUploadedFile(nombre, datos)


def xlsx(filas):
    book = Workbook()
    for fila in filas:
        book.active.append(fila)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def subir(client, course, **kwargs):
    return client.post(reverse("student_import", args=[course.pk]), {"file": archivo(**kwargs)})


def mapeo(**cols):
    return {f"map_{k}": "" if v is None else v for k, v in cols.items()}


# ── Subir ─────────────────────────────────────────────────────────────

class TestSubir:
    def test_formulario(self, professor_client, course):
        assert professor_client.get(reverse("student_import", args=[course.pk])).status_code == 200

    def test_csv_valido_lleva_a_la_vista_previa(self, professor_client, course):
        response = subir(professor_client, course)
        assert response.url == reverse("student_import_preview", args=[course.pk])
        assert professor_client.session[f"import_{course.pk}"]["headers"] == ["Matrícula", "Nombre", "Apellidos", "Correo"]

    def test_xlsx_valido(self, professor_client, course):
        datos = xlsx([["Matrícula", "Nombre"], ["00123", "Ana"]])
        assert subir(professor_client, course, nombre="lista.xlsx", contenido=datos).status_code == 302

    @pytest.mark.parametrize("nombre, contenido, fragmento", [
        ("lista.pdf", b"x", "Formato no admitido"),
        ("lista.csv", b"", "vacío"),
        ("lista.xlsx", b"basura", "No se pudo abrir"),
    ])
    def test_archivos_invalidos_muestran_el_error_sin_guardar_nada(self, professor_client, course, nombre, contenido, fragmento):
        response = subir(professor_client, course, nombre=nombre, contenido=contenido)
        assert response.status_code == 200 and fragmento in response.context["error"]
        assert f"import_{course.pk}" not in professor_client.session

    def test_sin_archivo(self, professor_client, course):
        response = professor_client.post(reverse("student_import", args=[course.pk]), {})
        assert response.status_code == 200 and "Elige un archivo" in response.context["error"]

    def test_archivo_demasiado_grande(self, professor_client, course):
        response = subir(professor_client, course, contenido=b"a," * (1024 * 1024 + 1))
        assert "2 MB" in response.context["error"]

    def test_plantilla_csv(self, professor_client):
        response = professor_client.get(reverse("student_import_template"))
        assert response["Content-Type"].startswith("text/csv")
        assert response.content.startswith("﻿".encode("utf-8"))
        assert "Matrícula,Nombre(s),Apellidos,Correo" in response.content.decode("utf-8-sig")


# ── Vista previa ──────────────────────────────────────────────────────

class TestVistaPrevia:
    def url(self, course):
        return reverse("student_import_preview", args=[course.pk])

    def test_detecta_las_columnas_y_resume_lo_que_pasara(self, professor_client, course):
        subir(professor_client, course)
        context = professor_client.get(self.url(course)).context
        assert {f["key"]: f["selected"] for f in context["fields"]} == {
            "student_number": 0, "first_name": 1, "last_name": 2, "email": 3,
        }
        plan = context["plan"]
        assert (plan.count("create"), plan.count("error")) == (2, 1)
        assert context["can_confirm"]

    def test_la_vista_previa_no_escribe_en_la_base(self, professor_client, course):
        subir(professor_client, course)
        professor_client.get(self.url(course))
        assert Student.objects.count() == 0 and Enrollment.objects.count() == 0

    def test_sin_archivo_previo_vuelve_a_subir(self, professor_client, course):
        assert professor_client.get(self.url(course)).url == reverse("student_import", args=[course.pk])

    def test_cambiar_el_mapeo_actualiza_la_vista_previa(self, professor_client, course):
        subir(professor_client, course, contenido="Código,Persona\n001,Ana\n002,Luis\n")
        # Los encabezados no se reconocen solos: sin nombre asignado no hay vista previa.
        inicial = professor_client.get(self.url(course)).context
        assert inicial["mapping_errors"] and inicial["plan"] is None and not inicial["can_confirm"]

        datos = {**mapeo(student_number=0, first_name=1, last_name=None, email=None), "action": "preview"}
        context = professor_client.post(self.url(course), datos).context
        assert not context["mapping_errors"]
        assert [r.values["first_name"] for r in context["plan"].rows] == ["Ana", "Luis"]
        assert [r.values["student_number"] for r in context["plan"].rows] == ["001", "002"]

    @pytest.mark.parametrize("datos", [
        mapeo(student_number=0, first_name=None, last_name=None, email=None),  # falta el nombre
        mapeo(student_number=1, first_name=1, last_name=None, email=None),  # columna repetida
        mapeo(student_number=None, first_name=9, last_name=None, email=None),  # columna inexistente
    ])
    def test_mapeos_invalidos_no_se_pueden_confirmar(self, professor_client, course, datos):
        subir(professor_client, course, contenido="A,B\n1,Ana\n")
        response = professor_client.post(self.url(course), {**datos, "action": "confirm"})
        assert response.status_code == 200 and response.context["mapping_errors"]
        assert Student.objects.count() == 0

    def test_muestra_solo_las_primeras_filas_pero_cuenta_todas(self, professor_client, course):
        filas = "\n".join(f"{n},Alumno {n}" for n in range(250))
        subir(professor_client, course, contenido="Matrícula,Nombre\n" + filas)
        context = professor_client.get(self.url(course)).context
        assert len(context["preview_rows"]) == 200 and context["hidden_rows"] == 50
        assert context["plan"].count("create") == 250


# ── Confirmar ─────────────────────────────────────────────────────────

class TestConfirmar:
    def confirmar(self, client, course, datos=None):
        datos = datos or mapeo(student_number=0, first_name=1, last_name=2, email=3)
        return client.post(
            reverse("student_import_preview", args=[course.pk]), {**datos, "action": "confirm"}, follow=True,
        )

    def test_importa_inscribe_y_resume(self, professor_client, course):
        subir(professor_client, course)
        response = self.confirmar(professor_client, course)
        assert response.redirect_chain[-1][0] == reverse("course_detail", args=[course.pk])
        mensaje = [str(m) for m in response.context["messages"]][0]
        assert "2 alumnos nuevos" in mensaje and "2 inscritos" in mensaje and "omitieron 1" in mensaje
        assert set(course.enrollments.values_list("student__student_number", flat=True)) == {"00123", "00124"}
        assert f"import_{course.pk}" not in professor_client.session

    def test_reimportar_la_lista_no_duplica(self, professor_client, course):
        for _ in range(2):
            subir(professor_client, course)
            self.confirmar(professor_client, course)
        assert Student.objects.count() == 2 and Enrollment.objects.count() == 2

    def test_la_matricula_conserva_los_ceros_desde_excel(self, professor_client, course):
        datos = xlsx([["Matrícula", "Nombre"], ["00123", "Ana"]])
        subir(professor_client, course, nombre="lista.xlsx", contenido=datos)
        self.confirmar(professor_client, course, mapeo(student_number=0, first_name=1, last_name=None, email=None))
        assert Student.objects.get().student_number == "00123"

    def test_los_alumnos_quedan_en_la_organizacion_del_grupo_sin_cuenta(self, professor_client, course):
        subir(professor_client, course)
        self.confirmar(professor_client, course)
        assert {(s.organization, s.user) for s in Student.objects.all()} == {(course.organization, None)}

    def test_confirmar_sin_archivo_vuelve_a_subir(self, professor_client, course):
        response = professor_client.post(
            reverse("student_import_preview", args=[course.pk]), {**mapeo(first_name=0), "action": "confirm"},
        )
        assert response.url == reverse("student_import", args=[course.pk])

    def test_el_resumen_del_detalle_lista_a_los_alumnos_importados(self, professor_client, course):
        subir(professor_client, course)
        response = self.confirmar(professor_client, course)
        html = response.content.decode()
        assert "Ana Pérez" in html and "00124" in html


# ── Permisos ──────────────────────────────────────────────────────────

class TestPermisos:
    @pytest.mark.parametrize("name", ["student_import", "student_import_preview"])
    def test_grupo_de_otro_docente_es_404(self, professor_client, name):
        ajeno = CourseFactory()
        assert professor_client.get(reverse(name, args=[ajeno.pk])).status_code == 404

    @pytest.mark.parametrize("name", ["student_import", "student_import_preview"])
    def test_grupo_archivado_es_404(self, professor_client, course, name):
        archive_course(course)
        assert professor_client.get(reverse(name, args=[course.pk])).status_code == 404

    def test_subir_al_grupo_ajeno_no_guarda_nada(self, professor_client):
        ajeno = CourseFactory()
        assert subir(professor_client, ajeno).status_code == 404
        assert Student.objects.count() == 0

    def test_el_alumno_no_importa(self, student_client, course, enrollment):
        assert student_client.get(reverse("student_import", args=[course.pk])).status_code == 302
        assert student_client.post(reverse("student_import", args=[course.pk]), {"file": archivo()}).status_code == 302
        assert student_client.get(reverse("student_import_template")).status_code == 302

    def test_anonimo_va_al_login(self, client, course):
        assert client.get(reverse("student_import", args=[course.pk])).url.startswith("/login/")

    def test_el_boton_solo_aparece_en_grupos_activos(self, professor_client, course):
        url = reverse("student_import", args=[course.pk])
        assert url in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
        archive_course(course)
        assert url not in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
