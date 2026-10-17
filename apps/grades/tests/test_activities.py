"""Actividades: crear, publicar, borrador y vista del alumno."""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.courses.services.courses import archive_course
from apps.organizations.tests.factories import MembershipFactory
from apps.organizations.models import Membership

from apps.grades.tests.factories import ActivityFactory, GradeFactory
from apps.grades.models import Activity
from apps.grades.services.grading import results_by_course

pytestmark = pytest.mark.django_db

BASE = {
    "title": "Tarea 1", "type": "homework", "criterion": "", "max_score": "10", "weight": "1",
    "instructions": "Resuelve los ejercicios.", "allow_late": "on", "late_penalty": "10",
}


def crear(client, course, **cambios):
    return client.post(reverse("grades:activity_create", args=[course.pk]), {**BASE, **cambios})


# ── Crear y editar ────────────────────────────────────────────────────

class TestCrear:
    def test_el_formulario_se_abre_con_los_criterios_del_grupo(self, professor_client, course):
        response = professor_client.get(reverse("grades:activity_create", args=[course.pk]))
        assert response.status_code == 200
        assert {c.name for c in response.context["form"].fields["criterion"].queryset} == {"Exámenes", "Tareas", "Proyecto", "Quizzes"}

    def test_el_formulario_de_edicion_se_abre(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        assert professor_client.get(reverse("grades:activity_update", args=[actividad.pk])).status_code == 200

    def test_nace_como_borrador_en_el_grupo(self, professor_client, course):
        response = crear(professor_client, course)
        actividad = Activity.objects.get(title="Tarea 1")
        assert response.url == reverse("grades:activity_detail", args=[actividad.pk])
        assert (actividad.course, actividad.published, actividad.organization) == (course, False, course.organization)

    def test_el_criterio_automatico_sigue_al_tipo(self, professor_client, course):
        crear(professor_client, course, title="Examen 1", type="exam")
        assert Activity.objects.get(title="Examen 1").criterion.name == "Exámenes"

    def test_un_criterio_explicito_se_respeta(self, professor_client, course):
        proyecto = course.scheme.criteria().get(name="Proyecto")
        crear(professor_client, course, criterion=proyecto.pk)
        assert Activity.objects.get(title="Tarea 1").criterion == proyecto

    def test_no_acepta_un_criterio_de_otro_grupo(self, professor_client, course):
        ajeno = CourseFactory().scheme.criteria().first()
        response = crear(professor_client, course, criterion=ajeno.pk)
        assert response.status_code == 200 and "criterion" in response.context["form"].errors
        assert not Activity.objects.exists()

    def test_guarda_fechas_y_politica_de_tardias(self, professor_client, course):
        crear(professor_client, course, opens_at="2026-10-01T08:00", due_at="2026-10-10T23:59", late_penalty="15")
        actividad = Activity.objects.get()
        limite = timezone.localtime(actividad.due_at)  # se captura en la zona horaria del proyecto
        assert (limite.day, limite.hour, float(actividad.late_penalty)) == (10, 23, 15.0)

    def test_la_fecha_limite_no_puede_ser_anterior_a_la_apertura(self, professor_client, course):
        response = crear(professor_client, course, opens_at="2026-10-10T08:00", due_at="2026-10-01T08:00")
        assert response.status_code == 200 and "due_at" in response.context["form"].errors

    def test_sin_entregas_tardias_no_hay_penalizacion(self, professor_client, course):
        datos = {k: v for k, v in BASE.items() if k != "allow_late"}
        professor_client.post(reverse("grades:activity_create", args=[course.pk]), datos)
        actividad = Activity.objects.get()
        assert (actividad.allow_late, float(actividad.late_penalty)) == (False, 0.0)

    @pytest.mark.parametrize("cambios, campo", [
        ({"title": ""}, "title"), ({"max_score": "0"}, "max_score"), ({"weight": "-1"}, "weight"),
        ({"late_penalty": "101"}, "late_penalty"), ({"type": "otro"}, "type"),
    ])
    def test_datos_invalidos(self, professor_client, course, cambios, campo):
        response = crear(professor_client, course, **cambios)
        assert response.status_code == 200 and campo in response.context["form"].errors

    def test_edita(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        datos = {**BASE, "title": "Nuevo título", "criterion": actividad.criterion_id}
        professor_client.post(reverse("grades:activity_update", args=[actividad.pk]), datos)
        actividad.refresh_from_db()
        assert actividad.title == "Nuevo título"


class TestPermisos:
    def test_grupo_de_otro_docente_es_404(self, professor_client):
        ajeno = CourseFactory()
        assert professor_client.get(reverse("grades:activity_create", args=[ajeno.pk])).status_code == 404
        actividad = ActivityFactory(course=ajeno)
        for name in ("activity_detail", "activity_update"):
            assert professor_client.get(reverse(f"grades:{name}", args=[actividad.pk])).status_code == 404
        for name in ("activity_publish", "activity_delete"):
            assert professor_client.post(reverse(f"grades:{name}", args=[actividad.pk])).status_code == 404

    def test_grupo_archivado_es_de_solo_lectura(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        archive_course(course)
        assert professor_client.get(reverse("grades:activity_create", args=[course.pk])).status_code == 404
        assert professor_client.get(reverse("grades:activity_update", args=[actividad.pk])).status_code == 404
        assert professor_client.post(reverse("grades:activity_publish", args=[actividad.pk])).status_code == 404
        assert professor_client.post(reverse("grades:activity_delete", args=[actividad.pk])).status_code == 404
        # pero se puede consultar, sin acciones
        html = professor_client.get(reverse("grades:activity_detail", args=[actividad.pk])).content.decode()
        assert reverse("grades:activity_update", args=[actividad.pk]) not in html

    def test_el_alumno_no_gestiona_actividades(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        assert student_client.get(reverse("grades:activity_create", args=[course.pk])).status_code == 302
        assert student_client.post(reverse("grades:activity_publish", args=[actividad.pk])).status_code == 302
        actividad.refresh_from_db()
        assert actividad.published

    def test_otra_organizacion_activa_es_404(self, professor_client, professor):
        otra = MembershipFactory(user=professor, role=Membership.Role.TEACHER).organization
        ajeno = CourseFactory(professor=professor, organization=otra)
        assert professor_client.get(reverse("grades:activity_create", args=[ajeno.pk])).status_code == 404

    def test_anonimo_va_al_login(self, client, course):
        assert client.get(reverse("grades:activity_create", args=[course.pk])).url.startswith("/login/")


# ── Publicar, borrador y eliminar ─────────────────────────────────────

class TestPublicar:
    def test_alterna_entre_borrador_y_publicada(self, professor_client, course):
        actividad = ActivityFactory(course=course, published=False)
        url = reverse("grades:activity_publish", args=[actividad.pk])
        professor_client.post(url)
        actividad.refresh_from_db()
        assert actividad.published
        professor_client.post(url)
        actividad.refresh_from_db()
        assert not actividad.published

    def test_solo_acepta_post(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        assert professor_client.get(reverse("grades:activity_publish", args=[actividad.pk])).status_code == 405


class TestBorrador:
    @pytest.fixture
    def borrador(self, course, enrollment):
        actividad = ActivityFactory(course=course, published=False, title="Secreta")
        GradeFactory(activity=actividad, student=enrollment.student, score=9)
        return actividad

    def test_el_alumno_no_la_ve_en_el_grupo(self, student_client, course, borrador):
        html = student_client.get(course.get_absolute_url()).content.decode()
        assert "Secreta" not in html

    def test_el_alumno_no_entra_a_su_detalle(self, student_client, borrador):
        assert student_client.get(borrador.get_absolute_url()).status_code == 404

    def test_el_alumno_no_ve_su_nota_ni_en_la_lista_ni_en_la_exportacion(self, student_client, borrador):
        assert list(student_client.get(reverse("grades:list")).context["grades"]) == []
        assert "Secreta" not in student_client.get(reverse("grades:export")).content.decode("utf-8-sig")

    def test_no_cuenta_para_su_calificacion_final(self, student_client, course, borrador):
        assert student_client.get(reverse("student_dashboard")).context["average"] is None
        assert student_client.get(course.get_absolute_url()).context["course_average"] is None

    def test_no_cuenta_para_el_docente_hasta_publicarla(self, professor_client, course, borrador):
        antes = professor_client.get(course.get_absolute_url()).context["enrollments"][0].result
        assert antes.final is None and antes.graded == 0
        borrador.published = True
        borrador.save()
        despues = professor_client.get(course.get_absolute_url()).context["enrollments"][0].result
        assert despues.final == 9.0

    def test_no_genera_notificaciones_al_alumno(self, student_client, borrador):
        assert [n for n in student_client.get(reverse("grades:list")).context["notifications"] if n["type"] == "grade"] == []

    def test_el_docente_si_la_ve_con_su_estado(self, professor_client, course, borrador):
        html = professor_client.get(course.get_absolute_url()).content.decode()
        assert "Secreta" in html and "Borrador" in html

    def test_al_publicarla_el_alumno_la_ve_con_su_nota(self, student_client, course, borrador):
        borrador.published = True
        borrador.save()
        assert "Secreta" in student_client.get(course.get_absolute_url()).content.decode()
        assert student_client.get(reverse("student_dashboard")).context["average"] == 9.0


class TestEliminar:
    def test_elimina_una_actividad_sin_notas(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        response = professor_client.post(reverse("grades:activity_delete", args=[actividad.pk]), follow=True)
        assert not Activity.objects.filter(pk=actividad.pk).exists()
        assert response.redirect_chain[-1][0] == course.get_absolute_url()

    def test_no_elimina_una_con_calificaciones(self, professor_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        GradeFactory(activity=actividad, student=enrollment.student)
        response = professor_client.post(reverse("grades:activity_delete", args=[actividad.pk]), follow=True)
        assert Activity.objects.filter(pk=actividad.pk).exists()
        assert any("calificaciones" in str(m) for m in response.context["messages"])

    def test_solo_acepta_post(self, professor_client, course):
        actividad = ActivityFactory(course=course)
        assert professor_client.get(reverse("grades:activity_delete", args=[actividad.pk])).status_code == 405


# ── Detalle ───────────────────────────────────────────────────────────

class TestDetalle:
    def test_el_docente_ve_a_sus_alumnos_con_la_nota(self, professor_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        GradeFactory(activity=actividad, student=enrollment.student, score=8, feedback="Muy bien")
        EnrollmentFactory(course=course)  # otro alumno, sin calificar
        context = professor_client.get(actividad.get_absolute_url()).context
        assert context["graded_count"] == 1
        notas = {e.student_id: e.grade for e in context["enrollments"]}
        assert notas[enrollment.student_id].score == 8
        assert None in notas.values()

    def test_el_alumno_ve_la_actividad_y_su_calificacion_con_el_comentario(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, instructions="Haz esto")
        GradeFactory(activity=actividad, student=enrollment.student, score=8, feedback="Muy bien")
        html = student_client.get(actividad.get_absolute_url()).content.decode()
        assert "Haz esto" in html and "Muy bien" in html and "Tu calificación" in html

    def test_el_alumno_no_ve_las_notas_de_otros(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        otro = EnrollmentFactory(course=course).student
        GradeFactory(activity=actividad, student=otro, score=3, feedback="Privado")
        assert "Privado" not in student_client.get(actividad.get_absolute_url()).content.decode()

    def test_un_alumno_no_inscrito_no_la_ve(self, student_client, enrollment):
        ajena = ActivityFactory()  # otro grupo
        assert student_client.get(ajena.get_absolute_url()).status_code == 404

    def test_enlaces_desde_el_grupo(self, professor_client, student_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        assert actividad.get_absolute_url() in professor_client.get(course.get_absolute_url()).content.decode()
        assert actividad.get_absolute_url() in student_client.get(course.get_absolute_url()).content.decode()

    def test_las_instrucciones_se_escapan(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, instructions="<script>alert(1)</script>")
        html = student_client.get(actividad.get_absolute_url()).content.decode()
        assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html

    def test_la_lista_del_grupo_cuenta_las_calificadas(self, professor_client, course, enrollment):
        actividad = ActivityFactory(course=course)
        GradeFactory(activity=actividad, student=enrollment.student)
        (fila,) = professor_client.get(course.get_absolute_url()).context["activities"]
        assert (fila.pk, fila.graded) == (actividad.pk, 1)


def test_el_calculo_ignora_borradores_con_modelos_reales(course, enrollment):
    publicada = ActivityFactory(course=course, published=True)
    borrador = ActivityFactory(course=course, published=False)
    notas = [GradeFactory(activity=publicada, student=enrollment.student, score=6), GradeFactory(activity=borrador, student=enrollment.student, score=10)]
    assert results_by_course(notas)[course.pk].final == 6.0


def test_la_fecha_limite_conserva_la_zona_horaria(professor_client, course):
    crear(professor_client, course, due_at="2026-10-10T23:59")
    due = Activity.objects.get().due_at
    assert timezone.is_aware(due) and timezone.localtime(due).hour == 23
    assert isinstance(due, datetime.datetime)
