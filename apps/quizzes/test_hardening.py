"""Endurecimiento del quiz: entradas hostiles, cierre automático y lo que no debe filtrarse."""

from datetime import timedelta
from io import StringIO

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.grades.models import Grade

from .factories import QuestionFactory, make_quiz
from .models import Answer, QuizAttempt
from .services import attempts as svc
from .services.attempts import GRACE_SECONDS, close_overdue_attempts
from .tasks import close_overdue_attempts_task

pytestmark = pytest.mark.django_db

MIN = timedelta(minutes=1)
GIGANTE = "9" * 5000
# Con etiquetas cortas: el id de una prueba con 5000 dígitos inunda la salida.
HOSTILES = [
    pytest.param(GIGANTE, id="gigante"), pytest.param("²", id="superindice"), pytest.param("٣", id="arabe"),
    pytest.param("-1", id="negativo"), pytest.param("1e3", id="exponente"), pytest.param("abc", id="letras"),
]


def correcta(pregunta):
    return next(c for c in pregunta.choices.all() if c.is_correct)


@pytest.fixture
def quiz(course):
    return make_quiz(course, questions=3, time_limit_minutes=10, attempts_allowed=3)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


# ── Entradas que antes provocaban un error 500 ────────────────────────

class TestEntradasHostiles:
    @pytest.mark.parametrize("valor", HOSTILES)
    def test_guardado_automatico_con_ids_invalidos(self, student_client, quiz, alumno, valor):
        intento = svc.start_attempt(quiz, alumno)
        p1 = quiz.questions.first()
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        url = reverse("quizzes:autosave", args=[intento.pk])
        # Un id de pregunta basura se ignora; si es absurdamente largo, Django mismo lo rechaza con 400. Nunca 500.
        assert student_client.post(url, {f"q_{valor}": "1"}).status_code in (200, 400)
        response = student_client.post(url, {f"q_{p1.pk}": valor})
        assert response.status_code == 200 and response.json()["ok"]
        assert intento.answers.get().choice_id == correcta(p1).pk  # un valor basura no borra lo ya respondido

    def test_un_valor_vacio_si_borra_la_respuesta(self, student_client, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno)
        p1 = quiz.questions.first()
        svc.save_answers(intento, {p1.pk: correcta(p1).pk})
        student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"q_{p1.pk}": ""})
        assert intento.answers.get().choice_id is None

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_enviar_con_ids_invalidos(self, student_client, quiz, alumno, valor):
        intento = svc.start_attempt(quiz, alumno)
        assert student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"q_{valor}": valor}).status_code in (302, 400)
        p1 = quiz.questions.first()
        response = student_client.post(reverse("quizzes:take", args=[intento.pk]), {f"q_{p1.pk}": valor})
        assert response.status_code == 302
        intento.refresh_from_db()
        assert intento.status == "submitted"

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_agregar_preguntas_con_ids_invalidos(self, professor_client, quiz, valor):
        professor_client.post(reverse("quizzes:builder", args=[quiz.activity_id]), {"action": "add", "question": [valor]})
        assert quiz.questions.count() == 3

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_crear_pregunta_con_add_to_invalido(self, professor_client, valor):
        datos = {
            "text": "x", "points": "1", "choices-TOTAL_FORMS": "2", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0",
            "choices-MAX_NUM_FORMS": "8", "choices-0-text": "a", "choices-0-is_correct": "on", "choices-1-text": "b",
        }
        response = professor_client.post(f"{reverse('quizzes:question_create', args=['multiple_choice'])}?add_to={valor}", datos)
        assert response.status_code == 302 and response.url.startswith("/banco/")

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_exportar_con_materia_invalida_es_400(self, professor_client, valor):
        assert professor_client.get(reverse("grades:export"), {"materia": valor}).status_code in (200, 400)
        if not valor.isascii() or not valor.isdigit() or len(valor) > 18:
            assert professor_client.get(reverse("grades:export"), {"materia": valor}).status_code == 400

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_formulario_de_notas_con_ids_iniciales_invalidos(self, professor_client, valor):
        assert professor_client.get(reverse("grades:create"), {"activity": valor, "student": valor}).status_code == 200

    @pytest.mark.parametrize("valor", HOSTILES)
    def test_importar_alumnos_con_mapeo_invalido(self, professor_client, course, valor):
        professor_client.post(
            reverse("student_import", args=[course.pk]), {"file": SimpleUploadedFile("l.csv", "Nombre\nAna\n".encode())},
        )
        response = professor_client.post(
            reverse("student_import_preview", args=[course.pk]), {"map_first_name": valor, "action": "confirm"},
        )
        assert response.status_code == 200 and response.context["mapping_errors"]

    @pytest.mark.parametrize("correcta_celda", [pytest.param(GIGANTE, id="gigante"), pytest.param("٣", id="arabe")])
    def test_importar_preguntas_con_correcta_enorme(self, professor_client, correcta_celda):
        contenido = f"Pregunta,Opción A,Opción B,Correcta\n¿P?,Sí,No,\"{correcta_celda}\"\n"
        professor_client.post(reverse("quizzes:import"), {"file": SimpleUploadedFile("p.csv", contenido.encode())})
        response = professor_client.get(reverse("quizzes:import_preview"))
        assert response.status_code == 200 and response.context["plan"].count_error == 1


# ── Cierre automático ─────────────────────────────────────────────────

def abrir(quiz, estudiante, *, vencio_hace):
    """Un intento en curso cuyo plazo venció hace ``vencio_hace``."""
    intento = svc.start_attempt(quiz, estudiante)
    QuizAttempt.objects.filter(pk=intento.pk).update(deadline=timezone.now() - vencio_hace)
    return QuizAttempt.objects.get(pk=intento.pk)


class TestCierreAutomatico:
    def test_cierra_los_vencidos_y_los_califica(self, quiz, alumno):
        intento = abrir(quiz, alumno, vencio_hace=5 * MIN)
        p1 = quiz.questions.first()
        Answer.objects.create(attempt=intento, question=p1, choice=correcta(p1))
        assert close_overdue_attempts() == 1
        intento.refresh_from_db()
        assert (intento.status, float(intento.score)) == ("expired", 1.0)
        assert Grade.objects.get(activity=quiz.activity, student=alumno).source == "quiz"

    def test_respeta_el_margen_de_red(self, quiz, alumno):
        abrir(quiz, alumno, vencio_hace=timedelta(seconds=GRACE_SECONDS - 1))
        assert close_overdue_attempts() == 0
        assert QuizAttempt.objects.get().status == "in_progress"

    def test_no_toca_lo_que_no_ha_vencido_ni_lo_ya_cerrado(self, quiz, alumno, course):
        svc.start_attempt(quiz, alumno)  # aún vigente
        otro = EnrollmentFactory(course=course).student
        terminado = svc.submit_attempt(svc.start_attempt(quiz, otro))
        assert close_overdue_attempts() == 0
        assert QuizAttempt.objects.get(pk=terminado.pk).status == "submitted"

    def test_los_intentos_sin_plazo_nunca_se_cierran(self, quiz, alumno):
        quiz.time_limit_minutes = None
        quiz.save()
        svc.start_attempt(quiz, alumno)
        assert close_overdue_attempts(timezone.now() + timedelta(days=365)) == 0

    def test_es_idempotente(self, quiz, alumno):
        abrir(quiz, alumno, vencio_hace=5 * MIN)
        assert close_overdue_attempts() == 1
        assert close_overdue_attempts() == 0
        assert Grade.objects.count() == 1

    def test_recorre_todas_las_organizaciones(self, quiz, alumno):
        ajeno_quiz = make_quiz(CourseFactory(), questions=1, time_limit_minutes=5)
        ajeno = EnrollmentFactory(course=ajeno_quiz.activity.course).student
        abrir(quiz, alumno, vencio_hace=5 * MIN)
        abrir(ajeno_quiz, ajeno, vencio_hace=5 * MIN)
        assert close_overdue_attempts() == 2

    def test_un_fallo_no_detiene_a_los_demas(self, quiz, alumno, course, monkeypatch):
        otro = EnrollmentFactory(course=course).student
        malo = abrir(quiz, alumno, vencio_hace=5 * MIN)
        bueno = abrir(quiz, otro, vencio_hace=5 * MIN)
        original = svc.finalize_attempt

        def falla_con_el_malo(attempt, **kwargs):
            if attempt.pk == malo.pk:
                raise RuntimeError("boom")
            return original(attempt, **kwargs)

        monkeypatch.setattr(svc, "finalize_attempt", falla_con_el_malo)
        assert close_overdue_attempts() == 1
        assert QuizAttempt.objects.get(pk=bueno.pk).status == "expired"
        assert QuizAttempt.objects.get(pk=malo.pk).status == "in_progress"

    def test_cierra_en_lote(self, quiz, course):
        for _ in range(12):
            abrir(quiz, EnrollmentFactory(course=course).student, vencio_hace=5 * MIN)
        assert close_overdue_attempts() == 12
        assert not QuizAttempt.objects.filter(status="in_progress").exists()

    def test_el_alumno_ve_el_resultado_despues_del_cierre(self, student_client, quiz, alumno):
        intento = abrir(quiz, alumno, vencio_hace=5 * MIN)
        close_overdue_attempts()
        assert "Se acabó el tiempo" in student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode()

    def test_comando(self, quiz, alumno):
        abrir(quiz, alumno, vencio_hace=5 * MIN)
        salida = StringIO()
        call_command("cerrar_intentos_vencidos", stdout=salida)
        assert "Intentos cerrados por tiempo: 1" in salida.getvalue()

    def test_tarea_de_celery(self, quiz, alumno):
        abrir(quiz, alumno, vencio_hace=5 * MIN)
        assert close_overdue_attempts_task.delay().get() == 1

    def test_esta_programada_cada_minuto_con_una_tarea_que_existe(self):
        from django.conf import settings

        from core.celery import app

        programada = settings.CELERY_BEAT_SCHEDULE["cerrar-intentos-de-quiz-vencidos"]
        assert programada["schedule"] == 60.0
        app.loader.import_default_modules()
        assert programada["task"] in app.tasks


# ── Quiz despublicado ─────────────────────────────────────────────────

class TestDespublicado:
    @pytest.fixture
    def intento(self, quiz, alumno):
        return svc.start_attempt(quiz, alumno)

    def despublicar(self, quiz):
        quiz.activity.published = False
        quiz.activity.save()

    def test_el_alumno_deja_de_ver_el_quiz_y_sus_intentos(self, student_client, quiz, intento):
        self.despublicar(quiz)
        assert student_client.get(reverse("quizzes:overview", args=[quiz.activity_id])).status_code == 404
        for name in ("take", "result"):
            assert student_client.get(reverse(f"quizzes:{name}", args=[intento.pk])).status_code == 404
        assert student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {}).status_code == 404

    def test_el_docente_si_ve_los_resultados(self, professor_client, quiz, intento):
        svc.submit_attempt(intento)
        self.despublicar(quiz)
        assert professor_client.get(reverse("quizzes:results", args=[quiz.activity_id])).status_code == 200
        assert professor_client.get(reverse("quizzes:review", args=[intento.pk])).status_code == 200

    def test_al_volver_a_publicar_el_alumno_retoma(self, student_client, quiz, intento):
        self.despublicar(quiz)
        quiz.activity.published = True
        quiz.activity.save()
        assert student_client.get(reverse("quizzes:take", args=[intento.pk])).status_code == 200


# ── Lo que no debe filtrarse ni romperse ──────────────────────────────

class TestSeguridad:
    def test_durante_el_intento_no_hay_pistas_de_la_correcta(self, student_client, quiz, alumno, professor):
        intento = svc.start_attempt(quiz, alumno)
        pregunta = quiz.questions.first()
        type(pregunta).objects.filter(pk=pregunta.pk).update(explanation="EXPLICACION-SECRETA")
        html = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert "EXPLICACION-SECRETA" not in html and "is_correct" not in html and "correcta" not in html.lower()

    def test_el_texto_de_las_preguntas_se_escapa_al_resolver(self, student_client, course, alumno):
        quiz = make_quiz(course, questions=0)
        from .services.builder import add_questions

        add_questions(quiz, [QuestionFactory(
            author=course.professor, organization=course.organization, text="<script>alert(1)</script>",
            choices=[("<img src=x onerror=alert(2)>", True), ("ok", False)],
        )])
        quiz.activity.published = True
        quiz.activity.save()
        intento = svc.start_attempt(quiz, alumno)
        html = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert "<script>alert(1)</script>" not in html and "<img src=x" not in html and "&lt;script&gt;" in html

    def test_un_intento_cerrado_no_cambia_con_guardados_posteriores(self, student_client, quiz, alumno):
        intento = svc.start_attempt(quiz, alumno)
        p1, p2, _ = list(quiz.questions.all())
        enviado = svc.submit_attempt(intento, {p1.pk: correcta(p1).pk})
        response = student_client.post(reverse("quizzes:autosave", args=[intento.pk]), {f"q_{p2.pk}": correcta(p2).pk})
        assert response.status_code == 409
        enviado.refresh_from_db()
        assert float(enviado.score) == 1.0 and enviado.answers.get(question=p2).choice_id is None

    def test_la_base_impide_dos_intentos_abiertos_a_la_vez(self, quiz, alumno):
        svc.start_attempt(quiz, alumno)
        with pytest.raises(IntegrityError), transaction.atomic():
            QuizAttempt.objects.create(quiz=quiz, student=alumno, number=2, started_at=timezone.now())

    def test_una_carrera_al_empezar_devuelve_el_intento_ya_abierto(self, quiz, alumno, monkeypatch):
        """Dos pestañas empiezan a la vez: la que pierde la carrera recibe el intento de la otra, no un error."""
        competidor = {}
        contar = svc.attempts_used

        def competir(quiz_, student_):
            # Después de comprobar que no hay intento abierto y antes de crear el nuestro, la otra pestaña ya
            # confirmó el suyo. Esta comprobación todavía no lo ve (devuelve el conteo que ya traía).
            total = contar(quiz_, student_)
            competidor["intento"] = QuizAttempt.objects.create(
                quiz=quiz_, student=student_, number=1, started_at=timezone.now(), deadline=timezone.now() + 10 * MIN,
            )
            return total

        monkeypatch.setattr(svc, "attempts_used", competir)
        resultado = svc.start_attempt(quiz, alumno)
        assert resultado.pk == competidor["intento"].pk
        assert QuizAttempt.objects.filter(student=alumno).count() == 1
