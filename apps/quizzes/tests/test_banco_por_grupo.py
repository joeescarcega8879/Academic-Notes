"""Banco de preguntas por grupo: una pregunta es de un grupo o general (sin grupo)."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.courses.models import Course
from apps.courses.tests.factories import CourseFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY, teaching_organization
from apps.organizations.tests.factories import MembershipFactory

from apps.quizzes.models import Question
from apps.quizzes.services import builder, question_import as qi
from apps.quizzes.services.bank import (
    UNSET, bank_courses, duplicate_question, questions_for_course, save_question, teaching_courses, visible_questions,
)
from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db

MC = Question.Kind.MULTIPLE_CHOICE
BANCO = reverse('quizzes:bank')
CABECERA = "Pregunta,Tipo,Opción A,Opción B,Opción C,Opción D,Correcta,Puntos,Tema,Explicación"


@pytest.fixture
def org(professor):
    return teaching_organization(professor)


@pytest.fixture
def mates(professor, org):
    return CourseFactory(professor=professor, organization=org, name="Matemáticas")


@pytest.fixture
def espanol(professor, org):
    return CourseFactory(professor=professor, organization=org, name="Español")


@pytest.fixture
def colega(org):
    """Otro docente de la misma organización, con su propio grupo."""
    otro = ProfessorFactory()
    MembershipFactory(user=otro, organization=org, role=Membership.Role.TEACHER)
    return otro


def cliente(user, org):
    c = Client()
    c.force_login(user)
    s = c.session
    s[SESSION_KEY] = org.pk
    s.save()
    return c


def archivar(course):
    Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)


def ids(response, key="page"):
    return {q.pk for q in response.context[key]}


def datos(**extra):
    base = {
        "text": "¿Cuánto es 2 + 2?", "points": "1", "topic": "", "explanation": "", "course": "",
        "choices-TOTAL_FORMS": "3", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
        "choices-0-text": "4", "choices-0-is_correct": "on", "choices-1-text": "5", "choices-2-text": "3",
    }
    return {**base, **extra}


# ── Servicio ──────────────────────────────────────────────────────────

class TestGuardarConGrupo:
    def test_una_pregunta_nueva_sin_grupo_es_general(self, professor, org):
        p = save_question(organization=org, author=professor, kind=MC, text="x", points=1, choices=[("A", True), ("B", False)])
        assert p.course is None

    def test_se_guarda_en_el_grupo_indicado(self, professor, org, mates):
        p = save_question(organization=org, author=professor, kind=MC, text="x", points=1, choices=[("A", True), ("B", False)], course=mates)
        p.refresh_from_db()
        assert p.course == mates

    def test_editar_sin_indicar_el_grupo_lo_conserva(self, professor, org, mates):
        p = QuestionFactory(author=professor, course=mates)
        save_question(organization=org, author=professor, kind=MC, text="nuevo", points=1, choices=[("A", True), ("B", False)], question=p)
        p.refresh_from_db()
        assert (p.text, p.course) == ("nuevo", mates)

    def test_se_puede_cambiar_de_grupo_o_volverla_general(self, professor, org, mates, espanol):
        p = QuestionFactory(author=professor, course=mates)
        for destino in (espanol, None):
            save_question(organization=org, author=professor, kind=MC, text="x", points=1, choices=[("A", True), ("B", False)], question=p, course=destino)
            p.refresh_from_db()
            assert p.course == destino

    def test_un_grupo_de_otra_organizacion_se_rechaza(self, professor, org):
        ajeno = CourseFactory()
        with pytest.raises(ValidationError, match="otra organización"):
            save_question(organization=org, author=professor, kind=MC, text="x", points=1, choices=[("A", True), ("B", False)], course=ajeno)
        assert not Question.objects.exists()

    def test_duplicar_conserva_el_grupo_o_la_manda_a_otro(self, professor, mates, espanol):
        original = QuestionFactory(author=professor, course=mates)
        assert duplicate_question(original, by=professor).course == mates
        assert duplicate_question(original, by=professor, course=espanol).course == espanol
        assert duplicate_question(original, by=professor, course=None).course is None
        assert duplicate_question(original, by=professor, course=UNSET).course == mates

    def test_si_el_grupo_desaparece_sus_preguntas_pasan_a_ser_generales(self, professor, mates):
        p = QuestionFactory(author=professor, course=mates)
        mates.delete()
        p.refresh_from_db()
        assert p.course is None


class TestAlcance:
    def test_visibles_son_las_de_mis_grupos_y_las_generales(self, professor, colega, org, mates):
        suyo = CourseFactory(professor=colega, organization=org)
        mia, general, del_colega = QuestionFactory(author=professor, course=mates), QuestionFactory(author=colega, organization=org), QuestionFactory(author=colega, organization=org, course=suyo)
        assert set(visible_questions(org, professor)) == {mia, general}
        assert del_colega not in visible_questions(org, professor)

    def test_para_un_quiz_se_ofrecen_las_del_grupo_y_las_generales(self, professor, org, mates, espanol):
        del_grupo, general, de_otro = (
            QuestionFactory(author=professor, course=mates), QuestionFactory(author=professor), QuestionFactory(author=professor, course=espanol),
        )
        assert set(questions_for_course(org, mates)) == {del_grupo, general}
        assert de_otro not in questions_for_course(org, mates)

    def test_los_grupos_para_crear_son_los_activos_del_docente(self, professor, colega, org, mates, espanol):
        CourseFactory(professor=colega, organization=org)
        archivar(espanol)
        assert set(teaching_courses(professor, org)) == {mates}

    def test_los_grupos_con_banco_incluyen_archivados_con_preguntas(self, professor, org, mates, espanol):
        QuestionFactory(author=professor, course=espanol)
        archivar(espanol)
        vacio = CourseFactory(professor=professor, organization=org)
        archivar(vacio)
        assert set(bank_courses(professor, org)) == {mates, espanol}

    def test_un_quiz_no_acepta_preguntas_del_banco_de_otro_grupo(self, professor, mates, espanol):
        quiz = make_quiz(mates, questions=0)
        de_otro = QuestionFactory(author=professor, course=espanol)
        with pytest.raises(ValidationError, match="otro grupo"):
            builder.add_questions(quiz, [de_otro])
        assert quiz.questions.count() == 0

    def test_un_quiz_acepta_las_de_su_grupo_y_las_generales(self, professor, mates):
        quiz = make_quiz(mates, questions=0)
        builder.add_questions(quiz, [QuestionFactory(author=professor, course=mates), QuestionFactory(author=professor)])
        assert quiz.questions.count() == 2


# ── Pantalla del banco ────────────────────────────────────────────────

class TestPantallaDelBanco:
    @pytest.fixture
    def banco(self, professor, mates, espanol):
        return {
            "mates": QuestionFactory(author=professor, course=mates, text="Raíz de 144"),
            "espanol": QuestionFactory(author=professor, course=espanol, text="Sinónimo de rápido"),
            "general": QuestionFactory(author=professor, text="Hábitos de estudio"),
        }

    def test_sin_filtro_salen_las_de_todos_mis_grupos_y_las_generales(self, professor_client, banco):
        assert ids(professor_client.get(BANCO)) == {q.pk for q in banco.values()}

    def test_filtra_por_un_grupo(self, professor_client, banco, mates):
        assert ids(professor_client.get(BANCO, {"grupo": mates.pk})) == {banco["mates"].pk}

    def test_filtra_las_generales(self, professor_client, banco):
        assert ids(professor_client.get(BANCO, {"grupo": "sin"})) == {banco["general"].pk}

    def test_un_grupo_que_no_es_mio_no_es_una_opcion(self, professor_client, banco, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        QuestionFactory(author=colega, organization=org, course=ajeno, text="Del colega")
        respuesta = professor_client.get(BANCO, {"grupo": ajeno.pk})
        assert respuesta.status_code == 200 and ids(respuesta) == {q.pk for q in banco.values()}

    @pytest.mark.parametrize("valor", ["abc", "1 OR 1=1", "-3", "99999999999999999999"])
    def test_un_valor_raro_no_rompe_la_pantalla(self, professor_client, banco, valor):
        assert professor_client.get(BANCO, {"grupo": valor}).status_code == 200

    def test_la_tabla_dice_de_que_grupo_es_cada_una(self, professor_client, banco):
        html = professor_client.get(BANCO).content.decode()
        assert "<th>Grupo</th>" in html and "Matemáticas" in html and "Español" in html and "General" in html

    def test_el_selector_ofrece_mis_grupos_y_las_generales(self, professor_client, banco):
        html = professor_client.get(BANCO).content.decode()
        assert 'name="grupo"' in html and "Todos los grupos" in html and "Sin grupo (generales)" in html

    def test_no_se_ven_las_preguntas_de_los_grupos_de_otro_docente(self, professor_client, banco, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        ajena = QuestionFactory(author=colega, organization=org, course=ajeno)
        assert ajena.pk not in ids(professor_client.get(BANCO))
        assert professor_client.get(reverse("quizzes:question_detail", args=[ajena.pk])).status_code == 404

    def test_si_se_ven_las_generales_de_un_colega(self, professor_client, banco, colega, org):
        general = QuestionFactory(author=colega, organization=org)
        assert general.pk in ids(professor_client.get(BANCO))

    def test_los_temas_sugeridos_son_solo_los_de_lo_que_veo(self, professor_client, banco, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        QuestionFactory(author=colega, organization=org, course=ajeno, topic="Secreto")
        QuestionFactory(author=colega, organization=org, topic="Compartido")
        temas = set(professor_client.get(BANCO).context["topics"])
        assert "Secreto" not in temas and "Compartido" in temas

    def test_al_ver_un_grupo_las_preguntas_nuevas_se_proponen_en_el_(self, professor_client, banco, mates):
        html = professor_client.get(BANCO, {"grupo": mates.pk}).content.decode()
        assert f"?grupo={mates.pk}" in html

    def test_el_alumno_no_entra(self, student_client):
        assert student_client.get(BANCO).status_code == 302


# ── Formulario de pregunta ────────────────────────────────────────────

class TestFormulario:
    def crear(self, client, **extra):
        return client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos(**extra))

    def test_se_crea_en_el_grupo_elegido(self, professor_client, mates):
        assert self.crear(professor_client, course=mates.pk).status_code == 302
        assert Question.objects.get().course == mates

    def test_sin_elegir_grupo_queda_general(self, professor_client, mates, espanol):
        assert self.crear(professor_client, course="").status_code == 302
        assert Question.objects.get().course is None

    def test_no_se_puede_crear_en_el_grupo_de_otro_docente(self, professor_client, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        assert self.crear(professor_client, course=ajeno.pk).status_code == 200
        assert not Question.objects.exists()

    def test_no_se_puede_crear_en_un_grupo_archivado(self, professor_client, mates):
        archivar(mates)
        assert self.crear(professor_client, course=mates.pk).status_code == 200
        assert not Question.objects.exists()

    def test_el_formulario_ofrece_solo_mis_grupos_activos(self, professor_client, mates, espanol, colega, org):
        CourseFactory(professor=colega, organization=org)
        archivar(espanol)
        form = professor_client.get(reverse("quizzes:question_create", args=["multiple_choice"])).context["form"]
        assert list(form.fields["course"].queryset) == [mates]

    def test_con_dos_grupos_viene_vacio_y_con_uno_viene_elegido(self, professor_client, mates, espanol):
        url = reverse("quizzes:question_create", args=["multiple_choice"])
        assert professor_client.get(url).context["form"]["course"].value() is None
        archivar(espanol)
        assert professor_client.get(url).context["form"]["course"].value() == mates.pk

    def test_viene_elegido_el_grupo_que_se_estaba_viendo(self, professor_client, mates, espanol):
        url = reverse("quizzes:question_create", args=["true_false"])
        assert professor_client.get(url, {"grupo": espanol.pk}).context["form"]["course"].value() == espanol.pk

    def test_desde_el_constructor_viene_el_grupo_del_quiz(self, professor_client, mates, espanol):
        quiz = make_quiz(espanol, questions=0)
        url = reverse("quizzes:question_create", args=["multiple_choice"])
        form = professor_client.get(url, {"add_to": quiz.activity_id}).context["form"]
        assert form["course"].value() == espanol.pk

    def test_editar_cambia_de_grupo(self, professor_client, professor, mates, espanol):
        p = QuestionFactory(author=professor, course=mates)
        respuesta = professor_client.post(reverse("quizzes:question_update", args=[p.pk]), datos(course=espanol.pk, text=p.text))
        assert respuesta.status_code == 302
        p.refresh_from_db()
        assert p.course == espanol

    def test_editar_una_pregunta_de_un_grupo_archivado_no_obliga_a_cambiarla(self, professor_client, professor, mates):
        p = QuestionFactory(author=professor, course=mates)
        archivar(mates)
        form = professor_client.get(reverse("quizzes:question_update", args=[p.pk])).context["form"]
        assert mates in form.fields["course"].queryset
        respuesta = professor_client.post(reverse("quizzes:question_update", args=[p.pk]), datos(course=mates.pk, text="Editada"))
        assert respuesta.status_code == 302 and Question.objects.get(pk=p.pk).course == mates

    def test_la_pregunta_nueva_desde_el_constructor_queda_en_el_quiz(self, professor_client, mates):
        quiz = make_quiz(mates, questions=0)
        url = reverse("quizzes:question_create", args=["multiple_choice"]) + f"?add_to={quiz.activity_id}"
        assert professor_client.post(url, datos(course=mates.pk)).status_code == 302
        assert quiz.questions.count() == 1


class TestDuplicar:
    def duplicar(self, client, pregunta, **extra):
        return client.post(reverse("quizzes:question_duplicate", args=[pregunta.pk]), extra)

    def test_por_omision_la_copia_queda_en_el_mismo_grupo(self, professor_client, professor, mates):
        p = QuestionFactory(author=professor, course=mates)
        assert self.duplicar(professor_client, p, grupo="").status_code == 302
        assert Question.objects.exclude(pk=p.pk).get().course == mates

    def test_se_puede_duplicar_en_el_banco_de_otro_grupo(self, professor_client, professor, mates, espanol):
        p = QuestionFactory(author=professor, course=mates)
        self.duplicar(professor_client, p, grupo=espanol.pk)
        assert Question.objects.exclude(pk=p.pk).get().course == espanol

    def test_o_como_pregunta_general(self, professor_client, professor, mates):
        p = QuestionFactory(author=professor, course=mates)
        self.duplicar(professor_client, p, grupo="sin")
        assert Question.objects.exclude(pk=p.pk).get().course is None

    def test_no_se_duplica_en_el_grupo_de_otro_docente(self, professor_client, professor, mates, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        p = QuestionFactory(author=professor, course=mates)
        respuesta = self.duplicar(professor_client, p, grupo=ajeno.pk)
        assert respuesta.status_code == 302 and Question.objects.count() == 1

    def test_el_detalle_ofrece_donde_dejar_la_copia(self, professor_client, professor, mates, espanol):
        p = QuestionFactory(author=professor, course=mates)
        html = professor_client.get(reverse("quizzes:question_detail", args=[p.pk])).content.decode()
        assert "En el mismo grupo" in html and "En Español" in html and "Como pregunta general" in html


# ── Importar ──────────────────────────────────────────────────────────

def archivo(*filas):
    texto = CABECERA + "\n" + "\n".join(filas) + "\n"
    return SimpleUploadedFile("preguntas.csv", texto.encode("utf-8"), content_type="text/csv")


FILA = "¿Cuánto es 2 + 2?,Opción múltiple,3,4,5,6,B,1,Aritmética,"


class TestImportar:
    def subir(self, client, grupo, *filas):
        return client.post(reverse("quizzes:import"), {"file": archivo(*(filas or (FILA,))), "grupo": grupo})

    def test_el_paso_uno_pide_el_grupo_de_destino(self, professor_client, mates, espanol):
        html = professor_client.get(reverse("quizzes:import")).content.decode()
        assert "Grupo de destino" in html and "Matemáticas" in html and "Español" in html and "Sin grupo" in html

    def test_viene_marcado_el_grupo_que_se_estaba_viendo(self, professor_client, mates, espanol):
        contexto = professor_client.get(reverse("quizzes:import"), {"grupo": espanol.pk}).context
        assert contexto["selected_group"] == espanol.pk

    def test_importa_al_banco_del_grupo_elegido(self, professor_client, mates):
        assert self.subir(professor_client, mates.pk).status_code == 302
        vista = professor_client.get(reverse("quizzes:import_preview"))
        assert "al banco de Matemáticas" in vista.content.decode()
        assert professor_client.post(reverse("quizzes:import_preview")).status_code == 302
        assert Question.objects.get().course == mates

    def test_importa_como_generales(self, professor_client, mates):
        self.subir(professor_client, "sin")
        assert "como preguntas generales" in professor_client.get(reverse("quizzes:import_preview")).content.decode()
        professor_client.post(reverse("quizzes:import_preview"))
        assert Question.objects.get().course is None

    def test_la_misma_pregunta_puede_estar_en_el_banco_de_dos_grupos(self, professor_client, mates, espanol):
        for grupo in (mates, espanol):
            self.subir(professor_client, grupo.pk)
            professor_client.post(reverse("quizzes:import_preview"))
        assert sorted(Question.objects.values_list("course__name", flat=True)) == ["Español", "Matemáticas"]

    def test_dentro_de_un_grupo_si_se_detectan_las_repetidas(self, professor_client, mates):
        for _ in range(2):
            self.subir(professor_client, mates.pk)
            professor_client.post(reverse("quizzes:import_preview"))
        assert Question.objects.count() == 1

    def test_un_grupo_ajeno_no_se_acepta(self, professor_client, colega, org):
        ajeno = CourseFactory(professor=colega, organization=org)
        respuesta = self.subir(professor_client, ajeno.pk)
        assert respuesta.status_code == 200 and "Elige uno de tus grupos" in respuesta.content.decode()

    def test_si_el_grupo_se_archiva_antes_de_confirmar_no_se_importa(self, professor_client, mates):
        self.subir(professor_client, mates.pk)
        archivar(mates)
        respuesta = professor_client.post(reverse("quizzes:import_preview"))
        assert respuesta.status_code == 302 and respuesta.url == reverse("quizzes:import")
        assert not Question.objects.exists()

    def test_el_analisis_directo_compara_solo_con_el_banco_de_destino(self, professor, org, mates):
        QuestionFactory(author=professor, text="¿Cuánto es 2 + 2?", course=mates)
        headers = CABECERA.split(",")
        rows = [FILA.split(",")]
        assert qi.analyze(org, headers, rows, mates).count_duplicate == 1
        assert qi.analyze(org, headers, rows).count_new == 1  # en las generales todavía no está


# ── Constructor de quizzes ────────────────────────────────────────────

class TestConstructor:
    @pytest.fixture
    def escenario(self, professor, mates, espanol):
        quiz = make_quiz(mates, questions=0)
        return quiz, {
            "propia": QuestionFactory(author=professor, course=mates),
            "general": QuestionFactory(author=professor),
            "otra": QuestionFactory(author=professor, course=espanol),
        }

    def test_ofrece_las_del_grupo_y_las_generales_pero_no_las_de_otro_grupo(self, professor_client, escenario):
        quiz, q = escenario
        respuesta = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id]))
        assert ids(respuesta, "picker") == {q["propia"].pk, q["general"].pk}

    def test_dice_de_que_banco_viene(self, professor_client, escenario):
        quiz, _ = escenario
        html = professor_client.get(reverse("quizzes:builder", args=[quiz.activity_id])).content.decode()
        assert "Agregar desde el banco de Matemáticas" in html and "General" in html

    def test_aunque_se_fabrique_la_peticion_no_agrega_las_de_otro_grupo(self, professor_client, escenario):
        quiz, q = escenario
        professor_client.post(
            reverse("quizzes:builder", args=[quiz.activity_id]),
            {"action": "add", "question": [q["otra"].pk, q["propia"].pk]},
        )
        assert [c.source_id for c in quiz.questions.all()] == [q["propia"].pk]

    def test_agrega_las_del_grupo_y_las_generales(self, professor_client, escenario):
        quiz, q = escenario
        professor_client.post(
            reverse("quizzes:builder", args=[quiz.activity_id]),
            {"action": "add", "question": [q["propia"].pk, q["general"].pk]},
        )
        assert quiz.questions.count() == 2

    def test_un_grupo_distinto_ve_su_propio_banco(self, professor_client, professor, espanol, escenario):
        _, q = escenario
        quiz_espanol = make_quiz(espanol, questions=0)
        respuesta = professor_client.get(reverse("quizzes:builder", args=[quiz_espanol.activity_id]))
        assert ids(respuesta, "picker") == {q["otra"].pk, q["general"].pk}
