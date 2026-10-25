"""Preguntas de ordenar: el alumno acomoda los elementos y cada uno en su lugar vale lo mismo."""

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
from apps.quizzes.services.bank import duplicate_question, save_question, validate_items
from apps.quizzes.services.builder import add_questions
from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db

ORDERING = Question.Kind.ORDERING
RAIZ = Path(__file__).resolve().parents[3]
ETAPAS = ("Evaporación", "Condensación", "Precipitación", "Escurrimiento")


def ordenar(course, items=ETAPAS, points=4, text="Ordena el ciclo del agua.", grupo=None, **extra):
    return QuestionFactory(
        author=course.professor, organization=course.organization, kind=ORDERING, text=text, points=points,
        choices=[(item, False) for item in items], course=grupo, **extra,
    )


def quiz_con(course, *preguntas, **config):
    quiz = make_quiz(course, questions=0, published=False, **config)
    add_questions(quiz, list(preguntas))
    quiz.activity.published = True
    quiz.activity.save()
    return quiz


def ids_correctos(pregunta):
    return svc_answers.correct_order(pregunta)


def contestar(quiz, alumno, respuestas):
    return svc.submit_attempt(svc.start_attempt(quiz, alumno), respuestas)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


@pytest.fixture
def caso(course):
    quiz = quiz_con(course, ordenar(course))
    return quiz, quiz.questions.get()


# ── Banco ─────────────────────────────────────────────────────────────

class TestBanco:
    def test_conserva_el_orden_correcto(self, course):
        pregunta = ordenar(course)
        assert [c.text for c in pregunta.choices.all()] == list(ETAPAS)
        assert [c.position for c in pregunta.choices.all()] == [0, 1, 2, 3]

    @pytest.mark.parametrize("items, mensaje", [
        ([], "al menos 2"), (["uno"], "al menos 2"), (["", "  ", "uno"], "al menos 2"),
        ([f"e{n}" for n in range(9)], "Máximo 8"), (["Agua", "agua"], "repetidos"), (["Árbol", "ARBOL"], "repetidos"),
        (["a" * 501, "b"], "500"),
    ])
    def test_valida_los_elementos(self, items, mensaje):
        with pytest.raises(ValidationError, match=mensaje):
            validate_items([(i, False) for i in items])

    def test_las_filas_vacias_se_ignoran_y_se_recorta(self):
        assert validate_items([(" uno ", False), ("", False), ("dos", False)]) == [("uno", False), ("dos", False)]

    def test_editar_cambia_el_orden_y_no_el_tipo(self, course, professor):
        pregunta = ordenar(course)
        save_question(
            organization=pregunta.organization, author=professor, kind=ORDERING, text="Nueva", points=2,
            choices=[("B", False), ("A", False)], question=pregunta,
        )
        assert [c.text for c in pregunta.choices.all()] == ["B", "A"]
        with pytest.raises(ValidationError, match="tipo"):
            save_question(
                organization=pregunta.organization, author=professor, kind=Question.Kind.OPEN, text="x", points=1, question=pregunta,
            )

    def test_duplicar_y_copiar_el_banco_conservan_el_orden(self, course, professor):
        original = ordenar(course, grupo=course)
        copia = duplicate_question(original, by=professor)
        assert [c.text for c in copia.choices.all()] == list(ETAPAS)
        nuevo_grupo = clone_course(course, AcademicYearFactory(organization=course.organization))
        assert any([c.text for c in q.choices.all()] == list(ETAPAS) for q in nuevo_grupo.bank_questions.all())

    def test_al_ponerla_en_un_quiz_se_copian_en_orden(self, caso):
        _, copia = caso
        assert copia.kind == ORDERING and [c.text for c in copia.choices.all()] == list(ETAPAS)


# ── Orden revuelto ────────────────────────────────────────────────────

class TestRevuelto:
    @pytest.mark.parametrize("semilla", range(40))
    def test_nunca_se_muestra_ya_ordenado(self, caso, semilla):
        quiz, pregunta = caso
        diseno = svc.build_layout(quiz, random.Random(semilla))
        assert sorted(diseno["choices"][str(pregunta.pk)]) == sorted(ids_correctos(pregunta))
        assert diseno["choices"][str(pregunta.pk)] != ids_correctos(pregunta)

    @pytest.mark.parametrize("semilla", range(30))
    def test_con_dos_elementos_tampoco(self, course, semilla):
        quiz = quiz_con(course, ordenar(course, items=("Primero", "Segundo")))
        pregunta = quiz.questions.get()
        assert svc.build_layout(quiz, random.Random(semilla))["choices"][str(pregunta.pk)] == ids_correctos(pregunta)[::-1]

    def test_si_el_azar_no_ayuda_se_rota(self, caso):
        quiz, pregunta = caso

        class SinAzar:
            def shuffle(self, lista):
                pass

        diseno = svc.build_layout(quiz, SinAzar())["choices"][str(pregunta.pk)]
        correcto = ids_correctos(pregunta)
        assert diseno == correcto[1:] + correcto[:1]

    def test_se_revuelve_aunque_el_quiz_no_baraje_las_opciones(self, course, alumno):
        quiz = quiz_con(course, ordenar(course), shuffle_choices=False, shuffle_questions=False)
        pregunta = quiz.questions.get()
        intento = svc.start_attempt(quiz, alumno)
        assert intento.layout["choices"][str(pregunta.pk)] != ids_correctos(pregunta)


# ── Leer lo que manda el alumno ───────────────────────────────────────

class TestLeer:
    def test_acepta_lista_o_texto(self, caso):
        _, pregunta = caso
        ids = ids_correctos(pregunta)
        validos = set(ids)
        assert svc_answers.coerce(pregunta, ids[::-1], validos) == {"response": ids[::-1]}
        assert svc_answers.coerce(pregunta, ",".join(map(str, ids[::-1])), validos) == {"response": ids[::-1]}
        assert svc_answers.coerce(pregunta, " , ".join(map(str, ids)), validos) == {"response": ids}

    @pytest.mark.parametrize("valor", [None, "", []])
    def test_vacio_borra(self, caso, valor):
        _, pregunta = caso
        assert svc_answers.coerce(pregunta, valor, set(ids_correctos(pregunta))) == {"response": None}

    @pytest.mark.parametrize("hacer", [
        lambda ids: ids[:-1],                    # falta uno
        lambda ids: ids + [ids[0]],              # repetido
        lambda ids: ids[:-1] + [10**9],          # de otra pregunta
        lambda ids: ids[:-1] + ["abc"],          # no es un id
        lambda ids: ids[:-1] + ["²"],
        lambda ids: ids[:-1] + ["9" * 40],
        lambda ids: ids + [10**9],               # de más
    ])
    def test_rechaza_ordenes_incompletos_o_ajenos(self, caso, hacer):
        _, pregunta = caso
        ids = ids_correctos(pregunta)
        valor = ",".join(str(i) for i in hacer(ids))
        with pytest.raises(ValidationError, match="Ordena todos"):
            svc_answers.coerce(pregunta, valor, set(ids))

    def test_guardar_rechaza_lo_invalido_sin_tocar_lo_anterior(self, caso, alumno):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        ids = ids_correctos(pregunta)
        svc.save_answers(intento, {pregunta.pk: ids[::-1]})
        with pytest.raises(ValidationError):
            svc.save_answers(intento, {pregunta.pk: ids[:2]})
        assert Answer.objects.get(attempt=intento).response == ids[::-1]
        svc.save_answers(intento, {pregunta.pk: None})
        assert Answer.objects.get(attempt=intento).response is None


# ── Calificar ─────────────────────────────────────────────────────────

class TestCalificar:
    def test_todo_en_su_lugar_vale_completo(self, caso, alumno):
        quiz, pregunta = caso
        intento = contestar(quiz, alumno, {pregunta.pk: ids_correctos(pregunta)})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded, intento.score) == (True, 4, 4)
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_ninguno_en_su_lugar_vale_cero(self, caso, alumno):
        quiz, pregunta = caso
        ids = ids_correctos(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: ids[1:] + ids[:1]})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded) == (False, 0)

    @pytest.mark.parametrize("orden, esperado", [
        ([0, 1, 3, 2], "2"), ([1, 0, 2, 3], "2"), ([0, 2, 1, 3], "2"), ([3, 1, 2, 0], "2"), ([0, 1, 2, 3], "4"),
        ([1, 0, 3, 2], "0"), ([0, 3, 2, 1], "2"), ([2, 1, 0, 3], "2"), ([1, 2, 3, 0], "0"),
    ])
    def test_los_puntos_son_proporcionales(self, caso, alumno, orden, esperado):
        quiz, pregunta = caso
        ids = ids_correctos(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: [ids[i] for i in orden]})
        assert Answer.objects.get(attempt=intento).points_awarded == Decimal(esperado)

    @pytest.mark.parametrize("puntos, colocados, total, esperado", [
        (1, 1, 3, "0.33"), (1, 2, 3, "0.67"), (5, 1, 4, "1.25"), (2.5, 1, 3, "0.83"), (10, 3, 4, "7.50"), (1, 1, 8, "0.13"),
    ])
    def test_redondea_a_dos_decimales_hacia_arriba(self, course, puntos, colocados, total, esperado):
        pregunta = ordenar(course, items=[f"e{n}" for n in range(total)], points=puntos)
        pregunta.refresh_from_db()
        assert svc_answers.partial_points(pregunta, colocados, total) == Decimal(esperado)

    def test_sin_mover_o_sin_responder_vale_cero(self, caso, alumno):
        quiz, pregunta = caso
        intento = contestar(quiz, alumno, {})
        respuesta = Answer.objects.get(attempt=intento)
        assert (respuesta.is_correct, respuesta.points_awarded, intento.score) == (False, 0, 0)
        assert not svc_answers.has_answer(pregunta, respuesta)

    def test_se_mezcla_con_opcion_multiple(self, course, alumno):
        mc = QuestionFactory(author=course.professor, organization=course.organization)
        quiz = quiz_con(course, mc, ordenar(course, points=4))
        p_mc, p_ord = quiz.questions.all()
        bueno = next(c.pk for c in p_mc.choices.all() if c.is_correct)
        ids = ids_correctos(p_ord)
        intento = contestar(quiz, alumno, {p_mc.pk: bueno, p_ord.pk: [ids[1], ids[0], ids[2], ids[3]]})
        assert intento.score == 3 and Grade.objects.get(activity=quiz.activity, student=alumno).score == 6


# ── Responder desde la página ─────────────────────────────────────────

class TestPagina:
    def test_muestra_los_elementos_revueltos_con_flechas_y_sin_orden_marcado(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert pagina.count('data-mover="-1"') == 4 and pagina.count('data-mover="1"') == 4
        assert f'name="o_{pregunta.pk}" value=""' in pagina and "cuenta como sin responder" in pagina
        mostrados = [pagina.index(f'data-id="{i}"') for i in intento.layout["choices"][str(pregunta.pk)]]
        assert mostrados == sorted(mostrados)
        assert intento.layout["choices"][str(pregunta.pk)] != ids_correctos(pregunta)

    def test_el_guardado_automatico_guarda_el_orden_y_se_muestra_al_volver(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        ids = ids_correctos(pregunta)
        nuevo = [ids[2], ids[0], ids[3], ids[1]]
        enviado = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"o_{pregunta.pk}": ",".join(map(str, nuevo))})
        assert enviado.json()["ok"] and Answer.objects.get(attempt=intento).response == nuevo
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert f'name="o_{pregunta.pk}" value="{",".join(map(str, nuevo))}"' in pagina
        posiciones = [pagina.index(f'data-id="{i}"') for i in nuevo]
        assert posiciones == sorted(posiciones)

    def test_un_orden_invalido_responde_400_y_no_cambia_nada(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        enviado = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"o_{pregunta.pk}": "1,2"})
        assert enviado.status_code == 400 and not Answer.objects.exists()

    def test_enviar_desde_la_pagina_califica(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"o_{pregunta.pk}": ",".join(map(str, ids_correctos(pregunta)))})
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 10

    def test_sin_mover_y_enviando_el_campo_vacio_cuenta_como_sin_responder(self, student_client, caso, alumno, enrollment):
        quiz, pregunta = caso
        intento = svc.start_attempt(quiz, alumno)
        student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"o_{pregunta.pk}": ""})
        assert Grade.objects.get(activity=quiz.activity, student=alumno).score == 0
        assert Answer.objects.get().response is None

    def test_el_script_trae_las_flechas_y_manda_el_orden(self):
        codigo = (RAIZ / "static/js/quiz.js").read_text(encoding="utf-8")
        assert "setupOrdering" in codigo and "data-mover" in codigo and 'input[type=hidden][name^=o_]' in codigo


# ── Revisión ──────────────────────────────────────────────────────────

class TestRevision:
    def test_el_alumno_ve_su_orden_junto_al_correcto(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, ordenar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        ids = ids_correctos(pregunta)
        intento = contestar(quiz, alumno, {pregunta.pk: [ids[1], ids[0], ids[2], ids[3]]})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Tu orden" in pagina and "Orden correcto" in pagina and "2 de 4 en su lugar" in pagina and ">Parcial</span>" in pagina
        assert "1. Condensación" in pagina and "1. Evaporación" in pagina
        assert '<span class="mal">1. Condensación</span>' in pagina and '<span class="bien">3. Precipitación</span>' in pagina

    def test_con_retroalimentacion_diferida_no_se_muestra_el_orden_correcto(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, ordenar(course), feedback_mode=QuizConfig.Feedback.AFTER_CLOSE, attempts_allowed=2)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: ids_correctos(pregunta)[::-1]})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Orden correcto" not in pagina and "Evaporación" not in pagina

    def test_sin_responder_se_dice_y_se_da_el_orden(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, ordenar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        intento = contestar(quiz, alumno, {})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Sin responder" in pagina and "El orden correcto era" in pagina

    def test_completa_se_marca_correcta(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, ordenar(course), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        pregunta = quiz.questions.get()
        intento = contestar(quiz, alumno, {pregunta.pk: ids_correctos(pregunta)})
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Correcta" in pagina and "4 de 4 en su lugar" in pagina and ">Parcial</span>" not in pagina

    def test_el_docente_ve_el_orden_del_alumno(self, professor_client, caso, alumno):
        quiz, pregunta = caso
        intento = contestar(quiz, alumno, {pregunta.pk: ids_correctos(pregunta)[::-1]})
        pagina = professor_client.get(reverse("quizzes:review", args=[intento.pk])).content.decode()
        assert "Orden del alumno" in pagina and "0 de 4 en su lugar" in pagina and "1. Escurrimiento" in pagina

    def test_el_analisis_cuenta_las_respuestas(self, caso, course, alumno):
        quiz, pregunta = caso
        contestar(quiz, alumno, {pregunta.pk: ids_correctos(pregunta)})
        otro = EnrollmentFactory(course=course, student=StudentFactory()).student
        contestar(quiz, otro, {})
        dato = results.question_stats(quiz)[0]
        assert (dato["answered"], dato["unanswered"], dato["correct"], dato["choices"]) == (1, 1, 1, [])

    def test_los_elementos_se_escapan(self, student_client, course, alumno, enrollment):
        quiz = quiz_con(course, ordenar(course, items=("<b>uno</b>", "dos")), feedback_mode=QuizConfig.Feedback.AFTER_SUBMIT)
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert "<b>uno</b>" not in pagina and "&lt;b&gt;uno&lt;/b&gt;" in pagina


# ── Formulario del banco ──────────────────────────────────────────────

def datos(**cambios):
    base = {
        "text": "Ordena las etapas.", "points": "4", "topic": "", "explanation": "",
        "choices-TOTAL_FORMS": "4", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
        "choices-0-text": "Primero", "choices-1-text": "Segundo", "choices-2-text": "Tercero", "choices-3-text": "",
    }
    base.update(cambios)
    return base


class TestFormulario:
    def test_se_abre_con_el_texto_de_ayuda_y_sin_casilla_de_correcta(self, professor_client):
        pagina = professor_client.get(reverse("quizzes:question_create", args=["ordering"])).content.decode()
        assert "en el orden correcto" in pagina and "Agregar elemento" in pagina and "is_correct" not in pagina and "orden-num" in pagina

    def test_crea_la_pregunta_en_el_orden_escrito(self, professor_client):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["ordering"]), datos())
        pregunta = Question.objects.get()
        assert respuesta.url == reverse("quizzes:question_detail", args=[pregunta.pk])
        assert [c.text for c in pregunta.choices.all()] == ["Primero", "Segundo", "Tercero"]

    @pytest.mark.parametrize("cambios, mensaje", [
        ({"choices-1-text": "", "choices-2-text": ""}, "al menos 2"),
        ({"choices-1-text": "primero"}, "repetidos"),
    ])
    def test_rechaza_lo_invalido(self, professor_client, cambios, mensaje):
        respuesta = professor_client.post(reverse("quizzes:question_create", args=["ordering"]), datos(**cambios))
        assert respuesta.status_code == 200 and mensaje in respuesta.content.decode() and not Question.objects.exists()

    def test_editar_conserva_y_reordena(self, professor_client, course):
        pregunta = ordenar(course, items=("A", "B", "C"))
        pagina = professor_client.get(reverse("quizzes:question_update", args=[pregunta.pk])).content.decode()
        assert 'value="A"' in pagina and 'value="C"' in pagina
        professor_client.post(reverse("quizzes:question_update", args=[pregunta.pk]), datos(**{
            "choices-INITIAL_FORMS": "3", "choices-0-text": "C", "choices-1-text": "A", "choices-2-text": "B",
        }))
        assert [c.text for c in pregunta.choices.all()] == ["C", "A", "B"]

    def test_detalle_banco_y_constructor(self, professor_client, course):
        pregunta = ordenar(course)
        detalle = professor_client.get(reverse("quizzes:question_detail", args=[pregunta.pk])).content.decode()
        assert "Orden correcto" in detalle and "Evaporación" in detalle and "✓ correcta" not in detalle
        assert "Nueva de ordenar" in professor_client.get(reverse("quizzes:bank")).content.decode()
        quiz = quiz_con(course, pregunta)
        constructor = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "Evaporación → Condensación → Precipitación → Escurrimiento" in constructor and "Nueva de ordenar" in constructor

    def test_desde_el_constructor_queda_en_el_quiz(self, professor_client, course):
        quiz = make_quiz(course, questions=1, published=False)
        url = reverse("quizzes:question_create", args=["ordering"]) + f"?add_to={quiz.activity_id}"
        assert professor_client.post(url, datos()).url == reverse("quizzes:builder", args=[quiz.activity_id])
        assert quiz.questions.filter(kind=ORDERING).count() == 1
