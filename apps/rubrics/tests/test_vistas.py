"""Las pantallas de la biblioteca: lista, editor, detalle y acciones."""

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.organizations.services import teaching_organization
from apps.rubrics.models import Rubric
from apps.rubrics.services import grading
from apps.rubrics.tests.factories import choices_for, make_rubric, rubric_activity
from apps.rubrics.tests.test_editor import formulario

pytestmark = pytest.mark.django_db


def post_editor(client, url, **cambios):
    return client.post(url, formulario(**cambios))


class TestLista:
    def test_vacia_ofrece_las_plantillas(self, professor_client):
        pagina = professor_client.get(reverse('rubrics:list')).content.decode()
        assert 'Todavía no tienes rúbricas' in pagina
        for clave in ('ensayo', 'exposicion', 'proyecto', 'portafolio'):
            assert f'plantilla={clave}' in pagina

    def test_muestra_las_rubricas_con_su_uso(self, professor_client, course):
        actividad = rubric_activity(course)
        pagina = professor_client.get(reverse('rubrics:list')).content.decode()
        assert actividad.rubric_version.rubric.name in pagina and 'Usada en 1 actividad' in pagina and '12 pts' in pagina

    def test_no_muestra_las_de_otros(self, professor_client):
        make_rubric(ProfessorFactory(), name='Ajena')
        assert 'Ajena' not in professor_client.get(reverse('rubrics:list')).content.decode()

    def test_no_muestra_las_de_otro_docente_de_la_misma_organizacion(self, professor_client, professor):
        make_rubric(ProfessorFactory(), name='Ajena', organization=teaching_organization(professor))
        assert 'Ajena' not in professor_client.get(reverse('rubrics:list')).content.decode()

    def test_busca_y_filtra_archivadas(self, professor_client, professor):
        make_rubric(professor, name='Exposición oral')
        archivada = make_rubric(professor, name='Vieja')
        archivada.is_archived = True
        archivada.save()
        assert 'Exposición oral' in professor_client.get(reverse('rubrics:list'), {'q': 'EXPOSICION'}).content.decode()
        assert 'Vieja' not in professor_client.get(reverse('rubrics:list')).content.decode()
        assert 'Vieja' in professor_client.get(reverse('rubrics:list'), {'archivadas': '1'}).content.decode()
        assert 'Ninguna rúbrica coincide' in professor_client.get(reverse('rubrics:list'), {'q': 'zzz'}).content.decode()

    def test_el_menu_la_ofrece_al_docente_y_no_al_alumno(self, professor_client, student_client, enrollment):
        assert reverse('rubrics:list') in professor_client.get(reverse('rubrics:list')).content.decode()
        assert reverse('rubrics:list') not in student_client.get(reverse('student_dashboard')).content.decode()


class TestCrear:
    def test_el_formulario_en_blanco(self, professor_client):
        pagina = professor_client.get(reverse('rubrics:create')).content.decode()
        assert pagina.count('data-criterion') >= 3 and 'name="level_3"' in pagina and 'js/rubrica.js' in pagina
        assert 'name="levels" value="4"' in pagina and 'name="criteria" value="3"' in pagina

    def test_una_plantilla_llega_rellena(self, professor_client):
        pagina = professor_client.get(reverse('rubrics:create'), {'plantilla': 'ensayo'}).content.decode()
        assert 'value="Ensayo argumentativo"' in pagina and 'Argumentos' in pagina and 'Tres o más argumentos' in pagina

    def test_una_plantilla_inexistente_cae_en_blanco(self, professor_client):
        assert professor_client.get(reverse('rubrics:create'), {'plantilla': 'x'}).status_code == 200

    def test_crea_y_lleva_al_detalle(self, professor_client, professor):
        response = post_editor(professor_client, reverse('rubrics:create'), criterios=(('Tesis', ('4', '2')), ('Fuentes', ('3', '0'))))
        rubrica = Rubric.objects.get()
        assert response.status_code == 302 and response.url == rubrica.get_absolute_url()
        assert (rubrica.author, rubrica.current_version.max_points) == (professor, 7)

    def test_los_errores_se_muestran_y_no_se_pierde_lo_escrito(self, professor_client):
        response = post_editor(professor_client, reverse('rubrics:create'), nombre='', criterios=(('Tesis', ('4', 'x')),))
        pagina = response.content.decode()
        assert response.status_code == 200 and not Rubric.objects.exists()
        assert 'Ponle un nombre' in pagina and 'los puntos deben ser un número' in pagina
        assert 'value="Tesis"' in pagina and 'value="x"' in pagina

    def test_el_alumno_no_crea(self, student_client, enrollment):
        assert student_client.post(reverse('rubrics:create'), formulario()).status_code == 302
        assert not Rubric.objects.exists()


class TestEditar:
    def test_el_formulario_trae_lo_guardado(self, professor_client, professor):
        rubrica = make_rubric(professor)
        pagina = professor_client.get(reverse('rubrics:update', args=[rubrica.pk])).content.decode()
        assert 'value="Ensayo"' in pagina and 'value="Criterio 2"' in pagina and 'Esta rúbrica ya se usó' not in pagina

    def test_guarda_los_cambios(self, professor_client, professor):
        rubrica = make_rubric(professor)
        response = post_editor(professor_client, reverse('rubrics:update', args=[rubrica.pk]), nombre='Cambiada')
        rubrica.refresh_from_db()
        assert response.url == rubrica.get_absolute_url() and rubrica.name == 'Cambiada' and rubrica.versions.count() == 1

    def test_avisa_y_crea_version_si_ya_se_califico(self, professor_client, course, enrollment):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        grading.grade_with_rubric(actividad, enrollment.student, choices=choices_for(actividad.rubric_version))
        pagina = professor_client.get(reverse('rubrics:update', args=[rubrica.pk])).content.decode()
        assert 'Esta rúbrica ya se usó para calificar' in pagina and 'Guardar como versión 2' in pagina
        response = post_editor(professor_client, reverse('rubrics:update', args=[rubrica.pk]), nombre='Nueva')
        assert rubrica.versions.count() == 2
        assert 'versión 2' in professor_client.get(response.url).content.decode()

    def test_ajena_es_404(self, professor_client):
        rubrica = make_rubric(ProfessorFactory())
        assert professor_client.get(reverse('rubrics:update', args=[rubrica.pk])).status_code == 404
        assert post_editor(professor_client, reverse('rubrics:update', args=[rubrica.pk]), nombre='Robada').status_code == 404
        rubrica.refresh_from_db()
        assert rubrica.name == 'Ensayo'

    def test_un_error_no_cambia_nada(self, professor_client, professor):
        rubrica = make_rubric(professor)
        post_editor(professor_client, reverse('rubrics:update', args=[rubrica.pk]), nombre='')
        rubrica.refresh_from_db()
        assert rubrica.name == 'Ensayo' and rubrica.current_version.criteria.count() == 2


class TestDetalle:
    def test_muestra_la_cuadricula_y_donde_se_usa(self, professor_client, course):
        actividad = rubric_activity(course)
        rubrica = actividad.rubric_version.rubric
        pagina = professor_client.get(rubrica.get_absolute_url()).content.decode()
        assert 'Excelente del criterio 1' in pagina and actividad.title in pagina and course.name in pagina
        assert reverse('rubrics:delete', args=[rubrica.pk]) not in pagina  # en uso: no se borra

    def test_sin_uso_ofrece_eliminar(self, professor_client, professor):
        rubrica = make_rubric(professor)
        pagina = professor_client.get(rubrica.get_absolute_url()).content.decode()
        assert 'Ninguna actividad la usa todavía' in pagina and reverse('rubrics:delete', args=[rubrica.pk]) in pagina

    def test_ajena_es_404(self, professor_client):
        assert professor_client.get(make_rubric(ProfessorFactory()).get_absolute_url()).status_code == 404


class TestAcciones:
    def test_duplicar(self, professor_client, professor):
        rubrica = make_rubric(professor)
        response = professor_client.post(reverse('rubrics:duplicate', args=[rubrica.pk]))
        copia = Rubric.objects.exclude(pk=rubrica.pk).get()
        assert response.url == reverse('rubrics:update', args=[copia.pk]) and copia.name == 'Ensayo (copia)'

    def test_archivar_y_restaurar(self, professor_client, professor):
        rubrica = make_rubric(professor)
        assert professor_client.post(reverse('rubrics:archive', args=[rubrica.pk])).url == reverse('rubrics:list')
        rubrica.refresh_from_db()
        assert rubrica.is_archived
        assert professor_client.post(reverse('rubrics:archive', args=[rubrica.pk])).url == rubrica.get_absolute_url()
        rubrica.refresh_from_db()
        assert not rubrica.is_archived

    def test_eliminar(self, professor_client, professor):
        rubrica = make_rubric(professor)
        assert professor_client.post(reverse('rubrics:delete', args=[rubrica.pk])).url == reverse('rubrics:list')
        assert not Rubric.objects.exists()

    def test_no_elimina_una_en_uso(self, professor_client, course):
        rubrica = rubric_activity(course).rubric_version.rubric
        response = professor_client.post(reverse('rubrics:delete', args=[rubrica.pk]), follow=True)
        assert Rubric.objects.filter(pk=rubrica.pk).exists() and 'en uso' in response.content.decode()

    @pytest.mark.parametrize('nombre', ['duplicate', 'archive', 'delete'])
    def test_las_acciones_son_solo_post_y_solo_del_dueno(self, professor_client, professor, nombre):
        propia = make_rubric(professor)
        assert professor_client.get(reverse(f'rubrics:{nombre}', args=[propia.pk])).status_code == 405
        ajena = make_rubric(ProfessorFactory())
        assert professor_client.post(reverse(f'rubrics:{nombre}', args=[ajena.pk])).status_code == 404
        assert Rubric.objects.filter(pk=ajena.pk, is_archived=False).exists()


class TestOtroDocenteDeLaMismaOrganizacion:
    @pytest.mark.parametrize('nombre', ['detail', 'update', 'duplicate', 'archive', 'delete'])
    def test_su_rubrica_es_404(self, professor_client, professor, nombre):
        ajena = make_rubric(ProfessorFactory(), organization=teaching_organization(professor))
        url = reverse(f'rubrics:{nombre}', args=[ajena.pk])
        respuesta = professor_client.get(url) if nombre in ('detail', 'update') else professor_client.post(url)
        assert respuesta.status_code == 404
        assert Rubric.objects.filter(pk=ajena.pk, is_archived=False).exists()
