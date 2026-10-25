"""Fórmulas y ecuaciones en las preguntas: KaTeX incluido en el proyecto, cargado donde se muestran preguntas."""

import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse

from apps.quizzes.models import Question
from apps.quizzes.services import attempts as svc
from apps.quizzes.services.builder import add_questions
from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db

KATEX_CSS = "vendor/katex/katex.min.css"
KATEX_JS = "vendor/katex/katex.min.js"
AUTO_RENDER = "vendor/katex/auto-render.min.js"
RAIZ = Path(__file__).resolve().parents[3]


def con_formulas(course, **extra):
    return QuestionFactory(
        author=course.professor, organization=course.organization, text=r"Resuelve \(2x + 3 = 11\). ¿Cuánto vale \(x\)?",
        choices=[(r"\(x = 4\)", True), (r"\(x = \dfrac{7}{2}\)", False)], explanation=r"Despeja: \[x = \frac{11 - 3}{2}\]", **extra,
    )


def quiz_con_formulas(course):
    quiz = make_quiz(course, questions=0, published=False)
    add_questions(quiz, [con_formulas(course)])
    quiz.activity.published = True
    quiz.activity.save()
    return quiz


def carga_formulas(pagina):
    return all(recurso in pagina for recurso in (KATEX_CSS, KATEX_JS, AUTO_RENDER, "js/math.js"))


class TestPaginasConPreguntas:
    def test_el_alumno_lo_ve_al_responder_y_al_revisar(self, student_client, course, enrollment):
        quiz = quiz_con_formulas(course)
        intento = svc.start_attempt(quiz, enrollment.student)
        assert carga_formulas(student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode())
        svc.submit_attempt(intento)
        assert carga_formulas(student_client.get(reverse("quizzes:result", args=[intento.pk])).content.decode())

    def test_el_docente_lo_ve_en_cada_pantalla_con_preguntas(self, professor_client, course, enrollment):
        quiz = quiz_con_formulas(course)
        pregunta = Question.objects.get()
        intento = svc.submit_attempt(svc.start_attempt(quiz, enrollment.student))
        rutas = [
            reverse("quizzes:builder", args=[quiz.activity_id]), reverse("quizzes:results", args=[quiz.activity_id]),
            reverse("quizzes:review", args=[intento.pk]), reverse("quizzes:bank"),
            reverse("quizzes:question_detail", args=[pregunta.pk]), reverse("quizzes:question_update", args=[pregunta.pk]),
            reverse("quizzes:question_create", args=["multiple_choice"]),
        ]
        for ruta in rutas:
            pagina = professor_client.get(ruta).content.decode()
            assert carga_formulas(pagina), ruta

    def test_el_texto_llega_intacto_para_que_la_libreria_lo_convierta(self, professor_client, course):
        con_formulas(course)
        pagina = professor_client.get(reverse("quizzes:bank")).content.decode()
        assert r"Resuelve \(2x + 3 = 11\)" in pagina

    def test_los_menores_y_mayores_se_escapan_pero_llegan_como_texto(self, student_client, course, enrollment):
        pregunta = QuestionFactory(author=course.professor, organization=course.organization, text=r"Si \(x < 5 \land y > 2\) entonces...")
        quiz = make_quiz(course, questions=0, published=False)
        add_questions(quiz, [pregunta])
        quiz.activity.published = True
        quiz.activity.save()
        intento = svc.start_attempt(quiz, enrollment.student)
        pagina = student_client.get(reverse("quizzes:take", args=[intento.pk])).content.decode()
        assert r"\(x &lt; 5 \land y &gt; 2\)" in pagina

    def test_las_paginas_sin_preguntas_no_cargan_la_libreria(self, professor_client, course):
        for ruta in (reverse("professor_dashboard"), course.get_absolute_url()):
            assert KATEX_JS not in professor_client.get(ruta).content.decode()


class TestLoQueEscribeElAlumno:
    def test_las_respuestas_de_texto_van_en_zona_sin_formulas(self, student_client, professor_client, course, enrollment):
        corta = QuestionFactory(
            author=course.professor, organization=course.organization, kind=Question.Kind.SHORT_ANSWER, text="¿Cuánto es el doble de 4?",
            choices=[("8", True)],
        )
        abierta = QuestionFactory(author=course.professor, organization=course.organization, kind=Question.Kind.OPEN, text="Explica.")
        quiz = make_quiz(course, questions=0, published=False)
        add_questions(quiz, [corta, abierta])
        quiz.activity.published = True
        quiz.activity.save()
        c, a = quiz.questions.all()
        intento = svc.submit_attempt(svc.start_attempt(quiz, enrollment.student), {c.pk: r"\(x\)", a.pk: r"El área es \[\pi r^2\]"})
        for cliente, nombre in ((student_client, "quizzes:result"), (professor_client, "quizzes:review")):
            pagina = cliente.get(reverse(nombre, args=[intento.pk])).content.decode()
            assert pagina.count('class="no-math"') == 2
            assert r"\(x\)" in pagina and r"\[\pi r^2\]" in pagina

    def test_el_script_de_formulas_respeta_la_zona_sin_formulas(self):
        codigo = (RAIZ / "static/js/math.js").read_text(encoding="utf-8")
        assert 'ignoredClasses: ["no-math"]' in codigo
        assert "trust: false" in codigo and "maxExpand" in codigo and "maxSize" in codigo
        assert '"$' not in codigo.split("delimiters")[1].split("ignoredClasses")[0]  # nunca $...$: «cuesta $15» no es una fórmula


class TestLibreriaIncluida:
    def test_estan_los_archivos_y_la_licencia(self):
        base = RAIZ / "static/vendor/katex"
        for nombre in ("katex.min.js", "katex.min.css", "auto-render.min.js", "LICENSE"):
            assert (base / nombre).is_file(), nombre
        assert len(list((base / "fonts").glob("*.woff2"))) >= 15

    def test_el_css_solo_pide_fuentes_que_existen(self):
        base = RAIZ / "static/vendor/katex"
        css = (base / "katex.min.css").read_text(encoding="utf-8")
        import re

        pedidas = set(re.findall(r"url\((fonts/[^)]+)\)", css))
        assert pedidas and all((base / ruta).is_file() for ruta in pedidas)
        assert not any(ruta.endswith((".woff", ".ttf")) for ruta in pedidas)

    def test_collectstatic_de_produccion_funciona_con_la_libreria(self, tmp_path):
        storages = {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.ManifestStaticFilesStorage"},
            "submissions": {"BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"location": str(tmp_path / "privado")}},
        }
        with override_settings(STORAGES=storages, STATIC_ROOT=str(tmp_path / "static")):
            call_command("collectstatic", interactive=False, verbosity=0)
        manifiesto = json.loads((tmp_path / "static" / "staticfiles.json").read_text(encoding="utf-8"))
        assert "vendor/katex/katex.min.css" in manifiesto["paths"] and "js/math.js" in manifiesto["paths"]
        assert any(ruta.startswith("vendor/katex/fonts/KaTeX_Main-Regular") for ruta in manifiesto["paths"])

