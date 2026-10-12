"""Resolver un quiz: ventana, plazo del servidor, guardado, envío y cierre por tiempo."""

import random
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.factories import StudentFactory
from apps.courses.factories import EnrollmentFactory
from apps.courses.services.courses import archive_course
from apps.grades.factories import ActivityFactory
from apps.grades.models import Activity

from .factories import QuestionFactory, make_quiz
from .models import Answer, QuizAttempt
from .services import attempts as svc
from .services.attempts import AttemptExpired, GRACE_SECONDS

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
MIN = timedelta(minutes=1)
DIA = timedelta(days=1)


@pytest.fixture
def quiz(course):
    return make_quiz(course, questions=3, time_limit_minutes=30, attempts_allowed=2)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


def correcta(pregunta):
    return next(c for c in pregunta.choices.all() if c.is_correct)


def incorrecta(pregunta):
    return next(c for c in pregunta.choices.all() if not c.is_correct)


# ── Ventana y plazo ───────────────────────────────────────────────────

class TestVentana:
    @pytest.mark.parametrize("opens, due, esperado", [
        (None, None, "open"), (-1, 1, "open"), (1, 2, "not_open"), (-2, -1, "closed"), (None, -1, "closed"),
    ])
    def test_estados(self, course, opens, due, esperado):
        dia = lambda n: None if n is None else AHORA + n * DIA  # noqa: E731
        actividad = ActivityFactory(course=course, opens_at=dia(opens), due_at=dia(due))
        assert svc.window_state(actividad, AHORA) == esperado

    def test_justo_en_los_limites_esta_abierto(self, course):
        actividad = ActivityFactory(course=course, opens_at=AHORA, due_at=AHORA + MIN)
        assert svc.window_state(actividad, AHORA) == "open"
        assert svc.window_state(actividad, AHORA + MIN) == "open"
        assert svc.window_state(actividad, AHORA + MIN + timedelta(seconds=1)) == "closed"


class TestPlazo:
    def deadline(self, quiz, **config):
        for campo, valor in config.items():
            setattr(quiz.activity, campo, valor) if campo == "due_at" else setattr(quiz, campo, valor)
        return svc.compute_deadline(quiz, AHORA)

    def test_solo_tiempo_limite(self, quiz):
        assert self.deadline(quiz, time_limit_minutes=30) == AHORA + 30 * MIN

    def test_solo_fecha_de_cierre(self, quiz):
        assert self.deadline(quiz, time_limit_minutes=None, due_at=AHORA + 2 * DIA) == AHORA + 2 * DIA

    def test_gana_lo_que_ocurra_antes(self, quiz):
        assert self.deadline(quiz, time_limit_minutes=60, due_at=AHORA + 10 * MIN) == AHORA + 10 * MIN
        assert self.deadline(quiz, time_limit_minutes=5, due_at=AHORA + 10 * MIN) == AHORA + 5 * MIN

    def test_sin_limites(self, quiz):
        assert self.deadline(quiz, time_limit_minutes=None, due_at=None) is None

    def test_segundos_restantes(self, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno, AHORA)
        assert svc.remaining_seconds(intento, AHORA) == 1800
        assert svc.remaining_seconds(intento, AHORA + 10 * MIN) == 1200
        assert svc.remaining_seconds(intento, AHORA + 31 * MIN) == 0

    def test_sin_limite_no_hay_segundos(self, quiz, alumno):
        quiz.time_limit_minutes = None
        quiz.save()
        assert svc.remaining_seconds(svc.start_attempt(quiz, alumno, AHORA)) is None


class TestOrden:
    def test_sin_aleatoriedad_conserva_el_orden(self, quiz):
        capa = svc.build_layout(quiz)
        assert capa["questions"] == [q.pk for q in quiz.questions.all()]
        for q in quiz.questions.all():
            assert capa["choices"][str(q.pk)] == [c.pk for c in q.choices.all()]

    def test_baraja_preguntas_y_opciones(self, course):
        quiz = make_quiz(course, questions=8, shuffle_questions=True, shuffle_choices=True)
        capa = svc.build_layout(quiz, random.Random(7))
        assert sorted(capa["questions"]) == sorted(q.pk for q in quiz.questions.all())
        assert capa["questions"] != [q.pk for q in quiz.questions.all()]
        for q in quiz.questions.all():
            assert sorted(capa["choices"][str(q.pk)]) == sorted(c.pk for c in q.choices.all())

    def test_verdadero_o_falso_no_se_baraja(self, course):
        quiz = make_quiz(course, questions=0, shuffle_choices=True)
        from .services.builder import add_questions

        add_questions(quiz, [QuestionFactory(author=course.professor, organization=course.organization, kind="true_false")])
        pregunta = quiz.questions.get()
        for semilla in range(10):
            assert svc.build_layout(quiz, random.Random(semilla))["choices"][str(pregunta.pk)] == [c.pk for c in pregunta.choices.all()]


# ── Empezar ───────────────────────────────────────────────────────────

class TestEmpezar:
    def test_crea_el_intento_con_su_plazo_y_orden(self, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno, AHORA)
        assert (intento.number, intento.status, intento.started_at, intento.deadline) == (1, "in_progress", AHORA, AHORA + 30 * MIN)
        assert intento.layout["questions"] == [q.pk for q in quiz.questions.all()]
        assert intento.organization_id == quiz.organization_id

    def test_si_hay_uno_en_curso_lo_retoma(self, quiz, alumno):
        primero = svc.start_attempt(quiz, alumno, AHORA)
        assert svc.start_attempt(quiz, alumno, AHORA + 5 * MIN).pk == primero.pk
        assert quiz.attempts.count() == 1

    def test_el_tiempo_no_se_reinicia_al_retomar(self, quiz, alumno):
        primero = svc.start_attempt(quiz, alumno, AHORA)
        retomado = svc.start_attempt(quiz, alumno, AHORA + 20 * MIN)
        assert retomado.deadline == primero.deadline == AHORA + 30 * MIN

    def test_respeta_el_numero_de_intentos(self, quiz, alumno):
        svc.submit_attempt(svc.start_attempt(quiz, alumno, AHORA), now=AHORA)
        segundo = svc.start_attempt(quiz, alumno, AHORA + MIN)
        assert segundo.number == 2
        svc.submit_attempt(segundo, now=AHORA + 2 * MIN)
        with pytest.raises(ValidationError, match="todos tus intentos"):
            svc.start_attempt(quiz, alumno, AHORA + 3 * MIN)

    def test_un_intento_vencido_se_cierra_y_consume_su_lugar(self, quiz, alumno):
        quiz.attempts_allowed = 1
        quiz.save()
        svc.start_attempt(quiz, alumno, AHORA)
        with pytest.raises(ValidationError, match="todos tus intentos"):
            svc.start_attempt(quiz, alumno, AHORA + 31 * MIN)
        assert quiz.attempts.get().status == "expired"

    def test_un_intento_vencido_deja_empezar_otro_si_quedan(self, quiz, alumno):
        svc.start_attempt(quiz, alumno, AHORA)
        nuevo = svc.start_attempt(quiz, alumno, AHORA + 31 * MIN)
        assert nuevo.number == 2 and nuevo.status == "in_progress"
        assert quiz.attempts.get(number=1).status == "expired"

    @pytest.mark.parametrize("preparar, mensaje", [
        (lambda q: setattr(q.activity, "published", False) or q.activity.save(), "no está disponible"),
        (lambda q: setattr(q.activity, "opens_at", timezone.now() + DIA) or q.activity.save(), "todavía no abre"),
        (lambda q: setattr(q.activity, "due_at", timezone.now() - DIA) or q.activity.save(), "ya cerró"),
        (lambda q: q.questions.all().delete(), "no tiene preguntas"),
    ])
    def test_no_empieza_si(self, quiz, alumno, preparar, mensaje):
        preparar(quiz)
        with pytest.raises(ValidationError, match=mensaje):
            svc.start_attempt(quiz, alumno)
        assert not quiz.attempts.exists()

    def test_quien_no_esta_inscrito_no_empieza(self, quiz, course):
        from apps.courses.factories import StudentRecordFactory

        with pytest.raises(ValidationError, match="No estás inscrito"):
            svc.start_attempt(quiz, StudentRecordFactory(organization=course.organization))

    def test_grupo_archivado(self, quiz, alumno, course):
        archive_course(course)
        with pytest.raises(ValidationError, match="archivado"):
            svc.start_attempt(quiz, alumno)

    def test_dos_alumnos_tienen_intentos_independientes(self, quiz, alumno, course):
        otro = EnrollmentFactory(course=course).student
        a, b = svc.start_attempt(quiz, alumno, AHORA), svc.start_attempt(quiz, otro, AHORA)
        assert a.pk != b.pk and (a.number, b.number) == (1, 1)

    def test_el_cierre_de_la_actividad_acota_el_plazo(self, course, alumno):
        quiz = make_quiz(course, questions=1, time_limit_minutes=120, activity={"due_at": timezone.now() + 10 * MIN})
        intento = svc.start_attempt(quiz, alumno)
        assert intento.deadline == quiz.activity.due_at


# ── Guardar y enviar ──────────────────────────────────────────────────

class TestGuardar:
    @pytest.fixture
    def intento(self, quiz, alumno):
        return svc.start_attempt(quiz, alumno, AHORA)

    def test_guarda_respuestas_parciales(self, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        restante = svc.save_answers(intento, {p1.pk: correcta(p1).pk}, AHORA + 5 * MIN)
        assert restante == 25 * 60
        assert dict(intento.answers.values_list("question_id", "choice_id")) == {p1.pk: correcta(p1).pk}
        svc.save_answers(intento, {p2.pk: incorrecta(p2).pk}, AHORA + 6 * MIN)
        assert intento.answers.count() == 2

    def test_cambiar_y_borrar_una_respuesta(self, intento, quiz):
        p1 = quiz.questions.first()
        svc.save_answers(intento, {p1.pk: incorrecta(p1).pk}, AHORA)
        svc.save_answers(intento, {p1.pk: correcta(p1).pk}, AHORA)
        assert intento.answers.get().choice_id == correcta(p1).pk
        svc.save_answers(intento, {p1.pk: None}, AHORA)
        assert intento.answers.get().choice_id is None
        assert intento.answers.count() == 1

    def test_pregunta_ajena(self, intento, course):
        otra = make_quiz(course, questions=1).questions.get()
        with pytest.raises(ValidationError, match="no es de este quiz"):
            svc.save_answers(intento, {otra.pk: correcta(otra).pk}, AHORA)

    def test_opcion_de_otra_pregunta(self, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        with pytest.raises(ValidationError, match="no es de esa pregunta"):
            svc.save_answers(intento, {p1.pk: correcta(p2).pk}, AHORA)
        assert not intento.answers.exists()

    def test_una_seleccion_invalida_no_guarda_ni_las_validas(self, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        with pytest.raises(ValidationError):
            svc.save_answers(intento, {p1.pk: correcta(p1).pk, p2.pk: correcta(p1).pk}, AHORA)
        assert not intento.answers.exists()

    def test_dentro_del_margen_de_red_se_acepta(self, intento, quiz):
        p1 = quiz.questions.first()
        tarde = AHORA + 30 * MIN + timedelta(seconds=GRACE_SECONDS)
        svc.save_answers(intento, {p1.pk: correcta(p1).pk}, tarde)
        assert intento.answers.count() == 1

    def test_pasado_el_plazo_se_rechaza_y_se_cierra_con_lo_ya_guardado(self, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        svc.save_answers(intento, {p1.pk: correcta(p1).pk}, AHORA + MIN)
        tarde = AHORA + 30 * MIN + timedelta(seconds=GRACE_SECONDS + 1)
        with pytest.raises(AttemptExpired) as error:
            svc.save_answers(intento, {p2.pk: correcta(p2).pk}, tarde)
        cerrado = error.value.attempt
        assert (cerrado.status, cerrado.submitted_at, float(cerrado.score)) == ("expired", intento.deadline, 1.0)
        assert not Answer.objects.filter(attempt=intento, question=p2, choice__isnull=False).exists()  # la tardía no cuenta

    def test_un_intento_ya_cerrado_no_acepta_respuestas(self, intento, quiz):
        svc.submit_attempt(intento, now=AHORA)
        with pytest.raises(AttemptExpired):
            svc.save_answers(intento, {quiz.questions.first().pk: None}, AHORA)


class TestEnviar:
    @pytest.fixture
    def intento(self, quiz, alumno):
        return svc.start_attempt(quiz, alumno, AHORA)

    def test_califica_aciertos_errores_y_omisiones(self, intento, quiz):
        p1, p2, p3 = list(quiz.questions.all())
        enviado = svc.submit_attempt(intento, {p1.pk: correcta(p1).pk, p2.pk: incorrecta(p2).pk}, AHORA + 10 * MIN)
        assert (enviado.status, float(enviado.score), float(enviado.max_points), enviado.submitted_at) == ("submitted", 1.0, 3.0, AHORA + 10 * MIN)
        respuestas = {a.question_id: (a.is_correct, float(a.points_awarded)) for a in enviado.answers.all()}
        assert respuestas == {p1.pk: (True, 1.0), p2.pk: (False, 0.0), p3.pk: (False, 0.0)}  # la omitida también queda registrada

    def test_los_puntos_de_cada_pregunta_cuentan(self, course, alumno):
        quiz = make_quiz(course, questions=2)
        a, b = list(quiz.questions.all())
        type(a).objects.filter(pk=a.pk).update(points=3)
        intento = svc.start_attempt(quiz, alumno, AHORA)
        enviado = svc.submit_attempt(intento, {a.pk: correcta(a).pk, b.pk: incorrecta(b).pk}, AHORA)
        assert (float(enviado.score), float(enviado.max_points)) == (3.0, 4.0)

    def test_enviar_sin_responder_nada(self, intento):
        enviado = svc.submit_attempt(intento, now=AHORA)
        assert float(enviado.score) == 0 and enviado.status == "submitted"

    def test_enviar_dos_veces_es_inofensivo(self, intento, quiz):
        p1 = quiz.questions.first()
        primero = svc.submit_attempt(intento, {p1.pk: correcta(p1).pk}, AHORA)
        segundo = svc.submit_attempt(intento, {p1.pk: incorrecta(p1).pk}, AHORA + MIN)
        assert (segundo.pk, float(segundo.score), segundo.submitted_at) == (primero.pk, 1.0, primero.submitted_at)

    def test_enviar_despues_del_plazo_cierra_por_tiempo(self, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        svc.save_answers(intento, {p1.pk: correcta(p1).pk}, AHORA + MIN)
        tarde = AHORA + 40 * MIN
        enviado = svc.submit_attempt(intento, {p2.pk: correcta(p2).pk}, tarde)
        assert (enviado.status, float(enviado.score), enviado.submitted_at) == ("expired", 1.0, intento.deadline)

    def test_enviar_justo_dentro_del_margen_se_acepta(self, intento, quiz):
        p1 = quiz.questions.first()
        limite = AHORA + 30 * MIN + timedelta(seconds=GRACE_SECONDS)
        assert svc.submit_attempt(intento, {p1.pk: correcta(p1).pk}, limite).status == "submitted"

    def test_cerrar_por_tiempo_solo_si_esta_en_curso(self, intento):
        enviado = svc.submit_attempt(intento, now=AHORA)
        assert svc.expire_if_overdue(enviado, AHORA + DIA).status == "submitted"

    def test_expire_if_overdue(self, intento):
        assert svc.expire_if_overdue(intento, AHORA + 29 * MIN).status == "in_progress"
        assert svc.expire_if_overdue(intento, AHORA + 31 * MIN).status == "expired"

    def test_sin_limite_de_tiempo_nunca_vence(self, quiz, alumno):
        quiz.time_limit_minutes = None
        quiz.save()
        intento = svc.start_attempt(quiz, alumno, AHORA)
        assert svc.expire_if_overdue(intento, AHORA + 365 * DIA).status == "in_progress"

    def test_un_alumno_con_un_intento_en_curso_puede_tener_otro_ya_enviado(self, quiz, alumno):
        svc.submit_attempt(svc.start_attempt(quiz, alumno, AHORA), now=AHORA)
        abierto = svc.start_attempt(quiz, alumno, AHORA + MIN)
        assert QuizAttempt.objects.filter(student=alumno).count() == 2 and abierto.status == "in_progress"


# ── Pantallas del alumno ──────────────────────────────────────────────

def overview(quiz):
    return reverse("quizzes:overview", args=[quiz.activity_id])


def vencer(intento):
    QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - MIN)


class TestPantallaPrevia:
    def test_muestra_las_reglas(self, student_client, quiz, enrollment):
        context = student_client.get(overview(quiz)).context
        assert (context["question_count"], context["attempts_used"], context["blocked"], context["open_attempt"]) == (3, 0, None, None)
        html = student_client.get(overview(quiz)).content.decode()
        assert "30 minutos" in html and "0 de 2 usados" in html and "Comenzar el quiz" in html

    def test_comenzar_crea_el_intento_y_lleva_a_resolverlo(self, student_client, quiz, enrollment):
        response = student_client.post(overview(quiz))
        intento = QuizAttempt.objects.get()
        assert response.url == reverse("quizzes:take", args=[intento.pk]) and intento.status == "in_progress"

    def test_con_un_intento_en_curso_ofrece_continuar_sin_crear_otro(self, student_client, quiz, enrollment):
        student_client.post(overview(quiz))
        html = student_client.get(overview(quiz)).content.decode()
        assert "Continuar el intento 1" in html
        student_client.post(overview(quiz))
        assert QuizAttempt.objects.count() == 1

    def test_sin_intentos_disponibles(self, student_client, quiz, enrollment):
        quiz.attempts_allowed = 1
        quiz.save()
        svc.submit_attempt(svc.start_attempt(quiz, enrollment.student))
        context = student_client.get(overview(quiz)).context
        assert context["blocked"] == "Ya usaste todos tus intentos."
        response = student_client.post(overview(quiz), follow=True)
        assert any("todos tus intentos" in str(m) for m in response.context["messages"])

    def test_lista_los_intentos_con_su_resultado(self, student_client, quiz, enrollment):
        p1 = quiz.questions.first()
        svc.submit_attempt(svc.start_attempt(quiz, enrollment.student), {p1.pk: correcta(p1).pk})
        assert "1 / 3" in student_client.get(overview(quiz)).content.decode().replace("1,00", "1").replace("1.00", "1")

    def test_cierra_por_tiempo_un_intento_vencido_al_mirar(self, student_client, quiz, enrollment):
        intento = svc.start_attempt(quiz, enrollment.student)
        vencer(intento)
        context = student_client.get(overview(quiz)).context
        assert context["open_attempt"] is None
        assert QuizAttempt.objects.get().status == "expired"

    def test_antes_de_abrir_y_despues_de_cerrar(self, student_client, course, enrollment):
        futuro = make_quiz(course, questions=1, activity={"opens_at": timezone.now() + DIA})
        pasado = make_quiz(course, questions=1, activity={"due_at": timezone.now() - DIA})
        assert student_client.get(overview(futuro)).context["blocked"] == "El quiz todavía no abre."
        assert student_client.get(overview(pasado)).context["blocked"] == "El quiz ya cerró."

    def test_no_aparece_a_quien_no_esta_inscrito_ni_si_es_borrador(self, student_client, course, enrollment):
        borrador = make_quiz(course, questions=1, published=False)
        assert student_client.get(overview(borrador)).status_code == 404
        ajeno = make_quiz(EnrollmentFactory().course, questions=1)
        assert student_client.get(overview(ajeno)).status_code == 404

    def test_el_docente_no_lo_resuelve(self, professor_client, quiz):
        assert professor_client.get(overview(quiz)).status_code == 404

    def test_anonimo_va_al_login(self, client, quiz):
        assert client.get(overview(quiz)).url.startswith("/login/")

    def test_la_actividad_ofrece_el_enlace(self, student_client, quiz, enrollment):
        assert overview(quiz) in student_client.get(quiz.activity.get_absolute_url()).content.decode()


class TestResolver:
    @pytest.fixture
    def intento(self, quiz, alumno):
        return svc.start_attempt(quiz, alumno)

    def take(self, intento):
        return reverse("quizzes:take", args=[intento.pk])

    def test_muestra_las_preguntas_en_el_orden_del_intento(self, student_client, intento, quiz):
        inverso = list(reversed(intento.layout["questions"]))
        QuizAttempt.objects.filter(pk=intento.pk).update(layout={**intento.layout, "questions": inverso})
        filas = student_client.get(self.take(intento)).context["rows"]
        assert [f["question"].pk for f in filas] == inverso

    def test_respeta_el_orden_de_las_opciones_del_intento(self, student_client, intento, quiz):
        p1 = quiz.questions.first()
        ids = list(reversed([c.pk for c in p1.choices.all()]))
        capa = {**intento.layout, "choices": {**intento.layout["choices"], str(p1.pk): ids}}
        QuizAttempt.objects.filter(pk=intento.pk).update(layout=capa)
        fila = next(f for f in student_client.get(self.take(intento)).context["rows"] if f["question"].pk == p1.pk)
        assert [c.pk for c in fila["choices"]] == ids

    def test_trae_marcado_lo_ya_guardado_y_el_tiempo_del_servidor(self, student_client, intento, quiz):
        p1 = quiz.questions.first()
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        response = student_client.get(self.take(intento))
        fila = next(f for f in response.context["rows"] if f["question"].pk == p1.pk)
        assert fila["selected"] == correcta(p1).pk
        assert 1790 <= response.context["remaining"] <= 1800
        assert f'data-remaining="{response.context["remaining"]}"' in response.content.decode()

    def test_sin_limite_no_hay_temporizador(self, student_client, quiz, alumno):
        quiz.time_limit_minutes = None
        quiz.save()
        intento = svc.start_attempt(quiz, alumno)
        html = student_client.get(self.take(intento)).content.decode()
        assert 'data-remaining=""' in html and 'id="timer"' not in html

    def test_el_formulario_apunta_al_guardado_y_carga_el_script(self, student_client, intento):
        html = student_client.get(self.take(intento)).content.decode()
        assert reverse("quizzes:autosave", args=[intento.pk]) in html and "js/quiz.js" in html

    def test_enviar_califica_y_lleva_al_resultado(self, student_client, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        response = student_client.post(self.take(intento), {f"q_{p1.pk}": correcta(p1).pk, f"q_{p2.pk}": incorrecta(p2).pk})
        intento.refresh_from_db()
        assert response.url == reverse("quizzes:result", args=[intento.pk])
        assert (intento.status, float(intento.score)) == ("submitted", 1.0)

    def test_enviar_no_borra_lo_ya_guardado_de_lo_que_no_viene(self, student_client, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        student_client.post(self.take(intento), {f"q_{p2.pk}": correcta(p2).pk})
        intento.refresh_from_db()
        assert float(intento.score) == 2.0

    def test_enviar_con_el_tiempo_vencido_guarda_solo_lo_anterior(self, student_client, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - 10 * MIN)
        response = student_client.post(self.take(intento), {f"q_{p2.pk}": correcta(p2).pk}, follow=True)
        intento.refresh_from_db()
        assert (intento.status, float(intento.score)) == ("expired", 1.0)
        assert "Se acabó el tiempo" in response.content.decode()

    def test_abrir_un_intento_vencido_lo_cierra_y_muestra_el_resultado(self, student_client, intento):
        vencer(intento)
        response = student_client.get(self.take(intento))
        assert response.url == reverse("quizzes:result", args=[intento.pk])
        intento.refresh_from_db()
        assert intento.status == "expired"

    def test_un_intento_terminado_redirige_al_resultado(self, student_client, intento):
        svc.submit_attempt(intento)
        assert student_client.get(self.take(intento)).url == reverse("quizzes:result", args=[intento.pk])
        assert student_client.post(self.take(intento), {}).url == reverse("quizzes:result", args=[intento.pk])

    def test_un_alumno_no_ve_el_intento_de_otro(self, client, intento, course):
        otro = StudentFactory()
        EnrollmentFactory(course=course, student=otro)
        client.force_login(otro)
        for name in ("take", "autosave", "result"):
            assert client.get(reverse(f"quizzes:{name}", args=[intento.pk])).status_code in (404, 405)
        assert client.post(self.take(intento), {}).status_code == 404

    def test_el_docente_no_resuelve_intentos(self, professor_client, intento):
        assert professor_client.get(self.take(intento)).status_code == 404

    def test_anonimo_va_al_login(self, client, intento):
        assert client.get(self.take(intento)).url.startswith("/login/")


class TestGuardadoAutomatico:
    @pytest.fixture
    def intento(self, quiz, alumno):
        return svc.start_attempt(quiz, alumno)

    def guardar(self, client, intento, datos=None):
        return client.post(reverse("quizzes:autosave", args=[intento.pk]), datos or {})

    def test_guarda_y_devuelve_el_tiempo_restante(self, student_client, intento, quiz):
        p1 = quiz.questions.first()
        response = self.guardar(student_client, intento, {f"q_{p1.pk}": correcta(p1).pk})
        cuerpo = response.json()
        assert response.status_code == 200 and cuerpo["ok"] and 1790 <= cuerpo["remaining"] <= 1800
        assert intento.answers.get().choice_id == correcta(p1).pk

    def test_sin_respuestas_no_hace_nada_pero_responde(self, student_client, intento):
        assert self.guardar(student_client, intento).json()["ok"]

    def test_opcion_invalida_es_400(self, student_client, intento, quiz):
        p1, p2, _ = list(quiz.questions.all())
        response = self.guardar(student_client, intento, {f"q_{p1.pk}": correcta(p2).pk})
        assert response.status_code == 400 and "error" in response.json()

    def test_sin_tiempo_es_409_y_cierra_el_intento(self, student_client, intento, quiz):
        p1 = quiz.questions.first()
        QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - 10 * MIN)
        response = self.guardar(student_client, intento, {f"q_{p1.pk}": correcta(p1).pk})
        cuerpo = response.json()
        assert response.status_code == 409 and cuerpo["expired"] and cuerpo["url"] == reverse("quizzes:result", args=[intento.pk])
        intento.refresh_from_db()
        assert intento.status == "expired" and not intento.answers.filter(choice__isnull=False).exists()

    def test_un_intento_ya_enviado_responde_409(self, student_client, intento):
        svc.submit_attempt(intento)
        assert self.guardar(student_client, intento).status_code == 409

    def test_exige_el_token_csrf(self, intento, alumno):
        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(alumno.user)
        assert cliente.post(reverse("quizzes:autosave", args=[intento.pk]), {}).status_code == 403

    def test_solo_acepta_post(self, student_client, intento):
        assert student_client.get(reverse("quizzes:autosave", args=[intento.pk])).status_code == 405


class TestResultado:
    @pytest.fixture
    def enviado(self, quiz, alumno):
        p1, p2, _ = list(quiz.questions.all())
        return svc.submit_attempt(svc.start_attempt(quiz, alumno), {p1.pk: correcta(p1).pk, p2.pk: correcta(p2).pk})

    def test_muestra_la_calificacion(self, student_client, enviado):
        response = student_client.get(reverse("quizzes:result", args=[enviado.pk]))
        assert response.status_code == 200 and response.context["percent"] == 67
        assert "de 3" in response.content.decode()

    def test_un_intento_en_curso_redirige_a_resolverlo(self, student_client, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno)
        assert student_client.get(reverse("quizzes:result", args=[intento.pk])).url == reverse("quizzes:take", args=[intento.pk])

    def test_avisa_si_se_cerro_por_tiempo(self, student_client, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno)
        vencer(intento)
        html = student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()
        assert "Se acabó el tiempo" in html
