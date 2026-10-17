"""Banco de preguntas: reglas de validación, servicio y pantallas."""

import pytest
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.organizations.factories import MembershipFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY, teaching_organization

from .factories import QuestionFactory
from .models import Choice, Question
from .services.bank import (
    MAX_CHOICES, can_edit_question, duplicate_question, save_question, validate_choices,
)

pytestmark = pytest.mark.django_db

MC = Question.Kind.MULTIPLE_CHOICE
TF = Question.Kind.TRUE_FALSE


@pytest.fixture
def org(professor):
    return teaching_organization(professor)


def cliente(user, organizacion=None):
    c = Client()
    c.force_login(user)
    if organizacion is not None:
        s = c.session
        s[SESSION_KEY] = organizacion.pk
        s.save()
    return c


@pytest.fixture
def colega(org):
    """Otro docente de la misma organización."""
    otro = ProfessorFactory()
    MembershipFactory(user=otro, organization=org, role=Membership.Role.TEACHER)
    return otro


# ── Validación de opciones ────────────────────────────────────────────

class TestValidarOpciones:
    def test_valido(self):
        assert validate_choices([("  Sí ", True), ("No", False)]) == [("Sí", True), ("No", False)]

    def test_las_opciones_en_blanco_se_ignoran(self):
        assert len(validate_choices([("A", True), ("B", False), ("", False), ("   ", False), (None, False)])) == 2

    @pytest.mark.parametrize("opciones, mensaje", [
        ([("Solo una", True)], "al menos 2"),
        ([("", True), ("", False)], "al menos 2"),
        ([(f"Op {n}", n == 0) for n in range(MAX_CHOICES + 1)], "Máximo"),
        ([("A", True), ("a", False)], "repetidas"),
        ([("A", False), ("B", False)], "exactamente una"),
        ([("A", True), ("B", True)], "exactamente una"),
    ])
    def test_invalido(self, opciones, mensaje):
        with pytest.raises(ValidationError, match=mensaje):
            validate_choices(opciones)

    def test_el_maximo_es_valido(self):
        assert len(validate_choices([(f"Op {n}", n == 0) for n in range(MAX_CHOICES)])) == MAX_CHOICES


# ── Servicio ──────────────────────────────────────────────────────────

class TestGuardar:
    def test_opcion_multiple(self, org, professor):
        p = save_question(
            organization=org, author=professor, kind=MC, text="  ¿Capital de México?  ", points=2,
            explanation=" Es CDMX ", topic=" Geografía ", choices=[("CDMX", True), ("Puebla", False)],
        )
        assert (p.text, p.points, p.explanation, p.topic, p.author, p.organization) == (
            "¿Capital de México?", 2, "Es CDMX", "Geografía", professor, org,
        )
        assert [(c.text, c.is_correct, c.position) for c in p.choices.all()] == [("CDMX", True, 0), ("Puebla", False, 1)]
        assert {c.organization_id for c in p.choices.all()} == {org.pk}

    @pytest.mark.parametrize("verdadera", [True, False])
    def test_verdadero_o_falso(self, org, professor, verdadera):
        p = save_question(organization=org, author=professor, kind=TF, text="El cielo es azul", points=1, true_is_correct=verdadera)
        assert [(c.text, c.is_correct) for c in p.choices.all()] == [("Verdadero", verdadera), ("Falso", not verdadera)]

    def test_verdadero_o_falso_exige_la_respuesta(self, org, professor):
        with pytest.raises(ValidationError, match="verdadero o falso"):
            save_question(organization=org, author=professor, kind=TF, text="x", points=1)

    def test_tipo_desconocido(self, org, professor):
        with pytest.raises(ValidationError, match="desconocido"):
            save_question(organization=org, author=professor, kind="essay", text="x", points=1)

    @pytest.mark.parametrize("puntos", [0, -1])
    def test_los_puntos_deben_ser_positivos(self, org, professor, puntos):
        with pytest.raises(ValidationError):
            save_question(organization=org, author=professor, kind=TF, text="x", points=puntos, true_is_correct=True)
        assert not Question.objects.exists()

    def test_el_texto_es_obligatorio(self, org, professor):
        with pytest.raises(ValidationError):
            save_question(organization=org, author=professor, kind=TF, text="   ", points=1, true_is_correct=True)

    def test_una_pregunta_invalida_no_deja_nada_a_medias(self, org, professor):
        with pytest.raises(ValidationError):
            save_question(organization=org, author=professor, kind=MC, text="x", points=1, choices=[("A", False), ("B", False)])
        assert not Question.objects.exists() and not Choice.objects.exists()

    def test_actualizar_reemplaza_las_opciones(self, professor):
        p = QuestionFactory(author=professor)
        save_question(
            organization=p.organization, author=professor, kind=MC, text="Nuevo texto", points=3,
            choices=[("X", False), ("Y", True)], question=p,
        )
        p.refresh_from_db()
        assert (p.text, p.points) == ("Nuevo texto", 3)
        assert [(c.text, c.is_correct) for c in p.choices.all()] == [("X", False), ("Y", True)]
        assert Choice.objects.count() == 2

    def test_una_actualizacion_invalida_conserva_la_pregunta(self, professor):
        p = QuestionFactory(author=professor)
        with pytest.raises(ValidationError):
            save_question(organization=p.organization, author=professor, kind=MC, text="x", points=1, choices=[("A", True)], question=p)
        assert p.choices.count() == 3

    def test_el_tipo_no_cambia(self, professor):
        p = QuestionFactory(author=professor)
        with pytest.raises(ValidationError, match="no se puede cambiar"):
            save_question(organization=p.organization, author=professor, kind=TF, text="x", points=1, true_is_correct=True, question=p)

    def test_no_se_actualiza_la_pregunta_de_otra_organizacion(self, professor):
        ajena = QuestionFactory()
        with pytest.raises(ValidationError, match="otra organización"):
            save_question(
                organization=teaching_organization(professor), author=professor, kind=MC, text="x", points=1,
                choices=[("A", True), ("B", False)], question=ajena,
            )

    def test_duplicar(self, professor, colega):
        original = QuestionFactory(author=professor, topic="Álgebra", explanation="Porque sí", points=2)
        copia = duplicate_question(original, by=colega)
        assert copia.pk != original.pk
        assert (copia.text, copia.topic, copia.explanation, copia.points, copia.author) == (
            f"{original.text} (copia)", "Álgebra", "Porque sí", 2, colega,
        )
        assert [(c.text, c.is_correct) for c in copia.choices.all()] == [(c.text, c.is_correct) for c in original.choices.all()]
        assert original.choices.count() == 3  # el original no se toca

    @pytest.mark.parametrize("verdadera", [True, False])
    def test_duplicar_verdadero_o_falso(self, professor, verdadera):
        original = QuestionFactory(author=professor, kind=TF, true_is_correct=verdadera)
        copia = duplicate_question(original, by=professor)
        assert [(c.text, c.is_correct) for c in copia.choices.all()] == [("Verdadero", verdadera), ("Falso", not verdadera)]


class TestPermisosDeEdicion:
    def test_la_autora_edita(self, professor, org):
        membership = Membership.objects.get(user=professor, organization=org)
        assert can_edit_question(professor, membership, QuestionFactory(author=professor))

    def test_otro_docente_no_edita(self, professor, colega, org):
        membership = Membership.objects.get(user=colega, organization=org)
        assert not can_edit_question(colega, membership, QuestionFactory(author=professor))

    def test_el_propietario_edita_las_de_todos(self, professor, colega, org):
        Membership.objects.filter(user=colega, organization=org).update(role=Membership.Role.OWNER)
        membership = Membership.objects.get(user=colega, organization=org)
        assert can_edit_question(colega, membership, QuestionFactory(author=professor))


# ── Banco: listado ────────────────────────────────────────────────────

class TestListado:
    def test_solo_las_de_la_organizacion(self, professor_client, professor):
        propia = QuestionFactory(author=professor)
        QuestionFactory()  # otra organización
        assert [q.pk for q in professor_client.get(reverse("quizzes:bank")).context["page"]] == [propia.pk]

    def test_los_colegas_comparten_el_banco(self, colega, professor, org):
        propia = QuestionFactory(author=professor)
        de_colega = QuestionFactory(author=colega, organization=org)
        page = cliente(colega, org).get(reverse("quizzes:bank")).context["page"]
        assert {q.pk for q in page} == {propia.pk, de_colega.pk}

    def test_filtra_por_texto_tema_y_tipo(self, professor_client, professor):
        a = QuestionFactory(author=professor, text="Derivadas básicas", topic="Cálculo")
        b = QuestionFactory(author=professor, text="Historia de Roma", topic="Historia", kind=TF)
        ids = lambda **params: {q.pk for q in professor_client.get(reverse("quizzes:bank"), params).context["page"]}  # noqa: E731
        assert ids(q="derivadas") == {a.pk}
        assert ids(q="historia") == {b.pk}  # busca también en el tema
        assert ids(topic="cálculo") == {a.pk}
        assert ids(kind="true_false") == {b.pk}
        assert ids(kind="multiple_choice", q="roma") == set()
        assert ids() == {a.pk, b.pk}

    def test_las_archivadas_van_aparte(self, professor_client, professor):
        viva = QuestionFactory(author=professor)
        archivada = QuestionFactory(author=professor)
        Question.objects.filter(pk=archivada.pk).update(is_archived=True)
        assert [q.pk for q in professor_client.get(reverse("quizzes:bank")).context["page"]] == [viva.pk]
        context = professor_client.get(reverse("quizzes:bank"), {"archived": "on"}).context
        assert [q.pk for q in context["page"]] == [archivada.pk] and context["showing_archived"]

    def test_pagina_de_20_en_20_conservando_los_filtros(self, professor_client, professor):
        for _ in range(23):
            QuestionFactory(author=professor, topic="Tema")
        primera = professor_client.get(reverse("quizzes:bank"), {"topic": "Tema"}).context
        assert len(primera["page"]) == 20 and primera["page"].paginator.count == 23
        assert "topic=Tema" in primera["querystring"] and "page=" not in primera["querystring"]
        assert len(professor_client.get(reverse("quizzes:bank"), {"topic": "Tema", "page": 2}).context["page"]) == 3

    def test_lista_los_temas_de_la_organizacion(self, professor_client, professor):
        QuestionFactory(author=professor, topic="B")
        QuestionFactory(author=professor, topic="A")
        QuestionFactory(author=professor, topic="A")
        QuestionFactory(topic="Ajeno")
        assert list(professor_client.get(reverse("quizzes:bank")).context["topics"]) == ["A", "B"]

    def test_el_alumno_no_accede(self, student_client, enrollment):
        assert student_client.get(reverse("quizzes:bank")).status_code == 302

    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("quizzes:bank")).url.startswith("/login/")

    def test_sigue_a_la_organizacion_activa(self, professor, professor_client):
        otra = MembershipFactory(user=professor, role=Membership.Role.TEACHER).organization
        en_otra = QuestionFactory(author=professor, organization=otra)
        propia = QuestionFactory(author=professor)
        assert [q.pk for q in professor_client.get(reverse("quizzes:bank")).context["page"]] == [propia.pk]
        assert [q.pk for q in cliente(professor, otra).get(reverse("quizzes:bank")).context["page"]] == [en_otra.pk]


# ── Banco: crear y editar ─────────────────────────────────────────────

def datos_mc(**cambios):
    base = {
        "text": "¿2 + 2?", "points": "1", "topic": "Aritmética", "explanation": "Suma básica",
        "choices-TOTAL_FORMS": "4", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
        "choices-0-text": "3", "choices-1-text": "4", "choices-1-is_correct": "on", "choices-2-text": "5", "choices-3-text": "",
    }
    base.update(cambios)
    return base


class TestCrear:
    def test_el_formulario_se_abre(self, professor_client):
        for kind in ("multiple_choice", "true_false"):
            assert professor_client.get(reverse("quizzes:question_create", args=[kind])).status_code == 200

    def test_tipo_desconocido(self, professor_client):
        assert professor_client.get(reverse("quizzes:question_create", args=["essay"])).status_code == 404

    def test_el_formulario_de_opcion_multiple_trae_filas_de_opciones(self, professor_client):
        context = professor_client.get(reverse("quizzes:question_create", args=["multiple_choice"])).context
        assert len(context["formset"].forms) == 4

    def test_crea_opcion_multiple(self, professor_client, professor, org):
        response = professor_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos_mc())
        p = Question.objects.get()
        assert response.url == reverse("quizzes:question_detail", args=[p.pk])
        assert (p.organization, p.author, p.topic) == (org, professor, "Aritmética")
        assert [(c.text, c.is_correct) for c in p.choices.all()] == [("3", False), ("4", True), ("5", False)]

    @pytest.mark.parametrize("cambios, fragmento", [
        ({"choices-1-is_correct": ""}, "exactamente una"),
        ({"choices-0-is_correct": "on"}, "exactamente una"),
        ({"choices-1-text": "", "choices-2-text": ""}, "al menos 2"),
        ({"choices-0-text": "4"}, "repetidas"),
    ])
    def test_opciones_invalidas_no_guardan_nada(self, professor_client, cambios, fragmento):
        response = professor_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos_mc(**cambios))
        assert response.status_code == 200 and fragmento in str(response.context["formset"].non_form_errors())
        assert not Question.objects.exists()

    @pytest.mark.parametrize("cambios, campo", [({"text": ""}, "text"), ({"points": "0"}, "points"), ({"points": "abc"}, "points")])
    def test_campos_invalidos(self, professor_client, cambios, campo):
        response = professor_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos_mc(**cambios))
        assert response.status_code == 200 and campo in response.context["form"].errors

    @pytest.mark.parametrize("correcta, verdadera", [("true", True), ("false", False)])
    def test_crea_verdadero_o_falso(self, professor_client, correcta, verdadera):
        professor_client.post(reverse("quizzes:question_create", args=["true_false"]), {"text": "Roma está en Italia", "points": "1", "correct": correcta})
        p = Question.objects.get()
        assert next(c for c in p.choices.all() if c.text == "Verdadero").is_correct is verdadera

    def test_verdadero_o_falso_exige_la_respuesta(self, professor_client):
        response = professor_client.post(reverse("quizzes:question_create", args=["true_false"]), {"text": "x", "points": "1"})
        assert "correct" in response.context["form"].errors and not Question.objects.exists()

    def test_el_alumno_no_crea(self, student_client, enrollment):
        assert student_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos_mc()).status_code == 302
        assert not Question.objects.exists()


class TestEditar:
    def test_el_formulario_viene_con_los_datos(self, professor_client, professor):
        p = QuestionFactory(author=professor, text="Original")
        context = professor_client.get(reverse("quizzes:question_update", args=[p.pk])).context
        assert context["form"].initial["text"] == "Original"
        assert [f.initial["text"] for f in context["formset"].forms[:3]] == ["Opción A", "Opción B", "Opción C"]
        assert len(context["formset"].forms) == 4

    def test_edita(self, professor_client, professor):
        p = QuestionFactory(author=professor)
        professor_client.post(reverse("quizzes:question_update", args=[p.pk]), datos_mc(text="Editada"))
        p.refresh_from_db()
        assert p.text == "Editada" and p.choices.count() == 3

    def test_edita_verdadero_o_falso(self, professor_client, professor):
        p = QuestionFactory(author=professor, kind=TF, true_is_correct=True)
        form = professor_client.get(reverse("quizzes:question_update", args=[p.pk])).context["form"]
        assert form.initial["correct"] == "true"
        professor_client.post(reverse("quizzes:question_update", args=[p.pk]), {"text": p.text, "points": "1", "correct": "false"})
        assert next(c for c in p.choices.all() if c.text == "Verdadero").is_correct is False

    def test_otro_docente_no_edita_la_pregunta_ajena(self, colega, professor, org):
        p = QuestionFactory(author=professor)
        c = cliente(colega, org)
        assert c.get(reverse("quizzes:question_update", args=[p.pk])).status_code == 404
        assert c.post(reverse("quizzes:question_update", args=[p.pk]), datos_mc(text="Hackeada")).status_code == 404
        p.refresh_from_db()
        assert p.text != "Hackeada"

    def test_pregunta_de_otra_organizacion_es_404(self, professor_client):
        ajena = QuestionFactory()
        for name in ("question_detail", "question_update"):
            assert professor_client.get(reverse(f"quizzes:{name}", args=[ajena.pk])).status_code == 404
        for name in ("question_duplicate", "question_archive", "question_delete"):
            assert professor_client.post(reverse(f"quizzes:{name}", args=[ajena.pk])).status_code == 404
        assert Question.objects.filter(pk=ajena.pk).exists()


# ── Banco: detalle, duplicar, archivar y eliminar ─────────────────────

class TestAcciones:
    def test_detalle_con_acciones_para_la_autora(self, professor_client, professor):
        p = QuestionFactory(author=professor, explanation="Porque sí")
        html = professor_client.get(reverse("quizzes:question_detail", args=[p.pk])).content.decode()
        assert "Opción A" in html and "correcta" in html and "Porque sí" in html
        assert reverse("quizzes:question_update", args=[p.pk]) in html

    def test_detalle_de_un_colega_sin_editar_pero_con_duplicar(self, colega, professor, org):
        p = QuestionFactory(author=professor)
        html = cliente(colega, org).get(reverse("quizzes:question_detail", args=[p.pk])).content.decode()
        assert reverse("quizzes:question_update", args=[p.pk]) not in html
        assert reverse("quizzes:question_duplicate", args=[p.pk]) in html

    def test_un_colega_duplica_y_edita_su_copia(self, colega, professor, org):
        p = QuestionFactory(author=professor)
        c = cliente(colega, org)
        response = c.post(reverse("quizzes:question_duplicate", args=[p.pk]))
        copia = Question.objects.exclude(pk=p.pk).get()
        assert copia.author == colega and response.url == reverse("quizzes:question_update", args=[copia.pk])
        assert c.get(response.url).status_code == 200

    def test_archivar_y_desarchivar(self, professor_client, professor):
        p = QuestionFactory(author=professor)
        url = reverse("quizzes:question_archive", args=[p.pk])
        professor_client.post(url)
        p.refresh_from_db()
        assert p.is_archived
        professor_client.post(url)
        p.refresh_from_db()
        assert not p.is_archived

    def test_eliminar(self, professor_client, professor):
        p = QuestionFactory(author=professor)
        professor_client.post(reverse("quizzes:question_delete", args=[p.pk]))
        assert not Question.objects.exists() and not Choice.objects.exists()

    def test_otro_docente_no_archiva_ni_elimina(self, colega, professor, org):
        p = QuestionFactory(author=professor)
        c = cliente(colega, org)
        assert c.post(reverse("quizzes:question_archive", args=[p.pk])).status_code == 404
        assert c.post(reverse("quizzes:question_delete", args=[p.pk])).status_code == 404
        assert Question.objects.filter(pk=p.pk, is_archived=False).exists()

    @pytest.mark.parametrize("name", ["question_duplicate", "question_archive", "question_delete"])
    def test_solo_aceptan_post(self, professor_client, professor, name):
        p = QuestionFactory(author=professor)
        assert professor_client.get(reverse(f"quizzes:{name}", args=[p.pk])).status_code == 405

    def test_el_contenido_se_escapa(self, professor_client, professor):
        p = QuestionFactory(author=professor, text="<script>alert(1)</script>", choices=[("<b>x</b>", True), ("y", False)])
        html = professor_client.get(reverse("quizzes:question_detail", args=[p.pk])).content.decode()
        assert "<script>alert(1)</script>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html

    def test_el_enlace_aparece_en_el_menu_del_docente(self, professor_client):
        assert reverse("quizzes:bank") in professor_client.get(reverse("professor_dashboard")).content.decode()
