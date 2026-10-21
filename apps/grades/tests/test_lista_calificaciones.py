"""Pantalla de Calificaciones: grupos activos, búsqueda, filtros, fechas, paginación y la exportación con los mismos filtros."""

import csv
import io
from datetime import datetime
from datetime import timezone as dt_timezone

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.courses.models import Course
from apps.courses.tests.factories import CourseFactory, EnrollmentFactory, StudentRecordFactory
from apps.grades.models import Grade
from apps.grades.tests.factories import ActivityFactory, GradeFactory

pytestmark = pytest.mark.django_db

LISTA = reverse('grades:list')
EXPORTAR = reverse('grades:export')


def archivar(course):
    Course.objects.filter(pk=course.pk).update(status=Course.Status.ARCHIVED)


def nota(course, *, nombre='Nombre', apellidos='Apellido', matricula='', titulo=None, feedback='', cuando=None, score=8):
    """Una calificación en ``course`` para un alumno nuevo (sin cuenta) con esos datos."""
    alumno = StudentRecordFactory(
        organization=course.organization, user=None, first_name=nombre, last_name=apellidos, student_number=matricula,
    )
    extra = {'title': titulo} if titulo else {}
    grade = GradeFactory(activity=ActivityFactory(course=course, **extra), student=alumno, feedback=feedback, score=score)
    if cuando is not None:
        Grade.objects.filter(pk=grade.pk).update(graded_at=cuando)
        grade.refresh_from_db()
    return grade


def ids(response):
    return {g.pk for g in response.context['grades']}


def filas_csv(response):
    return list(csv.reader(io.StringIO(response.content.decode('utf-8-sig'))))


class TestGruposActivos:
    @pytest.fixture
    def dos(self, professor):
        activo = CourseFactory(professor=professor, name='Matemáticas')
        viejo = CourseFactory(professor=professor, name='Historia')
        archivar(viejo)
        return nota(activo), nota(viejo)

    def test_por_omision_solo_salen_los_grupos_activos(self, professor_client, dos):
        activa, archivada = dos
        assert ids(professor_client.get(LISTA)) == {activa.pk}

    def test_la_casilla_de_archivados_los_incluye(self, professor_client, dos):
        activa, archivada = dos
        assert ids(professor_client.get(LISTA, {'archivados': 'on'})) == {activa.pk, archivada.pk}

    def test_elegir_un_grupo_archivado_lo_muestra_aunque_no_se_marque_la_casilla(self, professor_client, dos):
        activa, archivada = dos
        assert ids(professor_client.get(LISTA, {'grupo': archivada.activity.course_id})) == {archivada.pk}

    def test_el_selector_ofrece_solo_los_activos_y_los_archivados_si_se_piden(self, professor_client, dos):
        activa, archivada = dos
        sin = professor_client.get(LISTA).context['filter_form'].fields['grupo'].queryset
        con = professor_client.get(LISTA, {'archivados': 'on'}).context['filter_form'].fields['grupo'].queryset
        assert {c.pk for c in sin} == {activa.activity.course_id}
        assert {c.pk for c in con} == {activa.activity.course_id, archivada.activity.course_id}

    def test_el_recuadro_cuenta_solo_grupos_activos(self, professor_client, dos):
        assert len(professor_client.get(LISTA).context['courses']) == 1

    def test_un_grupo_archivado_se_marca_en_la_tabla(self, professor_client, dos):
        assert 'Archivado' in professor_client.get(LISTA, {'archivados': 'on'}).content.decode()

    def test_el_alumno_tambien_ve_solo_los_grupos_activos_por_omision(self, student_client, student):
        docente = ProfessorFactory()
        activo, viejo = CourseFactory(professor=docente), CourseFactory(professor=docente)
        EnrollmentFactory(course=activo, student=student)
        EnrollmentFactory(course=viejo, student=student)
        propia = GradeFactory(activity=ActivityFactory(course=activo), student=student)
        de_archivado = GradeFactory(activity=ActivityFactory(course=viejo), student=student)
        archivar(viejo)
        assert ids(student_client.get(LISTA)) == {propia.pk}
        assert ids(student_client.get(LISTA, {'archivados': 'on'})) == {propia.pk, de_archivado.pk}


class TestBusqueda:
    @pytest.fixture
    def grupo(self, professor):
        return CourseFactory(professor=professor, name='Álgebra')

    def test_por_nombre_o_apellido_sin_importar_mayusculas(self, professor_client, grupo):
        ana = nota(grupo, nombre='Ana Lucía', apellidos='Ramírez')
        nota(grupo, nombre='Diego', apellidos='Hernández')
        assert ids(professor_client.get(LISTA, {'q': 'ana'})) == {ana.pk}
        assert ids(professor_client.get(LISTA, {'q': 'RAMÍREZ'})) == {ana.pk}

    def test_ignora_los_acentos_en_lo_que_se_escribe_y_en_lo_que_se_guarda(self, professor_client, grupo):
        alvaro = nota(grupo, nombre='Álvaro', apellidos='Peña')
        assert ids(professor_client.get(LISTA, {'q': 'alvaro'})) == {alvaro.pk}
        assert ids(professor_client.get(LISTA, {'q': 'ÁLVARO pena'})) == {alvaro.pk}
        assert ids(professor_client.get(LISTA, {'q': 'peña'})) == {alvaro.pk}

    def test_por_matricula(self, professor_client, grupo):
        buscada = nota(grupo, matricula='230117')
        nota(grupo, matricula='999999')
        assert ids(professor_client.get(LISTA, {'q': '230117'})) == {buscada.pk}

    def test_por_titulo_de_la_evaluacion_nombre_del_grupo_y_comentario(self, professor_client, grupo):
        a = nota(grupo, titulo='Examen parcial')
        b = nota(grupo, titulo='Tarea 2', feedback='Falta justificar el procedimiento')
        assert ids(professor_client.get(LISTA, {'q': 'parcial'})) == {a.pk}
        assert ids(professor_client.get(LISTA, {'q': 'procedimiento'})) == {b.pk}
        assert ids(professor_client.get(LISTA, {'q': 'álgebra'})) == {a.pk, b.pk}

    def test_varias_palabras_deben_cumplirse_todas(self, professor_client, grupo):
        ana_parcial = nota(grupo, nombre='Ana', titulo='Examen parcial')
        nota(grupo, nombre='Ana', titulo='Tarea 2')
        nota(grupo, nombre='Luis', titulo='Examen parcial')
        assert ids(professor_client.get(LISTA, {'q': 'ana parcial'})) == {ana_parcial.pk}

    def test_sin_coincidencias_dice_que_no_hay(self, professor_client, grupo):
        nota(grupo)
        html = professor_client.get(LISTA, {'q': 'zzzz'}).content.decode()
        assert 'Ninguna calificación coincide' in html

    def test_el_comodin_de_sql_se_busca_como_texto(self, professor_client, grupo):
        nota(grupo, nombre='Ana')
        assert ids(professor_client.get(LISTA, {'q': '%'})) == set()

    def test_el_alumno_busca_por_evaluacion_pero_no_ve_datos_de_otros(self, student_client, student, course, enrollment):
        propia = GradeFactory(activity=ActivityFactory(course=course, title='Quiz de fracciones'), student=student)
        GradeFactory(activity=ActivityFactory(course=course, title='Otro'), student=student)
        assert ids(student_client.get(LISTA, {'q': 'fracciones'})) == {propia.pk}

    def test_no_se_filtran_notas_de_otro_docente_al_buscar(self, professor_client, grupo):
        propia = nota(grupo, nombre='Ana')
        nota(CourseFactory(name='Ajeno'), nombre='Ana')
        assert ids(professor_client.get(LISTA, {'q': 'ana'})) == {propia.pk}


class TestFiltroPorGrupo:
    def test_filtra_por_un_grupo(self, professor_client, professor):
        a, b = CourseFactory(professor=professor), CourseFactory(professor=professor)
        na, nb = nota(a), nota(b)
        assert ids(professor_client.get(LISTA, {'grupo': a.pk})) == {na.pk}
        assert ids(professor_client.get(LISTA, {'grupo': b.pk})) == {nb.pk}

    def test_un_grupo_ajeno_es_una_opcion_invalida_y_no_filtra(self, professor_client, professor):
        propia = nota(CourseFactory(professor=professor))
        ajeno = CourseFactory()
        nota(ajeno)
        respuesta = professor_client.get(LISTA, {'grupo': ajeno.pk})
        assert respuesta.status_code == 200 and ids(respuesta) == {propia.pk}
        assert 'Revisa los filtros' in respuesta.content.decode()

    @pytest.mark.parametrize('valor', ['abc', '1 OR 1=1', '-5', '99999999999999999999'])
    def test_un_valor_raro_no_rompe_la_pantalla(self, professor_client, professor, valor):
        nota(CourseFactory(professor=professor))
        assert professor_client.get(LISTA, {'grupo': valor}).status_code == 200


class TestFechas:
    @pytest.fixture
    def dos(self, professor):
        grupo = CourseFactory(professor=professor)
        viejo = nota(grupo, cuando=datetime(2026, 1, 10, 18, tzinfo=dt_timezone.utc))
        nuevo = nota(grupo, cuando=datetime(2026, 3, 10, 18, tzinfo=dt_timezone.utc))
        return viejo, nuevo

    def test_desde_y_hasta(self, professor_client, dos):
        viejo, nuevo = dos
        assert ids(professor_client.get(LISTA, {'desde': '2026-02-01'})) == {nuevo.pk}
        assert ids(professor_client.get(LISTA, {'hasta': '2026-02-01'})) == {viejo.pk}
        assert ids(professor_client.get(LISTA, {'desde': '2026-01-01', 'hasta': '2026-12-31'})) == {viejo.pk, nuevo.pk}

    def test_los_extremos_cuentan(self, professor_client, dos):
        viejo, _ = dos
        assert ids(professor_client.get(LISTA, {'desde': '2026-01-10', 'hasta': '2026-01-10'})) == {viejo.pk}

    def test_una_fecha_inicial_posterior_a_la_final_avisa_y_no_filtra(self, professor_client, dos):
        respuesta = professor_client.get(LISTA, {'desde': '2026-05-01', 'hasta': '2026-01-01'})
        assert 'La fecha final es anterior a la inicial' in respuesta.content.decode()
        assert len(ids(respuesta)) == 2

    @pytest.mark.parametrize('valor', ['abc', '2026-13-45', '10/01/2026'])
    def test_una_fecha_con_otro_formato_avisa_sin_romper(self, professor_client, dos, valor):
        respuesta = professor_client.get(LISTA, {'desde': valor})
        assert respuesta.status_code == 200 and 'Revisa los filtros' in respuesta.content.decode()

    def test_la_tabla_muestra_la_fecha_de_cada_calificacion(self, professor_client, dos):
        html = professor_client.get(LISTA).content.decode()
        assert '<th>Fecha</th>' in html and '10/01/2026' in html and '10/03/2026' in html

    def test_las_mas_recientes_van_primero(self, professor_client, dos):
        viejo, nuevo = dos
        assert [g.pk for g in professor_client.get(LISTA).context['grades']] == [nuevo.pk, viejo.pk]


class TestPaginacionYTotales:
    @pytest.fixture
    def muchas(self, professor):
        grupo = CourseFactory(professor=professor)
        return [nota(grupo, score=10 if i % 2 else 6) for i in range(30)]

    def test_se_pagina_de_25_en_25(self, professor_client, muchas):
        primera = professor_client.get(LISTA)
        segunda = professor_client.get(LISTA, {'page': 2})
        assert len(primera.context['grades']) == 25 and len(segunda.context['grades']) == 5

    def test_el_total_y_el_promedio_cubren_todas_no_solo_la_pagina(self, professor_client, muchas):
        contexto = professor_client.get(LISTA).context
        assert contexto['total'] == 30
        assert contexto['average'] == pytest.approx(8.0)

    def test_los_enlaces_de_pagina_conservan_los_filtros(self, professor_client, muchas):
        html = professor_client.get(LISTA, {'q': 'nombre'}).content.decode()
        assert 'q=nombre&amp;page=2' in html or 'q=nombre&page=2' in html

    def test_una_pagina_fuera_de_rango_es_404_y_una_invalida_tambien(self, professor_client, muchas):
        assert professor_client.get(LISTA, {'page': 999}).status_code == 404
        assert professor_client.get(LISTA, {'page': 'abc'}).status_code == 404


class TestExportacionConLosMismosFiltros:
    @pytest.fixture
    def grupos(self, professor):
        activo = CourseFactory(professor=professor, name='Álgebra')
        viejo = CourseFactory(professor=professor, name='Historia')
        archivar(viejo)
        return activo, viejo

    def test_por_omision_solo_grupos_activos(self, professor_client, grupos):
        activo, viejo = grupos
        nota(activo), nota(viejo)
        assert [f[3] for f in filas_csv(professor_client.get(EXPORTAR))[1:]] == ['Álgebra']

    def test_con_archivados(self, professor_client, grupos):
        activo, viejo = grupos
        nota(activo), nota(viejo)
        grupos_en_csv = {f[3] for f in filas_csv(professor_client.get(EXPORTAR, {'archivados': 'on'}))[1:]}
        assert grupos_en_csv == {'Álgebra', 'Historia'}

    def test_respeta_la_busqueda(self, professor_client, grupos):
        activo, _ = grupos
        nota(activo, nombre='Ana'), nota(activo, nombre='Luis')
        filas = filas_csv(professor_client.get(EXPORTAR, {'q': 'ana'}))
        assert [f[1] for f in filas[1:]] == ['Ana Apellido']

    def test_el_enlace_de_exportar_lleva_los_filtros_de_la_pantalla(self, professor_client, grupos):
        activo, _ = grupos
        nota(activo)
        html = professor_client.get(LISTA, {'q': 'ana', 'desde': '2026-01-01'}).content.decode()
        assert f'{EXPORTAR}?q=ana&amp;desde=2026-01-01' in html

    @pytest.mark.parametrize('params', [{'grupo': 'abc'}, {'desde': '2026-13-45'}, {'desde': '2026-05-01', 'hasta': '2026-01-01'}])
    def test_filtros_invalidos_dan_400_y_no_exportan(self, professor_client, params):
        assert professor_client.get(EXPORTAR, params).status_code == 400

    def test_un_grupo_ajeno_no_exporta_nada_suyo(self, professor_client, professor):
        ajeno = CourseFactory()
        nota(ajeno, nombre='Secreta')
        respuesta = professor_client.get(EXPORTAR, {'grupo': ajeno.pk})
        assert respuesta.status_code == 400 and 'Secreta' not in respuesta.content.decode()


class TestPantalla:
    def test_tiene_buscador_selector_de_grupo_y_fechas(self, professor_client, course):
        html = professor_client.get(LISTA).content.decode()
        for esperado in ('name="q"', 'name="grupo"', 'name="desde"', 'name="hasta"', 'name="archivados"', 'Todos los grupos'):
            assert esperado in html, esperado

    def test_no_hay_boton_de_limpiar_sin_filtros_y_si_con_filtros(self, professor_client, course):
        assert 'Limpiar' not in professor_client.get(LISTA).content.decode()
        assert 'Limpiar' in professor_client.get(LISTA, {'q': 'a'}).content.decode()

    def test_los_filtros_elegidos_se_conservan_en_los_campos(self, professor_client, course):
        html = professor_client.get(LISTA, {'q': 'ana', 'desde': '2026-02-01'}).content.decode()
        assert 'value="ana"' in html and 'value="2026-02-01"' in html

    def test_el_texto_vacio_distingue_sin_notas_de_sin_resultados(self, professor_client, course):
        assert 'Aún no has registrado calificaciones en tus grupos activos' in professor_client.get(LISTA).content.decode()

    def test_el_alumno_no_ve_la_columna_ni_el_buscador_de_alumnos(self, student_client, course, enrollment):
        html = student_client.get(LISTA).content.decode()
        assert '<th>Alumno</th>' not in html and 'Grupo, evaluación o comentario' in html

    def test_anonimo_va_al_login(self, client):
        assert client.get(LISTA, {'q': 'x'}).status_code == 302
