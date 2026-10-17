"""Importación de listas: lectura de CSV/Excel, mapeo, análisis y aplicación."""

import io

import pytest
from openpyxl import Workbook

from apps.courses.tests.factories import EnrollmentFactory, StudentRecordFactory
from apps.courses.models import Enrollment, Student
from apps.courses.services.importing import (
    ImportFileError, analyze, apply_import, detect_mapping, read_table, validate_mapping,
)

pytestmark = pytest.mark.django_db

CSV = "Matrícula,Nombre,Apellidos,Correo\n00123,Ana,Pérez,ana@x.test\n00124,Luis,Mora,\n"


def csv_bytes(text, encoding="utf-8"):
    return text.encode(encoding)


def xlsx_bytes(rows, formats=None):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    for (coordinate, number_format) in (formats or {}).items():
        sheet[coordinate].number_format = number_format
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def plan_for(course, text):
    headers, rows = read_table("lista.csv", csv_bytes(text))
    return analyze(course, rows, detect_mapping(headers))


# ── Lectura ───────────────────────────────────────────────────────────

class TestLectura:
    def test_csv_utf8_con_bom(self):
        headers, rows = read_table("l.csv", ("﻿" + CSV).encode("utf-8"))
        assert headers == ["Matrícula", "Nombre", "Apellidos", "Correo"]
        assert rows[0] == ["00123", "Ana", "Pérez", "ana@x.test"]

    def test_csv_de_excel_en_windows_1252_con_punto_y_coma(self):
        texto = "Matrícula;Nombre;Apellidos\n001;José;Peña\n"
        headers, rows = read_table("l.csv", csv_bytes(texto, "cp1252"))
        assert rows == [["001", "José", "Peña"]]

    def test_la_matricula_csv_conserva_los_ceros(self):
        _, rows = read_table("l.csv", csv_bytes(CSV))
        assert rows[0][0] == "00123"

    def test_xlsx_con_celdas_de_texto(self):
        data = xlsx_bytes([["Matrícula", "Nombre"], ["00123", "Ana"]])
        assert read_table("l.xlsx", data) == (["Matrícula", "Nombre"], [["00123", "Ana"]])

    def test_xlsx_con_numero_entero_y_formato_de_ceros(self):
        data = xlsx_bytes([["Matrícula", "Nombre"], [123, "Ana"]], formats={"A2": "00000"})
        assert read_table("l.xlsx", data)[1][0][0] == "00123"

    def test_xlsx_con_numero_sin_formato_no_inventa_decimales(self):
        data = xlsx_bytes([["Matrícula", "Nombre"], [20240001.0, "Ana"], [2024.5, "Luis"]])
        assert [r[0] for r in read_table("l.xlsx", data)[1]] == ["20240001", "2024.5"]

    def test_ignora_filas_vacias_y_rellena_las_cortas(self):
        headers, rows = read_table("l.csv", csv_bytes("A,B,C\n1,2\n,,\n\n3,4,5\n"))
        assert rows == [["1", "2", ""], ["3", "4", "5"]]

    def test_encabezados_vacios_reciben_nombre(self):
        headers, _ = read_table("l.csv", csv_bytes("A,,C\n1,2,3\n"))
        assert headers == ["A", "Columna 2", "C"]

    @pytest.mark.parametrize("nombre, datos, mensaje", [
        ("l.csv", b"", "vacío"),
        ("l.csv", b"Nombre\n", "solo tiene encabezados"),
        ("l.xls", b"x", ".xls antiguo"),
        ("l.pdf", b"x", "Formato no admitido"),
        ("l.xlsx", b"no es un zip", "No se pudo abrir"),
        ("l.xlsx", b"PK\x03\x04truncado", "No se pudo abrir"),
    ])
    def test_archivos_no_utilizables(self, nombre, datos, mensaje):
        with pytest.raises(ImportFileError, match=mensaje):
            read_table(nombre, datos)

    def test_rechaza_archivos_grandes(self):
        with pytest.raises(ImportFileError, match="2 MB"):
            read_table("l.csv", b"a," * (1024 * 1024 + 1))

    def test_rechaza_demasiadas_filas(self):
        filas = "\n".join(f"{n},Alumno" for n in range(2001))
        with pytest.raises(ImportFileError, match="2000"):
            read_table("l.csv", csv_bytes("Matrícula,Nombre\n" + filas))


# ── Mapeo ─────────────────────────────────────────────────────────────

class TestMapeo:
    def test_reconoce_encabezados_comunes(self):
        mapeo = detect_mapping(["No. de control", "Nombre(s)", "Apellido paterno", "Correo electrónico"])
        assert mapeo == {"student_number": 0, "first_name": 1, "last_name": 2, "email": 3}

    def test_ignora_acentos_y_mayusculas(self):
        assert detect_mapping(["MATRÍCULA", "NOMBRES"])["student_number"] == 0

    def test_columnas_desconocidas_quedan_sin_asignar(self):
        assert detect_mapping(["Grado", "Grupo"]) == {k: None for k in ("student_number", "first_name", "last_name", "email")}

    def test_valida_el_mapeo(self):
        assert validate_mapping({"first_name": 0, "last_name": 1}, 2) == []
        assert validate_mapping({"first_name": None}, 2)
        assert validate_mapping({"first_name": 0, "last_name": 0}, 2)
        assert validate_mapping({"first_name": 5}, 2)


# ── Análisis ──────────────────────────────────────────────────────────

class TestAnalisis:
    def test_lista_nueva_crea_a_todos(self, course):
        plan = plan_for(course, CSV)
        assert [r.action for r in plan.rows] == ["create", "create"]
        assert plan.to_enroll == 2

    def test_reimportar_la_misma_lista_no_duplica(self, course):
        apply_import(course, plan_for(course, CSV))
        plan = plan_for(course, CSV)
        assert [r.action for r in plan.rows] == ["unchanged", "unchanged"]
        assert [r.match for r in plan.rows] == ["matrícula", "matrícula"]
        assert plan.to_enroll == 0
        apply_import(course, plan)
        assert Student.objects.count() == 2 and Enrollment.objects.count() == 2

    def test_actualiza_los_datos_que_cambian_por_matricula(self, course):
        apply_import(course, plan_for(course, CSV))
        plan = plan_for(course, "Matrícula,Nombre,Apellidos,Correo\n00123,Ana María,Pérez,nuevo@x.test\n")
        fila = plan.rows[0]
        assert fila.action == "update" and set(fila.changes) == {"first_name", "email"}
        apply_import(course, plan)
        ana = Student.objects.get(student_number="00123")
        assert (ana.first_name, ana.email) == ("Ana María", "nuevo@x.test")

    def test_un_dato_vacio_no_borra_el_existente(self, course):
        apply_import(course, plan_for(course, CSV))
        plan = plan_for(course, "Matrícula,Nombre,Apellidos,Correo\n00123,Ana,,\n")
        assert plan.rows[0].action == "unchanged"
        apply_import(course, plan)
        assert Student.objects.get(student_number="00123").email == "ana@x.test"

    def test_alumno_existente_de_la_organizacion_se_inscribe_sin_duplicarse(self, course):
        existente = StudentRecordFactory(organization=course.organization, student_number="00123", first_name="Ana")
        plan = plan_for(course, CSV)
        assert plan.rows[0].student == existente and plan.rows[0].enroll
        apply_import(course, plan)
        assert Student.objects.filter(student_number="00123").count() == 1
        assert existente.enrollments.filter(course=course).exists()

    def test_la_misma_matricula_en_otra_organizacion_es_otro_alumno(self, course):
        StudentRecordFactory(student_number="00123")  # otra organización
        plan = plan_for(course, CSV)
        assert plan.rows[0].action == "create" and plan.rows[0].student is None

    def test_sin_matricula_busca_por_correo(self, course):
        existente = StudentRecordFactory(organization=course.organization, email="ana@x.test", user=None)
        plan = plan_for(course, "Nombre,Correo\nAna Otra,ana@x.test\n")
        assert plan.rows[0].student == existente and plan.rows[0].match == "correo"

    def test_con_matricula_nueva_y_correo_conocido_adopta_la_matricula(self, course):
        existente = StudentRecordFactory(organization=course.organization, email="ana@x.test", student_number="", user=None)
        plan = plan_for(course, "Matrícula,Nombre,Correo\n00999,Ana,ana@x.test\n")
        assert plan.rows[0].student == existente and "student_number" in plan.rows[0].changes
        apply_import(course, plan)
        existente.refresh_from_db()
        assert existente.student_number == "00999"

    def test_correo_de_alguien_con_otra_matricula_es_conflicto(self, course):
        StudentRecordFactory(organization=course.organization, email="ana@x.test", student_number="00001", user=None)
        plan = plan_for(course, "Matrícula,Nombre,Correo\n00999,Ana,ana@x.test\n")
        assert plan.rows[0].action == "error" and "00001" in plan.rows[0].errors[0]

    def test_sin_matricula_ni_correo_busca_por_nombre_entre_los_inscritos(self, course):
        inscrito = EnrollmentFactory(
            course=course, student=StudentRecordFactory(organization=course.organization, first_name="Ana", last_name="Pérez", user=None),
        ).student
        plan = plan_for(course, "Nombre,Apellidos\nana,PEREZ\n")
        assert plan.rows[0].student == inscrito and plan.rows[0].match == "nombre"
        assert not plan.rows[0].enroll

    def test_el_nombre_solo_se_busca_entre_los_inscritos_del_grupo(self, course):
        StudentRecordFactory(organization=course.organization, first_name="Ana", last_name="Pérez", user=None)
        plan = plan_for(course, "Nombre,Apellidos\nAna,Pérez\n")
        assert plan.rows[0].action == "create"

    def test_nombre_ambiguo_es_error(self, course):
        for _ in range(2):
            EnrollmentFactory(
                course=course, student=StudentRecordFactory(organization=course.organization, first_name="Ana", last_name="Pérez", user=None),
            )
        plan = plan_for(course, "Nombre,Apellidos\nAna,Pérez\n")
        assert plan.rows[0].action == "error"

    def test_con_matricula_nueva_adopta_al_inscrito_sin_matricula_del_mismo_nombre(self, course):
        inscrito = EnrollmentFactory(
            course=course, student=StudentRecordFactory(organization=course.organization, first_name="Ana", last_name="Pérez", student_number="", user=None),
        ).student
        plan = plan_for(course, "Matrícula,Nombre,Apellidos\n00777,Ana,Pérez\n")
        assert plan.rows[0].student == inscrito and plan.rows[0].match == "nombre"

    @pytest.mark.parametrize("texto, fragmento", [
        ("Matrícula,Nombre\n1,\n", "Falta el nombre"),
        ("Matrícula,Nombre,Correo\n1,Ana,no-es-correo\n", "correo no es válido"),
        ("Matrícula,Nombre\n1.23E+11,Ana\n", "notación científica"),
        ("Matrícula,Nombre\n" + "9" * 31 + ",Ana\n", "demasiado larga"),
        ("Matrícula,Nombre\n1,Ana\n1,Luis\n", "ya aparece en la fila 2"),
    ])
    def test_filas_con_errores(self, course, texto, fragmento):
        plan = plan_for(course, texto)
        errores = [e for fila in plan.rows for e in fila.errors]
        assert any(fragmento in e for e in errores), errores

    def test_dos_filas_para_el_mismo_alumno_es_error(self, course):
        StudentRecordFactory(organization=course.organization, email="ana@x.test", user=None)
        plan = plan_for(course, "Nombre,Correo\nAna,ana@x.test\nAna B,ana@x.test\n")
        assert [r.action for r in plan.rows] == ["update", "error"]
        assert "otra fila" in plan.rows[1].errors[0]

    def test_el_analisis_no_escribe_en_la_base(self, course):
        plan_for(course, CSV)
        assert Student.objects.count() == 0 and Enrollment.objects.count() == 0


# ── Aplicación ────────────────────────────────────────────────────────

class TestAplicacion:
    def test_resumen_y_datos(self, course):
        resumen = apply_import(course, plan_for(course, CSV))
        assert resumen == {"created": 2, "updated": 0, "enrolled": 2, "skipped": 0}
        ana = Student.objects.get(student_number="00123")
        assert (ana.organization, ana.first_name, ana.last_name, ana.email, ana.user) == (
            course.organization, "Ana", "Pérez", "ana@x.test", None,
        )
        assert ana.enrollments.get().course == course

    def test_omite_las_filas_con_error_y_aplica_el_resto(self, course):
        resumen = apply_import(course, plan_for(course, "Matrícula,Nombre\n1,Ana\n2,\n3,Luis\n"))
        assert resumen["created"] == 2 and resumen["skipped"] == 1
        assert set(Student.objects.values_list("student_number", flat=True)) == {"1", "3"}

    def test_es_atomica(self, course, monkeypatch):
        plan = plan_for(course, CSV)
        original = Enrollment.objects.create
        llamadas = []

        def falla_en_la_segunda(**kwargs):
            llamadas.append(1)
            if len(llamadas) == 2:
                raise RuntimeError("boom")
            return original(**kwargs)

        monkeypatch.setattr(Enrollment.objects, "create", falla_en_la_segunda)
        with pytest.raises(RuntimeError):
            apply_import(course, plan)
        assert Student.objects.count() == 0 and Enrollment.objects.count() == 0

    def test_no_inscribe_en_un_grupo_archivado(self, course):
        from django.core.exceptions import ValidationError

        from apps.courses.services.courses import archive_course

        plan = plan_for(course, CSV)
        archive_course(course)
        with pytest.raises(ValidationError):
            apply_import(course, plan)
        assert Student.objects.count() == 0

    def test_la_matricula_se_guarda_como_texto_con_ceros(self, course):
        apply_import(course, plan_for(course, CSV))
        assert Student.objects.get(first_name="Ana").student_number == "00123"
