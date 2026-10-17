"""«Materia» pasó a llamarse «grupo»: rutas nuevas, enlaces viejos que siguen sirviendo y textos de la interfaz."""

import csv
import io

import pytest
from django.urls import reverse

from apps.grades.tests.factories import ActivityFactory, GradeFactory

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory

pytestmark = pytest.mark.django_db


class TestRutas:
    @pytest.mark.parametrize("nombre, args", [
        ("course_detail", [1]), ("course_update", [1]), ("student_add", [1]), ("student_import", [1]),
        ("grades:gradesheet", [1]), ("grades:activity_create", [1]),
    ])
    def test_las_rutas_son_de_grupo(self, nombre, args):
        assert reverse(nombre, args=args).startswith("/grupo/")

    def test_la_ruta_vieja_de_materia_redirige_para_siempre(self, professor_client, course):
        response = professor_client.get(f"/materia/{course.pk}/")
        assert response.status_code == 301 and response.url == f"/grupo/{course.pk}/"
        assert professor_client.get(response.url).status_code == 200

    def test_conserva_el_resto_de_la_ruta_y_la_consulta(self, client):
        assert client.get("/materia/7/alumnos/3/editar/").url == "/grupo/7/alumnos/3/editar/"
        assert client.get("/materia/7/libreta/?q=1").url == "/grupo/7/libreta/?q=1"

    def test_la_redireccion_no_abre_a_otros_sitios(self, client):
        for ruta in ("/materia//evil.example/", "/materia/https://evil.example/", "/materia/\\evil.example"):
            destino = client.get(ruta).url
            assert destino.startswith("/grupo/") and "://" not in destino.split("/grupo/", 1)[0]


class TestTextos:
    def test_el_inicio_del_docente_habla_de_grupos(self, professor_client, course):
        html = professor_client.get(reverse("professor_dashboard")).content.decode()
        assert "Mis grupos" in html and "Nuevo grupo" in html and "Grupos activos" in html
        assert "Materia" not in html and "materia" not in html

    def test_el_inicio_del_alumno_habla_de_grupos(self, student_client, enrollment):
        html = student_client.get(reverse("student_dashboard")).content.decode()
        assert "Mis grupos" in html and "Grupos inscritos" in html
        assert "Materia" not in html and "materia" not in html

    def test_el_detalle_y_el_formulario_hablan_de_grupos(self, professor_client, course):
        detalle = professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
        formulario = professor_client.get(reverse("course_create")).content.decode()
        assert "Materia" not in detalle and "materia" not in detalle
        assert "Nuevo grupo" in formulario and "materia" not in formulario.lower()

    def test_las_calificaciones_hablan_de_grupos(self, professor_client, course, enrollment):
        html = professor_client.get(reverse("grades:list")).content.decode()
        assert 'name="grupo"' in html and "Todos los grupos" in html and "materia" not in html.lower()

    def test_las_clases_css_son_de_grupo(self, professor_client, course):
        html = professor_client.get(reverse("professor_dashboard")).content.decode()
        assert "group-card" in html and "subject-" not in html

    def test_el_modelo_se_llama_grupo_en_el_admin(self):
        from apps.courses.models import Course

        assert (Course._meta.verbose_name, Course._meta.verbose_name_plural) == ("grupo", "grupos")


class TestExportacionPorGrupo:
    url = "grades:export"

    def filas(self, response):
        return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))

    @pytest.fixture
    def dos_grupos(self, professor):
        a, b = (ActivityFactory(course=CourseFactory(professor=professor)) for _ in range(2))
        GradeFactory(activity=a)
        GradeFactory(activity=b)
        return a, b

    def test_el_encabezado_dice_grupo(self, professor_client, dos_grupos):
        assert self.filas(professor_client.get(reverse(self.url)))[0][3] == "Grupo"

    def test_filtra_por_el_parametro_grupo(self, professor_client, dos_grupos):
        a, _ = dos_grupos
        filas = self.filas(professor_client.get(reverse(self.url), {"grupo": a.course_id}))
        assert [f[3] for f in filas[1:]] == [a.course.name]

    def test_el_parametro_viejo_materia_sigue_funcionando(self, professor_client, dos_grupos):
        a, _ = dos_grupos
        filas = self.filas(professor_client.get(reverse(self.url), {"materia": a.course_id}))
        assert [f[3] for f in filas[1:]] == [a.course.name]

    def test_el_parametro_nuevo_manda_sobre_el_viejo(self, professor_client, dos_grupos):
        a, b = dos_grupos
        filas = self.filas(professor_client.get(reverse(self.url), {"grupo": b.course_id, "materia": a.course_id}))
        assert [f[3] for f in filas[1:]] == [b.course.name]

    @pytest.mark.parametrize("texto", ["=cmd|' /C calc'!A0", "+1+1", "-2+3", "@SUM(1)"])
    def test_un_nombre_que_parece_formula_no_se_ejecuta_al_abrir_el_csv(self, professor_client, course, texto):
        activity = ActivityFactory(course=course, title=texto)
        alumno = EnrollmentFactory(course=course, student__user=None, student__first_name=texto, student__last_name="X").student
        GradeFactory(activity=activity, student=alumno)
        fila = self.filas(professor_client.get(reverse(self.url)))[1]
        assert all(not celda.startswith(("=", "+", "-", "@")) for celda in fila if celda)
        assert "'" + texto in fila[1] and "'" + texto in fila[4]

    @pytest.mark.parametrize("valor", ["abc", "1 OR 1=1", "²", "9" * 40])
    def test_valor_invalido_es_400(self, professor_client, valor):
        response = professor_client.get(reverse(self.url), {"grupo": valor})
        assert response.status_code == 400 and "grupo" in response.content.decode()
