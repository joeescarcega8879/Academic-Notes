"""Examen en línea: se enciende por examen, usa el motor del quiz y exige su ventana para publicarse."""

from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.courses.services.courses import archive_course, clone_course
from apps.courses.tests.factories import AcademicYearFactory, EnrollmentFactory
from apps.grades.models import Activity, Grade
from apps.grades.tests.factories import ActivityFactory
from apps.quizzes.models import QuizAttempt, QuizConfig
from apps.quizzes.services import attempts as svc
from apps.quizzes.services import exams
from apps.quizzes.services.builder import add_questions
from apps.quizzes.tests.factories import QuestionFactory

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
DIA = timedelta(days=1)


def examen(course, **opciones):
    """Examen (borrador) aplicado en línea, con dos preguntas y su ventana."""
    opciones.setdefault('opens_at', AHORA - DIA)
    opciones.setdefault('due_at', AHORA + DIA)
    actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False, **opciones)
    quiz = exams.enable_online(actividad)
    add_questions(quiz, [QuestionFactory(author=course.professor, organization=course.organization) for _ in range(2)])
    return quiz


def publicar(quiz):
    quiz.activity.published = True
    quiz.activity.save()


def correcta(pregunta):
    return next(c for c in pregunta.choices.all() if c.is_correct)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


class TestAplicarEnLinea:
    def test_un_examen_normal_no_tiene_configuracion(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM)
        assert not QuizConfig.objects.filter(activity=actividad).exists()
        assert not exams.uses_quiz_engine(actividad)

    def test_nace_mas_cerrado_que_un_quiz(self, course):
        quiz = exams.enable_online(ActivityFactory(course=course, type=Activity.Type.EXAM, published=False))
        assert (quiz.attempts_allowed, quiz.shuffle_questions, quiz.shuffle_choices) == (1, True, True)
        assert quiz.feedback_mode == QuizConfig.Feedback.AFTER_CLOSE
        assert exams.uses_quiz_engine(quiz.activity)

    def test_aplicarlo_dos_veces_no_duplica_ni_pisa_la_configuracion(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        primero = exams.enable_online(actividad)
        primero.attempts_allowed = 3
        primero.save()
        assert exams.enable_online(actividad).pk == primero.pk
        assert QuizConfig.objects.get(activity=actividad).attempts_allowed == 3

    @pytest.mark.parametrize("tipo", [Activity.Type.HOMEWORK, Activity.Type.QUIZ, Activity.Type.PROJECT])
    def test_solo_un_examen_se_aplica_en_linea(self, course, tipo):
        with pytest.raises(ValidationError, match="Solo un examen"):
            exams.enable_online(ActivityFactory(course=course, type=tipo))

    def test_publicado_pide_pasarlo_a_borrador(self, course):
        with pytest.raises(ValidationError, match="borrador"):
            exams.enable_online(ActivityFactory(course=course, type=Activity.Type.EXAM, published=True))

    def test_grupo_archivado_es_de_solo_lectura(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        archive_course(course)
        with pytest.raises(ValidationError):
            exams.enable_online(actividad)

    def test_dejar_de_aplicarlo_borra_las_preguntas(self, course):
        quiz = examen(course)
        exams.disable_online(quiz.activity)
        assert not QuizConfig.objects.filter(activity=quiz.activity).exists()

    def test_no_se_deja_de_aplicar_con_intentos_hechos(self, course, alumno):
        quiz = examen(course)
        publicar(quiz)
        svc.start_attempt(quiz, alumno)
        quiz.activity.published = False
        quiz.activity.save()
        with pytest.raises(ValidationError, match="intentos"):
            exams.disable_online(quiz.activity)
        assert QuizConfig.objects.filter(activity=quiz.activity).exists()

    def test_publicado_no_se_deja_de_aplicar(self, course):
        quiz = examen(course)
        publicar(quiz)
        with pytest.raises(ValidationError, match="borrador"):
            exams.disable_online(quiz.activity)


class TestPublicar:
    def test_sin_preguntas_no_se_publica(self, course):
        quiz = exams.enable_online(ActivityFactory(course=course, type=Activity.Type.EXAM, published=False, opens_at=AHORA, due_at=AHORA + DIA))
        with pytest.raises(ValidationError, match="al menos una pregunta al examen"):
            publicar(quiz)

    @pytest.mark.parametrize("opens, due", [(None, 1), (-1, None), (None, None)])
    def test_sin_ventana_completa_no_se_publica(self, course, opens, due):
        dia = lambda n: None if n is None else AHORA + n * DIA  # noqa: E731
        quiz = examen(course, opens_at=dia(opens), due_at=dia(due))
        with pytest.raises(ValidationError, match="apertura y de cierre"):
            publicar(quiz)

    def test_con_preguntas_y_ventana_se_publica(self, course):
        quiz = examen(course)
        publicar(quiz)
        assert Activity.objects.get(pk=quiz.activity_id).published

    def test_un_examen_a_mano_se_publica_sin_nada_de_esto(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        actividad.published = True
        actividad.save()
        assert Activity.objects.get(pk=actividad.pk).published


class TestPresentarlo:
    def test_el_alumno_presenta_y_se_califica_en_la_libreta(self, course, alumno):
        quiz = examen(course)
        publicar(quiz)
        intento = svc.start_attempt(quiz, alumno)
        primera = quiz.questions.first()
        svc.submit_attempt(intento, {primera.pk: correcta(primera).pk})
        nota = Grade.objects.get(activity=quiz.activity, student=alumno)
        assert (nota.source, nota.score) == ("quiz", 5.0)
        assert "examen" in nota.feedback

    def test_un_solo_intento_por_omision(self, course, alumno):
        quiz = examen(course)
        publicar(quiz)
        svc.submit_attempt(svc.start_attempt(quiz, alumno))
        with pytest.raises(ValidationError, match="todos tus intentos"):
            svc.start_attempt(quiz, alumno)

    def test_los_mensajes_hablan_de_examen(self, course, alumno):
        antes = examen(course, opens_at=AHORA + DIA, due_at=AHORA + 2 * DIA)
        publicar(antes)
        with pytest.raises(ValidationError, match="El examen todavía no abre"):
            svc.start_attempt(antes, alumno)
        despues = examen(course, opens_at=AHORA - 2 * DIA, due_at=AHORA - DIA)
        publicar(despues)
        with pytest.raises(ValidationError, match="El examen ya cerró"):
            svc.start_attempt(despues, alumno)

    def test_el_plazo_nunca_pasa_del_cierre_de_la_ventana(self, course, alumno):
        quiz = examen(course, due_at=AHORA + timedelta(minutes=10))
        quiz.time_limit_minutes = 120
        quiz.save()
        publicar(quiz)
        intento = svc.start_attempt(quiz, alumno)
        assert intento.deadline == quiz.activity.due_at

    def test_la_respuesta_correcta_se_muestra_hasta_que_cierre(self, student_client, course, alumno):
        quiz = examen(course)
        publicar(quiz)
        intento = svc.submit_attempt(svc.start_attempt(quiz, alumno))
        pagina = student_client.get(reverse("quizzes:result", args=[intento.pk]))
        assert pagina.context["review"] is None
        assert "cuando cierre el examen" in pagina.content.decode()


class TestVistas:
    def test_aplicar_en_linea_lleva_al_constructor(self, professor_client, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        respuesta = professor_client.post(reverse("quizzes:exam_online", args=[actividad.pk]))
        assert respuesta.url == reverse("quizzes:builder", args=[actividad.pk])
        assert QuizConfig.objects.filter(activity=actividad).exists()

    def test_la_pagina_de_la_actividad_ofrece_cada_opcion(self, professor_client, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        pagina = professor_client.get(actividad.get_absolute_url()).content.decode()
        assert "Aplicar en línea" in pagina and "Armar examen" not in pagina
        exams.enable_online(actividad)
        pagina = professor_client.get(actividad.get_absolute_url()).content.decode()
        assert "Armar examen" in pagina and "Aplicar en línea" not in pagina

    def test_un_quiz_o_una_tarea_no_ofrecen_aplicar_en_linea(self, professor_client, course):
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        assert "Aplicar en línea" not in professor_client.get(tarea.get_absolute_url()).content.decode()
        assert professor_client.post(reverse("quizzes:exam_online", args=[tarea.pk])).status_code == 404

    def test_visitar_el_constructor_de_un_examen_a_mano_no_lo_aplica(self, professor_client, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM)
        assert professor_client.get(reverse("quizzes:builder", args=[actividad.pk])).status_code == 404
        assert not QuizConfig.objects.filter(activity=actividad).exists()

    def test_el_constructor_del_examen_habla_de_examen_y_ofrece_ia(self, professor_client, course):
        quiz = examen(course)
        pagina = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "Armar examen" in pagina and "Preguntas del examen" in pagina
        assert "Generar con IA" in pagina

    def test_el_alumno_ve_el_acceso_al_examen(self, student_client, course, enrollment):
        quiz = examen(course)
        publicar(quiz)
        pagina = student_client.get(quiz.activity.get_absolute_url()).content.decode()
        assert "Ir al examen" in pagina
        assert student_client.get(reverse("quizzes:overview", args=[quiz.activity_id])).status_code == 200

    def test_el_alumno_no_lee_que_se_aceptan_entregas_tardias(self, student_client, course, enrollment):
        quiz = examen(course)
        publicar(quiz)
        pagina = student_client.get(quiz.activity.get_absolute_url()).content.decode()
        assert "Entregas tardías" not in pagina and "Ya no se puede empezar ni enviar" in pagina

    def test_un_examen_a_mano_con_fecha_si_muestra_las_entregas_tardias(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, due_at=AHORA + DIA)
        assert "Entregas tardías" in student_client.get(actividad.get_absolute_url()).content.decode()

    def test_la_retroalimentacion_nombra_al_examen_y_al_quiz(self, course):
        from apps.quizzes.forms import QuizConfigForm
        from apps.quizzes.tests.factories import make_quiz

        etiquetas = lambda quiz: dict(QuizConfigForm(instance=quiz).fields["feedback_mode"].choices)["after_close"]  # noqa: E731
        assert etiquetas(examen(course)).endswith("cierre el examen")
        assert etiquetas(make_quiz(course, questions=1)).endswith("cierre el quiz")

    def test_la_confirmacion_de_envio_nombra_al_examen(self, student_client, course, alumno):
        quiz = examen(course)
        publicar(quiz)
        intento = svc.start_attempt(quiz, alumno)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert 'data-noun="examen"' in pagina and "Enviar examen" in pagina

    def test_el_alumno_no_ve_un_examen_a_mano_como_en_linea(self, student_client, course, enrollment):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM)
        assert "Ir al examen" not in student_client.get(actividad.get_absolute_url()).content.decode()
        assert student_client.get(reverse("quizzes:overview", args=[actividad.pk])).status_code == 404

    def test_otro_docente_no_puede_aplicarlo(self, client, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        otro = EnrollmentFactory().course.professor
        client.force_login(otro)
        assert client.post(reverse("quizzes:exam_online", args=[actividad.pk])).status_code in (302, 403, 404)
        assert not QuizConfig.objects.filter(activity=actividad).exists()

    def test_el_tipo_no_cambia_con_preguntas(self, course):
        from apps.grades.activity_forms import ActivityForm

        quiz = examen(course)
        formulario = ActivityForm(instance=quiz.activity, course=course)
        assert formulario.fields["type"].disabled
        assert "examen" in formulario.fields["type"].help_text


class TestDuplicarGrupo:
    def test_el_examen_en_linea_viaja_con_sus_preguntas_y_sin_intentos(self, course, alumno):
        origen = examen(course)
        origen.attempts_allowed = 2
        origen.save()
        publicar(origen)
        svc.start_attempt(origen, alumno)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        nuevo = QuizConfig.objects.get(activity__course=copia)
        assert nuevo.activity.type == Activity.Type.EXAM and nuevo.attempts_allowed == 2
        assert nuevo.questions.count() == 2
        assert not nuevo.activity.published and not nuevo.attempts.exists()
        assert QuizAttempt.objects.count() == 1

    def test_un_examen_a_mano_se_copia_sin_configuracion(self, course):
        ActivityFactory(course=course, type=Activity.Type.EXAM)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        assert not QuizConfig.objects.filter(activity__course=copia).exists()
