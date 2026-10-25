"""Editor de fórmulas del formulario de preguntas: lógica de inserción (en Node) y marcado de la página."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from django.urls import reverse

from apps.quizzes.models import Question
from apps.quizzes.tests.factories import QuestionFactory

pytestmark = pytest.mark.django_db

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
MARCA = "‸"
requiere_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node no está instalado")


def correr(casos):
    """Manda los casos al ejecutor de Node y devuelve sus resultados."""
    proceso = subprocess.run(
        ["node", str(AQUI / "js" / "math_editor_runner.cjs")], input=json.dumps(casos), capture_output=True, text=True,
        encoding="utf-8", timeout=60, check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    return json.loads(proceso.stdout)


def plantilla(nombre):
    """La plantilla del botón con esa ayuda (Fracción, Exponente…)."""
    grupos = correr([{"op": "grupos", "args": []}])[0]
    return next(item[1] for _, items in grupos for item in items if item[2] == nombre)


@requiere_node
class TestInsertar:
    @pytest.mark.parametrize("texto, ini, fin, boton, valor, cursor", [
        # Sin selección: dentro de \( \) y el cursor en el primer hueco.
        ("", 0, 0, "Fracción", r"\(\frac{}{}\)", 8),
        # Con selección: la envuelve y el cursor pasa al siguiente hueco.
        ("Simplifica x+1 entre 2", 11, 14, "Fracción", r"Simplifica \(\frac{x+1}{}\) entre 2", 24),
        ("x2", 1, 2, "Exponente", r"x\(^{2}\)", 7),
        ("3", 0, 1, "Raíz n-ésima", r"\(\sqrt[3]{}\)", 11),
        # Dentro de una fórmula abierta: sin repetir los delimitadores.
        (r"Calcula \(3", 11, 11, "Exponente", r"Calcula \(3^{}", 13),
        (r"\[x", 3, 3, "Fracción", r"\[x\frac{}{}", 9),
        # Después de una fórmula cerrada: una nueva.
        (r"Calcula \(3\) y", 15, 15, "Raíz cuadrada", r"Calcula \(3\) y\(\sqrt{}\)", 23),
        # En medio del texto y símbolos sin hueco (el cursor queda después).
        ("ab", 1, 1, "pi", r"a\(\pi \)b", 7),
        ("a", 1, 1, "Más o menos", r"a\(\pm \)", 7),
        # Un sistema de ecuaciones es un bloque.
        ("", 0, 0, "Sistema de ecuaciones", "\\[\\begin{cases}  \\\\  \\end{cases}\\]", 16),
        (r"\(x", 3, 3, "Sistema de ecuaciones", "\\(x\\begin{cases}  \\\\  \\end{cases}", 17),
        # Valor absoluto: las barras del símbolo no se confunden con la marca del cursor.
        ("", 0, 0, "Valor absoluto", r"\(\left|  \right|\)", 9),
        ("x+1", 0, 3, "Valor absoluto", r"\(\left| x+1 \right|\)", 20),
    ])
    def test_inserta_donde_debe(self, texto, ini, fin, boton, valor, cursor):
        resultado = correr([{"op": "insertar", "args": [texto, ini, fin, plantilla(boton)]}])[0]
        assert (resultado["value"], resultado["caret"]) == (valor, cursor)

    @pytest.mark.parametrize("texto, pos, esperado", [
        ("", 0, False), (r"\(x", 3, True), (r"\(x\)", 5, False), (r"\[x", 3, True), (r"\[x\]", 5, False),
        (r"\(x\) y \(", 10, True), (r"\(x\) y \(2\) z", 14, False), (r"\(x", 1, False), ("solo texto \\", 12, False),
    ])
    def test_sabe_si_ya_esta_dentro_de_una_formula(self, texto, pos, esperado):
        assert correr([{"op": "dentro", "args": [texto, pos]}])[0] is esperado

    def test_todas_las_plantillas_dan_formulas_balanceadas(self):
        grupos = correr([{"op": "grupos", "args": []}])[0]
        items = [item for _, lista in grupos for item in lista]
        assert len(items) >= 30
        casos = [{"op": "insertar", "args": ["", 0, 0, item[1]]} for item in items]
        for item, resultado in zip(items, correr(casos), strict=True):
            valor = resultado["value"]
            assert MARCA not in valor, item[2]
            assert valor.count("{") == valor.count("}"), item[2]
            assert valor.count("\\left") == valor.count("\\right"), item[2]
            assert valor.count("\\begin") == valor.count("\\end"), item[2]
            assert valor.startswith(("\\(", "\\[")) and valor.endswith(("\\)", "\\]")), item[2]
            assert 0 <= resultado["caret"] <= len(valor), item[2]

    def test_cada_plantilla_tiene_a_lo_mas_una_marca_y_una_ayuda(self):
        grupos = correr([{"op": "grupos", "args": []}])[0]
        ayudas = []
        for _, lista in grupos:
            for etiqueta, latex, ayuda in lista:
                assert latex.count(MARCA) <= 1, ayuda
                assert etiqueta and ayuda
                ayudas.append(ayuda)
        assert len(set(ayudas)) == len(ayudas)

    def test_con_seleccion_nunca_se_pierde_ni_se_duplica_lo_seleccionado(self):
        grupos = correr([{"op": "grupos", "args": []}])[0]
        items = [item for _, lista in grupos for item in lista if MARCA in item[1]]
        casos = [{"op": "insertar", "args": ["a x+1 b", 2, 5, item[1]]} for item in items]
        for item, resultado in zip(items, correr(casos), strict=True):
            assert resultado["value"].count("x+1") == 1, item[2]
            assert resultado["value"].startswith("a ") and resultado["value"].endswith(" b"), item[2]


class TestPagina:
    @pytest.mark.parametrize("tipo", ["multiple_choice", "true_false", "short_answer", "open", "ordering", "matching"])
    def test_el_formulario_trae_la_paleta_y_carga_el_editor(self, professor_client, tipo):
        pagina = professor_client.get(reverse("quizzes:question_create", args=[tipo])).content.decode()
        assert f'data-math-editor data-kind="{tipo}"' in pagina and "data-math-palette" in pagina
        assert "js/math_editor.js" in pagina and "vendor/katex/katex.min.js" in pagina and "js/math.js" in pagina
        assert pagina.index("vendor/katex/katex.min.js") < pagina.index("js/math_editor.js")

    def test_al_editar_tambien(self, professor_client, course):
        pregunta = QuestionFactory(author=course.professor, organization=course.organization, text=r"Si \(x^2 = 9\)...")
        pagina = professor_client.get(reverse("quizzes:question_update", args=[pregunta.pk])).content.decode()
        assert "data-math-editor" in pagina and r"Si \(x^2 = 9\)..." in pagina

    def test_las_demas_paginas_no_cargan_el_editor(self, professor_client, course):
        pregunta = QuestionFactory(author=course.professor, organization=course.organization)
        for ruta in (reverse("quizzes:bank"), reverse("quizzes:question_detail", args=[pregunta.pk])):
            assert "math_editor.js" not in professor_client.get(ruta).content.decode()

    def test_el_script_decide_que_campos_llevan_formulas(self):
        codigo = (RAIZ / "static/js/math_editor.js").read_text(encoding="utf-8")
        assert "id_text" in codigo and "id_explanation" in codigo and r"/-text$/" in codigo
        assert '["multiple_choice", "ordering", "matching"]' in codigo  # no las respuestas aceptadas ni la columna derecha
        assert "match_text" not in codigo.split("isMathField")[1].split("function fieldName")[0]

    def test_guardar_una_pregunta_con_formulas_conserva_el_texto_tal_cual(self, professor_client):
        datos = {
            "text": r"Resuelve \(2x + 3 = 11\) y \[x = \frac{8}{2}\]", "points": "1", "topic": "", "explanation": r"Despeja \(x\).",
            "choices-TOTAL_FORMS": "2", "choices-INITIAL_FORMS": "0", "choices-MIN_NUM_FORMS": "0", "choices-MAX_NUM_FORMS": "8",
            "choices-0-text": r"\(x = 4\)", "choices-0-is_correct": "on", "choices-1-text": r"\(x = \dfrac{7}{2}\)",
        }
        professor_client.post(reverse("quizzes:question_create", args=["multiple_choice"]), datos)
        pregunta = Question.objects.get()
        assert pregunta.text == datos["text"] and [c.text for c in pregunta.choices.all()] == [r"\(x = 4\)", r"\(x = \dfrac{7}{2}\)"]
