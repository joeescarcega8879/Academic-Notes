"""Importar preguntas desde Excel o CSV."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from openpyxl import Workbook

from apps.courses.services.importing import read_table
from apps.organizations.services import teaching_organization

from apps.quizzes.tests.factories import QuestionFactory
from apps.quizzes.models import Question
from apps.quizzes.services import question_import as qi

pytestmark = pytest.mark.django_db

MC = Question.Kind.MULTIPLE_CHOICE
TF = Question.Kind.TRUE_FALSE

CABECERA = "Pregunta,Tipo,Opción A,Opción B,Opción C,Opción D,Correcta,Puntos,Tema,Explicación"


def tabla(*filas, cabecera=CABECERA):
    texto = cabecera + "\n" + "\n".join(filas) + "\n"
    return read_table("preguntas.csv", texto.encode("utf-8"))


def analizar(org, *filas, cabecera=CABECERA):
    headers, rows = tabla(*filas, cabecera=cabecera)
    return qi.analyze(org, headers, rows)


@pytest.fixture
def org(professor):
    return teaching_organization(professor)


# ── Encabezados ───────────────────────────────────────────────────────

class TestEncabezados:
    def test_reconoce_las_columnas_y_las_opciones_en_orden(self):
        columnas, opciones = qi.detect_columns(CABECERA.split(","))
        assert columnas == {"text": 0, "kind": 1, "correct": 6, "points": 7, "topic": 8, "explanation": 9}
        assert opciones == [2, 3, 4, 5]

    @pytest.mark.parametrize("cabecera", [
        ["Enunciado", "A", "B", "C", "Respuesta correcta"],
        ["REACTIVO", "inciso a", "inciso b", "inciso c", "Clave"],
        ["texto", "Opción 1", "Opción 2", "Opción 3", "answer"],
    ])
    def test_variantes_de_encabezado(self, cabecera):
        columnas, opciones = qi.detect_columns(cabecera)
        assert columnas["text"] == 0 and columnas["correct"] == 4 and opciones == [1, 2, 3]

    def test_las_opciones_se_ordenan_por_letra_no_por_posicion(self):
        _, opciones = qi.detect_columns(["Pregunta", "Opción C", "Opción A", "Opción B", "Correcta"])
        assert opciones == [2, 3, 1]

    def test_faltan_columnas_obligatorias(self, org):
        sin_correcta = analizar(org, "x,a,b", cabecera="Pregunta,Opción A,Opción B")
        assert sin_correcta.header_errors == ['No encontré la columna "Correcta".'] and sin_correcta.items == []
        sin_pregunta = analizar(org, "a,b,A", cabecera="Opción A,Opción B,Correcta")
        assert 'No encontré la columna "Pregunta".' in sin_pregunta.header_errors


# ── Opción múltiple ───────────────────────────────────────────────────

class TestOpcionMultiple:
    def una(self, org, fila):
        (item,) = analizar(org, fila).items
        return item

    @pytest.mark.parametrize("correcta, indice", [("B", 1), ("b", 1), ("2", 1), ("Ciudad de México", 1), ("ciudad de mexico", 1), (" C ", 2)])
    def test_formas_de_indicar_la_correcta(self, org, correcta, indice):
        item = self.una(org, f"¿Capital?,,Guadalajara,Ciudad de México,Monterrey,Puebla,{correcta},1,,")
        assert item.errors == [] and item.kind == MC
        assert [c for _, c in item.choices].index(True) == indice

    def test_todos_los_datos(self, org):
        item = self.una(org, "¿Capital?,Opción múltiple,A,B,C,D,B,2.5,Geografía,Es CDMX")
        assert (item.text, item.points, item.topic, item.explanation) == ("¿Capital?", Decimal("2.50"), "Geografía", "Es CDMX")
        assert [t for t, _ in item.choices] == ["A", "B", "C", "D"]

    def test_las_opciones_vacias_se_ignoran(self, org):
        item = self.una(org, "¿Cuál?,,Uno,Dos,,,B,,,")
        assert item.errors == [] and [t for t, _ in item.choices] == ["Uno", "Dos"]

    def test_la_letra_apunta_a_la_columna_aunque_haya_huecos(self, org):
        item = self.una(org, "¿Cuál?,,Uno,,Tres,,C,,,")
        assert [(t, c) for t, c in item.choices] == [("Uno", False), ("Tres", True)]

    @pytest.mark.parametrize("correcta, mensaje", [
        ("", "Falta la respuesta correcta"),
        ("E", "no existe"),
        ("9", "no existe"),
        ("A, C", "Solo puede haber una"),
        ("Madrid", "no coincide"),
        ("C", "opción vacía"),
    ])
    def test_correcta_invalida(self, org, correcta, mensaje):
        item = self.una(org, f'¿Cuál?,,Uno,Dos,,,"{correcta}",,,')
        assert any(mensaje in e for e in item.errors), item.errors

    @pytest.mark.parametrize("fila, mensaje", [
        ("¿Cuál?,,Uno,,,,A,,,", "al menos 2"),
        ("¿Cuál?,,Sí,sí,No,,A,,,", "repetidas"),
        (",,Uno,Dos,,,A,,,", "Falta la pregunta"),
        ("¿Cuál?,,Uno,Dos,,,A,0,,", "mayores que 0"),
        ("¿Cuál?,,Uno,Dos,,,A,abc,,", "un número"),
        ("¿Cuál?,,Uno,Dos,,,A,10000,,", "mayores que 0"),
        (f"¿Cuál?,,Uno,Dos,,,A,,{'t' * 81},", "tema es demasiado largo"),
        (f"{'x' * 5001},,Uno,Dos,,,A,,,", "demasiado larga"),
        (f"¿Cuál?,,{'o' * 501},Dos,,,A,,,", "opción es demasiado larga"),
    ])
    def test_otros_errores(self, org, fila, mensaje):
        item = self.una(org, fila)
        assert any(mensaje in e for e in item.errors), item.errors

    def test_puntos_con_coma_y_por_defecto(self, org):
        assert self.una(org, "¿P?,,A,B,,,A,\"1,5\",,").points == Decimal("1.50")
        assert self.una(org, "¿P?,,A,B,,,A,,,").points == Decimal(1)


# ── Verdadero o falso ─────────────────────────────────────────────────

class TestVerdaderoFalso:
    def una(self, org, fila):
        (item,) = analizar(org, fila).items
        return item

    @pytest.mark.parametrize("correcta, esperado", [
        ("Verdadero", True), ("verdadero", True), ("V", True), ("true", True), ("Cierto", True),
        ("Falso", False), ("F", False), ("FALSE", False),
    ])
    def test_palabras_aceptadas(self, org, correcta, esperado):
        item = self.una(org, f"El sol sale por el este,Verdadero/Falso,,,,,{correcta},,,")
        assert item.errors == [] and (item.kind, item.true_is_correct) == (TF, esperado)

    def test_se_deduce_sin_tipo_ni_opciones(self, org):
        item = self.una(org, "El agua moja,,,,,,Verdadero,,,")
        assert (item.kind, item.true_is_correct, item.errors) == (TF, True, [])

    def test_ignora_las_opciones_si_el_tipo_es_verdadero_o_falso(self, org):
        item = self.una(org, "¿Cierto?,VF,A,B,,,Falso,,,")
        assert (item.kind, item.true_is_correct, item.errors) == (TF, False, [])

    @pytest.mark.parametrize("correcta", ["A", "tal vez", ""])
    def test_correcta_invalida(self, org, correcta):
        item = self.una(org, f"¿Cierto?,Verdadero/Falso,,,,,{correcta},,,")
        assert any("Verdadero" in e for e in item.errors), item.errors

    def test_sin_forma_de_deducir_el_tipo(self, org):
        item = self.una(org, "¿Algo?,,,,,,quizá,,,")
        assert any("saber el tipo" in e for e in item.errors)

    def test_el_tipo_explicito_gana(self, org):
        item = self.una(org, "¿P?,opcion multiple,Sí,No,,,A,,,")
        assert item.kind == MC


# ── Duplicadas ────────────────────────────────────────────────────────

class TestDuplicadas:
    def test_ya_existe_en_el_banco(self, org, professor):
        QuestionFactory(author=professor, text="¿Cuál es la CAPITAL de México?")
        plan = analizar(org, "  ¿cual es la capital de mexico?  ,,A,B,,,A,,,")
        assert plan.items[0].status == "duplicate" and plan.items[0].duplicate == "banco"

    def test_repetida_dentro_del_archivo(self, org):
        plan = analizar(org, "¿P?,,A,B,,,A,,,", "¿p?,,C,D,,,A,,,")
        assert [i.status for i in plan.items] == ["new", "duplicate"] and plan.items[1].duplicate == "archivo"

    def test_el_mismo_texto_de_otro_tipo_no_es_duplicado(self, org, professor):
        QuestionFactory(author=professor, text="¿Es cierto?")
        plan = analizar(org, "¿Es cierto?,Verdadero/Falso,,,,,Verdadero,,,")
        assert plan.items[0].status == "new"

    def test_las_archivadas_no_cuentan(self, org, professor):
        archivada = QuestionFactory(author=professor, text="¿Archivada?")
        Question.objects.filter(pk=archivada.pk).update(is_archived=True)
        assert analizar(org, "¿Archivada?,,A,B,,,A,,,").items[0].status == "new"

    def test_las_de_otra_organizacion_no_cuentan(self, org):
        QuestionFactory(text="¿Ajena?")
        assert analizar(org, "¿Ajena?,,A,B,,,A,,,").items[0].status == "new"

    def test_una_fila_con_error_no_marca_duplicado(self, org):
        plan = analizar(org, "¿P?,,A,B,,,Z,,,", "¿P?,,A,B,,,A,,,")
        assert [i.status for i in plan.items] == ["error", "new"]


# ── Aplicar ───────────────────────────────────────────────────────────

class TestAplicar:
    def test_crea_solo_las_nuevas(self, org, professor):
        QuestionFactory(author=professor, text="Ya estaba")
        plan = analizar(
            org, "Nueva uno,,A,B,,,B,2,Álgebra,Porque sí", "Ya estaba,,A,B,,,A,,,", "Mala,,A,B,,,Z,,,",
            "Nueva dos,Verdadero/Falso,,,,,Falso,,,",
        )
        resumen = qi.apply_import(org, professor, plan)
        assert resumen == {"created": 2, "duplicates": 1, "errors": 1}
        uno = Question.objects.get(text="Nueva uno")
        assert (uno.author, uno.organization, uno.points, uno.topic, uno.explanation) == (professor, org, 2, "Álgebra", "Porque sí")
        assert [(c.text, c.is_correct) for c in uno.choices.all()] == [("A", False), ("B", True)]
        dos = Question.objects.get(text="Nueva dos")
        assert next(c for c in dos.choices.all() if c.text == "Verdadero").is_correct is False

    def test_volver_a_subir_el_archivo_no_duplica(self, org, professor):
        filas = ("P1,,A,B,,,A,,,", "P2,Verdadero/Falso,,,,,Verdadero,,,")
        qi.apply_import(org, professor, analizar(org, *filas))
        segundo = analizar(org, *filas)
        assert [i.status for i in segundo.items] == ["duplicate", "duplicate"]
        assert qi.apply_import(org, professor, segundo)["created"] == 0
        assert Question.objects.count() == 2

    def test_es_atomica(self, org, professor, monkeypatch):
        llamadas = []
        original = qi.save_question

        def falla_en_la_segunda(**kwargs):
            llamadas.append(1)
            if len(llamadas) == 2:
                raise RuntimeError("boom")
            return original(**kwargs)

        monkeypatch.setattr(qi, "save_question", falla_en_la_segunda)
        with pytest.raises(RuntimeError):
            qi.apply_import(org, professor, analizar(org, "P1,,A,B,,,A,,,", "P2,,A,B,,,A,,,"))
        assert not Question.objects.exists()

    def test_excel_con_numeros_en_la_correcta(self, org, professor):
        libro = Workbook()
        libro.active.append(["Pregunta", "Opción A", "Opción B", "Opción C", "Correcta", "Puntos"])
        libro.active.append(["¿Cuánto es 2+2?", "3", "4", "5", 2, 1.5])
        buffer = io.BytesIO()
        libro.save(buffer)
        headers, rows = read_table("p.xlsx", buffer.getvalue())
        plan = qi.analyze(org, headers, rows)
        assert plan.items[0].errors == [] and plan.items[0].points == Decimal("1.50")
        qi.apply_import(org, professor, plan)
        assert next(c for c in Question.objects.get().choices.all() if c.is_correct).text == "4"


# ── Pantallas ─────────────────────────────────────────────────────────

def subir(client, contenido, nombre="preguntas.csv"):
    datos = contenido if isinstance(contenido, bytes) else contenido.encode("utf-8")
    return client.post(reverse("quizzes:import"), {"file": SimpleUploadedFile(nombre, datos)})


ARCHIVO = CABECERA + "\n" + "\n".join([
    "¿Capital de México?,,Guadalajara,Ciudad de México,Monterrey,Puebla,B,1,Geografía,Es CDMX",
    "El agua hierve a 100 °C,Verdadero/Falso,,,,,Verdadero,1,Ciencias,",
    "Mala,,A,B,,,Z,,,",
]) + "\n"


class TestPantallas:
    def test_formulario_y_plantilla(self, professor_client):
        assert professor_client.get(reverse("quizzes:import")).status_code == 200
        respuesta = professor_client.get(reverse("quizzes:import_template"))
        assert respuesta["Content-Type"].startswith("text/csv") and respuesta.content.startswith("﻿".encode("utf-8"))
        cabecera = respuesta.content.decode("utf-8-sig").splitlines()[0]
        assert cabecera.startswith("Pregunta,Tipo,Opción A")

    def test_la_plantilla_descargada_se_importa_sin_errores(self, professor_client, org):
        contenido = professor_client.get(reverse("quizzes:import_template")).content
        headers, rows = read_table("plantilla.csv", contenido)
        plan = qi.analyze(org, headers, rows)
        assert plan.count_error == 0 and plan.count_new == 2

    def test_subir_lleva_a_la_vista_previa(self, professor_client):
        assert subir(professor_client, ARCHIVO).url == reverse("quizzes:import_preview")

    @pytest.mark.parametrize("nombre, contenido, fragmento", [
        ("p.pdf", b"x", "Formato no admitido"), ("p.csv", b"", "vacío"), ("p.xlsx", b"basura", "No se pudo abrir"),
    ])
    def test_archivos_invalidos(self, professor_client, nombre, contenido, fragmento):
        response = subir(professor_client, contenido, nombre)
        assert response.status_code == 200 and fragmento in response.context["error"]

    def test_sin_archivo(self, professor_client):
        assert "Elige un archivo" in professor_client.post(reverse("quizzes:import"), {}).context["error"]

    def test_la_vista_previa_resume_y_no_escribe(self, professor_client):
        subir(professor_client, ARCHIVO)
        response = professor_client.get(reverse("quizzes:import_preview"))
        plan = response.context["plan"]
        assert (plan.count_new, plan.count_duplicate, plan.count_error) == (2, 0, 1) and response.context["can_confirm"]
        assert not Question.objects.exists()
        html = response.content.decode()
        assert "Capital de México" in html and "no coincide" in html

    def test_confirmar_crea_las_preguntas(self, professor_client, professor):
        subir(professor_client, ARCHIVO)
        response = professor_client.post(reverse("quizzes:import_preview"), follow=True)
        assert Question.objects.count() == 2 and response.redirect_chain[-1][0] == reverse("quizzes:bank")
        mensaje = [str(m) for m in response.context["messages"]][0]
        assert "2 preguntas nuevas" in mensaje and "1 filas con errores" in mensaje
        assert "question_import" not in professor_client.session

    def test_resubir_avisa_que_ya_existen(self, professor_client):
        subir(professor_client, ARCHIVO)
        professor_client.post(reverse("quizzes:import_preview"))
        subir(professor_client, ARCHIVO)
        response = professor_client.get(reverse("quizzes:import_preview"))
        assert response.context["plan"].count_duplicate == 2 and response.context["plan"].count_new == 0
        assert not response.context["can_confirm"]
        mensaje = [str(m) for m in professor_client.post(reverse("quizzes:import_preview"), follow=True).context["messages"]][0]
        assert "0 preguntas nuevas" in mensaje and "ya estaban en el banco" in mensaje
        assert Question.objects.count() == 2

    def test_encabezados_incorrectos(self, professor_client):
        subir(professor_client, "Algo,Otra cosa\nx,y\n")
        response = professor_client.get(reverse("quizzes:import_preview"))
        assert response.context["plan"].header_errors and "No encontré la columna" in response.content.decode()
        professor_client.post(reverse("quizzes:import_preview"))
        assert not Question.objects.exists()

    def test_sin_archivo_previo(self, professor_client):
        assert professor_client.get(reverse("quizzes:import_preview")).url == reverse("quizzes:import")
        assert professor_client.post(reverse("quizzes:import_preview")).url == reverse("quizzes:import")

    def test_las_preguntas_quedan_en_la_organizacion_activa_del_docente(self, professor_client, org):
        subir(professor_client, ARCHIVO)
        professor_client.post(reverse("quizzes:import_preview"))
        assert {q.organization_id for q in Question.objects.all()} == {org.pk}

    def test_el_alumno_no_importa(self, student_client, enrollment):
        for url in ("quizzes:import", "quizzes:import_preview", "quizzes:import_template"):
            assert student_client.get(reverse(url)).status_code == 302
        assert student_client.post(reverse("quizzes:import"), {}).status_code == 302

    def test_anonimo_va_al_login(self, client):
        assert client.get(reverse("quizzes:import")).url.startswith("/login/")

    def test_el_banco_ofrece_el_boton(self, professor_client):
        assert reverse("quizzes:import") in professor_client.get(reverse("quizzes:bank")).content.decode()
