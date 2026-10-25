"""Preguntas de relacionar columnas: el alumno elige la pareja de cada elemento y cada pareja vale lo mismo."""

import random
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounts.tests.factories import StudentFactory
from apps.courses.services.courses import clone_course
from apps.courses.tests.factories import AcademicYearFactory, EnrollmentFactory
from apps.grades.models import Grade
from apps.quizzes.models import Answer, Question, QuizConfig
from apps.quizzes.services import answers as svc_answers
from apps.quizzes.services import attempts as svc
from apps.quizzes.services import results
from apps.quizzes.services.bank import duplicate_question, save_question, validate_pairs
from apps.quizzes.services.builder import add_questions
from apps.quizzes.take_views import parse_selections
from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db

MATCHING = Question.Kind.MATCHING
RAIZ = Path(__file__).resolve().parents[3]
PAISES = (("México", "Ciudad de México"), ("Perú", "Lima"), ("Chile", "Santiago"), ("Colombia", "Bogotá"))


def relacionar(course, pares=PAISES, points=4, text="Relaciona cada país con su capital.", grupo=None, **extra):
    return QuestionFactory(
        author=course.professor, organization=course.organization, kind=MATCHING, text=text, points=points,
        choices=[(izq, der) for izq, der in pares], course=grupo, **extra,
    )


def quiz_con(course, *preguntas, **config):
    quiz = make_quiz(course, questions=0, published=False, **config)
    add_questions(quiz, list(preguntas))
    quiz.activity.published = True
    quiz.activity.save()
    return quiz


def ids(pregunta):
    return svc_answers.correct_order(pregunta)


def correctas(pregunta):
    return {i: i for i in ids(pregunta)}


def contestar(quiz, alumno, respuestas):
    return svc.submit_attempt(svc.start_attempt(quiz, alumno), respuestas)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


@pytest.fixture
def caso(course):
    quiz = quiz_con(course, relacionar(course))
    return quiz, quiz.questions.get()


# ── Banco ─────────────────────────────────────────────────────────────

class TestBanco:
    def test_guarda_cada_pareja_en_su_orden(self, course):
        pregunta = relacionar(course)
        assert [(c.text, c.match_text) for c in pregunta.choices.all()] == list(PAISES)
        assert [c.position for c in pregunta.choices.all()] == [0, 1, 2, 3]

    @pytest.mark.parametrize("pares, mensaje", [
        ([], "al menos 2"), ([("a", "b")], "al menos 2"), ([("", ""), ("  ", " "), ("a", "b")], "al menos 2"),
        ([(f"i{n}", f"d{n}") for n in range(9)], "Máximo 8"),
        ([("a", "b"), ("c", "")], "dos lados"), ([("a", "b"), ("", "d")], "dos lados"),
        ([("Perú", "Lima"), ("PERU", "Quito")], "izquierda"), ([("Perú", "Lima"), ("Chile", "lima")], "derecha"),
        ([("a" * 501, "b"), ("c", "d")], "500"), ([("Árbol", "x"), ("arbol", "y")], "izquierda"),
    ])
    def test_valida_las_parejas(self, pares, mensaje):
        with pytest.raises(ValidationError, match=mensaje):
            validate_pairs(pares)

    def test_ignora_filas_en_blanco_y_recorta(self):
        assert validate_pairs([(" a ", " b "), ("", ""), ("c", "d")]) == [("a", False, "b"), ("c", False, "d")]

    def test_un_valor_repetido_en_ambas_columnas_es_valido(self):
        assert len(validate_pairs([("2", "dos"), ("dos", "2")])) == 2

    def test_editar_reemplaza_las_parejas_y_no_cambia_el_tipo(self, course, professor):
        pregunta = relacionar(course)
        save_question(
            organization=pregunta.organization, author=professor, kind=MATCHING, text="Nueva", points=2,
            choices=[("1", "uno"), ("2", "dos")], question=pregunta,
        )
        assert [(c.text, c.match_text) for c in pregunta.choices.all()] == [("1", "uno"), ("2", "dos")]
        with pytest.raises(ValidationError, match="tipo"):
            save_question(
                organization=pregunta.organization, author=professor, kind=Question.Kind.ORDERING, text="x", points=1,
                choices=[("a", False), ("b", False)], question=pregunta,
            )

    def test_duplicar_la_pregunta_conserva_las_parejas(self, course, professor):
        copia = duplicate_question(relacionar(course), by=professor)
        assert [(c.text, c.match_text) for c in copia.choices.all()] == list(PAISES)

    def test_el_banco_del_grupo_duplicado_conserva_las_parejas(self, course):
        relacionar(course, grupo=course)
        nuevo = clone_course(course, AcademicYearFactory(organization=course.organization))
        copia = nuevo.bank_questions.get()
        assert [(c.text, c.match_text) for c in copia.choices.all()] == list(PAISES)

    def test_al_ponerla_en_un_quiz_y_al_duplicar_el_grupo_se_copian(self, course):
        quiz = quiz_con(course, relacionar(course))
        assert [(c.text, c.match_text) for c in quiz.questions.get().choices.all()] == list(PAISES)
        nuevo = clone_course(course, AcademicYearFactory(organization=course.organization))
        copia = QuizConfig.objects.get(activity__course=nuevo).questions.get()
        assert [(c.text, c.match_text) for c in copia.choices.all()] == list(PAISES)


# ── Revuelto ──────────────────────────────────────────────────────────

class TestRevuelto:
    @pytest.mark.parametrize("semilla", range(30))
    def test_la_columna_derecha_nunca_sale_alineada(self, caso, semilla):
        quiz, pregunta = caso
        derecha = svc.build_layout(quiz, random.Random(semilla))["choices"][str(pregunta.pk)]
        assert sorted(derecha) == sorted(ids(pregunta)) and derecha != ids(pregunta)

    def test_el_orden_de_la_izquierda_es_el_del_docente(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        posiciones = [pagina.index(f'name="m_{pregunta.pk}_{i}"') for i in ids(pregunta)]
        assert posiciones == sorted(posiciones)


# ── Leer lo que manda el alumno ───────────────────────────────────────

class TestLeer:
    def test_acepta_enteros_y_textos(self, caso):
        _, pregunta = caso
        a, b, c, d = ids(pregunta)
        validos = {a, b, c, d}
        assert svc_answers.coerce(pregunta, {a: b, c: d}, validos) == {"response": {str(a): b, str(c): d}}
        assert svc_answers.coerce(pregunta, {str(a): str(b)}, validos) == {"response": {str(a): b}}

    @pytest.mark.parametrize("valor", [None, "", {}])
    def test_vacio_borra(self, caso, valor):
        _, pregunta = caso
        assert svc_answers.coerce(pregunta, valor, set(ids(pregunta))) == {"response": None}

    @pytest.mark.parametrize("hacer, mensaje", [
        (lambda a, b, c, d: {a: 10**9}, "no es de esa pregunta"), (lambda a, b, c, d: {10**9: a}, "no es de esa pregunta"),
        (lambda a, b, c, d: {a: "abc"}, "no es de esa pregunta"), (lambda a, b, c, d: {"²": a}, "no es de esa pregunta"),
        (lambda a, b, c, d: {a: b, c: b}, "una sola vez"), (lambda a, b, c, d: [a, b], "Relaciona"), (lambda a, b, c, d: "1,2", "Relaciona"),
    ])
    def test_rechaza_lo_invalido(self, caso, hacer, mensaje):
        _, pregunta = caso
        a, b, c, d = ids(pregunta)
        with pytest.raises(ValidationError, match=mensaje):
            svc_answers.coerce(pregunta, hacer(a, b, c, d), {a, b, c, d})

    def test_dejar_un_elemento_sin_pareja_es_valido(self, caso):
        _, pregunta = caso
        a, b, c, d = ids(pregunta)
        assert svc_answers.coerce(pregunta, {a: a}, {a, b, c, d}) == {"response": {str(a): a}}

    def test_guardar_rechaza_lo_invalido_sin_tocar_lo_anterior(self, caso, alumno):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        a, b, *_ = ids(pregunta)
        svc.save_answers(intento, {pregunta.pk: {a: a}})
        with pytest.raises(ValidationError):
            svc.save_answers(intento, {pregunta.pk: {a: b, b: b}})
        assert Answer.objects.get(attempt=intento).response == {str(a): a}

    def test_el_formulario_se_convierte_en_parejas(self):
        assert parse_selections({"m_7_1": "5", "m_7_2": "", "m_7_3": "6", "q_8": "9"}) == {7: {1: "5", 3: "6"}, 8: "9"}

    def test_una_peticion_que_mezcla_los_dos_formatos_no_rompe(self):
        assert parse_selections({"q_7": "x", "m_7_1": "5"}) == {7: {1: "5"}}
        assert parse_selections({"m_7_1": "5", "q_7": "x"}) == {7: "x"}

    def test_si_no_eligio_ninguna_la_pregunta_queda_vacia(self):
        assert parse_selections({"m_7_1": "", "m_7_2": ""}) == {7: {}}

    @pytest.mark.parametrize("nombre", ["m_", "m_7", "m_7_", "m__1", "m_abc_1", "m_7_abc", "m_²_1", f"m_{'9' * 40}_1", "m_7_1_2", "m_-7_1"])
    def test_ignora_nombres_extranos(self, nombre):
        assert parse_selections({nombre: "5"}) in ({}, {7: {}})


# ── Calificar ─────────────────────────────────────────────────────────

class TestCalificar:
    def test_todo_bien_vale_completo(self, caso, alumno):
        quiz, pregunta = caso
        intento = contestar(quiz, alumno, {pregunta.pk: correctas(pregunta)})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded, intento.score) == (True, 4, 4)
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_todo_mal_vale_cero(self, caso, alumno):
        quiz, pregunta = caso
        a, b, c, d = ids(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: {a: b, b: c, c: d, d: a}})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded) == (False, 0)

    @pytest.mark.parametrize("elegidas, esperado", [
        ({0: 0, 1: 1, 2: 3, 3: 2}, "2"), ({0: 0}, "1"), ({0: 0, 1: 1, 2: 2}, "3"), ({0: 1, 1: 0, 2: 2, 3: 3}, "2"), ({0: 1, 1: 0, 2: 3, 3: 2}, "0"),
    ])
    def test_los_puntos_son_proporcionales_y_dejar_en_blanco_cuenta_como_fallo(self, caso, alumno, elegidas, esperado):
        quiz, pregunta = caso
        base = ids(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: {base[i]: base[j] for i, j in elegidas.items()}})
        assert Answer.objects.get(attempt=intento).points_awarded == Decimal(esperado)

    def test_sin_responder_vale_cero(self, caso, alumno):
        quiz, pregunta = caso
        intento = contestar(quiz, alumno, {})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded, intento.score) == (False, 0, 0)
        assert not svc_answers.has_answer(pregunta, respuesta)

    def test_se_mezcla_con_ordenar_y_con_abierta(self, course, alumno, professor):
        ordenar = QuestionFactory(
            author=course.professor, organization=course.organization, kind=Question.Kind.ORDERING, points=2,
            choices=[("a", False), ("b", False)],
        )
        abierta = QuestionFactory(author=course.professor, organization=course.organization, kind=Question.Kind.OPEN, points=2)
        quiz = quiz_con(course, relacionar(course, points=4), ordenar, abierta)
        p_rel, p_ord, p_abi = quiz.questions.all()
        intento = contestar(quiz, alumno, {p_rel.pk: correctas(p_rel), p_ord.pk: ids(p_ord), p_abi.pk: "texto"})
        assert intento.score == 6 and results.pending_count(intento) == 1 and not Grade.objects.filter(activity=quiz.activity).exists()
        results.grade_open_answers(intento, {Answer.objects.get(attempt=intento, question=p_abi).pk: ("1", "")}, by=professor)
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == pytest.approx(10 * 7 / 8)


# ── Responder desde la página ─────────────────────────────────────────

class TestPagina:
    def test_muestra_un_menu_por_elemento_con_las_mismas_opciones(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert pagina.count(f'name="m_{pregunta.pk}_') == 4 and pagina.count("Elige…") == 4
        for _, derecha in PAISES:
            assert pagina.count(f">{derecha}</option>") == 4
        assert "Cada opción se usa una sola vez" in pagina and "data-pareo" in pagina

    def test_el_guardado_automatico_guarda_y_se_muestra_al_volver(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        a, b, *_ = ids(pregunta)
        enviado = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {
            f"m_{pregunta.pk}_{a}": str(a), f"m_{pregunta.pk}_{b}": "",
        })
        assert enviado.json()["ok"] and Answer.objects.get(attempt=intento).response == {str(a): a}
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert f'<option value="{a}" selected>' in pagina and pagina.count(" selected>") == 1

    def test_quitar_todas_las_elecciones_borra_la_respuesta(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        a, b, *_ = ids(pregunta)
        url = reverse("quizzes:autosave", args=[intento.pk])
        student_client.post(url, {f"m_{pregunta.pk}_{a}": str(b)})
        student_client.post(url, {f"m_{pregunta.pk}_{a}": ""})
        assert Answer.objects.get(attempt=intento).response is None

    def test_una_opcion_repetida_responde_400(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        a, b, *_ = ids(pregunta)
        enviado = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {
            f"m_{pregunta.pk}_{a}": str(a), f"m_{pregunta.pk}_{b}": str(a),
        })
        assert enviado.status_code == 400 and not Answer.objects.exists()

    def test_enviar_desde_la_pagina_califica(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"m_{pregunta.pk}_{i}": str(i) for i in ids(pregunta)})
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_el_script_deshabilita_lo_ya_elegido_y_manda_los_menus(self):
        codigo = (RAIZ / "static/js/quiz.js").read_text(encoding="utf-8")
        assert "setupMatching" in codigo and "data-pareo" in codigo and "select[name^=m_]" in codigo and "option.disabled" in codigo

    def test_los_textos_se_escapan(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course, pares=(("<b>x</b>", "<i>y</i>"), ("z", "w"))))
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert "<b>x</b>" not in pagina and "<i>y</i>" not in pagina and "&lt;b&gt;x&lt;/b&gt;" in pagina


# ── Revisión ──────────────────────────────────────────────────────────

class TestRevision:
    def test_el_alumno_ve_sus_parejas_y_las_correctas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        a, b, c, d = ids(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: {a: a, b: c, c: b, d: d}})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Tu relación" in pagina and "2 de 4 parejas" in pagina and ">Parcial</span>" in pagina
        assert '<span class="bien">México → Ciudad de México</span>' in pagina and '<span class="mal">Perú → Santiago</span>' in pagina
        assert "Debía ser: Lima" in pagina and "✓ correcto" in pagina

    def test_un_elemento_sin_pareja_se_marca_mal(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        a, *_ = ids(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: {a: a}})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert '<span class="mal">Perú → —</span>' in pagina and "1 de 4 parejas" in pagina

    def test_con_retroalimentacion_diferida_no_se_revelan_las_parejas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course), feedback_mode=QuizConfig.Feedback.AFTER_CLOSE, attempts_allowed=2)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: {i: i for i in ids(pregunta)[:2]}})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Lima" not in pagina and "Debía ser" not in pagina

    def test_sin_responder_se_dice_y_se_dan_las_parejas(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        intento = contestar(quiz, alumno, {})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Sin responder" in pagina and "Las parejas correctas eran" in pagina and "Perú → Lima" in pagina

    def test_completa_se_marca_correcta(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, relacionar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: correctas(pregunta)})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Correcta" in pagina and "4 de 4 parejas" in pagina and ">Parcial</span>" not in pagina

    def test_el_docente_ve_la_relacion_del_alumno(self, professor_client, caso, alumno):
        quiz, pregunta = caso
        a, b, *_ = ids(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: {a: b}})
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        assert "Relación del alumno" in pagina and "México → Lima" in pagina and "0 de 4 parejas" in pagina

    def test_el_analisis_cuenta_las_respuestas(self, caso, course, alumno):
        quiz, pregunta = caso
        contestar(quiz, alumno, {pregunta.pk: correctas(pregunta)})
        otro = EnrollmentFactory(course=course, student=StudentFactory()).student
        contestar(quiz, otro, {})
        dato = results.question_stats(quiz)[0]
        assert (dato["answered"], dato["unanswered"], dato["correct"], dato["choices"]) == (1, 1, 1, [])


# ── Formulario del banco ──────────────────────────────────────────────

def datos(**cambios):
    base = {
        "text": "Relaciona.", "points": "3", "topic": "", "explanation": "",
        "choices-TOTAL_FORMS": "4", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
        "choices-0-text": "México", "choices-0-match_text": "CDMX", "choices-1-text": "Perú", "choices-1-match_text": "Lima",
        "choices-2-text": "Chile", "choices-2-match_text": "Santiago", "choices-3-text": "", "choices-3-match_text": "",
    }
    base.update(cambios)
    return base


class TestFormulario:
    def test_se_abre_con_dos_columnas_y_sin_casilla_de_correcta(self, professor_client):
        pagina = professor_client.get(reverse("quizzes:question_create", args=["matching"])).content.decode()
        assert "Parejas" in pagina and "Agregar pareja" in pagina and 'placeholder="Le corresponde"' in pagina
        assert "is_correct" not in pagina and "Correcta</label>" not in pagina and pagina.count('name="choices-0-') == 2

    def test_crea_la_pregunta(self, professor_client):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["matching"]), datos())
        pregunta = Question.objects.get()
        assert respuesta.url == reverse("quizzes:question_detail", args=[pregunta.pk])
        assert [(c.text, c.match_text) for c in pregunta.choices.all()] == [("México", "CDMX"), ("Perú", "Lima"), ("Chile", "Santiago")]

    @pytest.mark.parametrize("cambios, mensaje", [
        ({"choices-2-match_text": ""}, "dos lados"),
        ({"choices-1-text": "", "choices-1-match_text": "", "choices-2-text": "", "choices-2-match_text": ""}, "al menos 2"),
        ({"choices-1-match_text": "cdmx"}, "derecha"),
        ({"choices-1-text": "méxico"}, "izquierda"),
    ])
    def test_rechaza_lo_invalido_y_no_guarda(self, professor_client, cambios, mensaje):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["matching"]), datos(**cambios))
        assert respuesta.status_code == 200 and mensaje in respuesta.content.decode() and not Question.objects.exists()

    def test_editar_muestra_y_cambia_las_parejas(self, professor_client, course):
        pregunta = relacionar(course, pares=(("A", "1"), ("B", "2")))
        pagina = professor_client.get(reverse("quizzes:question_update", args=[pregunta.pk])).content.decode()
        assert 'value="A"' in pagina and 'value="2"' in pagina
        professor_client.post(reverse("quizzes:question_update", args=[pregunta.pk]), datos(**{
            "choices-INITIAL_FORMS": "2", "choices-0-text": "A", "choices-0-match_text": "uno", "choices-1-text": "B", "choices-1-match_text": "dos",
            "choices-2-text": "", "choices-2-match_text": "",
        }))
        assert [(c.text, c.match_text) for c in pregunta.choices.all()] == [("A", "uno"), ("B", "dos")]

    def test_detalle_banco_y_constructor(self, professor_client, course):
        pregunta = relacionar(course)
        detalle = professor_client.get(reverse("quizzes:question_detail", args=[pregunta.pk])).content.decode()
        assert "Perú → Lima" in detalle and "✓ correcta" not in detalle
        assert "Nueva de relacionar" in professor_client.get(reverse("quizzes:bank")).content.decode()
        quiz = quiz_con(course, pregunta)
        constructor = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "Perú → Lima" in constructor and "Nueva de relacionar" in constructor

    def test_desde_el_constructor_queda_en_el_quiz(self, professor_client, course):
        quiz = make_quiz(course, questions=1, published=False)
        url = reverse("quizzes:question_create", args=["matching"]) + f"?add_to={quiz.activity_id}"
        assert professor_client.post(url, datos()).url == reverse("quizzes:builder", args=[quiz.activity_id])
        assert quiz.questions.filter(kind=MATCHING).count() == 1
