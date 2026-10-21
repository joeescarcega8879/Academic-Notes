"""Ajustes de interfaz: botones de acción del mismo tamaño, barra lateral contraíble y libreta con más aire."""

from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse

from apps.quizzes.tests.factories import QuestionFactory, make_quiz

pytestmark = pytest.mark.django_db


def pagina(client, nombre, *args):
    return client.get(reverse(nombre, args=args)).content.decode()


class TestBarraLateral:
    def test_el_docente_tiene_el_boton_de_contraer_y_las_etiquetas_envueltas(self, professor_client):
        html = pagina(professor_client, "professor_dashboard")
        assert 'id="sidebar-collapse"' in html and 'aria-expanded="true"' in html
        for etiqueta in ("Mis grupos", "Calificaciones", "Mensajes", "Banco de preguntas", "Ciclos escolares", "Perfil", "Ajustes", "Ayuda", "Cerrar sesión"):
            assert f'<span class="nav-label">{etiqueta}</span>' in html, etiqueta

    def test_el_alumno_tambien(self, student_client, enrollment):
        html = pagina(student_client, "student_dashboard")
        assert 'id="sidebar-collapse"' in html
        for etiqueta in ("Mis grupos", "Mis Calificaciones", "Unirme a un grupo"):
            assert f'<span class="nav-label">{etiqueta}</span>' in html, etiqueta

    def test_la_preferencia_se_aplica_antes_del_primer_pintado(self, professor_client):
        html = pagina(professor_client, "professor_dashboard")
        cabecera = html.split("</head>")[0]
        assert "gl-sidebar" in cabecera and "sidebar-collapsed" in cabecera

    def test_el_script_y_los_estilos_traen_la_logica(self):
        css = Path(finders.find("css/gradelink.css")).read_text(encoding="utf-8")
        js = Path(finders.find("js/app.js")).read_text(encoding="utf-8")
        assert "html.sidebar-collapsed .app" in css and "min-width: 981px" in css
        assert "setupSidebarCollapse" in js and "gl-sidebar" in js

    def test_en_celular_el_boton_de_contraer_se_oculta(self):
        css = Path(finders.find("css/gradelink.css")).read_text(encoding="utf-8")
        assert ".sidebar-collapse { display: none !important; }" in css


class TestBotonesDeAccion:
    def test_las_filas_de_calificaciones_usan_el_mismo_contenedor(self, professor_client, course, enrollment, activity):
        from apps.grades.tests.factories import GradeFactory

        GradeFactory(activity=activity, student=enrollment.student)
        html = pagina(professor_client, "grades:list")
        assert '<div class="row-actions">' in html and "btn-sm" not in html.split("<tbody>")[1]

    def test_los_alumnos_del_grupo_llevan_editar_y_quitar_en_una_cuadricula(self, professor_client, course, enrollment):
        html = pagina(professor_client, "course_detail", course.pk)
        fila = html.split('class="row-actions row-actions-grid"')[1].split("</td>")[0]
        for texto in ("Boleta", "Editar", "Quitar"):
            assert texto in fila, texto
        assert 'class="col-actions"' in html and "Acciones" in html

    def test_un_grupo_archivado_no_muestra_acciones_de_alumnos(self, professor_client, course, enrollment):
        from apps.courses.models import Course

        Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)
        assert "row-actions-grid" not in pagina(professor_client, "course_detail", course.pk)

    def test_las_barras_de_acciones_de_la_pagina_usan_btn_action(self, professor_client, course, activity):
        grupo = pagina(professor_client, "course_detail", course.pk)
        actividad = pagina(professor_client, "grades:activity_detail", activity.pk)
        assert 'btn btn-ghost btn-action" href' in grupo and ">Archivar</button>" in grupo
        assert actividad.count("btn-action") == 2  # Editar y Eliminar

    def test_el_detalle_de_pregunta(self, professor_client, professor):
        pregunta = QuestionFactory(author=professor)
        html = pagina(professor_client, "quizzes:question_detail", pregunta.pk)
        assert html.count("btn-action") == 4  # Duplicar, Editar, Archivar y Eliminar

    def test_quitar_una_pregunta_del_quiz_y_sus_flechas(self, professor_client, course):
        quiz = make_quiz(course, questions=2)
        html = pagina(professor_client, "quizzes:builder", quiz.activity_id)
        assert 'class="row-actions"' in html and html.count("btn-square") == 4  # ↑ y ↓ de cada una

    def test_los_estilos_dan_el_mismo_tamano_a_los_botones_de_fila(self):
        css = Path(finders.find("css/gradelink.css")).read_text(encoding="utf-8")
        assert ".row-actions .btn { height: 34px; min-width: 104px;" in css
        assert ".row-actions-grid { display: grid; grid-template-columns: repeat(2, 100px);" in css


class TestLibretaConMasAire:
    def test_las_celdas_y_los_encabezados_tienen_mas_espacio(self):
        css = Path(finders.find("css/gradelink.css")).read_text(encoding="utf-8")
        assert "--gs-h: 56px" in css and "min-width: 120px; vertical-align: top" in css
        assert "top: var(--gs-h)" in css and "calc(var(--gs-h) * 2)" in css  # los encabezados fijos siguen alineados
        assert "table.gs tbody tr:hover > td" in css  # la fila bajo el cursor se resalta

    def test_la_columna_fija_del_final_sigue_pegada_al_nombre(self):
        css = Path(finders.find("css/gradelink.css")).read_text(encoding="utf-8")
        assert "min-width: 236px; max-width: 236px" in css and "left: 236px" in css

    def test_la_libreta_abre(self, professor_client, course, enrollment, activity):
        assert professor_client.get(reverse("grades:gradesheet", args=[course.pk])).status_code == 200
