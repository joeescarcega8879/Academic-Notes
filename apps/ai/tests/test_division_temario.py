"""División del temario en semanas con IA (T3): se propone, el docente la revisa y solo entonces reemplaza sus semanas."""

import pytest
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.ai import split_generation as split
from apps.ai.models import AIDraft, AIRequest
from apps.ai.providers import ProviderError, fake
from apps.grades.tests.factories import ActivityFactory
from apps.organizations.models import Organization
from apps.organizations.services import teaching_organization
from apps.syllabus.models import SyllabusWeek
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

TEXTO = (
    'Curso de biología. Unidad 1. La célula, unidad de la vida: ribosomas, mitocondria y núcleo. '
    'Unidad 2. Organelos celulares: cloroplastos, aparato de Golgi y lisosomas. Evaluación: examen parcial al final.'
)


@pytest.fixture(autouse=True)
def proveedor():
    fake.PROVIDER.reset()
    fake.PROVIDER.tier = 'fake'
    yield fake.PROVIDER
    fake.PROVIDER.reset()
    fake.PROVIDER.tier = 'fake'


@pytest.fixture
def plus(professor):
    org = teaching_organization(professor)
    org.plan, org.ai_enabled = Organization.Plan.TEACHER_PLUS, True
    org.save()
    return org


@pytest.fixture
def temario(course, plus):
    return SyllabusFactory(course=course, text=TEXTO)


def semana(**cambios):
    base = {
        'titulo': 'La célula', 'temas': ['Ribosomas', 'Mitocondria', 'Núcleo'], 'objetivos': 'Conocer la célula',
        'actividades': ['Examen parcial'], 'inicio_texto': 'Unidad 1. La célula, unidad de la vida',
    }
    return {**base, **cambios}


def programar(*semanas):
    fake.PROVIDER.responses.append({'semanas': list(semanas)})


def pedir(client, course, callbacks, **extra):
    with callbacks(execute=True):
        return client.post(reverse('ai:split_generate', args=[course.pk]), extra)


def pagina(client, course, draft=None):
    suffix = f'?ia={draft.pk}' if draft else ''
    return client.get(reverse('syllabus:index', args=[course.pk]) + suffix).content.decode()


def mensajes(respuesta):
    return ' '.join(str(m) for m in respuesta.wsgi_request._messages)


class TestInterpretar:
    def test_semanas_limpias_con_el_inicio_que_si_esta_en_el_texto(self):
        semanas = split.parse_weeks({'semanas': [semana(), semana(titulo='Organelos', inicio_texto='Texto que no está en el temario')]}, TEXTO)
        assert semanas[0] == {
            'title': 'La célula', 'topics': 'Ribosomas\nMitocondria\nNúcleo', 'objectives': 'Conocer la célula',
            'assessment': 'Examen parcial', 'source': 'Unidad 1. La célula, unidad de la vida',
        }
        assert semanas[1]['title'] == 'Organelos' and semanas[1]['source'] == ''

    def test_descarta_lo_vacio_y_lo_que_no_es_una_semana(self):
        semanas = split.parse_weeks({'semanas': [semana(titulo='', temas=[]), 'basura', None, semana(titulo='', temas=['Solo tema'])]}, TEXTO)
        assert [s['topics'] for s in semanas] == ['Solo tema']

    def test_recorta_titulos_y_limita_las_semanas(self):
        semanas = split.parse_weeks({'semanas': [semana(titulo='x' * 500)] * 70}, TEXTO)
        assert len(semanas) == 60 and len(semanas[0]['title']) == 200

    @pytest.mark.parametrize('basura', [None, [], 'texto', {'semanas': 'no'}, {'otra': 1}])
    def test_respuesta_que_no_es_una_lista(self, basura):
        assert split.parse_weeks(basura, TEXTO) == []

    def test_cuantas_semanas_dura_el_curso(self, temario):
        assert split.clean_params(QueryDict('weeks=16'), temario) == {'weeks': 16}
        assert split.clean_params(QueryDict(''), temario) == {'weeks': None}
        for malo in ('0', '61', 'mucho'):
            with pytest.raises(split.RequestError):
                split.clean_params(QueryDict(f'weeks={malo}'), temario)

    def test_un_temario_sin_texto_suficiente_o_demasiado_largo(self, temario):
        temario.text = 'Corto'
        with pytest.raises(split.RequestError, match='texto suficiente'):
            split.clean_params({}, temario)
        temario.text = 'x' * 60_001
        with pytest.raises(split.RequestError, match='demasiado largo'):
            split.clean_params({}, temario)


class TestFlujo:
    def test_propone_y_espera_en_la_pantalla_del_temario(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        programar(semana(), semana(titulo='Organelos', temas=['Cloroplastos'], inicio_texto='Unidad 2. Organelos celulares'))
        respuesta = pedir(professor_client, course, django_capture_on_commit_callbacks, weeks='16')
        draft = AIDraft.objects.get()
        assert respuesta.url == f'{reverse("syllabus:index", args=[course.pk])}?ia={draft.pk}'
        assert draft.kind == AIDraft.Kind.SYLLABUS_SPLIT and draft.status == AIDraft.Status.READY and draft.params == {'weeks': 16}
        assert AIRequest.objects.get().kind == AIRequest.Kind.SYLLABUS_SPLIT
        recibido = fake.PROVIDER.calls[0]
        assert 'Unidad 1. La célula' in recibido['prompt'] and 'dura 16 semanas' in recibido['prompt']
        html = pagina(professor_client, course, draft)
        assert 'La IA propone 2 semanas' in html and 'Usar estas semanas' in html and 'Del texto: «Unidad 1. La célula, unidad de la vida…»' in html
        assert 'value="16"' in html
        assert SyllabusWeek.objects.count() == 0  # nada se guarda hasta que el docente acepte

    def test_mientras_genera_la_pagina_espera(self, professor_client, course, temario):
        professor_client.post(reverse('ai:split_generate', args=[course.pk]))
        draft = AIDraft.objects.get()
        html = pagina(professor_client, course, draft)
        assert 'Pensando cómo dividir' in html and reverse('ai:draft_status', args=[draft.pk]) in html
        assert professor_client.get(reverse('ai:draft_status', args=[draft.pk])).json() == {'busy': True}

    def test_aceptar_reemplaza_las_semanas(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        vieja = SyllabusWeekFactory(syllabus=temario, position=1, title='Vieja')
        actividad = ActivityFactory(course=course, syllabus_week=vieja)
        programar(semana(), semana(titulo='Organelos', temas=['Cloroplastos'], actividades=[]))
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        respuesta = professor_client.post(reverse('syllabus:index', args=[course.pk]), {'action': 'ai_split_apply', 'draft': draft.pk})
        assert respuesta.status_code == 302
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.APPLIED and draft.applied_by == course.professor
        assert [(w.position, w.title) for w in temario.weeks.all()] == [(1, 'La célula'), (2, 'Organelos')]
        assert temario.weeks.first().assessment == 'Examen parcial'
        actividad.refresh_from_db()
        assert actividad.syllabus_week is None  # igual que con «Detectar semanas»
        assert 'La IA propone' not in pagina(professor_client, course, draft)

    def test_no_gracias_no_cambia_nada(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        SyllabusWeekFactory(syllabus=temario, position=1, title='Mía')
        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        professor_client.post(reverse('syllabus:index', args=[course.pk]), {'action': 'ai_split_discard', 'draft': draft.pk})
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.DISCARDED and [w.title for w in temario.weeks.all()] == ['Mía']

    def test_la_propuesta_aceptada_no_se_aplica_dos_veces(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        datos = {'action': 'ai_split_apply', 'draft': draft.pk}
        professor_client.post(reverse('syllabus:index', args=[course.pk]), datos)
        temario.weeks.update(title='Editada por el docente')
        respuesta = professor_client.post(reverse('syllabus:index', args=[course.pk]), datos)
        assert 'ya no se puede modificar' in mensajes(respuesta)
        assert temario.weeks.get().title == 'Editada por el docente'

    def test_si_falla_se_explica_y_se_puede_reintentar(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('caído', retryable=True)
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED
        html = pagina(professor_client, course, draft)
        assert 'No se pudo proponer las semanas' in html and 'No se pudo completar la solicitud' in html
        fake.PROVIDER.error = None
        programar(semana())
        with django_capture_on_commit_callbacks(execute=True):
            respuesta = professor_client.post(reverse('syllabus:index', args=[course.pk]), {'action': 'ai_split_retry', 'draft': draft.pk})
        assert respuesta.url.endswith(f'?ia={draft.pk}')
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.READY and len(draft.items) == 1

    def test_una_respuesta_inutil_falla_con_motivo(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        programar(semana(titulo='', temas=[]))
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        assert 'no pudo dividir' in AIDraft.objects.get().error

    def test_volver_a_proponer_hace_otra_solicitud(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        programar(semana(titulo='Otra'), semana(titulo='Y otra'))
        pedir(professor_client, course, django_capture_on_commit_callbacks, weeks='8')
        assert AIDraft.objects.count() == 2 and AIRequest.objects.count() == 2

    def test_con_una_clave_gratuita_si_funciona(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        fake.PROVIDER.tier = 'free'
        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        assert AIDraft.objects.get().status == AIDraft.Status.READY


class TestLimites:
    def test_sin_plan_plus_no_se_crea_nada(self, professor_client, professor, course, temario, django_capture_on_commit_callbacks):
        org = teaching_organization(professor)
        org.plan = Organization.Plan.TEACHER
        org.save()
        respuesta = pedir(professor_client, course, django_capture_on_commit_callbacks)
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == [] and 'plan Plus' in mensajes(respuesta)

    def test_el_boton_sale_apagado_y_dice_por_que(self, professor_client, professor, course, temario):
        org = teaching_organization(professor)
        org.ai_enabled = False
        org.save()
        html = pagina(professor_client, course)
        assert 'Proponer semanas con IA' in html and 'La IA está desactivada' in html

    def test_el_boton_esta_activo_con_plus(self, professor_client, course, temario):
        html = pagina(professor_client, course)
        assert 'Proponer semanas con IA' in html and 'desactivada' not in html

    def test_un_temario_sin_texto_no_se_puede_dividir(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        temario.text = 'Corto'
        temario.save()
        respuesta = pedir(professor_client, course, django_capture_on_commit_callbacks)
        assert AIDraft.objects.count() == 0 and 'texto suficiente' in mensajes(respuesta)

    def test_sin_temario_es_404(self, professor_client, course, plus, django_capture_on_commit_callbacks):
        assert pedir(professor_client, course, django_capture_on_commit_callbacks).status_code == 404

    def test_semanas_invalidas(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        respuesta = pedir(professor_client, course, django_capture_on_commit_callbacks, weeks='999')
        assert AIDraft.objects.count() == 0 and 'entre 1 y 60' in mensajes(respuesta)


class TestAcceso:
    def test_la_propuesta_de_otro_docente_es_404(self, professor_client, course, temario, django_capture_on_commit_callbacks):
        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert otro.post(reverse('syllabus:index', args=[course.pk]), {'action': 'ai_split_apply', 'draft': draft.pk}).status_code == 404
        assert otro.post(reverse('ai:split_generate', args=[course.pk])).status_code == 404

    def test_un_alumno_no_puede(self, student_client, course, temario):
        assert student_client.post(reverse('ai:split_generate', args=[course.pk])).status_code in (302, 403)
        assert AIDraft.objects.count() == 0

    def test_una_propuesta_de_otro_grupo_no_se_aplica_aqui(self, professor_client, professor, course, temario, django_capture_on_commit_callbacks):
        from apps.courses.tests.factories import CourseFactory

        programar(semana())
        pedir(professor_client, course, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        otro = CourseFactory(professor=professor)
        SyllabusFactory(course=otro, text=TEXTO)
        respuesta = professor_client.post(reverse('syllabus:index', args=[otro.pk]), {'action': 'ai_split_apply', 'draft': draft.pk})
        assert respuesta.status_code == 404
