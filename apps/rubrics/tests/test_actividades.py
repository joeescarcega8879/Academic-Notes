"""La rúbrica en el formulario de actividades: elegirla, proyectos, versiones, publicar y duplicar el grupo."""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.courses.services.courses import clone_course
from apps.courses.tests.factories import AcademicYearFactory
from apps.grades.models import Activity
from apps.grades.tests.factories import ActivityFactory
from apps.rubrics.services import editor, grading, library
from apps.rubrics.tests.factories import make_rubric, rubric_activity
from apps.rubrics.tests.test_calificar import niveles
from apps.accounts.tests.factories import ProfessorFactory

pytestmark = pytest.mark.django_db

BASE = {
    'title': 'Tarea 1', 'type': 'homework', 'criterion': '', 'max_score': '10', 'weight': '1',
    'instructions': 'Resuelve.', 'allow_late': 'on', 'late_penalty': '10',
}


def crear(client, course, **cambios):
    return client.post(reverse('grades:activity_create', args=[course.pk]), {**BASE, **cambios})


def editar(client, actividad, **cambios):
    datos = {**BASE, 'title': actividad.title, 'criterion': actividad.criterion_id, **cambios}
    return client.post(reverse('grades:activity_update', args=[actividad.pk]), datos)


class TestFormulario:
    def test_el_formulario_ofrece_sus_rubricas_con_los_puntos(self, professor_client, course, professor):
        make_rubric(professor, name='Mía')
        make_rubric(ProfessorFactory(), name='Ajena')
        archivada = make_rubric(professor, name='Archivada')
        library.set_archived(archivada, True)
        pagina = professor_client.get(reverse('grades:activity_create', args=[course.pk])).content.decode()
        assert 'Mía · 12 pts' in pagina and 'Ajena' not in pagina and 'Archivada' not in pagina
        assert 'id="rubric-points"' in pagina and 'js/rubrica.js' in pagina

    def test_una_tarea_sin_rubrica_sigue_igual(self, professor_client, course):
        crear(professor_client, course)
        assert Activity.objects.get().rubric_version is None

    def test_elige_una_rubrica(self, professor_client, course, professor):
        rubrica = make_rubric(professor)
        crear(professor_client, course, rubric=rubrica.pk)
        assert Activity.objects.get().rubric_version == rubrica.current_version

    def test_no_acepta_la_rubrica_de_otro_docente(self, professor_client, course):
        ajena = make_rubric(ProfessorFactory())
        response = crear(professor_client, course, rubric=ajena.pk)
        assert 'rubric' in response.context['form'].errors and not Activity.objects.exists()

    def test_no_acepta_la_rubrica_de_otro_docente_de_la_misma_organizacion(self, professor_client, course):
        ajena = make_rubric(ProfessorFactory(), organization=course.organization)
        response = crear(professor_client, course, rubric=ajena.pk)
        assert 'rubric' in response.context['form'].errors and not Activity.objects.exists()

    def test_quitarla_antes_de_calificar(self, professor_client, course):
        actividad = rubric_activity(course)
        editar(professor_client, actividad, rubric='')
        actividad.refresh_from_db()
        assert actividad.rubric_version is None

    def test_al_editar_la_rubrica_aparece_elegida(self, professor_client, course):
        actividad = rubric_activity(course)
        form = professor_client.get(reverse('grades:activity_update', args=[actividad.pk])).context['form']
        assert form.initial['rubric'] == actividad.rubric_version.rubric_id

    def test_una_rubrica_archivada_en_uso_se_sigue_ofreciendo_a_su_actividad(self, professor_client, course):
        actividad = rubric_activity(course)
        library.set_archived(actividad.rubric_version.rubric, True)
        form = professor_client.get(reverse('grades:activity_update', args=[actividad.pk])).context['form']
        assert actividad.rubric_version.rubric in form.fields['rubric'].queryset
        editar(professor_client, actividad, rubric=actividad.rubric_version.rubric_id, title='Otro título')
        actividad.refresh_from_db()
        assert actividad.title == 'Otro título' and actividad.rubric_version is not None

    @pytest.mark.parametrize('tipo', ['quiz'])
    def test_un_quiz_no_lleva_rubrica(self, professor_client, course, professor, tipo):
        response = crear(professor_client, course, type=tipo, rubric=make_rubric(professor).pk)
        assert 'rubric' in response.context['form'].errors

    def test_un_examen_en_linea_no_lleva_rubrica(self, professor_client, course, professor):
        from apps.quizzes.services.exams import enable_online

        examen = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        enable_online(examen)
        response = editar(professor_client, examen, type='exam', rubric=make_rubric(professor).pk)
        assert 'rubric' in response.context['form'].errors

    def test_un_examen_a_mano_si_puede_llevarla(self, professor_client, course, professor):
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM, published=False)
        editar(professor_client, examen, type='exam', rubric=make_rubric(professor).pk)
        examen.refresh_from_db()
        assert examen.rubric_version is not None


class TestProyecto:
    def test_exige_rubrica(self, professor_client, course):
        response = crear(professor_client, course, type='project')
        assert 'Un proyecto se califica con rúbrica' in response.context['form'].errors['rubric'][0] and not Activity.objects.exists()

    def test_con_rubrica_se_crea(self, professor_client, course, professor):
        crear(professor_client, course, type='project', rubric=make_rubric(professor).pk)
        assert Activity.objects.get().type == Activity.Type.PROJECT

    def test_no_se_publica_sin_rubrica(self, course):
        proyecto = ActivityFactory(course=course, type=Activity.Type.PROJECT, published=False, rubric_version=None)
        proyecto.published = True
        with pytest.raises(ValidationError, match='necesita una rúbrica'):
            proyecto.save()

    def test_un_proyecto_que_ya_estaba_publicado_sin_rubrica_se_puede_seguir_guardando(self, course):
        proyecto = ActivityFactory(course=course, type=Activity.Type.PROJECT, rubric_version=None, published=False)
        Activity.objects.filter(pk=proyecto.pk).update(published=True)  # como quedó antes de que existieran las rúbricas
        proyecto.refresh_from_db()
        proyecto.title = 'Otro título'
        proyecto.save()
        assert Activity.objects.get(pk=proyecto.pk).title == 'Otro título'

    def test_la_fabrica_de_pruebas_le_da_rubrica_a_los_proyectos(self, course):
        assert ActivityFactory(course=course, type=Activity.Type.PROJECT).rubric_version is not None
        assert ActivityFactory(course=course, type=Activity.Type.HOMEWORK).rubric_version is None

    def test_con_rubrica_si_se_publica(self, course):
        proyecto = rubric_activity(course, published=False)
        proyecto.type = Activity.Type.PROJECT
        proyecto.published = True
        proyecto.save()
        assert Activity.objects.get(pk=proyecto.pk).published

    def test_una_tarea_se_publica_sin_rubrica(self, course):
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, published=False)
        tarea.published = True
        tarea.save()
        assert tarea.published


class TestVersiones:
    def test_una_actividad_nueva_toma_la_version_vigente(self, professor_client, course, professor):
        rubrica = make_rubric(professor)
        library.save_rubric(rubrica, editor.validate(editor.draft_from_version(rubrica.current_version))[1])
        crear(professor_client, course, rubric=rubrica.pk)
        assert Activity.objects.get().rubric_version == rubrica.current_version

    def test_editar_la_actividad_no_la_pasa_a_otra_version(self, professor_client, course, enrollment):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        grading.grade_with_rubric(actividad, enrollment.student, choices=niveles(actividad, 0, 0))
        library.save_rubric(rubrica, editor.validate(editor.draft_from_version(rubrica.current_version))[1])
        editar(professor_client, actividad, rubric=rubrica.pk, title='Cambio de título')
        actividad.refresh_from_db()
        assert actividad.title == 'Cambio de título' and actividad.rubric_version.number == 1

    def test_no_cambia_ni_quita_la_rubrica_si_ya_califico(self, professor_client, course, enrollment, professor):
        actividad = rubric_activity(course)
        grading.grade_with_rubric(actividad, enrollment.student, choices=niveles(actividad, 0, 0))
        otra = make_rubric(professor, name='Otra')
        for valor in (otra.pk, ''):
            response = editar(professor_client, actividad, rubric=valor)
            assert 'no se puede cambiar' in response.context['form'].errors['rubric'][0]
        actividad.refresh_from_db()
        assert actividad.rubric_version.rubric.name == 'Ensayo'


class TestDuplicarGrupo:
    def test_las_actividades_copiadas_siguen_con_su_rubrica(self, course):
        actividad = rubric_activity(course)
        ciclo = AcademicYearFactory(organization=course.organization)
        copia = clone_course(course, ciclo, code='COPIA-1')
        assert copia.activities.get().rubric_version == actividad.rubric_version

    def test_las_que_no_tenian_rubrica_siguen_sin_ella(self, course):
        ActivityFactory(course=course)
        ciclo = AcademicYearFactory(organization=course.organization)
        assert clone_course(course, ciclo, code='COPIA-2').activities.get().rubric_version is None

    def test_la_copia_no_arrastra_calificaciones(self, course, enrollment):
        actividad = rubric_activity(course)
        grading.grade_with_rubric(actividad, enrollment.student, choices=niveles(actividad, 0, 0))
        ciclo = AcademicYearFactory(organization=course.organization)
        copia = clone_course(course, ciclo, code='COPIA-3').activities.get()
        assert not copia.grades.exists() and copia.rubric_version == actividad.rubric_version
