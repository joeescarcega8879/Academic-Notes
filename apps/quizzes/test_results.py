"""Calificación automática del quiz, retroalimentación para el alumno y resultados para el docente."""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.courses.services.courses import archive_course
from apps.grades.models import Grade, GradeHistory
from apps.grades.services.gradebook import grade_activity
from apps.grades.services.grading import results_by_course

from .factories import make_quiz
from .models import QuizAttempt, QuizConfig
from .services import attempts as svc
from .services import results

pytestmark = pytest.mark.django_db

MIN = timedelta(minutes=1)
DIA = timedelta(days=1)


def correcta(pregunta):
    return next(c for c in pregunta.choices.all() if c.is_correct)


def incorrecta(pregunta):
    return next(c for c in pregunta.choices.all() if not c.is_correct)


def terminar(quiz, estudiante, aciertos, *, now=None):
    """Un intento enviado con ``aciertos`` respuestas correctas (las primeras preguntas) y el resto mal."""
    intento = svc.start_attempt(quiz, estudiante, now)
    respuestas = {
        q.pk: (correcta(q) if i < aciertos else incorrecta(q)).pk for i, q in enumerate(quiz.questions.all())
    }
    return svc.submit_attempt(intento, respuestas, now)


@pytest.fixture
def quiz(course):
    return make_quiz(course, questions=4, attempts_allowed=3, activity={"max_score": 10})


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


def nota(quiz, alumno):
    return Grade.objects.filter(activity=quiz.activity, student=alumno).first()


# ── De los intentos a la libreta ──────────────────────────────────────

class TestPolitica:
    @pytest.mark.parametrize("politica, esperado", [("highest", 10.0), ("last", 2.5), ("average", 5.83)])
    def test_varios_intentos(self, quiz, alumno, politica, esperado):
        quiz.attempt_policy = politica
        quiz.save()
        for aciertos in (2, 4, 1):  # 50 %, 100 %, 25 %
            terminar(quiz, alumno, aciertos)
        assert nota(quiz, alumno).score == esperado

    def test_la_nota_se_escala_a_los_puntos_de_la_actividad(self, course, alumno):
        quiz = make_quiz(course, questions=4, activity={"max_score": 20})
        terminar(quiz, alumno, 3)
        assert nota(quiz, alumno).score == 15

    def test_redondea_mitad_hacia_arriba(self, course, alumno):
        quiz = make_quiz(course, questions=16, activity={"max_score": 10})
        terminar(quiz, alumno, 1)  # 1/16 de 10 = 0.625
        assert nota(quiz, alumno).score == 0.63

    @pytest.mark.parametrize("aciertos, esperado", [(0, 0.0), (1, 2.5), (4, 10.0)])
    def test_extremos(self, quiz, alumno, aciertos, esperado):
        terminar(quiz, alumno, aciertos)
        assert nota(quiz, alumno).score == esperado

    def test_los_puntos_de_cada_pregunta_pesan(self, course, alumno):
        quiz = make_quiz(course, questions=2, activity={"max_score": 10})
        a, b = list(quiz.questions.all())
        type(a).objects.filter(pk=a.pk).update(points=3)  # 3 de 4 puntos
        intento = svc.start_attempt(quiz, alumno)
        svc.submit_attempt(intento, {a.pk: correcta(a).pk, b.pk: incorrecta(b).pk})
        assert nota(quiz, alumno).score == 7.5


class TestLibreta:
    def test_un_intento_en_curso_no_califica(self, quiz, alumno):
        svc.start_attempt(quiz, alumno)
        assert nota(quiz, alumno) is None

    def test_terminar_crea_la_calificacion_automatica(self, quiz, alumno):
        terminar(quiz, alumno, 3)
        calificacion = nota(quiz, alumno)
        assert (calificacion.source, calificacion.score, calificacion.raw_score, float(calificacion.late_penalty)) == ("quiz", 7.5, 7.5, 0.0)
        assert "automática" in calificacion.feedback and "1 intento" in calificacion.feedback
        historia = GradeHistory.objects.get()
        assert (historia.action, historia.changed_by, historia.new_score) == ("created", None, 7.5)

    def test_un_intento_cerrado_por_tiempo_tambien_califica(self, quiz, alumno):
        quiz.time_limit_minutes = 10
        quiz.save()
        intento = svc.start_attempt(quiz, alumno)
        p1 = quiz.questions.first()
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - MIN)
        svc.expire_if_overdue(QuizAttempt.objects.get(pk=intento.pk))
        assert nota(quiz, alumno).score == 2.5

    def test_otro_intento_actualiza_la_misma_calificacion(self, quiz, alumno):
        terminar(quiz, alumno, 1)
        terminar(quiz, alumno, 3)
        assert Grade.objects.filter(activity=quiz.activity).count() == 1
        assert nota(quiz, alumno).score == 7.5 and "2 intentos" in nota(quiz, alumno).feedback
        assert [h.action for h in GradeHistory.objects.order_by("id")] == ["created", "updated"]

    def test_cada_alumno_tiene_su_calificacion(self, quiz, alumno, course):
        otro = EnrollmentFactory(course=course).student
        terminar(quiz, alumno, 4)
        terminar(quiz, otro, 1)
        assert (nota(quiz, alumno).score, nota(quiz, otro).score) == (10.0, 2.5)

    def test_la_nota_del_docente_manda(self, quiz, alumno, professor):
        terminar(quiz, alumno, 1)
        grade_activity(quiz.activity, alumno, score=9, feedback="Ajuste por participación", by=professor)
        terminar(quiz, alumno, 4)
        calificacion = nota(quiz, alumno)
        assert (calificacion.score, calificacion.source, calificacion.feedback) == (9, "manual", "Ajuste por participación")

    def test_si_el_docente_la_borra_vuelve_la_automatica(self, quiz, alumno, professor):
        terminar(quiz, alumno, 1)
        grade_activity(quiz.activity, alumno, score=9, by=professor)
        nota(quiz, alumno).delete()
        terminar(quiz, alumno, 4)
        assert (nota(quiz, alumno).score, nota(quiz, alumno).source) == (10.0, "quiz")

    def test_entra_en_la_calificacion_final_del_grupo(self, quiz, alumno, course):
        terminar(quiz, alumno, 3)
        assert results_by_course([nota(quiz, alumno)])[course.pk].final == 7.5

    def test_un_grupo_archivado_no_rompe_el_cierre(self, quiz, alumno, course):
        intento = svc.start_attempt(quiz, alumno)
        archive_course(course)
        enviado = svc.submit_attempt(intento)
        assert enviado.status == "submitted" and nota(quiz, alumno) is None

    def test_editar_a_mano_una_nota_automatica_la_vuelve_manual(self, quiz, alumno, professor):
        terminar(quiz, alumno, 2)
        grade_activity(quiz.activity, alumno, score=6, by=professor)
        assert nota(quiz, alumno).source == "manual"


class TestEliminarIntento:
    def test_con_otros_intentos_se_recalcula(self, quiz, alumno, professor):
        quiz.attempt_policy = "highest"
        quiz.save()
        terminar(quiz, alumno, 1)
        mejor = terminar(quiz, alumno, 4)
        assert nota(quiz, alumno).score == 10.0
        results.remove_attempt(mejor, by=professor)
        assert nota(quiz, alumno).score == 2.5
        assert GradeHistory.objects.first().changed_by == professor

    def test_sin_intentos_quita_la_calificacion_automatica(self, quiz, alumno, professor):
        intento = terminar(quiz, alumno, 3)
        results.remove_attempt(intento, by=professor)
        assert nota(quiz, alumno) is None
        assert GradeHistory.objects.first().action == "deleted"

    def test_no_toca_la_nota_manual(self, quiz, alumno, professor):
        intento = terminar(quiz, alumno, 3)
        grade_activity(quiz.activity, alumno, score=9, by=professor)
        results.remove_attempt(intento, by=professor)
        assert nota(quiz, alumno).score == 9

    def test_el_alumno_puede_repetir(self, quiz, alumno, professor):
        quiz.attempts_allowed = 1
        quiz.save()
        intento = terminar(quiz, alumno, 1)
        with pytest.raises(Exception, match="todos tus intentos"):
            svc.start_attempt(quiz, alumno)
        results.remove_attempt(intento, by=professor)
        assert svc.start_attempt(quiz, alumno).number == 1


# ── Retroalimentación ─────────────────────────────────────────────────

class TestRevision:
    def test_sin_retroalimentacion_solo_la_calificacion(self, quiz, alumno):
        quiz.feedback_mode = "none"
        quiz.save()
        assert not results.can_review(terminar(quiz, alumno, 2))

    def test_al_terminar_si(self, quiz, alumno):
        assert results.can_review(terminar(quiz, alumno, 2))

    def test_un_intento_en_curso_no_se_revisa(self, quiz, alumno):
        assert not results.can_review(svc.start_attempt(quiz, alumno))

    def test_al_cerrar_espera_a_la_fecha_limite(self, quiz, alumno):
        quiz.feedback_mode = "after_close"
        quiz.save()
        quiz.activity.due_at = timezone.now() + DIA
        quiz.activity.save()
        intento = terminar(quiz, alumno, 2)
        assert not results.can_review(intento)
        assert results.can_review(intento, timezone.now() + 2 * DIA)

    def test_al_cerrar_sin_fecha_espera_a_que_gaste_sus_intentos(self, quiz, alumno):
        quiz.feedback_mode, quiz.attempts_allowed = "after_close", 2
        quiz.save()
        primero = terminar(quiz, alumno, 2)
        assert not results.can_review(primero)
        terminar(quiz, alumno, 3)
        assert results.can_review(primero)

    def test_filas_de_revision(self, quiz, alumno):
        p1, p2, p3, p4 = list(quiz.questions.all())
        intento = svc.submit_attempt(svc.start_attempt(quiz, alumno), {p1.pk: correcta(p1).pk, p2.pk: incorrecta(p2).pk, p3.pk: None})
        filas = results.review_rows(intento)
        assert [f["question"].pk for f in filas] == [p1.pk, p2.pk, p3.pk, p4.pk]
        assert [(f["answered"], f["is_correct"], float(f["points"])) for f in filas] == [
            (True, True, 1.0), (True, False, 0.0), (False, False, 0.0), (False, False, 0.0),
        ]
        elegida = [i for i in filas[1]["choices"] if i["chosen"]]
        assert len(elegida) == 1 and not elegida[0]["correct"]
        assert sum(i["correct"] for i in filas[0]["choices"]) == 1

    def test_respeta_el_orden_visto_por_el_alumno(self, quiz, alumno):
        intento = terminar(quiz, alumno, 4)
        inverso = list(reversed(intento.layout["questions"]))
        QuizAttempt.objects.filter(pk=intento.pk).update(layout={**intento.layout, "questions": inverso})
        assert [f["question"].pk for f in results.review_rows(QuizAttempt.objects.get(pk=intento.pk))] == inverso


class TestPantallaDelAlumno:
    def resultado(self, intento):
        return reverse("quizzes:result", args=[intento.pk])

    def test_muestra_la_revision_con_correctas_y_explicaciones(self, student_client, quiz, alumno):
        pregunta = quiz.questions.first()
        type(pregunta).objects.filter(pk=pregunta.pk).update(explanation="Porque la suma conmuta")
        intento = terminar(quiz, alumno, 2)
        response = student_client.get(self.resultado(intento))
        html = response.content.decode()
        assert response.context["review"] is not None and "Porque la suma conmuta" in html
        assert "tu respuesta" in html and "correcta" in html

    def test_sin_retroalimentacion_no_revela_nada(self, student_client, quiz, alumno):
        quiz.feedback_mode = "none"
        quiz.save()
        pregunta = quiz.questions.first()
        type(pregunta).objects.filter(pk=pregunta.pk).update(explanation="Secreto de la explicación")
        intento = terminar(quiz, alumno, 2)
        response = student_client.get(self.resultado(intento))
        html = response.content.decode()
        assert response.context["review"] is None and "Secreto" not in html and "solo muestra la calificación" in html
        assert "Opción A" not in html

    def test_al_cerrar_avisa_que_se_mostrara_despues(self, student_client, quiz, alumno):
        quiz.feedback_mode, quiz.attempts_allowed = "after_close", 3
        quiz.save()
        intento = terminar(quiz, alumno, 2)
        response = student_client.get(self.resultado(intento))
        assert response.context["review"] is None and "cuando cierre el quiz" in response.content.decode()

    def test_muestra_la_calificacion_de_la_libreta(self, student_client, quiz, alumno):
        quiz.attempts_allowed = 2
        quiz.attempt_policy = "average"
        quiz.save()
        terminar(quiz, alumno, 4)
        intento = terminar(quiz, alumno, 0)
        html = student_client.get(self.resultado(intento)).content.decode()
        assert "5 / 10" in html.replace(",00", "").replace(".00", "") and "el promedio de los intentos" in html

    def test_otro_alumno_no_ve_la_revision(self, client, quiz, alumno, course):
        intento = terminar(quiz, alumno, 2)
        otro = EnrollmentFactory(course=course).student
        client.force_login(otro.user)
        assert client.get(self.resultado(intento)).status_code == 404


# ── Resultados del docente ────────────────────────────────────────────

def resultados(quiz):
    return reverse("quizzes:results", args=[quiz.activity_id])


def intento_ajeno(aciertos=1):
    """Un intento enviado en el quiz de otro docente (otro grupo, otra organización)."""
    otro_grupo = CourseFactory()
    otro_quiz = make_quiz(otro_grupo, questions=1)
    return terminar(otro_quiz, EnrollmentFactory(course=otro_grupo).student, aciertos)


class TestAnalisis:
    @pytest.fixture
    def con_datos(self, quiz, course):
        a = EnrollmentFactory(course=course).student
        b = EnrollmentFactory(course=course).student
        terminar(quiz, a, 4)
        terminar(quiz, b, 2)
        return quiz, a, b

    def test_cifras_generales(self, con_datos):
        quiz, *_ = con_datos
        datos = results.summary(quiz)
        assert (datos["attempts"], datos["students"], datos["average"], datos["highest"], datos["lowest"], datos["expired"]) == (2, 2, 75, 100, 50, 0)

    def test_sin_intentos(self, quiz):
        datos = results.summary(quiz)
        assert (datos["attempts"], datos["average"], datos["highest"]) == (0, None, None)
        assert all(q["percent_correct"] is None for q in results.question_stats(quiz))

    def test_analisis_por_pregunta(self, con_datos):
        quiz, a, b = con_datos
        estadisticas = results.question_stats(quiz)
        primera, ultima = estadisticas[0], estadisticas[-1]
        assert (primera["attempts"], primera["answered"], primera["correct"], primera["percent_correct"]) == (2, 2, 2, 100)
        assert (ultima["correct"], ultima["percent_correct"]) == (1, 50)
        # Cómo se repartieron las opciones de la última: uno acertó y el otro eligió una incorrecta.
        assert sorted(c["count"] for c in ultima["choices"] if c["count"]) == [1, 1]
        assert sum(c["percent"] for c in ultima["choices"]) == 100

    def test_cuenta_las_omitidas(self, quiz, alumno):
        svc.submit_attempt(svc.start_attempt(quiz, alumno))
        assert all(q["unanswered"] == 1 and q["answered"] == 0 for q in results.question_stats(quiz))

    def test_ignora_los_intentos_en_curso(self, quiz, alumno):
        svc.start_attempt(quiz, alumno)
        assert results.summary(quiz)["attempts"] == 0 and results.question_stats(quiz)[0]["attempts"] == 0

    def test_cuenta_los_cerrados_por_tiempo(self, quiz, alumno):
        quiz.time_limit_minutes = 5
        quiz.save()
        intento = svc.start_attempt(quiz, alumno)
        QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - MIN)
        svc.expire_if_overdue(QuizAttempt.objects.get(pk=intento.pk))
        assert results.summary(quiz)["expired"] == 1

    def test_una_fila_por_alumno(self, con_datos, course):
        quiz, a, b = con_datos
        EnrollmentFactory(course=course)  # sin intentos
        filas = {f["student"].pk: f for f in results.student_rows(quiz)}
        assert len(filas) == 3
        assert (filas[a.pk]["best"], filas[a.pk]["last"], filas[b.pk]["best"]) == (100, 100, 50)
        assert filas[a.pk]["grade"].score == 10.0
        sin = [f for f in filas.values() if not f["attempts"]]
        assert len(sin) == 1 and sin[0]["best"] is None and sin[0]["grade"] is None

    def test_mejor_y_ultimo_con_varios_intentos(self, quiz, alumno):
        terminar(quiz, alumno, 4)
        terminar(quiz, alumno, 1)
        fila = next(f for f in results.student_rows(quiz) if f["student"] == alumno)
        assert (fila["best"], fila["last"], len(fila["done"])) == (100, 25, 2)


class TestPantallaDelDocente:
    def test_se_abre_con_todo(self, professor_client, quiz, alumno):
        terminar(quiz, alumno, 3)
        response = professor_client.get(resultados(quiz))
        html = response.content.decode()
        assert response.status_code == 200 and "Análisis por pregunta" in html and "Quiz (automática)" in html
        assert response.context["summary"]["students"] == 1

    def test_se_puede_ver_en_un_grupo_archivado(self, professor_client, quiz, alumno, course):
        terminar(quiz, alumno, 3)
        archive_course(course)
        assert professor_client.get(resultados(quiz)).status_code == 200

    def test_otro_docente_no(self, professor_client):
        ajeno = make_quiz(CourseFactory(), questions=1)
        assert professor_client.get(resultados(ajeno)).status_code == 404

    def test_el_alumno_no(self, student_client, quiz, enrollment):
        assert student_client.get(resultados(quiz)).status_code == 302

    def test_una_actividad_que_no_es_quiz_es_404(self, professor_client, course):
        from apps.grades.factories import ActivityFactory

        assert professor_client.get(reverse("quizzes:results", args=[ActivityFactory(course=course).pk])).status_code == 404

    def test_enlaces(self, professor_client, quiz):
        assert resultados(quiz) in professor_client.get(quiz.activity.get_absolute_url()).content.decode()
        assert resultados(quiz) in professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()

    def test_la_actividad_marca_la_nota_automatica(self, professor_client, quiz, alumno):
        terminar(quiz, alumno, 3)
        assert "Automática" in professor_client.get(quiz.activity.get_absolute_url()).content.decode()


class TestRevisionDelDocente:
    def test_ve_las_respuestas_aunque_el_quiz_no_las_muestre(self, professor_client, quiz, alumno):
        quiz.feedback_mode = "none"
        quiz.save()
        intento = terminar(quiz, alumno, 2)
        response = professor_client.get(reverse("quizzes:review", args=[intento.pk]))
        html = response.content.decode()
        assert response.status_code == 200 and len(response.context["rows"]) == 4
        assert "respuesta del alumno" in html and "tu respuesta" not in html

    def test_otro_docente_y_el_alumno_no(self, professor_client, student_client, quiz, alumno):
        ajeno = intento_ajeno()
        assert professor_client.get(reverse("quizzes:review", args=[ajeno.pk])).status_code == 404
        propio = terminar(quiz, alumno, 1)
        assert student_client.get(reverse("quizzes:review", args=[propio.pk])).status_code == 302

    def test_eliminar_el_intento(self, professor_client, quiz, alumno):
        intento = terminar(quiz, alumno, 4)
        response = professor_client.post(reverse("quizzes:attempt_delete", args=[intento.pk]), follow=True)
        assert not QuizAttempt.objects.exists() and nota(quiz, alumno) is None
        assert response.redirect_chain[-1][0] == resultados(quiz)
        assert any("Se eliminó el intento" in str(m) for m in response.context["messages"])

    def test_eliminar_en_un_grupo_archivado(self, professor_client, quiz, alumno, course):
        intento = terminar(quiz, alumno, 4)
        archive_course(course)
        response = professor_client.post(reverse("quizzes:attempt_delete", args=[intento.pk]), follow=True)
        assert QuizAttempt.objects.exists() and any("archivado" in str(m) for m in response.context["messages"])

    def test_solo_post_y_solo_el_dueno(self, professor_client, quiz, alumno):
        intento = terminar(quiz, alumno, 4)
        assert professor_client.get(reverse("quizzes:attempt_delete", args=[intento.pk])).status_code == 405
        ajeno = intento_ajeno()
        assert professor_client.post(reverse("quizzes:attempt_delete", args=[ajeno.pk])).status_code == 404
        assert QuizAttempt.objects.filter(pk=ajeno.pk).exists()
