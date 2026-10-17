"""Pantallas de grupos y ciclos: crear, editar, archivar, duplicar y cambiar de ciclo."""

import pytest
from django.urls import reverse

from apps.grades.factories import ActivityFactory, GradeFactory
from apps.grades.models import Grade
from apps.organizations.tests.factories import MembershipFactory, OrganizationFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY

from apps.courses.tests.factories import AcademicYearFactory, CourseFactory, EnrollmentFactory
from apps.courses.models import AcademicYear, Course
from apps.courses.services.courses import archive_course

pytestmark = pytest.mark.django_db

DATOS = {"name": "Álgebra", "code": "ALG1", "schedule": "Lun 8:00", "color": "#336699", "description": "Intro"}


def _mensajes(response):
    return [str(m) for m in response.context["messages"]]


# ── Crear ─────────────────────────────────────────────────────────────

class TestCrear:
    def test_el_formulario_ofrece_el_ciclo_actual(self, professor_client, course):
        form = professor_client.get(reverse("course_create")).context["form"]
        assert form.fields["academic_year"].initial == course.academic_year

    def test_crea_el_grupo_del_docente_en_su_organizacion_y_ciclo(self, professor_client, professor, course):
        response = professor_client.post(
            reverse("course_create"), {**DATOS, "academic_year": course.academic_year_id}, follow=True,
        )
        nuevo = Course.objects.get(code="ALG1")
        assert response.redirect_chain[-1][0] == reverse("course_detail", args=[nuevo.pk])
        assert (nuevo.professor, nuevo.organization, nuevo.academic_year) == (
            professor, course.organization, course.academic_year,
        )
        assert nuevo.color == "#336699"
        assert 'Se creó el grupo "Álgebra".' in _mensajes(response)

    def test_rechaza_un_codigo_repetido_en_el_ciclo(self, professor_client, course):
        datos = {**DATOS, "code": course.code, "academic_year": course.academic_year_id}
        response = professor_client.post(reverse("course_create"), datos)
        assert response.status_code == 200
        assert "code" in response.context["form"].errors
        assert Course.objects.count() == 1

    def test_acepta_el_mismo_codigo_en_otro_ciclo(self, professor_client, course):
        otro = AcademicYearFactory(organization=course.organization)
        datos = {**DATOS, "code": course.code, "academic_year": otro.pk}
        assert professor_client.post(reverse("course_create"), datos).status_code == 302
        assert Course.objects.filter(code=course.code).count() == 2

    def test_no_ofrece_ciclos_de_otra_organizacion(self, professor_client, course):
        ajeno = AcademicYearFactory()
        response = professor_client.post(reverse("course_create"), {**DATOS, "academic_year": ajeno.pk})
        assert response.status_code == 200 and "academic_year" in response.context["form"].errors
        assert Course.objects.count() == 1

    def test_el_alumno_no_puede_crear(self, student_client, enrollment):
        assert student_client.get(reverse("course_create")).url == reverse("student_dashboard")
        assert student_client.post(reverse("course_create"), DATOS).status_code == 302
        assert not Course.objects.filter(code="ALG1").exists()

    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("course_create")).url.startswith("/login/")


# ── Editar ────────────────────────────────────────────────────────────

class TestEditar:
    def test_edita_su_grupo(self, professor_client, course):
        datos = {**DATOS, "code": course.code, "academic_year": course.academic_year_id, "name": "Nuevo nombre"}
        assert professor_client.post(reverse("course_update", args=[course.pk]), datos).status_code == 302
        course.refresh_from_db()
        assert course.name == "Nuevo nombre"

    def test_conservar_su_propio_codigo_no_cuenta_como_repetido(self, professor_client, course):
        response = professor_client.get(reverse("course_update", args=[course.pk]))
        assert response.status_code == 200

    def test_no_edita_el_grupo_de_otro_docente(self, professor_client):
        ajeno = CourseFactory()
        assert professor_client.get(reverse("course_update", args=[ajeno.pk])).status_code == 404

    def test_un_grupo_archivado_no_se_edita(self, professor_client, course):
        archive_course(course)
        assert professor_client.get(reverse("course_update", args=[course.pk])).status_code == 404


# ── Archivar / desarchivar ────────────────────────────────────────────

class TestArchivar:
    def test_archiva_y_sale_de_la_vista_principal(self, professor_client, course, enrollment):
        response = professor_client.post(reverse("course_archive", args=[course.pk]), follow=True)
        course.refresh_from_db()
        assert course.is_archived
        assert response.redirect_chain[-1][0] == reverse("professor_dashboard")
        assert response.context["courses"] == []
        assert [c.pk for c in response.context["archived_courses"]] == [course.pk]
        assert response.context["total_students"] == 0  # las estadísticas cubren solo grupos activos

    def test_solo_acepta_post(self, professor_client, course):
        assert professor_client.get(reverse("course_archive", args=[course.pk])).status_code == 405

    def test_no_archiva_el_grupo_de_otro_docente(self, professor_client):
        ajeno = CourseFactory()
        assert professor_client.post(reverse("course_archive", args=[ajeno.pk])).status_code == 404
        ajeno.refresh_from_db()
        assert not ajeno.is_archived

    def test_el_alumno_no_puede_archivar(self, student_client, course, enrollment):
        assert student_client.post(reverse("course_archive", args=[course.pk])).status_code == 302
        course.refresh_from_db()
        assert not course.is_archived

    def test_desarchiva(self, professor_client, course):
        archive_course(course)
        response = professor_client.post(reverse("course_unarchive", args=[course.pk]))
        course.refresh_from_db()
        assert response.status_code == 302 and not course.is_archived

    def test_el_detalle_archivado_sigue_siendo_consultable_y_ofrece_desarchivar(self, professor_client, course, enrollment):
        archive_course(course)
        html = professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()
        assert "Archivado" in html
        assert reverse("course_unarchive", args=[course.pk]) in html
        assert reverse("course_update", args=[course.pk]) not in html
        assert "/admin/courses/enrollment/add/" not in html

    def test_el_alumno_ve_el_grupo_archivado_como_ciclo_anterior(self, student_client, course, enrollment):
        archive_course(course)
        context = student_client.get(reverse("student_dashboard")).context
        assert context["enrollments"] == []
        assert [e.course for e in context["archived_enrollments"]] == [course]
        assert student_client.get(reverse("course_detail", args=[course.pk])).status_code == 200


class TestNotasEnGrupoArchivado:
    @pytest.fixture
    def nota(self, course, activity, enrollment):
        nota = GradeFactory(activity=activity, student=enrollment.student, score=7)
        archive_course(course)
        return nota

    def test_no_se_edita_ni_se_elimina(self, professor_client, nota):
        for name in ("grades:update", "grades:delete"):
            url = reverse(name, args=[nota.pk])
            assert professor_client.get(url).status_code == 404
            assert professor_client.post(url, {"score": 1}).status_code == 404
        assert Grade.objects.get(pk=nota.pk).score == 7

    def test_el_formulario_no_ofrece_sus_evaluaciones_ni_alumnos(self, professor_client, nota):
        form = professor_client.get(reverse("grades:create")).context["form"]
        assert list(form.fields["activity"].queryset) == []
        assert list(form.fields["student"].queryset) == []

    def test_sigue_en_el_listado_y_la_exportacion(self, professor_client, nota):
        assert [g.pk for g in professor_client.get(reverse("grades:list")).context["grades"]] == [nota.pk]
        assert nota.student.email in professor_client.get(reverse("grades:export")).content.decode("utf-8-sig")

    def test_la_validacion_del_formulario_rechaza_el_grupo_archivado(self, professor_client, nota, activity):
        # Aunque alguien fabrique la petición, ni el formulario ni el modelo lo aceptan.
        response = professor_client.post(
            reverse("grades:create"), {"activity": activity.pk, "student": nota.student.pk, "score": 5},
        )
        assert response.status_code == 200 and response.context["form"].errors
        assert Grade.objects.count() == 1


# ── Duplicar ──────────────────────────────────────────────────────────

class TestDuplicar:
    @pytest.fixture
    def nuevo_ciclo(self, course):
        return AcademicYearFactory(organization=course.organization, name="2027–2028")

    def test_el_formulario_propone_los_datos_actuales(self, professor_client, course, nuevo_ciclo):
        form = professor_client.get(reverse("course_clone", args=[course.pk])).context["form"]
        assert (form.fields["name"].initial, form.fields["code"].initial) == (course.name, course.code)
        assert list(form.fields["academic_year"].queryset) == [nuevo_ciclo]  # no su propio ciclo

    def test_duplica_con_sus_evaluaciones(self, professor_client, course, nuevo_ciclo):
        ActivityFactory(course=course, title="Parcial")
        response = professor_client.post(
            reverse("course_clone", args=[course.pk]),
            {"academic_year": nuevo_ciclo.pk, "name": course.name, "code": course.code},
            follow=True,
        )
        copia = Course.objects.get(academic_year=nuevo_ciclo)
        assert response.redirect_chain[-1][0] == reverse("course_detail", args=[copia.pk])
        assert [e.title for e in copia.activities.all()] == ["Parcial"]
        assert any("2027–2028" in m for m in _mensajes(response))

    def test_codigo_repetido_en_el_destino_muestra_el_error(self, professor_client, course, nuevo_ciclo):
        CourseFactory(professor=course.professor, code=course.code, academic_year=nuevo_ciclo)
        response = professor_client.post(
            reverse("course_clone", args=[course.pk]),
            {"academic_year": nuevo_ciclo.pk, "name": course.name, "code": course.code},
        )
        assert response.status_code == 200
        assert "Ya existe un grupo" in str(response.context["form"].non_field_errors())
        assert Course.objects.filter(academic_year=nuevo_ciclo).count() == 1

    def test_sin_otro_ciclo_remite_a_crearlo(self, professor_client, course):
        html = professor_client.get(reverse("course_clone", args=[course.pk])).content.decode()
        assert reverse("academic_years") in html

    def test_no_se_duplica_el_grupo_de_otro_docente(self, professor_client):
        assert professor_client.get(reverse("course_clone", args=[CourseFactory().pk])).status_code == 404

    def test_no_se_puede_duplicar_a_un_ciclo_de_otra_organizacion(self, professor_client, course):
        ajeno = AcademicYearFactory()
        response = professor_client.post(
            reverse("course_clone", args=[course.pk]), {"academic_year": ajeno.pk, "name": "X", "code": "X"},
        )
        assert response.status_code == 200 and "academic_year" in response.context["form"].errors
        assert not Course.objects.filter(academic_year=ajeno).exists()

    def test_se_puede_duplicar_un_grupo_archivado(self, professor_client, course, nuevo_ciclo):
        archive_course(course)
        response = professor_client.post(
            reverse("course_clone", args=[course.pk]),
            {"academic_year": nuevo_ciclo.pk, "name": course.name, "code": course.code},
        )
        assert response.status_code == 302 and Course.objects.filter(academic_year=nuevo_ciclo).exists()


# ── Ciclos escolares ──────────────────────────────────────────────────

class TestCiclos:
    def test_lista_los_ciclos_de_la_organizacion_con_su_numero_de_grupos(self, professor_client, course):
        AcademicYearFactory()  # otra organización: no debe aparecer
        years = professor_client.get(reverse("academic_years")).context["years"]
        assert [(y.pk, y.course_count) for y in years] == [(course.academic_year_id, 1)]

    def test_crea_un_ciclo(self, professor_client, course):
        datos = {"name": "2027–2028", "start_date": "2027-08-01", "end_date": "2028-07-31"}
        response = professor_client.post(reverse("academic_years"), datos, follow=True)
        year = AcademicYear.objects.get(name="2027–2028")
        assert year.organization == course.organization and not year.is_current
        assert "Se creó el ciclo 2027–2028." in _mensajes(response)

    def test_crear_uno_como_actual_desmarca_el_anterior(self, professor_client, course):
        datos = {"name": "Nuevo", "start_date": "2027-08-01", "end_date": "2028-07-31", "is_current": "on"}
        professor_client.post(reverse("academic_years"), datos)
        course.academic_year.refresh_from_db()
        assert not course.academic_year.is_current
        assert AcademicYear.objects.get(name="Nuevo").is_current

    @pytest.mark.parametrize("datos, campo", [
        ({"name": "X", "start_date": "2027-08-01", "end_date": "2027-01-01"}, "end_date"),
        ({"name": "", "start_date": "2027-08-01", "end_date": "2028-07-31"}, "name"),
        ({"name": "X", "start_date": "no", "end_date": "2028-07-31"}, "start_date"),
    ])
    def test_rechaza_datos_invalidos(self, professor_client, course, datos, campo):
        response = professor_client.post(reverse("academic_years"), datos)
        assert response.status_code == 200 and campo in response.context["form"].errors

    def test_rechaza_un_nombre_repetido(self, professor_client, course):
        datos = {"name": course.academic_year.name, "start_date": "2027-08-01", "end_date": "2028-07-31"}
        response = professor_client.post(reverse("academic_years"), datos)
        assert "name" in response.context["form"].errors

    def test_marca_un_ciclo_como_actual(self, professor_client, course):
        otro = AcademicYearFactory(organization=course.organization)
        assert professor_client.post(reverse("academic_year_current", args=[otro.pk])).status_code == 302
        otro.refresh_from_db()
        course.academic_year.refresh_from_db()
        assert otro.is_current and not course.academic_year.is_current

    def test_no_marca_el_ciclo_de_otra_organizacion(self, professor_client, course):
        ajeno = AcademicYearFactory()
        assert professor_client.post(reverse("academic_year_current", args=[ajeno.pk])).status_code == 404
        ajeno.refresh_from_db()
        assert not ajeno.is_current

    def test_el_alumno_no_accede(self, student_client, enrollment):
        assert student_client.get(reverse("academic_years")).status_code == 302
        assert student_client.post(reverse("academic_year_current", args=[1])).status_code == 302


# ── Alcance por organización activa ───────────────────────────────────

class TestOtraOrganizacion:
    @pytest.fixture
    def ajeno(self, professor, course):
        """Grupo del mismo docente, pero en otra organización donde también es docente."""
        otra = OrganizationFactory()
        MembershipFactory(user=professor, organization=otra, role=Membership.Role.TEACHER)
        return CourseFactory(professor=professor, organization=otra)

    @pytest.mark.parametrize("name, metodo", [
        ("course_update", "get"), ("course_archive", "post"), ("course_unarchive", "post"), ("course_clone", "get"),
    ])
    def test_el_grupo_de_la_organizacion_no_activa_es_404(self, professor_client, ajeno, name, metodo):
        assert getattr(professor_client, metodo)(reverse(name, args=[ajeno.pk])).status_code == 404

    def test_cambiando_de_organizacion_si_se_puede(self, professor_client, ajeno):
        session = professor_client.session
        session[SESSION_KEY] = ajeno.organization_id
        session.save()
        assert professor_client.get(reverse("course_update", args=[ajeno.pk])).status_code == 200
