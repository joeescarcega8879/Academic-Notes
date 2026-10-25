"""Respuesta abierta: el alumno escribe y el docente la califica; mientras tanto el intento no cuenta."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.tests.factories import StudentFactory
from apps.courses.services.courses import archive_course, clone_course
from apps.courses.tests.factories import AcademicYearFactory, EnrollmentFactory
from apps.grades.models import Grade, GradeHistory
from apps.grades.services.gradebook import grade_activity
from apps.quizzes.models import Answer, Question, QuizConfig
from apps.quizzes.services import answers as svc_answers
from apps.quizzes.services import attempts as svc
from apps.quizzes.services import results
from apps.quizzes.services.bank import duplicate_question
from apps.quizzes.services.builder import add_questions
from apps.quizzes.tests.factories import QuestionFactory, make_quiz
from apps.quizzes.tests.test_respuesta_corta import corta

pytestmark = pytest.mark.django_db

OPEN = Question.Kind.OPEN


def abierta(course, text="Explica la fotosíntesis.", points=4, grupo=None, **extra):
    return QuestionFactory(
        author=course.professor, organization=course.organization, kind=OPEN, text=text, points=points,
        explanation="Debe mencionar luz, agua y CO2.", course=grupo, **extra,
    )


def opcion(course, points=1):
    return QuestionFactory(author=course.professor, organization=course.organization, points=points)


def quiz_con(course, *preguntas, **config):
    quiz = make_quiz(course, questions=0, published=False, **config)
    add_questions(quiz, list(preguntas))
    quiz.activity.published = True
    quiz.activity.save()
    return quiz


def preguntas_de(quiz):
    return list(quiz.questions.all())


def contestar(quiz, alumno, respuestas):
    return svc.submit_attempt(svc.start_attempt(quiz, alumno), respuestas)


def buena(pregunta):
    return next(c for c in pregunta.choices.all() if c.is_correct).pk


def nota(quiz, alumno):
    return Grade.objects.filter(activity=quiz.activity, student=alumno).first()


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


@pytest.fixture
def caso(course, alumno):
    """Quiz de 10 puntos con una opción múltiple (1) y una abierta (4), y un intento enviado con texto."""
    quiz = quiz_con(course, opcion(course), abierta(course), attempts_allowed=3)
    mc, texto = preguntas_de(quiz)
    intento = contestar(quiz, alumno, {mc.pk: buena(mc), texto.pk: "Las plantas usan luz y agua."})
    return quiz, mc, texto, intento


# ── Banco ─────────────────────────────────────────────────────────────

class TestBanco:
    def test_se_crea_sin_opciones(self, professor_client):
        datos = {"text": "Explica la fotosíntesis.", "points": "4", "topic": "", "explanation": "Luz, agua y CO2."}
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["open"]), datos)
        pregunta = Question.objects.get()
        assert respuesta.url == reverse("quizzes:question_detail", args=[pregunta.pk])
        assert pregunta.kind == OPEN and not pregunta.choices.exists()

    def test_el_formulario_no_pide_opciones(self, professor_client):
        pagina = professor_client.get(reverse("quizzes:question_create", args=["open"])).content.decode()
        assert "choices-TOTAL_FORMS" not in pagina and "tú la calificas" in pagina

    def test_editar_y_duplicar(self, professor_client, course, professor):
        pregunta = abierta(course)
        assert professor_client.get(reverse("quizzes:question_update", args=[pregunta.pk])).status_code == 200
        copia = duplicate_question(pregunta, by=professor)
        assert copia.kind == OPEN and not copia.choices.exists() and copia.text.endswith("(copia)")

    def test_el_detalle_y_el_constructor_la_explican(self, professor_client, course):
        quiz = quiz_con(course, abierta(course))
        pregunta = Question.objects.get()
        assert "tú la calificas" in professor_client.get(reverse("quizzes:question_detail", args=[pregunta.pk])).content.decode()
        pagina = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "La califica el docente" in pagina and "Nueva respuesta abierta" in pagina

    def test_viaja_al_quiz_y_al_duplicar_el_grupo(self, course):
        quiz = quiz_con(course, abierta(course, grupo=course))
        assert quiz.questions.get().kind == OPEN
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        assert copia.bank_questions.get().kind == OPEN


# ── Responder y cerrar el intento ─────────────────────────────────────

class TestResponder:
    def test_grade_deja_por_calificar_lo_escrito_y_da_cero_a_lo_vacio(self, course):
        pregunta = abierta(course)
        assert svc_answers.grade(pregunta, Answer(text="algo")) == (None, None)
        for vacio in ("", "   ", "\n"):
            assert svc_answers.grade(pregunta, Answer(text=vacio)) == (False, Decimal(0))

    def test_el_limite_es_de_cinco_mil_caracteres(self, course, alumno):
        quiz = quiz_con(course, abierta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        svc.save_answers(intento, {pregunta.pk: "x" * 5000})
        assert len(Answer.objects.get().text) == 5000
        with pytest.raises(ValidationError, match="5000"):
            svc.save_answers(intento, {pregunta.pk: "x" * 5001})
        assert len(Answer.objects.get().text) == 5000

    def test_conserva_los_saltos_de_linea(self, course, alumno):
        quiz = quiz_con(course, abierta(course))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "Uno\n\nDos\r\nTres"})
        assert "Uno\n\nDos" in Answer.objects.get(attempt=intento).text

    def test_el_intento_queda_por_calificar_y_no_llega_a_la_libreta(self, caso, alumno):
        quiz, mc, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        assert (respuesta.is_correct, respuesta.points_awarded) == (None, None)
        assert (intento.score, intento.max_points) == (1, 5)  # solo cuenta lo que ya está calificado
        assert results.pending_count(intento) == 1
        assert nota(quiz, alumno) is None

    def test_vacia_vale_cero_y_no_deja_nada_por_calificar(self, course, alumno):
        quiz = quiz_con(course, opcion(course), abierta(course))
        mc, _ = preguntas_de(quiz)
        intento = contestar(quiz, alumno, {mc.pk: buena(mc)})
        assert results.pending_count(intento) == 0
        assert nota(quiz, alumno).score == pytest.approx(10 * 1 / 5)

    def test_se_cierra_por_tiempo_con_lo_escrito_por_calificar(self, course, alumno):
        quiz = quiz_con(course, abierta(course), time_limit_minutes=10)
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        svc.save_answers(intento, {pregunta.pk: "A medias"})
        cerrado = svc.finalize_attempt(intento, expired=True)
        assert cerrado.status == "expired" and results.pending_count(cerrado) == 1

    def test_solo_abiertas_el_alumno_ve_el_cuadro_de_texto(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, abierta(course))
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert "<textarea" in pagina and 'maxlength="5000"' in pagina and "Tu docente califica esta pregunta" in pagina
        assert "debe mencionar" not in pagina.lower()

    def test_el_guardado_automatico_acepta_textos_largos(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, abierta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        url = reverse("quizzes:autosave", args=[intento.pk])
        assert student_client.post(url, {f"q_{pregunta.pk}": "y" * 1200}).json()["ok"]
        assert student_client.post(url, {f"q_{pregunta.pk}": "y" * 5001}).status_code == 400

    def test_lo_escrito_con_html_se_muestra_escapado(self, student_client, professor_client, course, alumno, enrollment):
        quiz = quiz_con(course, abierta(course))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "<script>alert(1)</script>"})
        for cliente in (professor_client, student_client):
            nombre = "quizzes:review" if cliente is professor_client else "quizzes:result"
            pagina = cliente.get(reverse(nombre, args=[intento.pk])).content.decode()
            assert "<script>alert(1)</script>" not in pagina and "&lt;script&gt;alert(1)&lt;/script&gt;" in pagina


# ── Calificar ─────────────────────────────────────────────────────────

class TestCalificar:
    def test_la_nota_llega_a_la_libreta_cuando_ya_no_queda_nada(self, caso, alumno, professor):
        quiz, mc, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("3", "Bien, falta el CO2.")}, by=professor)
        intento.refresh_from_db()
        assert intento.score == 4 and results.pending_count(intento) == 0
        assert nota(quiz, alumno).score == pytest.approx(8.0)
        assert nota(quiz, alumno).source == Grade.Source.QUIZ

    def test_guarda_puntos_comentario_y_si_es_completa(self, caso, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("4", "Perfecta")}, by=professor)
        respuesta.refresh_from_db()
        assert (respuesta.points_awarded, respuesta.is_correct, respuesta.feedback) == (4, True, "Perfecta")
        results.grade_open_answers(intento, {respuesta.pk: ("1,5", "")}, by=professor)
        respuesta.refresh_from_db()
        assert (respuesta.points_awarded, respuesta.is_correct, respuesta.feedback) == (Decimal("1.50"), False, "")

    def test_la_bitacora_registra_al_docente(self, caso, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("2", "")}, by=professor)
        assert GradeHistory.objects.latest("changed_at").changed_by == professor

    def test_puntos_en_blanco_dejan_la_respuesta_como_estaba(self, caso, professor):
        quiz, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("", "Falta revisar")}, by=professor)
        respuesta.refresh_from_db()
        assert respuesta.points_awarded is None and respuesta.feedback == "Falta revisar"
        assert results.pending_count(intento) == 1 and nota(quiz, intento.student) is None
        results.grade_open_answers(intento, {respuesta.pk: ("3", "")}, by=professor)
        results.grade_open_answers(intento, {respuesta.pk: ("", "Otro comentario")}, by=professor)
        respuesta.refresh_from_db()
        assert respuesta.points_awarded == 3 and respuesta.feedback == "Otro comentario"

    @pytest.mark.parametrize("puntos, mensaje", [
        ("5", "0 a 4"), ("-1", "0 a 4"), ("4.01", "0 a 4"), ("abc", "número"), ("NaN", "número"), ("Infinity", "número"),
        ("-Infinity", "número"), ("1e3", "0 a 4"),
    ])
    def test_rechaza_puntos_invalidos_y_no_guarda_nada(self, caso, professor, puntos, mensaje):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        with pytest.raises(ValidationError, match=mensaje):
            results.grade_open_answers(intento, {respuesta.pk: (puntos, "x")}, by=professor)
        respuesta.refresh_from_db()
        assert respuesta.points_awarded is None and respuesta.feedback == ""

    def test_el_maximo_exacto_y_el_cero_son_validos(self, caso, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        for puntos in ("0", "4", "0.005"):
            results.grade_open_answers(intento, {respuesta.pk: (puntos, "")}, by=professor)

    def test_un_comentario_demasiado_largo_se_rechaza(self, caso, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        with pytest.raises(ValidationError, match="1000"):
            results.grade_open_answers(intento, {respuesta.pk: ("1", "c" * 1001)}, by=professor)

    def test_no_califica_respuestas_de_otro_intento_ni_de_otro_tipo(self, caso, course, professor):
        quiz, mc, texto, intento = caso
        otro_alumno = EnrollmentFactory(course=course, student=StudentFactory()).student
        ajeno = contestar(quiz, otro_alumno, {texto.pk: "Mi respuesta"})
        de_otro = Answer.objects.get(attempt=ajeno, question=texto)
        with pytest.raises(ValidationError, match="no es de este intento"):
            results.grade_open_answers(intento, {de_otro.pk: ("1", "")}, by=professor)
        de_opcion = Answer.objects.get(attempt=intento, question=mc)
        with pytest.raises(ValidationError, match="no es de este intento"):
            results.grade_open_answers(intento, {de_opcion.pk: ("1", "")}, by=professor)
        de_otro.refresh_from_db()
        assert de_otro.points_awarded is None

    def test_no_hay_nada_que_calificar_en_una_respuesta_vacia(self, course, alumno, professor):
        quiz = quiz_con(course, opcion(course), abierta(course))
        mc, texto = preguntas_de(quiz)
        intento = contestar(quiz, alumno, {mc.pk: buena(mc)})
        vacia = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {vacia.pk: ("4", "x")}, by=professor)
        vacia.refresh_from_db()
        assert vacia.points_awarded == 0 and vacia.feedback == ""

    def test_no_se_califica_un_intento_en_curso(self, course, alumno, professor):
        quiz = quiz_con(course, abierta(course))
        intento = svc.start_attempt(quiz, alumno)
        with pytest.raises(ValidationError, match="en curso"):
            results.grade_open_answers(intento, {}, by=professor)

    def test_un_grupo_archivado_es_de_solo_lectura(self, caso, course, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        archive_course(course)
        with pytest.raises(ValidationError):
            results.grade_open_answers(intento, {respuesta.pk: ("1", "")}, by=professor)

    def test_una_nota_puesta_a_mano_no_se_pisa(self, caso, alumno, professor):
        quiz, _, texto, intento = caso
        grade_activity(quiz.activity, alumno, score=9, by=professor)
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("0", "")}, by=professor)
        assert nota(quiz, alumno).score == 9 and nota(quiz, alumno).source == Grade.Source.MANUAL


# ── Varios intentos ───────────────────────────────────────────────────

class TestVariosIntentos:
    def test_un_intento_por_calificar_no_cuenta_pero_los_calificados_si(self, course, alumno, professor):
        quiz = quiz_con(course, opcion(course, points=2), abierta(course, points=2), attempts_allowed=3)
        mc, texto = preguntas_de(quiz)
        primero = contestar(quiz, alumno, {mc.pk: buena(mc), texto.pk: "uno"})
        respuesta = Answer.objects.get(attempt=primero, question=texto)
        results.grade_open_answers(primero, {respuesta.pk: ("2", "")}, by=professor)
        assert nota(quiz, alumno).score == 10
        segundo = contestar(quiz, alumno, {texto.pk: "dos"})  # solo abierta, sin calificar
        assert results.pending_count(segundo) == 1
        assert nota(quiz, alumno).score == 10  # sigue la del primero
        respuesta2 = Answer.objects.get(attempt=segundo, question=texto)
        quiz.attempt_policy = QuizConfig.Policy.AVERAGE
        quiz.save()
        results.grade_open_answers(segundo, {respuesta2.pk: ("0", "")}, by=professor)
        assert nota(quiz, alumno).score == 5  # promedio de 10 y 0

    def test_si_el_unico_intento_esta_pendiente_no_hay_nota(self, caso, alumno):
        quiz, *_ = caso
        assert results.finished_attempts(quiz, alumno) == []
        assert nota(quiz, alumno) is None

    def test_eliminar_el_intento_pendiente_no_deja_notas_huerfanas(self, caso, alumno, professor):
        quiz, _, _, intento = caso
        results.remove_attempt(intento, by=professor)
        assert nota(quiz, alumno) is None


# ── Lo que ven el alumno y el docente ─────────────────────────────────

class TestAlumno:
    def test_mientras_esta_por_calificar_no_ve_puntos_ni_nota(self, student_client, caso):
        _, _, _, intento = caso
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "todavía califica 1 respuesta abierta" in pagina
        assert "de 5 puntos" not in pagina and "% de aciertos" not in pagina and "Tu calificación en la libreta" not in pagina

    def test_ya_calificada_ve_nota_puntos_y_comentario(self, student_client, caso, professor):
        quiz, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("3", "Faltó el CO2")}, by=professor)
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "todavía califica" not in pagina and "Tu calificación en la libreta" in pagina
        assert "Faltó el CO2" in pagina and "Calificada" in pagina and "Debe mencionar luz" in pagina

    def test_con_solo_la_calificacion_no_ve_comentarios_ni_explicaciones(self, student_client, course, alumno, professor):
        quiz = quiz_con(course, abierta(course), feedback_mode=QuizConfig.Feedback.NONE)
        texto = quiz.questions.get()
        intento = contestar(quiz, alumno, {texto.pk: "algo"})
        respuesta = Answer.objects.get(attempt=intento)
        results.grade_open_answers(intento, {respuesta.pk: ("2", "Comentario privado")}, by=professor)
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Comentario privado" not in pagina and "Tu calificación en la libreta" in pagina

    def test_el_alumno_no_puede_calificarse(self, student_client, caso):
        quiz, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        resultado = student_client.post(reverse("quizzes:attempt_grade", args=[intento.pk]), {f"points_{respuesta.pk}": "4"})
        assert resultado.status_code in (302, 403, 404)
        respuesta.refresh_from_db()
        assert respuesta.points_awarded is None


class TestDocente:
    def test_la_revision_ofrece_calificar_solo_las_respuestas_con_texto(self, professor_client, caso):
        _, mc, texto, intento = caso
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        assert f'name="points_{respuesta.pk}"' in pagina and "1 por calificar" in pagina and "Guardar calificación" in pagina
        assert f'name="points_{Answer.objects.get(attempt=intento, question=mc).pk}"' not in pagina

    def test_el_campo_de_puntos_va_vacio_si_esta_por_calificar_y_con_los_puntos_si_ya_se_califico(self, professor_client, caso, professor):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        url = reverse("quizzes:review", args=[intento.pk])
        assert f'id="points_{respuesta.pk}"' in professor_client.get(url).content.decode()
        assert 'step="0.01" value=""' in professor_client.get(url).content.decode()
        results.grade_open_answers(intento, {respuesta.pk: ("2.5", "")}, by=professor)
        pagina = professor_client.get(url).content.decode()
        assert 'value="2.50"' in pagina and "Por calificar" not in pagina

    def test_una_abierta_en_blanco_no_ofrece_campos_de_calificacion(self, professor_client, course, alumno):
        quiz = quiz_con(course, abierta(course, text="Primera"), abierta(course, text="Segunda"))
        primera, segunda = preguntas_de(quiz)
        intento = contestar(quiz, alumno, {primera.pk: "Respondida"})
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        contestada = Answer.objects.get(attempt=intento, question=primera)
        en_blanco = Answer.objects.get(attempt=intento, question=segunda)
        assert f'name="points_{contestada.pk}"' in pagina and f'name="points_{en_blanco.pk}"' not in pagina
        assert "Sin respuesta" in pagina

    def test_una_revision_sin_abiertas_no_trae_formulario(self, professor_client, course, alumno):
        quiz = quiz_con(course, opcion(course))
        intento = contestar(quiz, alumno, {})
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        assert "Guardar calificación" not in pagina

    def test_califica_desde_la_pagina(self, professor_client, caso, alumno):
        quiz, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        enviado = professor_client.post(
            reverse("quizzes:attempt_grade", args=[intento.pk]),
            {f"points_{respuesta.pk}": "4", f"comment_{respuesta.pk}": "Excelente"}, follow=True,
        )
        assert any("Se guardó la calificación" in str(m) for m in enviado.context["messages"])
        assert nota(quiz, alumno).score == 10
        assert "Excelente" in enviado.content.decode()

    def test_los_errores_se_avisan_y_no_cambian_nada(self, professor_client, caso, alumno):
        quiz, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        enviado = professor_client.post(reverse("quizzes:attempt_grade", args=[intento.pk]), {f"points_{respuesta.pk}": "99"}, follow=True)
        assert any("0 a 4" in str(m) for m in enviado.context["messages"])
        assert nota(quiz, alumno) is None

    def test_nombres_de_campo_extraños_se_ignoran(self, professor_client, caso):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        enviado = professor_client.post(reverse("quizzes:attempt_grade", args=[intento.pk]), {
            "points_": "1", "points_abc": "1", f"points_{'9' * 40}": "1", f"points_{respuesta.pk}²": "1",
        })
        assert enviado.status_code == 302
        respuesta.refresh_from_db()
        assert respuesta.points_awarded is None

    def test_otro_docente_no_puede_calificar(self, client, caso):
        _, _, texto, intento = caso
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        client.force_login(EnrollmentFactory().course.professor)
        assert client.post(reverse("quizzes:attempt_grade", args=[intento.pk]), {f"points_{respuesta.pk}": "4"}).status_code == 404
        respuesta.refresh_from_db()
        assert respuesta.points_awarded is None

    def test_los_resultados_cuentan_y_senalan_lo_pendiente(self, professor_client, caso, course, alumno, professor):
        quiz, _, texto, intento = caso
        resumen = results.summary(quiz)
        assert (resumen["attempts"], resumen["pending"], resumen["average"]) == (1, 1, None)
        fila = next(f for f in results.student_rows(quiz) if f["student"] == alumno)
        assert (len(fila["waiting"]), fila["done"], fila["best"]) == (1, [], None)
        pagina = professor_client.get(reverse("quizzes:results", args=[quiz.activity_id])).content.decode()
        assert "1 por calificar" in pagina and "Por calificar" in pagina
        respuesta = Answer.objects.get(attempt=intento, question=texto)
        results.grade_open_answers(intento, {respuesta.pk: ("4", "")}, by=professor)
        resumen = results.summary(quiz)
        assert (resumen["pending"], resumen["average"]) == (0, 100)

    def test_el_analisis_de_preguntas_cuenta_las_abiertas_contestadas(self, caso):
        quiz, _, texto, _ = caso
        dato = next(d for d in results.question_stats(quiz) if d["question"].pk == texto.pk)
        assert (dato["answered"], dato["unanswered"], dato["common_wrong"], dato["choices"]) == (1, 0, [], [])

    def test_en_un_examen_en_linea_tambien(self, course, alumno, professor):
        from apps.grades.models import Activity
        from apps.grades.tests.factories import ActivityFactory
        from apps.quizzes.services import exams

        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False, opens_at=None, due_at=None)
        from django.utils import timezone
        from datetime import timedelta

        actividad.opens_at, actividad.due_at = timezone.now() - timedelta(hours=1), timezone.now() + timedelta(days=1)
        actividad.save()
        quiz = exams.enable_online(actividad)
        add_questions(quiz, [abierta(course, points=10)])
        actividad.published = True
        actividad.save()
        intento = contestar(quiz, alumno, {quiz.questions.get().pk: "Respuesta larga"})
        assert results.pending_count(intento) == 1 and nota(quiz, alumno) is None
        results.grade_open_answers(intento, {Answer.objects.get(attempt=intento).pk: ("8", "")}, by=professor)
        assert nota(quiz, alumno).score == 8


def test_se_mezcla_con_la_respuesta_corta(course, alumno, professor):
    quiz = quiz_con(course, corta(course), abierta(course, points=2))
    c, a = preguntas_de(quiz)
    intento = contestar(quiz, alumno, {c.pk: "cdmx", a.pk: "algo"})
    assert intento.score == 1 and nota(quiz, alumno) is None
    results.grade_open_answers(intento, {Answer.objects.get(attempt=intento, question=a).pk: ("2", "")}, by=professor)
    assert nota(quiz, alumno).score == 10
