"""Armado de quizzes: configuración, preguntas copiadas, bloqueo y publicación."""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.courses.tests.factories import AcademicYearFactory, CourseFactory, EnrollmentFactory
from apps.courses.services.courses import archive_course, clone_course
from apps.grades.factories import ActivityFactory
from apps.grades.models import Activity

from .factories import QuestionFactory, QuizAttemptFactory, make_quiz
from .models import Question, QuizAttempt, QuizConfig, QuizQuestion
from .services import builder

pytestmark = pytest.mark.django_db

QUIZ = Activity.Type.QUIZ


def url(activity):
    return reverse("quizzes:builder", args=[activity.pk])


@pytest.fixture
def quiz(course):
    return make_quiz(course, questions=3, published=False)


def intentar(quiz, estudiante):
    return QuizAttemptFactory(quiz=quiz, student=estudiante)


# ── Configuración por defecto y publicación ───────────────────────────

class TestConfiguracion:
    def test_un_quiz_nace_con_su_configuracion(self, course):
        actividad = ActivityFactory(course=course, type=QUIZ)
        config = actividad.quiz
        assert (config.attempts_allowed, config.time_limit_minutes, config.shuffle_questions, config.shuffle_choices) == (1, None, False, False)
        assert (config.feedback_mode, config.attempt_policy, config.organization_id) == ("after_submit", "highest", course.organization_id)

    def test_otros_tipos_no_tienen_configuracion(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        assert not QuizConfig.objects.filter(activity=actividad).exists()

    def test_cambiar_una_actividad_a_quiz_le_crea_su_configuracion(self, course):
        actividad = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=False)
        actividad.type = QUIZ
        actividad.save()
        assert QuizConfig.objects.filter(activity=actividad).count() == 1
        actividad.save()
        assert QuizConfig.objects.filter(activity=actividad).count() == 1

    @pytest.mark.parametrize("campo, valor", [
        ("attempts_allowed", 0), ("attempts_allowed", 21), ("time_limit_minutes", 0), ("time_limit_minutes", 601),
    ])
    def test_limites(self, quiz, campo, valor):
        setattr(quiz, campo, valor)
        with pytest.raises(ValidationError):
            quiz.full_clean()

    def test_valores_extremos_validos(self, quiz):
        quiz.attempts_allowed, quiz.time_limit_minutes = 20, 600
        quiz.full_clean()


class TestPublicar:
    def test_sin_preguntas_no_se_publica(self, course):
        actividad = ActivityFactory(course=course, type=QUIZ)
        actividad.published = True
        with pytest.raises(ValidationError, match="al menos una pregunta"):
            actividad.save()

    def test_con_preguntas_si(self, quiz):
        quiz.activity.published = True
        quiz.activity.save()
        assert Activity.objects.get(pk=quiz.activity_id).published

    def test_crear_publicado_sin_preguntas_tampoco(self, course):
        with pytest.raises(ValidationError):
            ActivityFactory(course=course, type=QUIZ, published=True)

    def test_el_boton_de_publicar_avisa_y_no_publica(self, professor_client, course):
        actividad = ActivityFactory(course=course, type=QUIZ)
        response = professor_client.post(reverse("grades:activity_publish", args=[actividad.pk]), follow=True)
        assert any("al menos una pregunta" in str(m) for m in response.context["messages"])
        actividad.refresh_from_db()
        assert not actividad.published

    def test_el_formulario_de_actividad_tambien_lo_impide(self, professor_client, course):
        datos = {"title": "Quiz 1", "type": "quiz", "criterion": "", "max_score": "10", "weight": "1", "allow_late": "on", "late_penalty": "0", "published": "on"}
        response = professor_client.post(reverse("grades:activity_create", args=[course.pk]), datos)
        assert response.status_code == 200 and "al menos una pregunta" in str(response.context["form"].non_field_errors())
        assert not Activity.objects.exists()

    def test_publicar_otros_tipos_no_se_ve_afectado(self, course):
        assert ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=True).published

    def test_el_tipo_de_un_quiz_armado_no_cambia(self, professor_client, quiz):
        form = professor_client.get(reverse("grades:activity_update", args=[quiz.activity_id])).context["form"]
        assert form.fields["type"].disabled

    def test_el_tipo_de_un_quiz_vacio_si_cambia(self, professor_client, course):
        actividad = ActivityFactory(course=course, type=QUIZ)
        assert not professor_client.get(reverse("grades:activity_update", args=[actividad.pk])).context["form"].fields["type"].disabled


# ── Servicio de armado ────────────────────────────────────────────────

class TestAgregarPreguntas:
    @pytest.fixture
    def vacio(self, course):
        return ActivityFactory(course=course, type=QUIZ).quiz

    def test_copia_la_pregunta_con_sus_opciones(self, vacio, professor):
        original = QuestionFactory(author=professor, text="¿Cuánto es 2+2?", points=2, explanation="Suma", topic="Aritmética")
        (copia,) = builder.add_questions(vacio, [original])
        assert (copia.text, copia.points, copia.explanation, copia.kind, copia.position, copia.source) == (
            "¿Cuánto es 2+2?", 2, "Suma", "multiple_choice", 0, original,
        )
        assert [(c.text, c.is_correct) for c in copia.choices.all()] == [(c.text, c.is_correct) for c in original.choices.all()]
        assert copia.organization_id == vacio.organization_id

    def test_se_agregan_al_final_en_orden(self, vacio, professor):
        a, b, c = (QuestionFactory(author=professor) for _ in range(3))
        builder.add_questions(vacio, [a, b])
        builder.add_questions(vacio, [c])
        assert [q.source_id for q in vacio.questions.all()] == [a.pk, b.pk, c.pk]
        assert [q.position for q in vacio.questions.all()] == [0, 1, 2]

    def test_una_pregunta_no_se_agrega_dos_veces(self, vacio, professor):
        p = QuestionFactory(author=professor)
        builder.add_questions(vacio, [p])
        assert builder.add_questions(vacio, [p]) == []
        assert vacio.questions.count() == 1

    def test_editar_el_banco_despues_no_altera_el_quiz(self, vacio, professor):
        from .services.bank import save_question

        original = QuestionFactory(author=professor, text="Original")
        builder.add_questions(vacio, [original])
        save_question(
            organization=original.organization, author=professor, kind=original.kind, text="Cambiada", points=9,
            choices=[("X", True), ("Y", False)], question=original,
        )
        copia = vacio.questions.get()
        assert (copia.text, copia.points, copia.choices.count()) == ("Original", 1, 3)

    def test_borrar_la_pregunta_del_banco_conserva_la_copia(self, vacio, professor):
        original = QuestionFactory(author=professor)
        builder.add_questions(vacio, [original])
        original.delete()
        copia = vacio.questions.get()
        assert copia.source is None and copia.choices.count() == 3

    def test_pregunta_de_otra_organizacion(self, vacio):
        with pytest.raises(ValidationError, match="otra organización"):
            builder.add_questions(vacio, [QuestionFactory()])

    def test_pregunta_archivada(self, vacio, professor):
        p = QuestionFactory(author=professor)
        Question.objects.filter(pk=p.pk).update(is_archived=True)
        with pytest.raises(ValidationError, match="archivadas"):
            builder.add_questions(vacio, [Question.objects.get(pk=p.pk)])

    def test_en_un_grupo_archivado(self, vacio, professor, course):
        archive_course(course)
        with pytest.raises(ValidationError, match="archivado"):
            builder.add_questions(vacio, [QuestionFactory(author=professor)])

    def test_con_intentos_se_bloquea(self, quiz, enrollment):
        intentar(quiz, enrollment.student)
        with pytest.raises(ValidationError, match="ya tiene intentos"):
            builder.add_questions(quiz, [QuestionFactory(author=quiz.activity.course.professor)])


class TestOrdenarYPonderar:
    def test_quitar_renumera(self, quiz):
        primera, segunda, tercera = list(quiz.questions.all())
        builder.remove_question(segunda)
        assert [(q.pk, q.position) for q in quiz.questions.all()] == [(primera.pk, 0), (tercera.pk, 1)]

    def test_mover(self, quiz):
        a, b, c = list(quiz.questions.all())
        builder.move_question(c, -1)
        assert [q.pk for q in quiz.questions.all()] == [a.pk, c.pk, b.pk]
        builder.move_question(a, 1)
        assert [q.pk for q in quiz.questions.all()] == [c.pk, a.pk, b.pk]

    def test_mover_en_los_extremos_no_hace_nada(self, quiz):
        a, b, c = list(quiz.questions.all())
        builder.move_question(a, -1)
        builder.move_question(c, 1)
        assert [q.pk for q in quiz.questions.all()] == [a.pk, b.pk, c.pk]

    @pytest.mark.parametrize("valor, esperado", [("2", 2), ("1,5", 1.5), ("0.25", 0.25), (" 3 ", 3), (4, 4)])
    def test_puntos_validos(self, quiz, valor, esperado):
        pregunta = quiz.questions.first()
        builder.set_points(pregunta, valor)
        pregunta.refresh_from_db()
        assert float(pregunta.points) == esperado

    @pytest.mark.parametrize("valor", ["0", "-1", "abc", "", "nan", "inf", "10000"])
    def test_puntos_invalidos(self, quiz, valor):
        pregunta = quiz.questions.first()
        with pytest.raises(ValidationError):
            builder.set_points(pregunta, valor)
        pregunta.refresh_from_db()
        assert pregunta.points == 1

    def test_totales(self, course):
        quiz = make_quiz(course, questions=3, points=2, published=False)
        assert builder.totals(quiz) == (3, 6)
        assert builder.totals(ActivityFactory(course=course, type=QUIZ).quiz) == (0, 0)

    def test_igualar_los_puntos_de_la_actividad(self, course):
        quiz = make_quiz(course, questions=4, points=2.5, published=False)
        builder.sync_activity_points(quiz)
        quiz.activity.refresh_from_db()
        assert quiz.activity.max_score == 10

    def test_igualar_sin_preguntas(self, course):
        with pytest.raises(ValidationError, match="todavía no tiene preguntas"):
            builder.sync_activity_points(ActivityFactory(course=course, type=QUIZ).quiz)

    def test_con_intentos_no_se_cambia_nada(self, quiz, enrollment):
        intentar(quiz, enrollment.student)
        pregunta = quiz.questions.first()
        for operacion in (
            lambda: builder.remove_question(pregunta), lambda: builder.move_question(pregunta, 1),
            lambda: builder.set_points(pregunta, 5),
        ):
            with pytest.raises(ValidationError, match="ya tiene intentos"):
                operacion()
        assert quiz.questions.count() == 3 and quiz.questions.first().points == 1


# ── Pantalla del constructor ──────────────────────────────────────────

@pytest.mark.usefixtures('plan_docente')  # el tiempo límite es del plan Docente (ver test_planes_y_limites)
class TestPantalla:
    def test_se_abre_con_el_resumen(self, professor_client, quiz):
        context = professor_client.get(url(quiz.activity)).context
        assert (context["question_count"], context["total_points"], context["locked"], context["read_only"]) == (3, 3, False, False)
        assert context["points_match"] is False  # 3 puntos de preguntas contra 10 de la actividad
        assert [q.pk for q in context["questions"]] == [q.pk for q in quiz.questions.all()]

    def test_el_banco_ofrece_solo_lo_que_falta_y_no_archivadas(self, professor_client, quiz, professor):
        libre = QuestionFactory(author=professor, text="Libre")
        archivada = QuestionFactory(author=professor)
        Question.objects.filter(pk=archivada.pk).update(is_archived=True)
        QuestionFactory()  # otra organización
        ofrecidas = {q.pk for q in professor_client.get(url(quiz.activity)).context["picker"]}
        assert ofrecidas == {libre.pk}

    def test_filtra_el_banco(self, professor_client, quiz, professor):
        a = QuestionFactory(author=professor, text="Derivadas", topic="Cálculo")
        b = QuestionFactory(author=professor, text="Roma", topic="Historia", kind="true_false")
        ids = lambda **p: {q.pk for q in professor_client.get(url(quiz.activity), p).context["picker"]}  # noqa: E731
        assert ids(bq="derivadas") == {a.pk} and ids(btopic="historia") == {b.pk} and ids(bkind="true_false") == {b.pk}

    def test_pagina_el_banco(self, professor_client, quiz, professor):
        for _ in range(17):
            QuestionFactory(author=professor)
        assert len(professor_client.get(url(quiz.activity)).context["picker"]) == 15
        assert len(professor_client.get(url(quiz.activity), {"bp": 2}).context["picker"]) == 2

    def test_guarda_la_configuracion(self, professor_client, quiz):
        response = professor_client.post(url(quiz.activity), {
            "action": "settings", "attempts_allowed": 3, "time_limit_minutes": 45, "shuffle_questions": "on",
            "feedback_mode": "none", "attempt_policy": "average",
        })
        quiz.refresh_from_db()
        assert response.status_code == 302
        assert (quiz.attempts_allowed, quiz.time_limit_minutes, quiz.shuffle_questions, quiz.shuffle_choices) == (3, 45, True, False)
        assert (quiz.feedback_mode, quiz.attempt_policy) == ("none", "average")

    def test_sin_limite_de_tiempo(self, professor_client, quiz):
        quiz.time_limit_minutes = 30
        quiz.save()
        professor_client.post(url(quiz.activity), {"action": "settings", "attempts_allowed": 1, "time_limit_minutes": "", "feedback_mode": "none", "attempt_policy": "highest"})
        quiz.refresh_from_db()
        assert quiz.time_limit_minutes is None

    @pytest.mark.parametrize("cambios, campo", [
        ({"attempts_allowed": 0}, "attempts_allowed"), ({"time_limit_minutes": 0}, "time_limit_minutes"),
        ({"feedback_mode": "otro"}, "feedback_mode"), ({"attempt_policy": "otra"}, "attempt_policy"),
    ])
    def test_configuracion_invalida(self, professor_client, quiz, cambios, campo):
        datos = {"action": "settings", "attempts_allowed": 1, "time_limit_minutes": "", "feedback_mode": "none", "attempt_policy": "highest", **cambios}
        response = professor_client.post(url(quiz.activity), datos)
        assert response.status_code == 200 and campo in response.context["config_form"].errors

    def test_agrega_preguntas_del_banco(self, professor_client, quiz, professor):
        nuevas = [QuestionFactory(author=professor) for _ in range(2)]
        response = professor_client.post(url(quiz.activity), {"action": "add", "question": [q.pk for q in nuevas]}, follow=True)
        assert quiz.questions.count() == 5
        assert any("2 preguntas" in str(m) for m in response.context["messages"])

    def test_ignora_ids_de_preguntas_ajenas(self, professor_client, quiz):
        ajena = QuestionFactory()
        professor_client.post(url(quiz.activity), {"action": "add", "question": [ajena.pk, "abc"]})
        assert quiz.questions.count() == 3

    def test_quita_sube_y_baja(self, professor_client, quiz):
        a, b, c = list(quiz.questions.all())
        professor_client.post(url(quiz.activity), {"action": "down", "question_id": a.pk})
        assert [q.pk for q in quiz.questions.all()] == [b.pk, a.pk, c.pk]
        professor_client.post(url(quiz.activity), {"action": "up", "question_id": c.pk})
        assert [q.pk for q in quiz.questions.all()] == [b.pk, c.pk, a.pk]
        professor_client.post(url(quiz.activity), {"action": "remove", "question_id": b.pk})
        assert [q.pk for q in quiz.questions.all()] == [c.pk, a.pk]

    def test_cambia_los_puntos_de_una_pregunta(self, professor_client, quiz):
        pregunta = quiz.questions.first()
        professor_client.post(url(quiz.activity), {"action": "points", "question_id": pregunta.pk, "points": "2,5"})
        pregunta.refresh_from_db()
        assert float(pregunta.points) == 2.5

    def test_puntos_invalidos_avisan(self, professor_client, quiz):
        pregunta = quiz.questions.first()
        response = professor_client.post(url(quiz.activity), {"action": "points", "question_id": pregunta.pk, "points": "abc"}, follow=True)
        assert any("número" in str(m) for m in response.context["messages"])

    def test_no_se_toca_una_pregunta_de_otro_quiz(self, professor_client, quiz, course):
        otro = make_quiz(course, questions=1, published=False)
        ajena = otro.questions.get()
        response = professor_client.post(url(quiz.activity), {"action": "remove", "question_id": ajena.pk})
        assert response.status_code == 404 and QuizQuestion.objects.filter(pk=ajena.pk).exists()

    def test_igualar_los_puntos(self, professor_client, quiz):
        professor_client.post(url(quiz.activity), {"action": "sync"})
        quiz.activity.refresh_from_db()
        assert quiz.activity.max_score == 3

    def test_accion_desconocida(self, professor_client, quiz):
        response = professor_client.post(url(quiz.activity), {"action": "otra"}, follow=True)
        assert any("desconocida" in str(m) for m in response.context["messages"])

    def test_con_intentos_las_preguntas_quedan_bloqueadas_pero_la_configuracion_no(self, professor_client, quiz, enrollment):
        intentar(quiz, enrollment.student)
        context = professor_client.get(url(quiz.activity)).context
        assert context["locked"]
        response = professor_client.post(url(quiz.activity), {"action": "remove", "question_id": quiz.questions.first().pk}, follow=True)
        assert any("ya tiene intentos" in str(m) for m in response.context["messages"]) and quiz.questions.count() == 3
        professor_client.post(url(quiz.activity), {"action": "settings", "attempts_allowed": 5, "time_limit_minutes": "", "feedback_mode": "none", "attempt_policy": "last"})
        quiz.refresh_from_db()
        assert quiz.attempts_allowed == 5

    def test_un_grupo_archivado_es_de_solo_lectura(self, professor_client, quiz, course):
        archive_course(course)
        assert professor_client.get(url(quiz.activity)).context["read_only"]
        response = professor_client.post(url(quiz.activity), {"action": "remove", "question_id": quiz.questions.first().pk}, follow=True)
        assert any("archivado" in str(m) for m in response.context["messages"]) and quiz.questions.count() == 3

    def test_otro_docente_no_entra(self, professor_client):
        ajeno = make_quiz(CourseFactory(), questions=1, published=False)
        assert professor_client.get(url(ajeno.activity)).status_code == 404
        assert professor_client.post(url(ajeno.activity), {"action": "sync"}).status_code == 404

    def test_una_actividad_que_no_es_quiz_es_404(self, professor_client, course):
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        assert professor_client.get(url(tarea)).status_code == 404

    def test_el_alumno_no_entra(self, student_client, quiz, enrollment):
        assert student_client.get(url(quiz.activity)).status_code == 302

    def test_anonimo_va_al_login(self, client, quiz):
        assert client.get(url(quiz.activity)).url.startswith("/login/")

    def test_el_enlace_aparece_solo_en_los_quizzes(self, professor_client, quiz, course):
        assert url(quiz.activity) in professor_client.get(quiz.activity.get_absolute_url()).content.decode()
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        assert "Armar quiz" not in professor_client.get(tarea.get_absolute_url()).content.decode()


class TestCrearYAgregar:
    def datos(self, **cambios):
        base = {
            "text": "Nueva", "points": "1", "choices-TOTAL_FORMS": "3", "choices-INITIAL_FORMS": "0",
            "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
            "choices-0-text": "Sí", "choices-0-is_correct": "on", "choices-1-text": "No", "choices-2-text": "",
        }
        base.update(cambios)
        return base

    def crear(self, client, activity_id):
        return client.post(f"{reverse('quizzes:question_create', args=['multiple_choice'])}?add_to={activity_id}", self.datos())

    def test_la_pregunta_nueva_queda_en_el_banco_y_en_el_quiz(self, professor_client, quiz):
        response = self.crear(professor_client, quiz.activity_id)
        assert response.url == url(quiz.activity)
        nueva = Question.objects.get(text="Nueva")
        assert quiz.questions.filter(source=nueva).exists()

    def test_sin_add_to_va_al_detalle(self, professor_client):
        response = professor_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), self.datos())
        assert response.url.startswith("/banco/")

    @pytest.mark.parametrize("valor", ["abc", "0", "999999"])
    def test_add_to_invalido_se_ignora(self, professor_client, valor):
        response = professor_client.post(f"{reverse('quizzes:question_create', args=['multiple_choice'])}?add_to={valor}", self.datos())
        assert response.url.startswith("/banco/") and Question.objects.count() == 1

    def test_no_se_agrega_al_quiz_de_otro_docente(self, professor_client):
        ajeno = make_quiz(CourseFactory(), questions=1, published=False)
        before = ajeno.questions.count()
        response = self.crear(professor_client, ajeno.activity_id)
        assert response.url.startswith("/banco/") and ajeno.questions.count() == before

    def test_un_quiz_bloqueado_guarda_la_pregunta_y_avisa(self, professor_client, quiz, enrollment):
        intentar(quiz, enrollment.student)
        response = self.crear(professor_client, quiz.activity_id)
        assert response.url == url(quiz.activity) and quiz.questions.count() == 3
        assert Question.objects.filter(text="Nueva").exists()


# ── Duplicar el grupo ─────────────────────────────────────────────────

class TestDuplicarGrupo:
    def test_el_quiz_se_copia_con_su_configuracion_y_preguntas_pero_sin_intentos(self, course, enrollment):
        origen = make_quiz(course, questions=2, attempts_allowed=3, time_limit_minutes=20, shuffle_questions=True, feedback_mode="none", attempt_policy="last")
        intentar(origen, enrollment.student)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        nueva = QuizConfig.objects.get(activity__course=copia)
        assert (nueva.attempts_allowed, nueva.time_limit_minutes, nueva.shuffle_questions, nueva.feedback_mode, nueva.attempt_policy) == (3, 20, True, "none", "last")
        assert [q.text for q in nueva.questions.all()] == [q.text for q in origen.questions.all()]
        assert not nueva.activity.published and not nueva.attempts.exists()
        assert QuizAttempt.objects.count() == 1  # solo el del original

    def test_las_copias_son_independientes(self, course):
        origen = make_quiz(course, questions=2)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        nueva = QuizConfig.objects.get(activity__course=copia)
        assert not set(nueva.questions.values_list("pk", flat=True)) & set(origen.questions.values_list("pk", flat=True))
        builder.remove_question(nueva.questions.first())
        assert origen.questions.count() == 2

    def test_el_grupo_copiado_conserva_el_origen_de_cada_pregunta(self, course):
        origen = make_quiz(course, questions=2)
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        nueva = QuizConfig.objects.get(activity__course=copia)
        assert list(nueva.questions.values_list("source_id", flat=True)) == list(origen.questions.values_list("source_id", flat=True))
