"""Calificar con rúbrica: la suma y su escala, la penalización, el detalle y los permisos."""

import datetime
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.courses.services.courses import archive_course
from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.grades.models import Grade, GradeHistory
from apps.grades.services.gradebook import grade_activity
from apps.grades.services.submissions import submit
from apps.rubrics.models import RubricScore
from apps.rubrics.services import grading
from apps.rubrics.tests.factories import choices_for, make_rubric, rubric_activity

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


@pytest.fixture
def actividad(course):
    """Tarea de 10 puntos con una rúbrica de 12 (criterios de 4 y 8)."""
    return rubric_activity(course)


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


def niveles(actividad, *posiciones):
    """Elige en cada criterio el nivel de esa posición (0 = el mejor)."""
    criterios = list(actividad.rubric_version.criteria.prefetch_related('levels'))
    return {c.pk: c.levels.all()[p].pk for c, p in zip(criterios, posiciones, strict=True)}


# ── La suma y su escala ───────────────────────────────────────────────

class TestSuma:
    @pytest.mark.parametrize('posiciones, puntos, nota', [
        ((0, 0), '12.00', 10.0), ((1, 1), '9.00', 7.5), ((3, 3), '0.00', 0.0), ((0, 3), '4.00', 3.33), ((2, 1), '8.00', 6.67),
    ])
    def test_la_nota_es_la_suma_escalada_a_la_actividad(self, actividad, alumno, posiciones, puntos, nota):
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, *posiciones))
        assert (grading.rubric_points(grade), grade.raw_score, grade.score) == (Decimal(puntos), nota, nota)

    def test_si_valen_lo_mismo_no_se_escala(self, course, alumno):
        actividad = rubric_activity(course, max_score=12)
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 1, 1))
        assert grade.score == 9.0

    def test_otra_escala_de_actividad(self, course, alumno):
        actividad = rubric_activity(course, max_score=100)
        assert grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 1, 1)).score == 75.0

    def test_redondea_mitad_hacia_arriba(self, professor, course, alumno):
        rubrica = make_rubric(professor, rows=((1, 0), (1, 0), (1, 0), (1, 0), (1, 0), (1, 0), (1, 0), (1, 0)), name='Octavos')
        actividad = rubric_activity(course, rubrica, max_score=10)
        # 1 de 8 criterios en el nivel alto: 1/8 de 10 = 1.25 (exacto); 3/8 = 3.75
        criterios = list(rubrica.current_version.criteria.prefetch_related('levels'))
        eleccion = {c.pk: c.levels.all()[0 if i < 3 else 1].pk for i, c in enumerate(criterios)}
        assert grading.grade_with_rubric(actividad, alumno, choices=eleccion).score == 3.75

    def test_la_calificacion_queda_como_de_rubrica(self, actividad, alumno):
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0), feedback='  Bien  ')
        assert (grade.source, grade.feedback) == (Grade.Source.RUBRIC, 'Bien')

    def test_una_rubrica_sin_puntos_da_cero(self, actividad):
        actividad.rubric_version.max_points = 0
        assert grading.scaled_score(actividad.rubric_version, 0, 100) == 0.0


# ── Detalle y reglas ──────────────────────────────────────────────────

class TestDetalle:
    def test_guarda_nivel_puntos_y_comentario_por_criterio(self, actividad, alumno):
        criterios = list(actividad.rubric_version.criteria.all())
        grade = grading.grade_with_rubric(
            actividad, alumno, choices=niveles(actividad, 1, 2), comments={criterios[0].pk: ' Tesis clara '},
        )
        filas = [(s.criterion.name, s.level.name, s.points, s.comment) for s in grade.rubric_scores.all()]
        assert filas == [('Criterio 1', 'Bueno', Decimal('3'), 'Tesis clara'), ('Criterio 2', 'Regular', Decimal('3'), '')]

    def test_volver_a_calificar_reemplaza_el_detalle(self, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 3, 3))
        assert Grade.objects.count() == 1 and RubricScore.objects.count() == 2
        assert grade.score == 0.0 and {s.points for s in grade.rubric_scores.all()} == {Decimal('0')}

    def test_las_piezas_del_detalle_son_de_la_organizacion(self, actividad, alumno):
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        assert {s.organization_id for s in grade.rubric_scores.all()} == {actividad.organization_id}

    def test_exige_un_nivel_en_todos_los_criterios(self, actividad, alumno):
        eleccion = niveles(actividad, 0, 0)
        eleccion.pop(next(iter(eleccion)))
        with pytest.raises(ValidationError, match='Elige un nivel en «Criterio 1»'):
            grading.grade_with_rubric(actividad, alumno, choices=eleccion)
        assert not Grade.objects.exists() and not RubricScore.objects.exists()

    def test_un_nivel_de_otro_criterio_no_vale(self, actividad, alumno):
        criterios = list(actividad.rubric_version.criteria.prefetch_related('levels'))
        eleccion = {criterios[0].pk: criterios[1].levels.all()[0].pk, criterios[1].pk: criterios[1].levels.all()[0].pk}
        with pytest.raises(ValidationError, match='Elige un nivel'):
            grading.grade_with_rubric(actividad, alumno, choices=eleccion)

    def test_un_nivel_de_otra_rubrica_no_vale(self, actividad, alumno, professor):
        otra = make_rubric(professor, name='Otra').current_version
        eleccion = {c.pk: choices_for(otra)[o.pk] for c, o in zip(actividad.rubric_version.criteria.all(), otra.criteria.all(), strict=True)}
        with pytest.raises(ValidationError, match='Elige un nivel'):
            grading.grade_with_rubric(actividad, alumno, choices=eleccion)

    def test_comentario_demasiado_largo(self, actividad, alumno):
        criterio = actividad.rubric_version.criteria.first()
        with pytest.raises(ValidationError, match='no puede pasar de 500'):
            grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0), comments={criterio.pk: 'x' * 501})
        assert not Grade.objects.exists()

    def test_un_comentario_de_500_caracteres_si_vale(self, actividad, alumno):
        criterio = actividad.rubric_version.criteria.first()
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0), comments={criterio.pk: 'x' * 500})
        assert RubricScore.objects.get(criterion=criterio).comment == 'x' * 500

    def test_un_error_no_deja_la_calificacion_a_medias(self, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        eleccion = niveles(actividad, 3, 3)
        eleccion.popitem()
        with pytest.raises(ValidationError):
            grading.grade_with_rubric(actividad, alumno, choices=eleccion)
        assert Grade.objects.get().score == 10.0 and RubricScore.objects.count() == 2

    def test_una_actividad_sin_rubrica_no_se_califica_asi(self, course, alumno):
        from apps.grades.tests.factories import ActivityFactory

        with pytest.raises(ValidationError, match='no se califica con rúbrica'):
            grading.grade_with_rubric(ActivityFactory(course=course), alumno, choices={})

    def test_un_alumno_ajeno_al_grupo_no_se_califica(self, actividad):
        ajeno = EnrollmentFactory(course=CourseFactory()).student
        with pytest.raises(ValidationError):
            grading.grade_with_rubric(actividad, ajeno, choices=niveles(actividad, 0, 0))

    def test_un_grupo_archivado_no_se_califica(self, actividad, alumno):
        archive_course(actividad.course)
        with pytest.raises(ValidationError):
            grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))

    def test_queda_en_la_bitacora(self, actividad, alumno, professor):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0), by=professor)
        registro = GradeHistory.objects.get()
        assert (registro.new_score, registro.changed_by) == (10.0, professor)


class TestPenalizacion:
    @pytest.fixture
    def tardia(self, course, alumno):
        actividad = rubric_activity(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20)
        submit(actividad, alumno, text='tarde', now=AHORA)
        return actividad

    def test_se_aplica_sobre_el_total_de_la_rubrica(self, tardia, alumno):
        grade = grading.grade_with_rubric(tardia, alumno, choices=niveles(tardia, 0, 0))
        assert (grade.raw_score, grade.score, grade.late_penalty) == (10.0, 8.0, Decimal('20'))

    def test_se_puede_perdonar(self, tardia, alumno):
        grade = grading.grade_with_rubric(tardia, alumno, choices=niveles(tardia, 0, 0), waive_penalty=True)
        assert (grade.score, grade.late_penalty) == (10.0, Decimal('0'))


class TestAjusteAMano:
    def test_cambiar_la_nota_a_mano_lo_deja_dicho(self, actividad, alumno):
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        assert grading.adjusted_by_hand(grade) is False
        ajustada = grade_activity(actividad, alumno, score=9)
        assert grading.adjusted_by_hand(ajustada) is True and ajustada.rubric_scores.count() == 2

    def test_calificar_de_nuevo_con_la_rubrica_quita_el_ajuste(self, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        grade_activity(actividad, alumno, score=9)
        grade = grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        assert grading.adjusted_by_hand(grade) is False

    def test_una_nota_manual_sin_rubrica_no_es_un_ajuste(self, actividad, alumno):
        assert grading.adjusted_by_hand(grade_activity(actividad, alumno, score=7)) is False

    def test_sin_calificar_con_rubrica_no_hay_puntos(self, actividad, alumno):
        assert grading.rubric_points(grade_activity(actividad, alumno, score=7)) is None


# ── Las pantallas del docente ─────────────────────────────────────────

def datos(actividad, *posiciones, **extra):
    eleccion = niveles(actividad, *posiciones)
    return {**{f'c_{criterio}': nivel for criterio, nivel in eleccion.items()}, **extra}


class TestPantallas:
    def url(self, actividad, alumno):
        return reverse('rubrics:grade_student', args=[actividad.pk, alumno.pk])

    def test_calificar_redirige_a_la_pantalla_de_la_rubrica(self, professor_client, actividad, alumno):
        lista = professor_client.get(reverse('grades:activity_grading', args=[actividad.pk]))
        assert lista.status_code == 302 and lista.url == reverse('rubrics:grade_list', args=[actividad.pk])
        uno = professor_client.get(reverse('grades:activity_grading', args=[actividad.pk]), {'alumno': alumno.pk})
        assert uno.url == self.url(actividad, alumno)

    def test_un_post_a_la_tabla_de_notas_tampoco_guarda_una_nota_suelta(self, professor_client, actividad, alumno):
        professor_client.post(reverse('grades:activity_grading', args=[actividad.pk]), {f'score_{alumno.pk}': '9'})
        assert not Grade.objects.exists()

    def test_la_lista_muestra_el_estado_de_cada_alumno(self, professor_client, actividad, alumno):
        pagina = professor_client.get(reverse('rubrics:grade_list', args=[actividad.pk])).content.decode()
        assert str(alumno) in pagina and 'Sin calificar' in pagina and 'Calificar' in pagina
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 1, 1))
        pagina = professor_client.get(reverse('rubrics:grade_list', args=[actividad.pk])).content.decode()
        assert '7.5' in pagina and 'Revisar' in pagina

    def test_la_pantalla_trae_la_cuadricula_y_los_radios(self, professor_client, actividad, alumno):
        pagina = professor_client.get(self.url(actividad, alumno)).content.decode()
        assert pagina.count('type="radio"') == 8 and 'id="rubric-grade"' in pagina and 'js/rubrica.js' in pagina
        assert 'data-max-points="12.00"' in pagina and 'data-activity-max="10.0"' in pagina

    def test_guarda_y_vuelve_a_la_actividad(self, professor_client, actividad, alumno):
        response = professor_client.post(self.url(actividad, alumno), datos(actividad, 0, 1, feedback='Muy bien'))
        assert response.status_code == 302 and response.url == actividad.get_absolute_url()
        grade = Grade.objects.get()
        assert (grade.score, grade.feedback, grade.source) == (8.33, 'Muy bien', Grade.Source.RUBRIC)

    def test_guarda_los_comentarios_por_criterio(self, professor_client, actividad, alumno):
        criterio = actividad.rubric_version.criteria.first()
        professor_client.post(self.url(actividad, alumno), datos(actividad, 0, 0, **{f'n_{criterio.pk}': 'Excelente tesis'}))
        assert RubricScore.objects.get(criterion=criterio).comment == 'Excelente tesis'

    def test_falta_un_criterio_no_guarda_nada_y_conserva_lo_elegido(self, professor_client, actividad, alumno):
        envio = datos(actividad, 0, 0, feedback='Mi texto')
        envio.pop(next(k for k in envio if k.startswith('c_')))
        response = professor_client.post(self.url(actividad, alumno), envio)
        pagina = response.content.decode()
        assert response.status_code == 200 and 'Elige un nivel en «Criterio 1»' in pagina and 'Mi texto' in pagina
        assert pagina.count('checked') == 1 and not Grade.objects.exists()

    def test_una_calificacion_hecha_se_muestra_marcada_para_revisarla(self, professor_client, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 1, 2), feedback='Notas')
        pagina = professor_client.get(self.url(actividad, alumno)).content.decode()
        assert pagina.count('checked') == 2 and 'Notas' in pagina

    def test_avisa_si_la_nota_se_ajusto_a_mano(self, professor_client, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        grade_activity(actividad, alumno, score=9)
        assert 'se ajustó a mano' in professor_client.get(self.url(actividad, alumno)).content.decode()

    def test_guardar_y_siguiente_va_al_proximo_sin_calificar(self, professor_client, actividad, alumno, course):
        otro = EnrollmentFactory(course=course).student
        primero, segundo = sorted([alumno, otro], key=lambda a: (a.last_name, a.first_name))
        response = professor_client.post(self.url(actividad, primero), datos(actividad, 0, 0, siguiente='1'))
        assert response.url == self.url(actividad, segundo)

    def test_guardar_y_siguiente_en_el_ultimo_vuelve_a_la_actividad(self, professor_client, actividad, alumno):
        response = professor_client.post(self.url(actividad, alumno), datos(actividad, 0, 0, siguiente='1'))
        assert response.url == actividad.get_absolute_url()

    def test_el_siguiente_se_salta_a_los_ya_calificados(self, actividad, course, alumno):
        from apps.rubrics.views import RubricGradeStudentView

        otros = [EnrollmentFactory(course=course).student for _ in range(2)]
        orden = [alumno, *otros]
        filas = [{'student': a, 'grade': None} for a in orden]
        filas[1]['grade'] = object()
        assert RubricGradeStudentView.next_student(filas, orden[0]) == orden[2].pk
        assert RubricGradeStudentView.next_student(filas, orden[2]) is None
        assert RubricGradeStudentView.next_student(filas, orden[1]) == orden[2].pk

    def test_la_penalizacion_se_puede_perdonar_desde_la_pantalla(self, professor_client, course, alumno):
        actividad = rubric_activity(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20)
        submit(actividad, alumno, text='tarde', now=AHORA)
        assert 'name="waive"' in professor_client.get(self.url(actividad, alumno)).content.decode()
        professor_client.post(self.url(actividad, alumno), datos(actividad, 0, 0, waive='on'))
        assert Grade.objects.get().score == 10.0

    def test_sin_entrega_tardia_no_se_ofrece_perdonar(self, professor_client, actividad, alumno):
        assert 'name="waive"' not in professor_client.get(self.url(actividad, alumno)).content.decode()


class TestPermisos:
    def test_otro_docente_no_entra(self, actividad, alumno, client):
        from apps.accounts.tests.factories import ProfessorFactory

        client.force_login(ProfessorFactory())
        for nombre, args in (('grade_list', [actividad.pk]), ('grade_student', [actividad.pk, alumno.pk])):
            assert client.get(reverse(f'rubrics:{nombre}', args=args)).status_code == 404

    def test_el_alumno_no_entra(self, student_client, actividad, alumno):
        for nombre, args in (('grade_list', [actividad.pk]), ('grade_student', [actividad.pk, alumno.pk])):
            assert student_client.get(reverse(f'rubrics:{nombre}', args=args)).status_code == 302

    def test_sin_sesion_pide_acceso(self, client, actividad, alumno):
        assert client.get(reverse('rubrics:grade_list', args=[actividad.pk])).status_code == 302

    def test_un_alumno_de_otro_grupo_es_404(self, professor_client, actividad):
        ajeno = EnrollmentFactory().student
        assert professor_client.get(reverse('rubrics:grade_student', args=[actividad.pk, ajeno.pk])).status_code == 404
        assert professor_client.post(reverse('rubrics:grade_student', args=[actividad.pk, ajeno.pk]), {}).status_code == 404

    def test_una_actividad_sin_rubrica_es_404(self, professor_client, course, alumno):
        from apps.grades.tests.factories import ActivityFactory

        sin = ActivityFactory(course=course)
        assert professor_client.get(reverse('rubrics:grade_list', args=[sin.pk])).status_code == 404

    def test_un_grupo_archivado_es_404(self, professor_client, actividad, alumno):
        archive_course(actividad.course)
        assert professor_client.get(reverse('rubrics:grade_student', args=[actividad.pk, alumno.pk])).status_code == 404


# ── Lo que ve el alumno ───────────────────────────────────────────────

class TestAlumno:
    def test_antes_de_entregar_ve_como_se_calificara(self, student_client, actividad, enrollment):
        pagina = student_client.get(actividad.get_absolute_url()).content.decode()
        assert 'Cómo se calificará' in pagina and 'Excelente del criterio 1' in pagina and 'class="rub-lv sel"' not in pagina

    def test_ya_calificado_ve_su_nivel_su_comentario_y_su_total(self, student_client, actividad, alumno):
        criterio = actividad.rubric_version.criteria.first()
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 1, 2), comments={criterio.pk: 'Casi perfecta'})
        pagina = student_client.get(actividad.get_absolute_url()).content.decode()
        assert 'Así se calificó tu trabajo' in pagina and pagina.count('class="rub-lv sel"') == 2
        assert 'Casi perfecta' in pagina and 'Obtuviste 6' in pagina

    def test_avisa_si_el_docente_ajusto_la_nota(self, student_client, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        grade_activity(actividad, alumno, score=9)
        assert 'ajustó la calificación final' in student_client.get(actividad.get_absolute_url()).content.decode()

    def test_una_nota_manual_sin_detalle_no_muestra_niveles_elegidos(self, student_client, actividad, alumno):
        grade_activity(actividad, alumno, score=7)
        pagina = student_client.get(actividad.get_absolute_url()).content.decode()
        assert 'Cómo se calificará' in pagina and 'class="rub-lv sel"' not in pagina

    def test_una_actividad_sin_rubrica_no_muestra_el_panel(self, student_client, course, enrollment):
        from apps.grades.tests.factories import ActivityFactory

        sin = ActivityFactory(course=course)
        assert 'rub-lv' not in student_client.get(sin.get_absolute_url()).content.decode()

    def test_el_docente_ve_de_cual_rubrica_y_su_enlace(self, professor_client, actividad):
        pagina = professor_client.get(actividad.get_absolute_url()).content.decode()
        assert 'versión 1' in pagina and actividad.rubric_version.rubric.get_absolute_url() in pagina
        assert 'rub-lv' not in pagina

    def test_la_lista_del_docente_marca_las_notas_de_rubrica(self, professor_client, actividad, alumno):
        grading.grade_with_rubric(actividad, alumno, choices=niveles(actividad, 0, 0))
        assert '<span class="chip">Rúbrica</span>' in professor_client.get(actividad.get_absolute_url()).content.decode()
