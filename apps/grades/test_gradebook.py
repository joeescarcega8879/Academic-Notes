"""Calificar: penalización por entrega tardía, bitácora de cambios y pantalla de calificación."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.accounts.factories import ProfessorFactory
from apps.courses.factories import CourseFactory, EnrollmentFactory, StudentRecordFactory
from apps.courses.services.courses import archive_course

from .factories import ActivityFactory, GradeFactory
from .models import Activity, Grade, GradeHistory, apply_late_penalty
from .services.gradebook import grade_activity, late_penalty_for, remove_grade
from .services.grading import results_by_course
from .services.submissions import submit

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


@pytest.fixture
def tarea(course):
    return ActivityFactory(
        course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20, max_score=10,
    )


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


# ── La penalización ───────────────────────────────────────────────────

class TestPenalizacion:
    @pytest.mark.parametrize("nota, pct, esperado", [
        (10, 0, 10.0), (10, 20, 8.0), (10, 100, 0.0), (7.5, 10, 6.75), (3.33, 15, 2.83), (8, 12.5, 7.0), (0, 50, 0.0),
    ])
    def test_calculo(self, nota, pct, esperado):
        assert apply_late_penalty(nota, pct) == esperado

    def test_redondea_mitad_hacia_arriba(self):
        assert apply_late_penalty(5.05, 10) == 4.55  # 4.545 -> 4.55 (el redondeo de Python daría 4.54)

    def test_una_entrega_tardia_se_penaliza(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        nota = grade_activity(tarea, alumno, score=10)
        assert (nota.raw_score, nota.score, float(nota.late_penalty)) == (10, 8.0, 20.0)

    def test_una_entrega_a_tiempo_no(self, tarea, alumno):
        submit(tarea, alumno, text="a tiempo", now=AHORA - 2 * UN_DIA)
        assert grade_activity(tarea, alumno, score=10).score == 10

    def test_sin_entrega_no_hay_penalizacion(self, tarea, alumno):
        assert grade_activity(tarea, alumno, score=10).score == 10

    def test_se_puede_perdonar(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        nota = grade_activity(tarea, alumno, score=10, waive_penalty=True)
        assert (nota.score, float(nota.late_penalty)) == (10, 0.0)

    def test_recalificar_nunca_aplica_la_penalizacion_dos_veces(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        grade_activity(tarea, alumno, score=10)
        assert grade_activity(tarea, alumno, score=10).score == 8.0
        assert grade_activity(tarea, alumno, score=9).score == 7.2
        assert Grade.objects.count() == 1

    def test_una_actividad_sin_penalizacion_no_reduce(self, course, alumno):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, late_penalty=0)
        submit(actividad, alumno, text="tarde", now=AHORA)
        assert grade_activity(actividad, alumno, score=10).score == 10

    def test_late_penalty_for(self, tarea, alumno):
        assert late_penalty_for(tarea, alumno) == 0
        submit(tarea, alumno, text="tarde", now=AHORA)
        assert late_penalty_for(tarea, alumno) == 20

    def test_la_calificacion_efectiva_es_la_que_cuenta_para_la_final(self, tarea, alumno, course):
        submit(tarea, alumno, text="tarde", now=AHORA)
        nota = grade_activity(tarea, alumno, score=10)
        assert results_by_course([nota])[course.pk].final == 8.0

    def test_una_calificacion_creada_sin_el_servicio_no_tiene_penalizacion(self, tarea, alumno):
        nota = Grade.objects.create(activity=tarea, student=alumno, score=7)
        assert (nota.raw_score, nota.score) == (7, 7)


# ── Validaciones del servicio ─────────────────────────────────────────

class TestValidaciones:
    @pytest.mark.parametrize("nota, mensaje", [(-1, "negativa"), (10.01, "máximo de 10"), (None, "negativa")])
    def test_rango(self, tarea, alumno, nota, mensaje):
        with pytest.raises(ValidationError, match=mensaje):
            grade_activity(tarea, alumno, score=nota)
        assert not Grade.objects.exists()

    def test_los_extremos_son_validos(self, tarea, alumno):
        assert grade_activity(tarea, alumno, score=0).score == 0
        assert grade_activity(tarea, alumno, score=10).score == 10

    def test_el_alumno_debe_estar_inscrito(self, tarea, course):
        with pytest.raises(ValidationError, match="no está inscrito"):
            grade_activity(tarea, StudentRecordFactory(organization=course.organization), score=5)

    def test_un_grupo_archivado_no_se_califica(self, tarea, alumno, course):
        archive_course(course)
        with pytest.raises(ValidationError, match="archivado"):
            grade_activity(tarea, alumno, score=5)

    def test_el_comentario_se_limpia(self, tarea, alumno):
        assert grade_activity(tarea, alumno, score=5, feedback="  Bien  ").feedback == "Bien"


# ── Bitácora ──────────────────────────────────────────────────────────

class TestBitacora:
    def test_calificar_deja_constancia(self, tarea, alumno, professor):
        grade_activity(tarea, alumno, score=8, feedback="Bien", by=professor)
        (h,) = GradeHistory.objects.all()
        assert (h.action, h.old_score, h.new_score, h.new_feedback, h.changed_by) == ("created", None, 8, "Bien", professor)
        assert (h.student, h.activity, h.activity_title, h.student_name) == (alumno, tarea, tarea.title, str(alumno))
        assert h.organization_id == tarea.organization_id

    def test_cambiar_la_nota_registra_antes_y_despues(self, tarea, alumno, professor):
        grade_activity(tarea, alumno, score=8, feedback="Bien", by=professor)
        grade_activity(tarea, alumno, score=9, feedback="Muy bien", by=professor)
        ultimo = GradeHistory.objects.first()
        assert (ultimo.action, ultimo.old_score, ultimo.new_score) == ("updated", 8, 9)
        assert (ultimo.old_feedback, ultimo.new_feedback) == ("Bien", "Muy bien")

    def test_cambiar_solo_el_comentario_tambien_cuenta(self, tarea, alumno, professor):
        grade_activity(tarea, alumno, score=8, feedback="a", by=professor)
        grade_activity(tarea, alumno, score=8, feedback="b", by=professor)
        assert GradeHistory.objects.count() == 2

    def test_guardar_sin_cambios_no_ensucia_la_bitacora(self, tarea, alumno, professor):
        grade_activity(tarea, alumno, score=8, feedback="a", by=professor)
        grade_activity(tarea, alumno, score=8, feedback="a", by=professor)
        assert GradeHistory.objects.count() == 1

    def test_la_penalizacion_queda_registrada(self, tarea, alumno, professor):
        submit(tarea, alumno, text="tarde", now=AHORA)
        grade_activity(tarea, alumno, score=10, by=professor)
        h = GradeHistory.objects.get()
        assert (h.new_score, float(h.late_penalty)) == (8.0, 20.0)

    def test_eliminar_deja_constancia(self, tarea, alumno, professor):
        nota = grade_activity(tarea, alumno, score=8, feedback="a", by=professor)
        remove_grade(nota, by=professor)
        h = GradeHistory.objects.first()
        assert (h.action, h.old_score, h.new_score, h.changed_by) == ("deleted", 8, None, professor)
        assert h.grade is None and not Grade.objects.exists()

    def test_cualquier_via_queda_registrada_aunque_no_se_conozca_quien(self, tarea, alumno):
        nota = GradeFactory(activity=tarea, student=alumno, score=6)  # sin pasar por el servicio
        nota.raw_score = 7
        nota.save()
        assert [h.action for h in GradeHistory.objects.order_by("id")] == ["created", "updated"]
        assert {h.changed_by for h in GradeHistory.objects.all()} == {None}

    def test_el_historial_sobrevive_al_borrado_de_la_actividad(self, course, alumno, professor):
        actividad = ActivityFactory(course=course)
        grade_activity(actividad, alumno, score=8, by=professor)
        titulo, nombre = actividad.title, str(alumno)
        actividad.grades.all().delete()
        actividad.delete()
        h = GradeHistory.objects.filter(action="deleted").first()
        assert h is not None and (h.activity, h.activity_title, h.student_name) == (None, titulo, nombre)
        assert GradeHistory.objects.filter(action="created").exists()

    def test_borrar_al_docente_no_borra_la_bitacora(self, tarea, alumno):
        docente = ProfessorFactory()
        grade_activity(tarea, alumno, score=8, by=docente)
        docente.delete()
        assert GradeHistory.objects.get().changed_by is None

    def test_orden_del_mas_reciente_al_mas_antiguo(self, tarea, alumno, professor):
        for nota in (5, 6, 7):
            grade_activity(tarea, alumno, score=nota, by=professor)
        assert [h.new_score for h in GradeHistory.objects.all()] == [7, 6, 5]


# ── Pantalla de calificación ──────────────────────────────────────────

class TestPantallaDeCalificacion:
    def url(self, actividad):
        return reverse("grades:activity_grading", args=[actividad.pk])

    @pytest.fixture
    def grupo(self, course, enrollment):
        otro = EnrollmentFactory(course=course).student
        actividad = ActivityFactory(course=course, type=Activity.Type.PARTICIPATION, max_score=10)
        return actividad, enrollment.student, otro

    def test_lista_a_los_alumnos_del_grupo(self, professor_client, grupo):
        actividad, uno, otro = grupo
        filas = professor_client.get(self.url(actividad)).context["rows"]
        assert {f["student"] for f in filas} == {uno, otro}

    def test_califica_a_varios_a_la_vez(self, professor_client, grupo, professor):
        actividad, uno, otro = grupo
        response = professor_client.post(self.url(actividad), {
            f"score_{uno.pk}": "9", f"feedback_{uno.pk}": "Participó mucho", f"score_{otro.pk}": "7,5",
        }, follow=True)
        assert response.redirect_chain[-1][0] == actividad.get_absolute_url()
        assert any("2 calificaciones" in str(m) for m in response.context["messages"])
        assert Grade.objects.get(student=uno).feedback == "Participó mucho"
        assert Grade.objects.get(student=otro).score == 7.5
        assert {h.changed_by for h in GradeHistory.objects.all()} == {professor}

    def test_una_fila_vacia_no_toca_la_nota_que_ya_habia(self, professor_client, grupo):
        actividad, uno, otro = grupo
        grade_activity(actividad, uno, score=6)
        professor_client.post(self.url(actividad), {f"score_{uno.pk}": "", f"score_{otro.pk}": "8"})
        assert Grade.objects.get(student=uno).score == 6 and Grade.objects.get(student=otro).score == 8

    def test_corrige_una_nota_existente(self, professor_client, grupo):
        actividad, uno, _ = grupo
        grade_activity(actividad, uno, score=6, feedback="regular")
        professor_client.post(self.url(actividad), {f"score_{uno.pk}": "8", f"feedback_{uno.pk}": "mejoró"})
        nota = Grade.objects.get(student=uno)
        assert (nota.raw_score, nota.feedback) == (8, "mejoró")

    @pytest.mark.parametrize("valor", ["abc", "-1", "11", "1e999", "nan"])
    def test_si_una_fila_es_invalida_no_se_guarda_ninguna(self, professor_client, grupo, valor):
        actividad, uno, otro = grupo
        response = professor_client.post(self.url(actividad), {f"score_{uno.pk}": "9", f"score_{otro.pk}": valor})
        assert response.status_code == 200
        assert not Grade.objects.exists()
        filas = {f["student"].pk: f for f in response.context["rows"]}
        assert filas[otro.pk]["error"] and not filas[uno.pk].get("error")
        assert filas[uno.pk]["input"]["score"] == "9"  # lo escrito se conserva

    def test_la_penalizacion_se_aplica_y_se_puede_perdonar(self, professor_client, tarea, course, enrollment):
        otro = EnrollmentFactory(course=course).student
        for estudiante in (enrollment.student, otro):
            submit(tarea, estudiante, text="tarde", now=AHORA)
        professor_client.post(self.url(tarea), {
            f"score_{enrollment.student.pk}": "10", f"score_{otro.pk}": "10", f"waive_{otro.pk}": "on",
        })
        assert Grade.objects.get(student=enrollment.student).score == 8.0
        assert Grade.objects.get(student=otro).score == 10

    def test_muestra_la_entrega_y_si_es_tardia(self, professor_client, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        html = professor_client.get(self.url(tarea)).content.decode()
        assert "Ver entrega" in html and "Tardía" in html and "Sin penalización" in html

    def test_se_puede_calificar_un_borrador(self, professor_client, course, alumno):
        borrador = ActivityFactory(course=course, published=False)
        professor_client.post(self.url(borrador), {f"score_{alumno.pk}": "7"})
        assert Grade.objects.get().score == 7

    def test_ignora_alumnos_que_no_son_del_grupo(self, professor_client, grupo):
        actividad, _, _ = grupo
        ajeno = EnrollmentFactory().student
        professor_client.post(self.url(actividad), {f"score_{ajeno.pk}": "10"})
        assert not Grade.objects.exists()

    def test_otro_docente_no_puede(self, professor_client):
        ajena = ActivityFactory()
        assert professor_client.get(self.url(ajena)).status_code == 404
        assert professor_client.post(self.url(ajena), {}).status_code == 404

    def test_grupo_archivado_es_404(self, professor_client, grupo, course):
        actividad, _, _ = grupo
        archive_course(course)
        assert professor_client.get(self.url(actividad)).status_code == 404

    def test_el_alumno_no_accede(self, student_client, grupo):
        actividad, _, _ = grupo
        assert student_client.get(self.url(actividad)).status_code == 302
        assert student_client.post(self.url(actividad), {}).status_code == 302

    def test_anonimo_va_al_login(self, client, grupo):
        assert client.get(self.url(grupo[0])).url.startswith("/login/")


# ── Formularios clásicos de calificación ──────────────────────────────

class TestFormulariosClasicos:
    def test_crear_viene_con_la_actividad_y_el_alumno_elegidos(self, professor_client, course, enrollment, activity):
        response = professor_client.get(reverse("grades:create"), {"activity": activity.pk, "student": enrollment.student.pk})
        assert response.context["form"].initial == {"activity": activity.pk, "student": enrollment.student.pk}

    def test_crear_pasa_por_el_servicio(self, professor_client, tarea, alumno, professor):
        submit(tarea, alumno, text="tarde", now=AHORA)
        professor_client.post(reverse("grades:create"), {"activity": tarea.pk, "student": alumno.pk, "score": "10", "feedback": "ok"})
        nota = Grade.objects.get()
        assert (nota.score, nota.raw_score, nota.feedback) == (8.0, 10, "ok")
        assert GradeHistory.objects.get().changed_by == professor

    def test_editar_cambia_la_nota_y_deja_historial(self, professor_client, activity, enrollment, professor):
        nota = grade_activity(activity, enrollment.student, score=6, by=professor)
        professor_client.post(reverse("grades:update", args=[nota.pk]), {
            "activity": activity.pk, "student": enrollment.student.pk, "score": "9", "feedback": "mejor",
        })
        nota.refresh_from_db()
        assert (nota.score, nota.feedback) == (9, "mejor")
        assert GradeHistory.objects.first().action == "updated"

    def test_editar_no_permite_cambiar_alumno_ni_actividad(self, professor_client, course, activity, enrollment, professor):
        otro = EnrollmentFactory(course=course).student
        otra = ActivityFactory(course=course)
        nota = grade_activity(activity, enrollment.student, score=6, by=professor)
        professor_client.post(reverse("grades:update", args=[nota.pk]), {
            "activity": otra.pk, "student": otro.pk, "score": "9", "feedback": "",
        })
        nota.refresh_from_db()
        assert (nota.student, nota.activity, nota.score) == (enrollment.student, activity, 9)
        assert Grade.objects.count() == 1

    def test_eliminar_deja_constancia(self, professor_client, activity, enrollment, professor):
        nota = grade_activity(activity, enrollment.student, score=6, by=professor)
        professor_client.post(reverse("grades:delete", args=[nota.pk]))
        assert not Grade.objects.exists()
        h = GradeHistory.objects.first()
        assert (h.action, h.changed_by) == ("deleted", professor)

    def test_no_se_puede_calificar_dos_veces_con_el_formulario_de_alta(self, professor_client, activity, enrollment, professor):
        grade_activity(activity, enrollment.student, score=6, by=professor)
        response = professor_client.post(reverse("grades:create"), {
            "activity": activity.pk, "student": enrollment.student.pk, "score": "9", "feedback": "",
        })
        assert response.status_code == 200 and Grade.objects.get().score == 6


# ── Historial y lo que ve el alumno ───────────────────────────────────

class TestHistorialYAlumno:
    def test_el_docente_ve_el_historial(self, professor_client, activity, enrollment, professor):
        grade_activity(activity, enrollment.student, score=6, by=professor)
        grade_activity(activity, enrollment.student, score=9, by=professor)
        response = professor_client.get(reverse("grades:activity_history", args=[activity.pk]))
        assert [(h.old_score, h.new_score) for h in response.context["history"]] == [(6, 9), (None, 6)]
        assert "Cambió la calificación" in response.content.decode()

    def test_otro_docente_no_lo_ve(self, professor_client):
        assert professor_client.get(reverse("grades:activity_history", args=[ActivityFactory().pk])).status_code == 404

    def test_el_alumno_no_lo_ve(self, student_client, activity, enrollment):
        assert student_client.get(reverse("grades:activity_history", args=[activity.pk])).status_code == 302

    def test_no_incluye_el_historial_de_otras_actividades(self, professor_client, course, enrollment, professor):
        una, otra = ActivityFactory(course=course), ActivityFactory(course=course)
        grade_activity(una, enrollment.student, score=5, by=professor)
        grade_activity(otra, enrollment.student, score=6, by=professor)
        historial = professor_client.get(reverse("grades:activity_history", args=[una.pk])).context["history"]
        assert [h.activity_id for h in historial] == [una.pk]

    def test_el_alumno_ve_la_penalizacion_explicada(self, student_client, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        grade_activity(tarea, alumno, score=10, feedback="Buen trabajo")
        response = student_client.get(tarea.get_absolute_url())
        html = response.content.decode()
        assert response.context["grade"].score == 8.0
        assert "Calificación original: 10" in html and "20 % por entrega tardía" in html and "Buen trabajo" in html

    def test_el_alumno_sin_penalizacion_no_ve_el_aviso(self, student_client, activity, enrollment):
        grade_activity(activity, enrollment.student, score=10)
        assert "Calificación original" not in student_client.get(activity.get_absolute_url()).content.decode()

    def test_enlaces_del_docente(self, professor_client, activity, enrollment):
        html = professor_client.get(activity.get_absolute_url()).content.decode()
        assert reverse("grades:activity_grading", args=[activity.pk]) in html
        assert reverse("grades:activity_history", args=[activity.pk]) in html

    def test_calificar_no_se_ofrece_en_un_grupo_archivado(self, professor_client, activity, course):
        archive_course(course)
        html = professor_client.get(activity.get_absolute_url()).content.decode()
        assert reverse("grades:activity_grading", args=[activity.pk]) not in html
        assert reverse("grades:activity_history", args=[activity.pk]) in html  # el historial sí se consulta
