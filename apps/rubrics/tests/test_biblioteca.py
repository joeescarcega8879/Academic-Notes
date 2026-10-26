"""La biblioteca de rúbricas: crear, editar con versiones, duplicar, archivar, borrar y consultar."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.tests.factories import ProfessorFactory
from apps.courses.tests.factories import CourseFactory
from apps.grades.models import Activity
from apps.rubrics.models import Rubric, RubricCriterion, RubricLevel, RubricScore
from apps.rubrics.services import editor, grading, library
from apps.rubrics.tests.factories import choices_for, make_draft, make_rubric, rubric_activity

pytestmark = pytest.mark.django_db


def calificar(actividad, alumno, version=None, nivel=0):
    return grading.grade_with_rubric(actividad, alumno, choices=choices_for(version or actividad.rubric_version, nivel))


class TestCrear:
    def test_crea_la_rubrica_con_su_primera_version(self, professor):
        rubrica = make_rubric(professor)
        version = rubrica.current_version
        assert (rubrica.author, version.number, version.max_points) == (professor, 1, Decimal('12.00'))
        assert [c.name for c in version.criteria.all()] == ['Criterio 1', 'Criterio 2']
        assert [c.max_points for c in version.criteria.all()] == [Decimal('4'), Decimal('8')]
        assert RubricLevel.objects.filter(criterion__version=version).count() == 8

    def test_cada_pieza_queda_en_la_organizacion_del_docente(self, professor):
        rubrica = make_rubric(professor)
        version = rubrica.current_version
        assert {version.organization_id, *RubricCriterion.objects.values_list('organization_id', flat=True),
                *RubricLevel.objects.values_list('organization_id', flat=True)} == {rubrica.organization_id}

    def test_el_maximo_de_un_criterio_es_su_nivel_mas_alto_aunque_no_vaya_primero(self, professor):
        rubrica = library.create_rubric(organization=make_rubric(professor).organization, author=professor, draft=make_draft(((1, 5, 2),)))
        assert rubrica.current_version.max_points == Decimal('5')

    def test_los_niveles_conservan_su_orden(self, professor):
        criterio = make_rubric(professor).current_version.criteria.first()
        assert [(n.name, n.points) for n in criterio.levels.all()] == [
            ('Excelente', Decimal('4')), ('Bueno', Decimal('3')), ('Regular', Decimal('2')), ('Insuficiente', Decimal('0')),
        ]


class TestEditar:
    def nuevo_borrador(self, rubrica, **cambios):
        borrador = editor.draft_from_version(rubrica.current_version)
        borrador.update(cambios)
        errores, limpio = editor.validate(borrador)
        assert errores == []
        return limpio

    def test_sin_calificar_se_corrige_en_su_lugar(self, professor):
        rubrica = make_rubric(professor)
        version = rubrica.current_version
        cambio, nueva = library.save_rubric(rubrica, self.nuevo_borrador(rubrica, name='Otro nombre'))
        assert (cambio.pk, nueva) == (version.pk, False)
        rubrica.refresh_from_db()
        assert rubrica.name == 'Otro nombre' and rubrica.versions.count() == 1

    def test_corregir_en_su_lugar_cambia_los_puntos_y_los_criterios(self, professor):
        rubrica = make_rubric(professor)
        borrador = self.nuevo_borrador(rubrica)
        borrador['criteria'] = borrador['criteria'][:1]
        borrador['criteria'][0]['cells'][0]['points'] = Decimal('10')
        library.save_rubric(rubrica, borrador)
        version = rubrica.current_version
        assert version.max_points == Decimal('10') and version.criteria.count() == 1

    def test_las_actividades_sin_calificar_siguen_usando_la_misma_version(self, course):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        library.save_rubric(rubrica, self.nuevo_borrador(rubrica, name='Editada'))
        actividad.refresh_from_db()
        assert actividad.rubric_version == rubrica.current_version

    def test_ya_calificada_nace_una_version_nueva(self, course, enrollment):
        actividad = rubric_activity(course)
        rubrica, anterior = actividad.rubric_version.rubric, actividad.rubric_version
        calificar(actividad, enrollment.student)
        version, nueva = library.save_rubric(rubrica, self.nuevo_borrador(rubrica, name='Versión nueva'))
        assert nueva and version.number == 2 and rubrica.versions.count() == 2
        # la versión anterior queda intacta, con su detalle
        assert anterior.criteria.count() == 2 and RubricScore.objects.filter(criterion__version=anterior).count() == 2

    def test_la_actividad_ya_calificada_conserva_su_version_y_la_otra_pasa_a_la_nueva(self, course, enrollment):
        calificada = rubric_activity(course)
        rubrica = calificada.rubric_version.rubric
        pendiente = rubric_activity(course, rubrica)
        calificar(calificada, enrollment.student)
        version, _ = library.save_rubric(rubrica, self.nuevo_borrador(rubrica))
        calificada.refresh_from_db()
        pendiente.refresh_from_db()
        assert calificada.rubric_version.number == 1 and pendiente.rubric_version == version

    def test_una_actividad_solo_con_otra_rubrica_no_se_toca(self, course, enrollment, professor):
        usada = rubric_activity(course)
        otra = rubric_activity(course, make_rubric(professor, name='Otra'))
        calificar(usada, enrollment.student)
        library.save_rubric(usada.rubric_version.rubric, self.nuevo_borrador(usada.rubric_version.rubric))
        otra.refresh_from_db()
        assert otra.rubric_version.number == 1

    def test_el_detalle_ya_dado_no_cambia_al_editar(self, course, enrollment):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        calificar(actividad, enrollment.student)
        antes = list(RubricScore.objects.values_list('criterion__name', 'level__name', 'points'))
        borrador = self.nuevo_borrador(rubrica)
        borrador['criteria'][0]['name'] = 'Renombrado'
        library.save_rubric(rubrica, borrador)
        assert list(RubricScore.objects.values_list('criterion__name', 'level__name', 'points')) == antes

    def test_is_graded_solo_mira_la_version(self, course, enrollment):
        actividad = rubric_activity(course)
        assert library.is_graded(actividad.rubric_version) is False
        calificar(actividad, enrollment.student)
        assert library.is_graded(actividad.rubric_version) is True


class TestDuplicar:
    def test_copia_el_contenido_como_rubrica_nueva(self, professor):
        original = make_rubric(professor, name='Ensayo')
        copia = library.duplicate(original, author=professor)
        assert copia.pk != original.pk and copia.name == 'Ensayo (copia)'
        assert copia.current_version.number == 1 and copia.current_version.max_points == original.current_version.max_points
        assert [c.name for c in copia.current_version.criteria.all()] == [c.name for c in original.current_version.criteria.all()]

    def test_la_copia_es_independiente(self, professor):
        original = make_rubric(professor)
        copia = library.duplicate(original, author=professor)
        library.delete_rubric(copia)
        assert Rubric.objects.filter(pk=original.pk).exists() and original.current_version.criteria.count() == 2

    def test_un_nombre_largo_se_recorta(self, professor):
        original = make_rubric(professor, name='x' * 150)
        assert len(library.duplicate(original, author=professor).name) == 150


class TestArchivarYBorrar:
    def test_archivar_la_saca_de_la_lista_y_restaurar_la_devuelve(self, professor):
        rubrica = make_rubric(professor)
        library.set_archived(rubrica, True)
        assert library.library_rows(professor, rubrica.organization) == []
        assert [r['rubric'] for r in library.library_rows(professor, rubrica.organization, archived=True)] == [rubrica]
        library.set_archived(rubrica, False)
        assert len(library.library_rows(professor, rubrica.organization)) == 1

    def test_borra_una_rubrica_que_nadie_usa(self, professor):
        rubrica = make_rubric(professor)
        library.delete_rubric(rubrica)
        assert not Rubric.objects.exists() and not RubricCriterion.objects.exists()

    def test_no_borra_una_rubrica_en_uso(self, course):
        rubrica = rubric_activity(course).rubric_version.rubric
        with pytest.raises(ValidationError, match='en uso'):
            library.delete_rubric(rubrica)
        assert Rubric.objects.filter(pk=rubrica.pk).exists()

    def test_borrar_la_actividad_libera_la_rubrica(self, course):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        actividad.delete()
        library.delete_rubric(rubrica)
        assert not Rubric.objects.exists()


class TestConsulta:
    def test_cada_fila_trae_sus_numeros(self, course, enrollment, professor):
        actividad = rubric_activity(course)
        rubric_activity(CourseFactory(professor=professor), actividad.rubric_version.rubric)
        fila = library.library_rows(professor, course.organization)[0]
        assert (fila['criteria'], fila['levels'], fila['activities'], fila['groups']) == (2, 4, 2, 2)

    def test_una_rubrica_sin_usar_cuenta_cero(self, professor):
        rubrica = make_rubric(professor)
        fila = library.library_rows(professor, rubrica.organization)[0]
        assert (fila['activities'], fila['groups']) == (0, 0)

    def test_busca_sin_acentos_ni_mayusculas(self, professor):
        rubrica = make_rubric(professor, name='Exposición ORAL')
        make_rubric(professor, name='Ensayo')
        assert [f['rubric'] for f in library.library_rows(professor, rubrica.organization, query='exposicion')] == [rubrica]

    def test_solo_ve_las_suyas(self, professor):
        propia = make_rubric(professor, name='Propia')
        make_rubric(ProfessorFactory(), name='Ajena')
        assert [f['rubric'] for f in library.library_rows(professor, propia.organization)] == [propia]

    def test_otro_docente_de_la_misma_organizacion_no_las_ve(self, professor):
        propia = make_rubric(professor, name='Propia')
        make_rubric(ProfessorFactory(), name='Ajena', organization=propia.organization)
        assert [f['rubric'] for f in library.library_rows(professor, propia.organization)] == [propia]

    def test_uso_cuenta_actividades_y_grupos(self, course, professor):
        actividad = rubric_activity(course)
        rubric_activity(course, actividad.rubric_version.rubric)
        assert library.usage(actividad.rubric_version.rubric) == (2, 1)


class TestResolverVersion:
    def test_sin_rubrica_no_hay_version(self, course):
        assert library.resolve_version(rubric_activity(course), None) is None

    def test_una_actividad_nueva_toma_la_version_vigente(self, course, professor):
        rubrica = make_rubric(professor)
        actividad = Activity(course=course, title='x', type='homework')
        assert library.resolve_version(actividad, rubrica) == rubrica.current_version

    def test_se_queda_con_la_version_que_ya_tiene_aunque_haya_otra_mas_nueva(self, course, enrollment):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        calificar(actividad, enrollment.student)
        borrador = editor.draft_from_version(rubrica.current_version)
        library.save_rubric(rubrica, editor.validate(borrador)[1])
        rubrica = Rubric.objects.get(pk=rubrica.pk)
        assert library.resolve_version(actividad, rubrica).number == 1

    def test_no_se_cambia_de_rubrica_si_ya_se_califico_con_ella(self, course, enrollment, professor):
        actividad = rubric_activity(course)
        calificar(actividad, enrollment.student)
        with pytest.raises(ValidationError, match='no se puede cambiar'):
            library.resolve_version(actividad, make_rubric(professor, name='Otra'))
        with pytest.raises(ValidationError, match='no se puede cambiar'):
            library.resolve_version(actividad, None)

    def test_sin_calificaciones_si_se_puede_cambiar(self, course, professor):
        actividad = rubric_activity(course)
        otra = make_rubric(professor, name='Otra')
        assert library.resolve_version(actividad, otra) == otra.current_version
