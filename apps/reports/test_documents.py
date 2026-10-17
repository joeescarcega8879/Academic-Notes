"""Datos de la boleta, PDF y concentrado en Excel."""

import datetime
import re
from io import BytesIO

import pytest
from django.utils import timezone
from openpyxl import load_workbook

from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.tests.factories import ActivityFactory
from apps.grades.models import Activity, EvaluationCriterion, EvaluationPeriod
from apps.grades.services.gradebook import grade_activity
from apps.grades.services.gradesheet import build_gradesheet
from apps.grades.services.schemes import ensure_scheme
from apps.grades.services.submissions import submit

from .services import pdf, workbook
from .services.transcript import build_transcripts

pytestmark = pytest.mark.django_db

AHORA = timezone.now()


def inscribir(course, apellido, nombre="Ana", matricula=""):
    return EnrollmentFactory(
        course=course, student__user=None, student__first_name=nombre, student__last_name=apellido,
        student__student_number=matricula,
    ).student


def texto_pdf(contenido):
    """Texto de un PDF sin comprimir (las cadenas de reportlab van entre paréntesis)."""
    return b" ".join(re.findall(rb"\((.*?)\)\s*Tj", contenido)).decode("latin-1")


def paginas(contenido):
    return len(re.findall(rb"/Type /Page\b(?!s)", contenido))


@pytest.fixture
def grupo(course):
    """Un grupo con un examen y dos tareas publicadas, un borrador y dos alumnos."""
    examen = ActivityFactory(course=course, title="Examen 1", type=Activity.Type.EXAM, max_score=10)
    tarea = ActivityFactory(course=course, title="Tarea 1", type=Activity.Type.HOMEWORK, max_score=20, due_at=AHORA - datetime.timedelta(days=1))
    ActivityFactory(course=course, title="Borrador", type=Activity.Type.PROJECT, published=False)
    ana, beto = inscribir(course, "Zapata", "Ana", "00123"), inscribir(course, "Álvarez", "Beto", "00045")
    grade_activity(examen, ana, score=9)
    grade_activity(tarea, ana, score=10)
    grade_activity(examen, beto, score=4)
    return {"examen": examen, "tarea": tarea, "ana": ana, "beto": beto}


# ── Datos de la boleta ────────────────────────────────────────────────

class TestTranscript:
    def test_una_boleta_por_alumno_en_orden_alfabetico(self, course, grupo):
        assert [t.student for t in build_transcripts(course)] == [grupo["beto"], grupo["ana"]]

    def test_encabezado(self, course, grupo, professor):
        boleta = build_transcripts(course)[0]
        assert boleta.course == course and boleta.organization_name == course.organization.name
        assert boleta.professor == professor.get_full_name() and boleta.academic_year == str(course.academic_year)
        assert (boleta.scale_max, boleta.pass_mark) == (10, "6")

    def test_la_final_es_la_de_la_libreta(self, course, grupo):
        hoja = {r.student.pk: r.final for r in build_gradesheet(course).rows}
        for boleta in build_transcripts(course):
            assert boleta.final == hoja[boleta.student.pk]["text"]
            assert boleta.passed is hoja[boleta.student.pk]["passed"]

    def test_desglose_por_criterio_y_actividad(self, course, grupo):
        ana = next(t for t in build_transcripts(course) if t.student == grupo["ana"])
        (periodo,) = ana.periods
        criterios = {c.name: c for c in periodo.criteria}
        assert criterios["Exámenes"].value == "9.00" and criterios["Tareas"].value == "5.00"
        assert [(linea.title, linea.score_text, linea.max_score) for linea in criterios["Exámenes"].lines] == [("Examen 1", "9", "10")]
        assert [(linea.title, linea.score_text, linea.max_score) for linea in criterios["Tareas"].lines] == [("Tarea 1", "10", "20")]
        assert criterios["Proyecto"].value == "" and criterios["Proyecto"].lines == []  # el borrador no aparece

    def test_actividad_sin_calificar(self, course, grupo):
        beto = build_transcripts(course)[0]
        linea = next(linea for c in beto.periods[0].criteria for linea in c.lines if linea.title == "Tarea 1")
        assert (linea.graded, linea.score_text) == (False, "")

    def test_un_borrador_no_cuenta_ni_aparece(self, course, grupo):
        borrador = Activity.objects.get(title="Borrador")
        grade_activity(borrador, grupo["ana"], score=0)
        ana = next(t for t in build_transcripts(course) if t.student == grupo["ana"])
        assert "Borrador" not in [linea.title for linea in ana.criterion_lines()]
        assert ana.final == "7.29"  # (0.9 * 40 + 0.5 * 30) / 70: el 0 del borrador no entra

    def test_penalizacion_visible(self, course):
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - datetime.timedelta(days=1), allow_late=True, late_penalty=20)
        alumno = inscribir(course, "Tarde")
        submit(tarea, alumno, text="x", now=AHORA)
        grade_activity(tarea, alumno, score=10)
        linea = build_transcripts(course)[0].criterion_lines()[0]
        assert (linea.score_text, linea.raw_score) == ("8", 10) and "20" in linea.note

    def test_alumno_sin_calificaciones(self, course, grupo):
        sin = inscribir(course, "Nuevo")
        boleta = next(t for t in build_transcripts(course) if t.student == sin)
        assert (boleta.final, boleta.passed, boleta.status) == ("", None, "Sin calificaciones")

    def test_varios_periodos(self, course, grupo):
        esquema = ensure_scheme(course)
        segundo = EvaluationPeriod.objects.create(scheme=esquema, name="Segundo parcial", weight=50, position=1)
        criterio = EvaluationCriterion.objects.create(period=segundo, name="Final", weight=100, position=0)
        ActivityFactory(course=course, title="Examen final", criterion=criterio)
        boleta = build_transcripts(course)[0]
        assert boleta.multiple_periods and [p.name for p in boleta.periods] == ["Periodo único", "Segundo parcial"]

    def test_solo_los_alumnos_pedidos(self, course, grupo):
        assert [t.student for t in build_transcripts(course, [grupo["ana"]])] == [grupo["ana"]]

    def test_consultas_constantes(self, course, grupo, django_assert_max_num_queries):
        for i in range(10):
            alumno = inscribir(course, f"Extra{i}")
            grade_activity(grupo["examen"], alumno, score=7)
        with django_assert_max_num_queries(14):
            build_transcripts(course)


# ── PDF ───────────────────────────────────────────────────────────────

class TestPdf:
    def test_es_un_pdf(self, course, grupo):
        contenido = pdf.render_transcripts(build_transcripts(course))
        assert contenido.startswith(b"%PDF-") and contenido.rstrip().endswith(b"%%EOF")

    def test_una_pagina_por_alumno(self, course, grupo):
        assert paginas(pdf.render_transcripts(build_transcripts(course), compress=False)) == 2

    def test_contiene_los_datos_del_alumno(self, course, grupo):
        contenido = pdf.render_transcripts(build_transcripts(course, [grupo["ana"]]), compress=False)
        texto = texto_pdf(contenido)
        for esperado in ("Boleta de calificaciones", "00123", "Examen 1", "Tarea 1", "9 / 10", "10 / 20", "Aprobado", "7.29 / 10"):
            assert esperado in texto, esperado
        assert "Borrador" not in texto

    def test_sin_alumnos_igual_genera_un_documento(self, course):
        contenido = pdf.render_transcripts([], compress=False)
        assert contenido.startswith(b"%PDF-") and "no tiene alumnos" in texto_pdf(contenido)

    def test_el_marcado_de_un_nombre_no_rompe_ni_se_interpreta(self, course):
        inscribir(course, "<b>Negrita</b> & <font color='red'>", "<i>Cursiva</i>")
        contenido = pdf.render_transcripts(build_transcripts(course), compress=False)
        assert contenido.startswith(b"%PDF-")
        assert "<b>Negrita</b>" in texto_pdf(contenido).replace(" ", "")  # el marcado sale literal, no en negritas

    def test_caracteres_fuera_de_la_fuente_no_tumban_el_pdf(self, course):
        inscribir(course, "Łukasz 山田", "Zoë ✓")
        assert pdf.render_transcripts(build_transcripts(course)).startswith(b"%PDF-")

    @pytest.mark.parametrize("texto, esperado", [("Peña", "Peña"), ("山", "?"), ("a<b", "a&lt;b"), ("R&D", "R&amp;D")])
    def test_clean(self, texto, esperado):
        assert pdf.clean(texto) == esperado

    def test_alumno_con_muchas_actividades_ocupa_mas_de_una_pagina_sin_romperse(self, course):
        alumno = inscribir(course, "Largo")
        for i in range(70):
            grade_activity(ActivityFactory(course=course, title=f"Actividad {i}"), alumno, score=8)
        assert paginas(pdf.render_transcripts(build_transcripts(course), compress=False)) >= 2


# ── Excel ─────────────────────────────────────────────────────────────

def abrir(contenido):
    return load_workbook(BytesIO(contenido))


class TestWorkbook:
    def test_columnas_por_defecto(self, course, grupo):
        hoja = abrir(workbook.build_workbook(course, list(workbook.DEFAULT_KEYS)))["Concentrado"]
        assert [c.value for c in hoja[1]] == [
            "Matrícula", "Apellidos", "Nombre(s)", "Examen 1 (/10)", "Tarea 1 (/20)", "Calificación final", "Resultado",
        ]
        assert [c.value for c in hoja[2]] == ["00045", "Álvarez", "Beto", 4, None, 4, "No aprobado"]
        assert [c.value for c in hoja[3]] == ["00123", "Zapata", "Ana", 9, 10, 7.29, "Aprobado"]

    def test_la_matricula_es_texto_y_conserva_los_ceros(self, course, grupo):
        celda = abrir(workbook.build_workbook(course, ["student_number"]))["Concentrado"]["A3"]
        assert celda.value == "00123" and celda.data_type == "s" and celda.number_format == "@"

    def test_el_orden_y_la_seleccion_son_los_pedidos(self, course, grupo):
        hoja = abrir(workbook.build_workbook(course, ["final", "last_name", "student_number"]))["Concentrado"]
        assert [c.value for c in hoja[1]] == ["Calificación final", "Apellidos", "Matrícula"]
        assert [c.value for c in hoja[3]] == [7.29, "Zapata", "00123"]

    def test_las_claves_repetidas_o_desconocidas_se_ignoran(self, course, grupo):
        assert workbook.parse_columns(["final", "x", "final", "email", "../etc"]) == ["final", "email"]
        hoja = abrir(workbook.build_workbook(course, ["final", "final", "nada"]))["Concentrado"]
        assert [c.value for c in hoja[1]] == ["Calificación final"]

    def test_sin_columnas_validas_usa_las_de_siempre(self, course, grupo):
        hoja = abrir(workbook.build_workbook(course, ["nada"]))["Concentrado"]
        assert hoja["A1"].value == "Matrícula"

    def test_las_calificaciones_son_numeros(self, course, grupo):
        hoja = abrir(workbook.build_workbook(course, ["activities", "final"]))["Concentrado"]
        assert isinstance(hoja["A3"].value, (int, float)) and isinstance(hoja["C3"].value, (int, float))
        assert hoja["C3"].number_format == "0.00"

    def test_promedio_por_criterio(self, course, grupo):
        hoja = abrir(workbook.build_workbook(course, ["criteria"]))["Concentrado"]
        assert [c.value for c in hoja[1]] == ["Exámenes (40 %)", "Tareas (30 %)", "Proyecto (20 %)", "Quizzes (10 %)"]
        assert [c.value for c in hoja[3]] == [9, 5, None, None]

    def test_con_varios_periodos_el_encabezado_dice_el_periodo(self, course, grupo):
        esquema = ensure_scheme(course)
        segundo = EvaluationPeriod.objects.create(scheme=esquema, name="Segundo", weight=50, position=1)
        EvaluationCriterion.objects.create(period=segundo, name="Final", weight=100, position=0)
        encabezados = [c.value for c in abrir(workbook.build_workbook(course, ["criteria"]))["Concentrado"][1]]
        assert "Periodo único · Exámenes (40 %)" in encabezados and "Segundo · Final (100 %)" in encabezados

    def test_un_nombre_que_parece_formula_no_se_ejecuta(self, course):
        inscribir(course, "=HYPERLINK(\"http://x\")", "+cmd|' /C calc'!A0", "@SUM(1)")
        hoja = abrir(workbook.build_workbook(course, ["student_number", "last_name", "first_name"]))["Concentrado"]
        assert hoja["B2"].value == "=HYPERLINK(\"http://x\")" and hoja["B2"].data_type == "s"
        assert hoja["C2"].value.startswith("+cmd") and hoja["C2"].data_type == "s"
        assert hoja["A2"].data_type == "s"

    def test_hoja_de_resumen(self, course, grupo):
        resumen = abrir(workbook.build_workbook(course, list(workbook.DEFAULT_KEYS)))["Resumen"]
        datos = {fila[0].value: fila[1].value for fila in resumen.iter_rows()}
        assert datos["Alumnos inscritos"] == 2 and datos["Aprobados"] == 1 and datos["No aprobados"] == 1
        assert datos["Promedio del grupo"] == "5.65" and datos["Mínimo aprobatorio"] == "6"
        assert course.name in datos["Grupo"]

    def test_grupo_vacio(self, course):
        libro = abrir(workbook.build_workbook(course, list(workbook.DEFAULT_KEYS)))
        assert libro["Concentrado"].max_row == 1 and libro.sheetnames == ["Concentrado", "Resumen"]

    def test_las_columnas_de_identidad_quedan_fijas(self, course, grupo):
        assert abrir(workbook.build_workbook(course, ["student_number", "last_name", "final"]))["Concentrado"].freeze_panes == "C2"
        assert abrir(workbook.build_workbook(course, ["final", "last_name"]))["Concentrado"].freeze_panes == "A2"
