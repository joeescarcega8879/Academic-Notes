"""Navegación: flecha de regreso, pestañas del grupo, acciones agrupadas por tipo, filtros automáticos y aviso de «sin entrega»."""

from pathlib import Path

import pytest
from django.contrib.staticfiles import finders
from django.urls import reverse
from django.utils import timezone

from apps.courses.models import Course
from apps.grades.models import Activity, Submission
from apps.grades.tests.factories import ActivityFactory

pytestmark = pytest.mark.django_db


def pagina(client, nombre, *args):
    respuesta = client.get(reverse(nombre, args=args))
    assert respuesta.status_code == 200, nombre
    return respuesta.content.decode()


def flecha(html):
    """Destino y rótulo de la flecha de regreso de la barra superior."""
    assert html.count('class="icon-btn back-btn"') == 1
    etiqueta = html.split('class="icon-btn back-btn" href="')[1].split('"')
    return etiqueta[0], html.split('class="icon-btn back-btn"')[1].split('aria-label="')[1].split('"')[0]


# ── Flecha de regreso ─────────────────────────────────────────────────

class TestFlechaDeRegreso:
    def test_el_grupo_regresa_a_mis_grupos(self, professor_client, course):
        assert flecha(pagina(professor_client, 'course_detail', course.pk)) == (reverse('professor_dashboard'), 'Volver a mis grupos')

    def test_el_alumno_regresa_a_sus_calificaciones(self, student_client, course, enrollment):
        assert flecha(pagina(student_client, 'course_detail', course.pk))[0] == reverse('student_dashboard')

    @pytest.mark.parametrize('nombre', [
        'grades:gradesheet', 'grades:scheme', 'reports:risk', 'reports:workbook', 'syllabus:index',
        'student_add', 'student_import', 'course_clone', 'grades:activity_create',
    ])
    def test_las_pantallas_del_grupo_regresan_al_grupo(self, professor_client, course, nombre):
        assert flecha(pagina(professor_client, nombre, course.pk)) == (course.get_absolute_url(), 'Volver al grupo')

    @pytest.mark.parametrize('nombre', ['grades:activity_grading', 'grades:activity_history', 'grades:activity_update'])
    def test_las_pantallas_de_la_actividad_regresan_a_la_actividad(self, professor_client, activity, nombre):
        assert flecha(pagina(professor_client, nombre, activity.pk))[0] == activity.get_absolute_url()

    def test_la_actividad_regresa_al_grupo(self, professor_client, activity):
        assert flecha(pagina(professor_client, 'grades:activity_detail', activity.pk))[0] == activity.course.get_absolute_url()

    def test_crear_o_editar_un_grupo(self, professor_client, course):
        assert flecha(pagina(professor_client, 'course_create'))[0] == reverse('professor_dashboard')
        assert flecha(pagina(professor_client, 'course_update', course.pk))[0] == course.get_absolute_url()

    def test_ya_no_quedan_botones_de_volver_en_la_barra(self, professor_client, course, activity):
        for nombre, argumento in (('grades:gradesheet', course.pk), ('reports:risk', course.pk), ('syllabus:index', course.pk),
                                  ('grades:activity_grading', activity.pk)):
            barra = pagina(professor_client, nombre, argumento).split('</header>')[0]
            assert '>Volver' not in barra, nombre

    def test_las_pantallas_principales_no_la_llevan(self, professor_client):
        for nombre in ('professor_dashboard', 'grades:list', 'quizzes:bank', 'academic_years'):
            assert 'back-btn' not in pagina(professor_client, nombre), nombre


# ── Pestañas del grupo ────────────────────────────────────────────────

class TestPestanasDelGrupo:
    def test_el_resumen_y_el_temario_son_pestanas(self, professor_client, course):
        resumen = pagina(professor_client, 'course_detail', course.pk)
        assert 'class="tab is-active" href="%s" aria-current="page">Resumen' % course.get_absolute_url() in resumen
        assert 'class="tab" href="%s">Temario' % reverse('syllabus:index', args=[course.pk]) in resumen
        temario = pagina(professor_client, 'syllabus:index', course.pk)
        assert 'class="tab is-active" href="%s" aria-current="page">Temario' % reverse('syllabus:index', args=[course.pk]) in temario
        assert 'class="tab" href="%s">Resumen' % course.get_absolute_url() in temario

    def test_el_temario_ya_no_es_un_boton_del_grupo(self, professor_client, course):
        html = pagina(professor_client, 'course_detail', course.pk)
        assert 'btn btn-ghost" href="%s">Temario' % reverse('syllabus:index', args=[course.pk]) not in html

    def test_un_grupo_archivado_no_muestra_pestanas(self, professor_client, course):
        Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)
        assert 'class="tabs"' not in pagina(professor_client, 'course_detail', course.pk)

    def test_el_alumno_no_las_ve(self, student_client, course, enrollment):
        html = pagina(student_client, 'course_detail', course.pk)
        assert 'class="tabs"' not in html and 'Temario' not in html


# ── Acciones agrupadas por tipo ───────────────────────────────────────

class TestAccionesPorTipo:
    def test_el_grupo_las_clasifica(self, professor_client, course):
        html = pagina(professor_client, 'course_detail', course.pk)
        for rotulo in ('Calificar', 'Reportes', 'Grupo'):
            assert f'<span class="cluster-label">{rotulo}</span>' in html, rotulo
        reportes = html.split('<span class="cluster-label">Reportes</span>')[1].split('<div class="cluster end">')[0]
        for texto in ('Alumnos en riesgo', 'Concentrado Excel', 'Boletas PDF'):
            assert texto in reportes
        grupo = html.split('<div class="cluster end">')[1].split('</div>\n      </div>')[0]
        assert 'btn-danger-ghost">Archivar' in grupo and 'Duplicar para nuevo ciclo' in grupo and 'Editar' in grupo

    def test_un_grupo_archivado_ofrece_desarchivar_y_no_el_esquema(self, professor_client, course):
        Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)
        html = pagina(professor_client, 'course_detail', course.pk)
        assert 'Desarchivar' in html and 'Esquema de evaluación' not in html and '>Archivar<' not in html

    def test_la_actividad_tiene_un_solo_boton_principal(self, professor_client, activity):
        html = pagina(professor_client, 'grades:activity_detail', activity.pk)
        assert html.split('<main')[1].split('</main>')[0].count('btn btn-primary') == 1 and 'btn btn-primary" href="%s">Calificar' % reverse('grades:activity_grading', args=[activity.pk]) in html
        for rotulo in ('Actividad', 'Seguimiento', 'Peligro'):
            assert f'<span class="cluster-label">{rotulo}</span>' in html, rotulo
        assert 'btn-danger-ghost">Eliminar' in html.split('<span class="cluster-label">Peligro</span>')[1]
        assert 'Pasar a borrador' in html.split('class="clusters"')[0]  # el estado y su cambio van junto al título

    def test_un_quiz_suma_armar_y_resultados(self, professor_client, course):
        quiz = ActivityFactory(course=course, type=Activity.Type.QUIZ)
        html = pagina(professor_client, 'grades:activity_detail', quiz.pk)
        assert 'Armar quiz' in html.split('<span class="cluster-label">Seguimiento</span>')[0]
        assert '>Resultados<' in html.split('<span class="cluster-label">Seguimiento</span>')[1]

    def test_un_grupo_archivado_solo_deja_el_seguimiento(self, professor_client, course, activity):
        Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)
        html = pagina(professor_client, 'grades:activity_detail', activity.pk)
        assert 'Seguimiento' in html and 'Peligro' not in html and 'Editar' not in html and '>Calificar<' not in html

    def test_el_alumno_no_ve_acciones_de_docente(self, student_client, activity, enrollment):
        html = pagina(student_client, 'grades:activity_detail', activity.pk)
        assert 'class="clusters"' not in html


# ── Calificar: alumnos sin entrega ────────────────────────────────────

class TestCalificarSinEntrega:
    @pytest.fixture
    def tarea(self, course):
        return ActivityFactory(course=course, type=Activity.Type.HOMEWORK)

    def test_marca_a_quien_no_entrego_y_pide_confirmar(self, professor_client, tarea, enrollment):
        html = pagina(professor_client, 'grades:activity_grading', tarea.pk)
        fila = html.split('<tbody>')[1].split('</tr>')[0]
        assert 'row-sin-entrega' in fila and 'data-sin-entrega' in fila and 'chip warn">Sin entrega' in fila
        assert 'te pediremos confirmar al guardar' in html.split('<tbody>')[0]
        assert "getElementById('form-calificar')" in html and 'confirm(' in html.split("getElementById('form-calificar')")[1]

    def test_quien_si_entrego_no_se_marca(self, professor_client, tarea, enrollment):
        Submission.objects.create(activity=tarea, student=enrollment.student, text='Listo', submitted_at=timezone.now())
        fila = pagina(professor_client, 'grades:activity_grading', tarea.pk).split('<tbody>')[1].split('</tr>')[0]
        assert 'row-sin-entrega' not in fila and 'Ver entrega' in fila

    def test_un_examen_no_tiene_entregas_y_no_marca_a_nadie(self, professor_client, activity, enrollment):
        html = pagina(professor_client, 'grades:activity_grading', activity.pk)
        assert 'row-sin-entrega' not in html.split('<tbody>')[1] and 'Sin entrega' not in html and 'te pediremos confirmar' not in html

    def test_guardar_sigue_permitido_aunque_no_haya_entrega(self, professor_client, tarea, enrollment):
        respuesta = professor_client.post(
            reverse('grades:activity_grading', args=[tarea.pk]), {f'score_{enrollment.student.pk}': '8', f'feedback_{enrollment.student.pk}': ''},
        )
        assert respuesta.status_code == 302
        assert tarea.grades.get().raw_score == 8


# ── Calificaciones: filtros automáticos ───────────────────────────────

class TestFiltrosAutomaticos:
    def test_ya_no_hay_boton_filtrar_visible(self, professor_client):
        html = pagina(professor_client, 'grades:list')
        assert 'class="btn btn-primary">Filtrar' not in html.replace('<noscript><button type="submit" class="btn btn-primary">Filtrar', '')
        assert '<noscript><button type="submit" class="btn btn-primary">Filtrar</button></noscript>' in html  # respaldo sin JavaScript
        assert 'class="sr-only" tabindex="-1">Filtrar' in html  # Enter en la búsqueda sigue enviando

    def test_cada_cambio_envia_el_formulario(self, professor_client):
        html = pagina(professor_client, 'grades:list')
        assert "addEventListener('change'" in html and 'requestSubmit()' in html

    def test_la_casilla_de_archivados_va_alineada(self, professor_client):
        html = pagina(professor_client, 'grades:list')
        assert '<label class="filter-check">' in html and 'Incluir grupos archivados' in html
        css = Path(finders.find('css/gradelink.css')).read_text(encoding='utf-8')
        assert '.filter-check { display: flex; align-items: center;' in css

    def test_limpiar_solo_aparece_con_filtros(self, professor_client):
        assert 'Limpiar' not in pagina(professor_client, 'grades:list')
        respuesta = professor_client.get(reverse('grades:list'), {'q': 'algo'})
        assert 'Limpiar' in respuesta.content.decode()
