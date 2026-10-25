"""Respuesta corta: se compara con las respuestas aceptadas sin distinguir mayúsculas, acentos ni signos."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.courses.services.courses import clone_course
from apps.courses.tests.factories import AcademicYearFactory
from apps.grades.models import Grade
from apps.quizzes.models import Answer, Choice, Question, QuizConfig, QuizQuestion
from apps.quizzes.services import answers as svc_answers
from apps.quizzes.services import attempts as svc
from apps.quizzes.services import results
from apps.quizzes.services.bank import duplicate_question, save_question, validate_accepted
from apps.quizzes.services.builder import add_questions
from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db

SHORT = Question.Kind.SHORT_ANSWER


def corta(course, text="¿Capital de México?", accepted=("Ciudad de México", "CDMX"), grupo=None, **extra):
    return QuestionFactory(
        author=course.professor, organization=course.organization, kind=SHORT, text=text,
        choices=[(a, True) for a in accepted], course=grupo, **extra,
    )


def quiz_con(course, *preguntas, **config):
    quiz = make_quiz(course, questions=0, published=False, **config)
    add_questions(quiz, list(preguntas))
    quiz.activity.published = True
    quiz.activity.save()
    return quiz


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


# ── Normalización ─────────────────────────────────────────────────────

class TestNormalizar:
    @pytest.mark.parametrize("a, b", [
        ("Ciudad de México", "ciudad de mexico"),
        ("  ciudad   de\tméxico  ", "CIUDAD DE MEXICO"),
        ("¡Ciudad de México!", "ciudad de méxico"),
        ("Ciudad-de-México.", "ciudad de mexico"),
        ("3,5", "3.5"),
        ("año", "AÑO"),
        ("Ünïcödé", "unicode"),
    ])
    def test_son_la_misma_respuesta(self, a, b):
        assert svc_answers.normalize(a) == svc_answers.normalize(b)

    @pytest.mark.parametrize("a, b", [
        ("año", "ano"), ("ciudad de mexico", "ciudad mexico"), ("3.5", "35"), ("1,000", "1000"), ("pera", "peras"),
    ])
    def test_no_son_la_misma(self, a, b):
        assert svc_answers.normalize(a) != svc_answers.normalize(b)

    @pytest.mark.parametrize("texto", ["", "   ", "???", "...", "-_-", None])
    def test_sin_letras_ni_numeros_queda_vacio(self, texto):
        assert svc_answers.normalize(texto) == ""

    def test_el_punto_final_no_cambia_el_numero(self):
        assert svc_answers.normalize("el 3.") == "el 3"
        assert svc_answers.normalize("3.5.") == "3.5"


class TestAceptadas:
    def test_necesita_al_menos_una(self):
        for vacio in ([], [("", True)], [("   ", True)]):
            with pytest.raises(ValidationError, match="al menos una"):
                validate_accepted(vacio)

    def test_rechaza_repetidas_aunque_cambien_en_acentos_o_signos(self):
        with pytest.raises(ValidationError, match="repetidas"):
            validate_accepted([("México", True), ("mexico!", True)])

    def test_rechaza_respuestas_sin_letras_ni_numeros(self):
        with pytest.raises(ValidationError, match="letras o números"):
            validate_accepted([("???", True)])

    def test_tope_de_ocho_y_de_largo(self):
        with pytest.raises(ValidationError, match="Máximo"):
            validate_accepted([(f"r{n}", True) for n in range(9)])
        with pytest.raises(ValidationError, match="200"):
            validate_accepted([("x" * 201, True)])

    def test_conserva_el_texto_original_recortado(self):
        assert validate_accepted([("  CDMX ", False)]) == [("CDMX", True)]


# ── Banco ─────────────────────────────────────────────────────────────

class TestBanco:
    def test_se_guarda_con_sus_respuestas_aceptadas(self, course):
        pregunta = corta(course, accepted=("Roma", "Roma, Italia"))
        assert pregunta.kind == SHORT
        assert [(c.text, c.is_correct) for c in pregunta.choices.all()] == [("Roma", True), ("Roma, Italia", True)]

    def test_editar_reemplaza_las_respuestas_y_no_cambia_el_tipo(self, course, professor):
        pregunta = corta(course)
        save_question(
            organization=pregunta.organization, author=professor, kind=SHORT, text="Nueva", points=2,
            choices=[("Madrid", True)], question=pregunta,
        )
        assert [c.text for c in pregunta.choices.all()] == ["Madrid"]
        with pytest.raises(ValidationError, match="tipo"):
            save_question(
                organization=pregunta.organization, author=professor, kind=Question.Kind.MULTIPLE_CHOICE, text="x", points=1,
                choices=[("a", True), ("b", False)], question=pregunta,
            )

    def test_duplicar_copia_las_respuestas(self, course, professor):
        copia = duplicate_question(corta(course, accepted=("uno", "1")), by=professor)
        assert copia.kind == SHORT and [c.text for c in copia.choices.all()] == ["uno", "1"]

    def test_al_duplicar_el_grupo_viaja_su_banco(self, course):
        original = corta(course, grupo=course)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        nueva = copia.bank_questions.get()
        assert nueva.kind == SHORT and [c.text for c in nueva.choices.all()] == [c.text for c in original.choices.all()]

    def test_al_ponerla_en_un_quiz_se_copian_las_respuestas(self, course):
        quiz = quiz_con(course, corta(course))
        copia = quiz.questions.get()
        assert copia.kind == SHORT and {c.text for c in copia.choices.all()} == {"Ciudad de México", "CDMX"}
        assert [c.text for c in copia.correct_choices] == ["Ciudad de México", "CDMX"]


# ── Calificar ─────────────────────────────────────────────────────────

def contestar(quiz, alumno, respuestas):
    """Empieza un intento y lo envía con ``respuestas`` = {pregunta: texto}."""
    intento = svc.start_attempt(quiz, alumno)
    return svc.submit_attempt(intento, respuestas)


class TestCalificar:
    @pytest.mark.parametrize("texto, acierta", [
        ("Ciudad de México", True), ("ciudad de mexico", True), ("CDMX", True), ("  cdmx. ", True), ("¡¡CDMX!!", True),
        ("Mexico", False), ("Guadalajara", False), ("", False), ("   ", False), ("???", False),
    ])
    def test_la_comparacion(self, course, alumno, texto, acierta):
        quiz = quiz_con(course, corta(course, points=2))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: texto})
        respuesta = Answer.objects.get(attempt=intento)
        assert respuesta.is_correct is acierta
        assert respuesta.points_awarded == (Decimal(2) if acierta else Decimal(0))
        assert intento.score == (Decimal(2) if acierta else Decimal(0))

    def test_sin_contestar_vale_cero(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        intento = contestar(quiz, alumno, {})
        assert intento.score == 0 and Answer.objects.get(attempt=intento).text == ""

    def test_se_mezcla_con_opcion_multiple(self, course, alumno):
        quiz = quiz_con(course, corta(course), QuestionFactory(author=course.professor, organization=course.organization))
        corta_q, mc = quiz.questions.all()
        buena = next(c for c in mc.choices.all() if c.is_correct)
        intento = contestar(quiz, alumno, {corta_q.pk: "cdmx", mc.pk: buena.pk})
        assert (intento.score, intento.max_points) == (2, 2)
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_la_nota_de_la_libreta_cuenta_los_puntos_de_cada_tipo(self, course, alumno):
        quiz = quiz_con(course, corta(course), QuestionFactory(author=course.professor, organization=course.organization))
        corta_q, _ = quiz.questions.all()
        contestar(quiz, alumno, {corta_q.pk: "cdmx"})
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 5

    def test_las_mayusculas_no_alteran_lo_que_se_guarda(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "  Ciudad De MÉXICO "})
        assert Answer.objects.get(attempt=intento).text == "Ciudad De MÉXICO"


# ── Guardar mientras responde ─────────────────────────────────────────

class TestGuardar:
    def test_guarda_y_reemplaza_el_texto(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        svc.save_answers(intento, {pregunta.pk: "CD"})
        svc.save_answers(intento, {pregunta.pk: "CDMX"})
        assert Answer.objects.get(attempt=intento).text == "CDMX"

    def test_vacio_o_none_borra_lo_escrito(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        svc.save_answers(intento, {pregunta.pk: "CDMX"})
        svc.save_answers(intento, {pregunta.pk: None})
        assert Answer.objects.get(attempt=intento).text == ""

    def test_rechaza_un_texto_demasiado_largo_sin_guardar_nada(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        with pytest.raises(ValidationError, match="500"):
            svc.save_answers(intento, {pregunta.pk: "x" * 501})
        assert not Answer.objects.filter(attempt=intento).exists()

    def test_un_numero_se_guarda_como_texto_con_ceros(self, course, alumno):
        quiz = quiz_con(course, corta(course, accepted=("007",)))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "007"})
        assert Answer.objects.get(attempt=intento).text == "007" and intento.score == 1

    def test_el_orden_del_intento_no_incluye_las_respuestas_aceptadas(self, course, alumno):
        quiz = quiz_con(course, corta(course))
        intento = svc.start_attempt(quiz, alumno)
        assert intento.layout["choices"] == {}


# ── Lo que ve el alumno ───────────────────────────────────────────────

class TestAlumno:
    def test_la_pagina_del_examen_tiene_el_campo_y_no_filtra_las_respuestas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course, accepted=("Respuesta-secreta-xyz",)))
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert 'type="text"' in pagina and 'maxlength="500"' in pagina
        assert "Respuesta-secreta-xyz" not in pagina and "secreta" not in pagina.lower()

    def test_lo_escrito_se_vuelve_a_mostrar_al_reanudar(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        svc.save_answers(intento, {pregunta.pk: 'mi "respuesta" <b>'})
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert 'value="mi &quot;respuesta&quot; &lt;b&gt;"' in pagina

    def test_el_guardado_automatico_acepta_texto(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        respuesta = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"q_{pregunta.pk}": "CDMX"})
        assert respuesta.json()["ok"] and Answer.objects.get(attempt=intento).text == "CDMX"
        respuesta = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"q_{pregunta.pk}": "x" * 501})
        assert respuesta.status_code == 400 and Answer.objects.get(attempt=intento).text == "CDMX"

    def test_enviar_desde_la_pagina_califica(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"q_{pregunta.pk}": "cdmx"})
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_la_revision_muestra_la_respuesta_y_las_aceptadas_si_fallo(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "Guadalajara"})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Guadalajara" in pagina and "Ciudad de México · CDMX" in pagina and "tu respuesta" in pagina

    def test_si_acerto_no_repite_las_aceptadas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "cdmx"})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Respuesta aceptada" not in pagina and "Respuestas aceptadas" not in pagina

    def test_con_retroalimentacion_diferida_no_se_muestran_las_aceptadas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course), feedback_mode=QuizConfig.Feedback.AFTER_CLOSE, attempts_allowed=2)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "Guadalajara"})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "CDMX" not in pagina and "Ciudad de México" not in pagina

    def test_sin_responder_lo_dice(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        intento = contestar(quiz, alumno, {})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Sin responder" in pagina


# ── Lo que ve el docente ──────────────────────────────────────────────

class TestDocente:
    def test_revision_de_un_intento(self, professor_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: "Monterrey"})
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        assert "Monterrey" in pagina and "respuesta del alumno" in pagina and "CDMX" in pagina

    def test_analisis_cuenta_respuestas_y_muestra_las_incorrectas_mas_comunes(self, course, alumno):
        from apps.accounts.tests.factories import StudentFactory
        from apps.courses.tests.factories import EnrollmentFactory

        quiz = quiz_con(course, corta(course), attempts_allowed=3)
        pregunta = quiz.questions.get()
        contestar(quiz, alumno, {pregunta.pk: "Monterrey"})
        for texto in ("monterrey!", "CDMX", ""):
            otro = EnrollmentFactory(course=course, student=StudentFactory()).student
            contestar(quiz, otro, {pregunta.pk: texto})
        dato = results.question_stats(quiz)[0]
        assert (dato["answered"], dato["unanswered"], dato["correct"]) == (3, 1, 1)
        assert dato["common_wrong"] == [("monterrey", 2)] and dato["choices"] == []

    def test_la_pagina_de_resultados_se_abre(self, professor_client, course, alumno, enrollment):
        quiz = quiz_con(course, corta(course))
        pregunta = quiz.questions.get()
        contestar(quiz, alumno, {pregunta.pk: "Monterrey"})
        pagina = professor_client.get(reverse("quizzes:results", args=[quiz.activity_id])).content.decode()
        assert "«monterrey»: 1" in pagina and "añádela a las aceptadas" in pagina


# ── Formulario del banco ──────────────────────────────────────────────

def datos(**cambios):
    base = {
        "text": "¿Capital de Francia?", "points": "1", "topic": "Geografía", "explanation": "",
        "choices-TOTAL_FORMS": "3", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
        "choices-0-text": "París", "choices-1-text": "Paris, Francia", "choices-2-text": "",
    }
    base.update(cambios)
    return base


class TestFormulario:
    def test_se_abre_con_filas_vacias_y_sin_casilla_de_correcta(self, professor_client):
        pagina = professor_client.get(reverse("quizzes:question_create", args=["short_answer"])).content.decode()
        assert "Respuestas aceptadas" in pagina and "Agregar respuesta" in pagina and "is_correct" not in pagina

    def test_crea_la_pregunta(self, professor_client):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["short_answer"]), datos())
        pregunta = Question.objects.get(text="¿Capital de Francia?")
        assert respuesta.url == reverse("quizzes:question_detail", args=[pregunta.pk]) and pregunta.kind == SHORT
        assert [c.text for c in pregunta.choices.all()] == ["París", "Paris, Francia"]

    @pytest.mark.parametrize("cambios, mensaje", [
        ({"choices-0-text": "", "choices-1-text": ""}, "al menos una"),
        ({"choices-1-text": "paris"}, "repetidas"),
        ({"choices-0-text": "???", "choices-1-text": ""}, "letras o números"),
    ])
    def test_rechaza_lo_invalido_y_no_guarda(self, professor_client, cambios, mensaje):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["short_answer"]), datos(**cambios))
        assert respuesta.status_code == 200 and mensaje in respuesta.content.decode()
        assert not Question.objects.exists()

    def test_editar_muestra_y_conserva_las_aceptadas(self, professor_client, course):
        pregunta = corta(course, accepted=("uno", "dos"))
        pagina = professor_client.get(reverse("quizzes:question_update", args=[pregunta.pk])).content.decode()
        assert 'value="uno"' in pagina and 'value="dos"' in pagina
        professor_client.post(reverse("quizzes:question_update", args=[pregunta.pk]), datos(**{
            "choices-INITIAL_FORMS": "2", "choices-0-text": "uno", "choices-1-text": "tres",
        }))
        assert [c.text for c in pregunta.choices.all()] == ["uno", "tres"]

    def test_el_detalle_y_el_banco_la_muestran(self, professor_client, course):
        pregunta = corta(course, accepted=("Roma",))
        detalle = professor_client.get(reverse("quizzes:question_detail", args=[pregunta.pk])).content.decode()
        assert "Respuestas aceptadas" in detalle and "Roma" in detalle and "✓ correcta" not in detalle
        banco = professor_client.get(reverse("quizzes:bank")).content.decode()
        assert "Respuesta corta" in banco and "Nueva respuesta corta" in banco

    def test_desde_el_constructor_queda_en_el_quiz(self, professor_client, course):
        quiz = make_quiz(course, questions=1, published=False)
        url = reverse("quizzes:question_create", args=["short_answer"]) + f"?add_to={quiz.activity_id}"
        respuesta = professor_client.post(url, datos())
        assert respuesta.url == reverse("quizzes:builder", args=[quiz.activity_id])
        assert quiz.questions.filter(kind=SHORT).count() == 1

    def test_el_constructor_muestra_las_respuestas_aceptadas_en_su_columna(self, professor_client, course):
        quiz = quiz_con(course, corta(course, accepted=("Roma", "Roma Italia")))
        pagina = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "Roma · Roma Italia" in pagina and "Nueva respuesta corta" in pagina


def test_la_pregunta_de_un_quiz_no_cambia_si_se_edita_la_del_banco(course):
    pregunta = corta(course, accepted=("Roma",))
    quiz = quiz_con(course, pregunta)
    save_question(
        organization=pregunta.organization, author=course.professor, kind=SHORT, text="Otra", points=1,
        choices=[("Milán", True)], question=pregunta,
    )
    assert [c.text for c in quiz.questions.get().choices.all()] == ["Roma"]
    assert QuizQuestion.objects.get().text != "Otra" and Choice.objects.filter(text="Milán").count() == 1
