"""Tareas y proyectos con IA (T4): tres alternativas, criterios que suman los puntos y nada existe hasta que el docente crea una."""

from decimal import Decimal

import pytest
from django.http import QueryDict
from django.test import Client
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory
from apps.ai import assignment_generation as gen
from apps.ai import drafts
from apps.ai.models import AIDraft, AIRequest
from apps.ai.providers import ProviderError, fake
from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.grades.models import Activity
from apps.organizations.models import Organization
from apps.organizations.services import teaching_organization
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

SEMANA_1 = 'Ribosomas: síntesis de proteínas\nMitocondria: producción de energía en forma de ATP\nNúcleo: guarda el ADN'
SEMANA_2 = 'Cloroplastos y fotosíntesis\nAparato de Golgi: empaca y envía proteínas'


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
def semanas(course):
    temario = SyllabusFactory(course=course)
    return (
        SyllabusWeekFactory(syllabus=temario, position=1, title='La célula', topics=SEMANA_1),
        SyllabusWeekFactory(syllabus=temario, position=2, title='Organelos', topics=SEMANA_2),
    )


def alternativa(**cambios):
    base = {
        'titulo': 'Mapa conceptual de los organelos',
        'descripcion': 'Elabora un mapa conceptual que relacione cinco organelos con su función.',
        'entregable': 'Un PDF o una foto legible del mapa.',
        'criterios': [
            {'nombre': 'Organelos y funciones', 'descripcion': 'Cinco organelos con su función.', 'porcentaje': 40},
            {'nombre': 'Relaciones', 'descripcion': 'Enlaces con verbos.', 'porcentaje': 30},
            {'nombre': 'Claridad', 'descripcion': 'Se entiende a simple vista.', 'porcentaje': 30},
        ],
        'cita': 'Ribosomas: síntesis de proteínas',
    }
    return {**base, **cambios}


def tres():
    return [
        alternativa(),
        alternativa(titulo='La célula como una ciudad', descripcion='Escribe una analogía de una página.', cita='Mitocondria: producción de energía en forma de ATP'),
        alternativa(titulo='Maqueta de un organelo', descripcion='Construye una maqueta con material reciclado.', cita='Cloroplastos y fotosíntesis'),
    ]


def programar(*alternativas):
    fake.PROVIDER.responses.append({'alternativas': list(alternativas)})


def formulario(**campos):
    data = QueryDict(mutable=True)
    for clave, valor in campos.items():
        if isinstance(valor, (list, tuple)):
            data.setlist(clave, [str(v) for v in valor])
        else:
            data[clave] = str(valor)
    return data


def pedir(client, course, semanas, callbacks, **extra):
    datos = {'weeks': [s.pk for s in semanas], 'type': 'homework', 'points': '10', 'difficulty': 'medium', **extra}
    with callbacks(execute=True):
        return client.post(reverse('ai:assignment_generate', args=[course.pk]), datos)


def accion(client, draft, valor, **extra):
    return client.post(reverse('ai:assignment_draft', args=[draft.pk]), {'action': valor, **extra})


def mensajes(respuesta):
    return ' '.join(str(m) for m in respuesta.wsgi_request._messages)


@pytest.fixture
def generada(professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
    programar(*tres())
    pedir(professor_client, course, [semanas[0], semanas[1]], django_capture_on_commit_callbacks)
    return AIDraft.objects.get()


class TestPuntos:
    @pytest.mark.parametrize('total, pesos', [(10, [40, 30, 30]), (10, [1, 1, 1]), (7, [50, 50]), ('2.5', [3, 1, 1, 1]), (100, [33, 33, 34])])
    def test_los_puntos_siempre_suman_el_total(self, total, pesos):
        reparto = gen.split_points(Decimal(str(total)), [Decimal(p) for p in pesos])
        assert sum(reparto) == Decimal(str(total)) and all(p > 0 for p in reparto)

    def test_reparto_por_porcentaje(self):
        assert gen.split_points(Decimal(10), [Decimal(40), Decimal(30), Decimal(30)]) == [Decimal('4.00'), Decimal('3.00'), Decimal('3.00')]


class TestPeticion:
    def test_valores_por_omision_y_saneados(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], type='otro', difficulty='x'), course)
        assert params == {
            'week_ids': [semanas[0].pk], 'type': 'homework', 'difficulty': 'medium', 'points': '10', 'instructions': '',
        }

    def test_proyecto_y_puntos_con_coma(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], type='project', points='12,5', difficulty='hard'), course)
        assert (params['type'], params['points'], params['difficulty']) == ('project', '12.5', 'hard')

    @pytest.mark.parametrize('puntos', ['0', '0,5', '-3', 'abc', '1001', 'nan'])
    def test_puntos_invalidos(self, course, semanas, puntos):
        with pytest.raises(gen.RequestError, match='puntos'):
            gen.clean_params(formulario(weeks=[semanas[0].pk], points=puntos), course)

    def test_pide_semanas_y_limita_las_instrucciones(self, course, semanas):
        with pytest.raises(gen.RequestError, match='al menos una semana'):
            gen.clean_params(formulario(points='10'), course)
        with pytest.raises(gen.RequestError, match='500'):
            gen.clean_params(formulario(weeks=[semanas[0].pk], instructions='x' * 501), course)

    def test_el_texto_enviado(self, semanas):
        prompt = gen.build_prompt({'type': 'project', 'difficulty': 'hard', 'points': '20', 'instructions': 'Individual'}, [semanas[1]])
        assert 'Cloroplastos' in prompt and 'Ribosomas' not in prompt
        assert '3 alternativas' in prompt and 'proyecto' in prompt and '20 puntos' in prompt and 'Individual' in prompt


class TestValidacion:
    PARAMS = {'points': '10', 'type': 'homework'}

    def analizar(self, alternativas, semanas, **params):
        return gen.parse_items({'alternativas': alternativas}, list(semanas), {**self.PARAMS, **params})

    def test_acepta_una_alternativa_valida(self, semanas):
        items, descartadas = self.analizar([alternativa()], semanas)
        assert descartadas == 0
        item = items[0]
        assert (item['title'], item['week'], item['week_id'], item['points'], item['type'], item['state']) == (
            'Mapa conceptual de los organelos', 1, semanas[0].pk, '10', 'homework', 'pending',
        )
        assert [c['points'] for c in item['criteria']] == ['4', '3', '3'] and item['activity_id'] is None

    def test_una_cita_que_junta_varios_temas_no_vale(self, semanas):
        junta = 'Ribosomas: síntesis de proteínas Mitocondria: producción de energía en forma de ATP'
        assert self.analizar([alternativa(cita=junta)], semanas) == ([], 1)

    def test_la_semana_la_decide_la_cita(self, semanas):
        items, _ = self.analizar([alternativa(cita='Cloroplastos y fotosíntesis')], semanas)
        assert items[0]['week'] == 2

    def test_descarta_lo_que_no_cita_el_temario(self, semanas):
        assert self.analizar([alternativa(cita='Inventado por la IA'), alternativa(cita='')], semanas) == ([], 2)

    @pytest.mark.parametrize('cambios', [
        {'titulo': ''}, {'descripcion': ''}, {'entregable': ''}, {'criterios': []}, {'criterios': 'no'},
        {'criterios': [{'nombre': 'Uno', 'descripcion': '', 'porcentaje': 100}]},
        {'criterios': [{'nombre': f'C{n}', 'descripcion': '', 'porcentaje': 10} for n in range(7)]},
        {'criterios': [{'nombre': 'A', 'descripcion': '', 'porcentaje': 50}, {'nombre': '', 'descripcion': '', 'porcentaje': 50}]},
        {'criterios': [{'nombre': 'A', 'descripcion': '', 'porcentaje': 0}, {'nombre': 'B', 'descripcion': '', 'porcentaje': 100}]},
        {'criterios': [{'nombre': 'A', 'descripcion': '', 'porcentaje': -5}, {'nombre': 'B', 'descripcion': '', 'porcentaje': 105}]},
        {'criterios': [{'nombre': 'A', 'descripcion': '', 'porcentaje': True}, {'nombre': 'B', 'descripcion': '', 'porcentaje': 50}]},
        {'criterios': [{'nombre': 'A', 'descripcion': '', 'porcentaje': '50'}, {'nombre': 'B', 'descripcion': '', 'porcentaje': 50}]},
        {'criterios': ['texto', 'otro']},
    ])
    def test_descarta_alternativas_invalidas(self, semanas, cambios):
        assert self.analizar([alternativa(**cambios)], semanas) == ([], 1)

    def test_normaliza_porcentajes_que_no_suman_cien(self, semanas):
        criterios = [{'nombre': 'A', 'descripcion': '', 'porcentaje': 60}, {'nombre': 'B', 'descripcion': '', 'porcentaje': 30}]
        items, _ = self.analizar([alternativa(criterios=criterios)], semanas)
        assert [c['points'] for c in items[0]['criteria']] == ['6.67', '3.33'] and sum(Decimal(c['points']) for c in items[0]['criteria']) == 10

    def test_descarta_repetidas_y_limita_a_tres(self, semanas):
        items, descartadas = self.analizar([alternativa(), alternativa()], semanas)
        assert len(items) == 1 and descartadas == 1
        distintas = [alternativa(titulo=t) for t in ('Informe de laboratorio', 'Cartel científico', 'Podcast de cinco minutos', 'Línea del tiempo')]
        items, descartadas = self.analizar(distintas, semanas)
        assert len(items) == 3 and descartadas == 1

    @pytest.mark.parametrize('basura', [None, [], 'texto', {'alternativas': 'no'}, {'otra': 1}])
    def test_respuesta_que_no_es_una_lista(self, semanas, basura):
        assert gen.parse_items(basura, list(semanas), self.PARAMS) == ([], 0)


class TestInstrucciones:
    def test_se_arman_con_descripcion_entregable_y_criterios(self, semanas):
        item, _ = gen.parse_items({'alternativas': [alternativa()]}, list(semanas), {'points': '10', 'type': 'homework'})
        assert gen.render_instructions(item[0]) == (
            'Elabora un mapa conceptual que relacione cinco organelos con su función.\n\n'
            'Qué entregar: Un PDF o una foto legible del mapa.\n\n'
            'Criterios de calificación (10 puntos):\n'
            '- Organelos y funciones (4 pts): Cinco organelos con su función.\n'
            '- Relaciones (3 pts): Enlaces con verbos.\n'
            '- Claridad (3 pts): Se entiende a simple vista.'
        )


class TestEdicion:
    @pytest.fixture
    def item(self, semanas):
        return gen.parse_items({'alternativas': [alternativa()]}, list(semanas), {'points': '10', 'type': 'homework'})[0][0]

    def editar(self, item, **cambios):
        datos = {
            'edit_title': 'Nuevo título', 'edit_description': 'Nueva descripción', 'edit_deliverable': 'Un PDF', 'edit_points': '10',
            'edit_criterion_name': ['A', 'B'], 'edit_criterion_description': ['a', 'b'], 'edit_criterion_points': ['6', '4'],
        }
        return gen.edited_item(item, formulario(**{**datos, **cambios}))

    def test_aplica_los_cambios_y_marca_editada(self, item):
        nuevo = self.editar(item)
        assert (nuevo['title'], nuevo['description'], nuevo['deliverable'], nuevo['points'], nuevo['edited']) == ('Nuevo título', 'Nueva descripción', 'Un PDF', '10', True)
        assert nuevo['criteria'] == [{'name': 'A', 'description': 'a', 'points': '6'}, {'name': 'B', 'description': 'b', 'points': '4'}]
        assert nuevo['citation'] == item['citation'] and nuevo['week_id'] == item['week_id']

    def test_cambiar_el_total_exige_reajustar_los_criterios(self, item):
        nuevo = self.editar(item, edit_points='20', edit_criterion_points=['12', '8'])
        assert nuevo['points'] == '20'

    @pytest.mark.parametrize('puntos, mensaje', [
        (['6', '3'], 'suman 9 de 10: te falta 1 punto'), (['6', '5'], 'suman 11 de 10: te sobra 1 punto'),
        (['6', '3.5'], 'suman 9.5 de 10: te falta 0.5 puntos'),
    ])
    def test_los_criterios_deben_sumar_el_total(self, item, puntos, mensaje):
        with pytest.raises(gen.ValidationError, match=mensaje):
            self.editar(item, edit_criterion_points=puntos)

    def test_las_filas_en_blanco_quitan_criterios(self, item):
        nuevo = self.editar(
            item, edit_criterion_name=['A', 'B', '', ''], edit_criterion_description=['a', 'b', '', ''], edit_criterion_points=['6', '4', '', ''],
        )
        assert len(nuevo['criteria']) == 2

    @pytest.mark.parametrize('cambios, mensaje', [
        ({'edit_title': ' '}, 'título'), ({'edit_description': ''}, 'descripción'), ({'edit_deliverable': ''}, 'entregar'),
        ({'edit_points': 'x'}, 'puntos de la actividad'), ({'edit_points': '0'}, 'puntos de la actividad'),
        ({'edit_criterion_name': ['', 'B'], 'edit_criterion_description': ['a', 'b']}, 'nombre'),
        ({'edit_criterion_points': ['x', '4']}, 'puntos del criterio'), ({'edit_criterion_points': ['0', '10']}, 'puntos del criterio'),
        ({'edit_criterion_name': [''], 'edit_criterion_description': [''], 'edit_criterion_points': ['']}, 'al menos un criterio'),
    ])
    def test_cambios_invalidos(self, item, cambios, mensaje):
        with pytest.raises(gen.ValidationError, match=mensaje):
            self.editar(item, **cambios)


class TestPedir:
    def test_genera_tres_alternativas_por_revisar(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        programar(*tres())
        respuesta = pedir(professor_client, course, [semanas[0], semanas[1]], django_capture_on_commit_callbacks, instructions='Individual')
        draft = AIDraft.objects.get()
        assert respuesta.url == reverse('ai:assignment_draft', args=[draft.pk])
        assert draft.kind == AIDraft.Kind.ASSIGNMENTS and draft.status == AIDraft.Status.READY and len(draft.items) == 3
        assert AIRequest.objects.get().kind == AIRequest.Kind.ASSIGNMENT and AIRequest.objects.count() == 1
        assert 'Individual' in fake.PROVIDER.calls[0]['prompt']
        assert Activity.objects.count() == 0  # nada existe hasta que el docente crea una

    def test_el_texto_enviado_no_lleva_datos_de_alumnos(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        inscritos = [EnrollmentFactory(course=course) for _ in range(3)]
        programar(*tres())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        recibido = ' '.join(f"{c['system']} {c['prompt']}" for c in fake.PROVIDER.calls)
        for alta in inscritos:
            for secreto in (alta.student.first_name, alta.student.last_name, alta.student.email, alta.student.student_number):
                if secreto:
                    assert str(secreto) not in recibido
        assert not AIRequest.objects.get().contains_student_data

    def test_con_una_clave_gratuita_si_funciona(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        fake.PROVIDER.tier = 'free'
        programar(*tres())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        assert AIDraft.objects.get().status == AIDraft.Status.READY

    def test_la_pantalla_espera_mientras_genera(self, professor_client, course, plus, semanas):
        professor_client.post(reverse('ai:assignment_generate', args=[course.pk]), {'weeks': [semanas[0].pk]})
        draft = AIDraft.objects.get()
        html = professor_client.get(reverse('ai:assignment_draft', args=[draft.pk])).content.decode()
        assert 'Pensando tres alternativas' in html and reverse('ai:draft_status', args=[draft.pk]) in html
        assert professor_client.get(reverse('ai:draft_status', args=[draft.pk])).json() == {'busy': True}

    @pytest.mark.parametrize('plan, interruptor, texto', [
        (Organization.Plan.TEACHER, True, 'plan Plus'), (Organization.Plan.TEACHER_PLUS, False, 'desactivada'),
    ])
    def test_sin_plan_o_con_la_ia_apagada_no_se_crea_nada(
        self, professor_client, professor, course, semanas, plan, interruptor, texto, django_capture_on_commit_callbacks,
    ):
        org = teaching_organization(professor)
        org.plan, org.ai_enabled = plan, interruptor
        org.save()
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == [] and texto in mensajes(respuesta)
        assert respuesta.url == reverse('syllabus:index', args=[course.pk])

    def test_un_error_desde_el_formulario_vuelve_al_formulario(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, points='0', origin='form')
        assert respuesta.url == reverse('grades:activity_create', args=[course.pk]) and AIDraft.objects.count() == 0

    def test_puntos_o_semanas_invalidos_no_llaman_a_la_ia(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        pedir(professor_client, course, [], django_capture_on_commit_callbacks)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, points='5000')
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == []

    def test_si_el_proveedor_falla_se_puede_reintentar(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('caído', retryable=True)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED and set(AIRequest.objects.values_list('status', flat=True)) == {'error'}
        html = professor_client.get(reverse('ai:assignment_draft', args=[draft.pk])).content.decode()
        assert 'No se pudo generar' in html and 'Intentar de nuevo' in html
        fake.PROVIDER.error = None
        programar(*tres())
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, draft, 'retry')
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.READY and len(draft.items) == 3

    def test_si_ninguna_cita_el_temario_falla(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        programar(alternativa(cita='Inventada'), alternativa(titulo='Otra', cita=''))
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED and 'no citaban el temario' in draft.error

    def test_un_grupo_archivado_o_ajeno_es_404(self, professor_client, course, plus, semanas, django_capture_on_commit_callbacks):
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert pedir(otro, course, semanas, django_capture_on_commit_callbacks).status_code == 404
        course.status = course.Status.ARCHIVED
        course.save()
        assert pedir(professor_client, course, semanas, django_capture_on_commit_callbacks).status_code == 404


class TestRevisar:
    def test_la_pantalla_muestra_las_alternativas(self, professor_client, generada):
        html = professor_client.get(reverse('ai:assignment_draft', args=[generada.pk])).content.decode()
        for texto in ('Mapa conceptual de los organelos', 'La célula como una ciudad', 'Maqueta de un organelo', 'Qué entregar', 'Criterios de calificación',
                      'Organelos y funciones', '4 pts', 'Cita del temario', 'Crear tarea', 'Semana 1 · La célula', 'Semana 2 · Organelos', '10 puntos'):
            assert texto in html

    def test_descartar_y_recuperar(self, professor_client, generada):
        accion(professor_client, generada, 'discard:1')
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['pending', 'discarded', 'pending']
        accion(professor_client, generada, 'restore:1')
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['pending'] * 3

    def test_descartar_las_tres_cierra_la_propuesta(self, professor_client, generada):
        for index in range(3):
            accion(professor_client, generada, f'discard:{index}')
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.DISCARDED and Activity.objects.count() == 0

    def test_editar_y_guardar(self, professor_client, generada):
        respuesta = accion(professor_client, generada, 'edit:0')
        assert respuesta.url.endswith('?editar=0#p1')
        html = professor_client.get(respuesta.url).content.decode()
        assert 'name="edit_title"' in html and 'name="edit_criterion_points"' in html and 'Agregar criterio' in html
        accion(professor_client, generada, 'save_edit:0', **{
            'edit_title': 'Mi título', 'edit_description': 'Mi descripción', 'edit_deliverable': 'Un PDF', 'edit_points': '10',
            'edit_criterion_name': ['A', 'B'], 'edit_criterion_description': ['', ''], 'edit_criterion_points': ['5', '5'],
        })
        generada.refresh_from_db()
        assert generada.items[0]['title'] == 'Mi título' and generada.items[0]['edited'] and len(generada.items[0]['criteria']) == 2

    def test_guardar_con_puntos_que_no_suman_se_queda_editando(self, professor_client, generada):
        respuesta = accion(professor_client, generada, 'save_edit:0', **{
            'edit_title': 'T', 'edit_description': 'D', 'edit_deliverable': 'E', 'edit_points': '10',
            'edit_criterion_name': ['A', 'B'], 'edit_criterion_description': ['', ''], 'edit_criterion_points': ['5', '4'],
        })
        assert respuesta.url.endswith('?editar=0#p1') and 'te falta 1 punto' in mensajes(respuesta)
        generada.refresh_from_db()
        assert generada.items[0]['title'] == 'Mapa conceptual de los organelos' and not generada.items[0]['edited']

    def test_posiciones_inexistentes_no_rompen(self, professor_client, generada):
        for valor in ('discard:99', 'edit:99', 'regen:99', 'create:99', 'create:', 'discard:abc', 'nada'):
            assert accion(professor_client, generada, valor).status_code == 302
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.READY and Activity.objects.count() == 0

    def test_regenerar_cambia_la_alternativa_y_cuenta_un_uso(self, professor_client, generada, django_capture_on_commit_callbacks):
        usos = AIRequest.objects.filter(status='ok').count()
        programar(alternativa(titulo='Informe de laboratorio', descripcion='Redacta un informe.', cita='Núcleo: guarda el ADN'))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:1')
        generada.refresh_from_db()
        assert generada.items[1]['title'] == 'Informe de laboratorio' and generada.items[1]['state'] == 'pending'
        assert AIRequest.objects.filter(status='ok').count() == usos + 1
        enviado = fake.PROVIDER.calls[-1]['prompt']
        assert 'La célula como una ciudad' in enviado and 'Mapa conceptual de los organelos' in enviado and '1 alternativa ' in enviado

    def test_si_regenerar_falla_queda_con_un_aviso(self, professor_client, generada, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('caído')
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:0')
        generada.refresh_from_db()
        assert generada.items[0]['state'] == 'pending' and 'No se pudo completar' in generada.items[0]['note']

    def test_si_regenerar_devuelve_algo_invalido(self, professor_client, generada, django_capture_on_commit_callbacks):
        programar(alternativa(cita='Inventada'))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:0')
        generada.refresh_from_db()
        assert 'no devolvió una alternativa válida' in generada.items[0]['note']


class TestCrear:
    def test_crea_la_actividad_en_borrador(self, professor_client, generada, course, semanas, professor):
        respuesta = accion(professor_client, generada, 'create:0')
        actividad = Activity.objects.get()
        assert respuesta.url == reverse('grades:activity_detail', args=[actividad.pk])
        assert (actividad.title, actividad.type, actividad.max_score, actividad.published, actividad.ai_generated, actividad.course) == (
            'Mapa conceptual de los organelos', 'homework', 10.0, False, True, course,
        )
        assert actividad.syllabus_week == semanas[0]
        assert 'Criterios de calificación (10 puntos):' in actividad.instructions and '- Organelos y funciones (4 pts)' in actividad.instructions
        assert 'Qué entregar: Un PDF o una foto legible del mapa.' in actividad.instructions
        generada.refresh_from_db()
        assert generada.items[0]['state'] == 'created' and generada.items[0]['activity_id'] == actividad.pk
        assert generada.status == AIDraft.Status.READY and generada.applied_by == professor and generada.applied_at is not None

    def test_las_demas_siguen_disponibles_y_se_pueden_crear_mas(self, professor_client, generada):
        accion(professor_client, generada, 'create:0')
        accion(professor_client, generada, 'create:2')
        assert Activity.objects.count() == 2 and Activity.objects.filter(ai_generated=True).count() == 2
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['created', 'pending', 'created']
        assert Activity.objects.get(title='Maqueta de un organelo').syllabus_week.position == 2

    def test_no_se_crea_dos_veces(self, professor_client, generada):
        accion(professor_client, generada, 'create:0')
        respuesta = accion(professor_client, generada, 'create:0')
        assert Activity.objects.count() == 1 and 'ya no se puede crear' in mensajes(respuesta)

    def test_la_propuesta_se_cierra_al_resolver_todas(self, professor_client, generada):
        accion(professor_client, generada, 'create:0')
        accion(professor_client, generada, 'discard:1')
        accion(professor_client, generada, 'discard:2')
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.APPLIED
        html = professor_client.get(reverse('ai:assignment_draft', args=[generada.pk])).content.decode()
        assert 'Cerrada' in html and 'Mapa conceptual de los organelos' in html

    def test_una_creada_no_se_descarta(self, professor_client, generada):
        accion(professor_client, generada, 'create:0')
        respuesta = accion(professor_client, generada, 'discard:0')
        generada.refresh_from_db()
        assert generada.items[0]['state'] == 'created' and 'ya se creó' in mensajes(respuesta)

    def test_terminar_descarta_el_resto(self, professor_client, generada, course):
        accion(professor_client, generada, 'create:1')
        respuesta = accion(professor_client, generada, 'finish')
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.APPLIED and [i['state'] for i in generada.items] == ['discarded', 'created', 'discarded']
        assert respuesta.url == reverse('syllabus:index', args=[course.pk])

    def test_terminar_sin_crear_nada_descarta_la_propuesta(self, professor_client, generada):
        accion(professor_client, generada, 'finish')
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.DISCARDED and Activity.objects.count() == 0

    def test_lo_editado_es_lo_que_se_crea(self, professor_client, generada):
        accion(professor_client, generada, 'save_edit:0', **{
            'edit_title': 'Título corregido', 'edit_description': 'Descripción corregida', 'edit_deliverable': 'Un PDF', 'edit_points': '8',
            'edit_criterion_name': ['A', 'B'], 'edit_criterion_description': ['', ''], 'edit_criterion_points': ['5', '3'],
        })
        accion(professor_client, generada, 'create:0')
        actividad = Activity.objects.get()
        assert (actividad.title, actividad.max_score) == ('Título corregido', 8.0)
        assert 'Criterios de calificación (8 puntos):' in actividad.instructions and '- A (5 pts)' in actividad.instructions

    def test_un_proyecto_se_crea_como_proyecto(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        programar(*tres())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, type='project', points='20')
        draft = AIDraft.objects.get()
        accion(professor_client, draft, 'create:0')
        actividad = Activity.objects.get()
        assert (actividad.type, actividad.max_score) == ('project', 20.0)
        assert 'proyecto' in fake.PROVIDER.calls[0]['prompt']

    def test_si_la_semana_ya_no_existe_se_crea_sin_semana(self, professor_client, generada, semanas):
        semanas[0].delete()
        accion(professor_client, generada, 'create:0')
        assert Activity.objects.get().syllabus_week is None

    def test_un_grupo_archivado_no_recibe_actividades(self, professor_client, generada, course):
        course.status = course.Status.ARCHIVED
        course.save()
        respuesta = accion(professor_client, generada, 'create:0')
        assert Activity.objects.count() == 0 and 'archivado' in mensajes(respuesta)

    def test_el_detalle_marca_la_actividad_como_redactada_con_ia(self, professor_client, generada):
        accion(professor_client, generada, 'create:0')
        actividad = Activity.objects.get()
        assert 'Redactada con IA' in professor_client.get(reverse('grades:activity_detail', args=[actividad.pk])).content.decode()
        otra = Activity.objects.create(course=actividad.course, title='A mano', criterion=actividad.criterion)
        assert 'Redactada con IA' not in professor_client.get(reverse('grades:activity_detail', args=[otra.pk])).content.decode()


class TestPantallas:
    def test_el_editor_de_la_semana_ofrece_el_boton_y_las_propuestas_pendientes(self, professor_client, generada, course):
        html = professor_client.get(reverse('syllabus:index', args=[course.pk]) + '?semana=2').content.decode()
        assert 'Generar tarea con IA' in html and 'modal-ai-assignment' in html and 'Revisar 3 alternativas de tarea' in html
        assert reverse('ai:assignment_draft', args=[generada.pk]) in html

    def test_la_semana_abierta_viene_marcada_en_el_panel(self, professor_client, plus, course, semanas):
        html = professor_client.get(reverse('syllabus:index', args=[course.pk]) + '?semana=2').content.decode()
        panel = html[html.index('id="modal-ai-assignment"'):]
        assert f'value="{semanas[1].pk}" checked' in panel and f'value="{semanas[0].pk}" checked' not in panel

    def test_el_boton_dice_por_que_esta_apagado(self, professor_client, professor, course, semanas):
        org = teaching_organization(professor)
        org.plan = Organization.Plan.FREE
        org.save()
        html = professor_client.get(reverse('syllabus:index', args=[course.pk])).content.decode()
        assert 'Generar tarea con IA' in html and 'plan Plus' in html and 'modal-ai-assignment' not in html

    def test_nueva_actividad_ofrece_redactar_con_ia(self, professor_client, plus, course, semanas):
        html = professor_client.get(reverse('grades:activity_create', args=[course.pk]) + f'?semana={semanas[1].pk}').content.decode()
        assert 'Redactar con IA' in html and 'modal-ai-assignment' in html and 'name="origin" value="form"' in html
        assert f'value="{semanas[1].pk}" checked' in html[html.index('id="modal-ai-assignment"'):]

    def test_editar_una_actividad_no_ofrece_redactar_con_ia(self, professor_client, plus, course, semanas, activity):
        html = professor_client.get(reverse('grades:activity_update', args=[activity.pk])).content.decode()
        assert 'Redactar con IA' not in html and 'modal-ai-assignment' not in html

    def test_nueva_actividad_sin_plan_explica_el_motivo(self, professor_client, professor, course, semanas):
        org = teaching_organization(professor)
        org.plan = Organization.Plan.FREE
        org.save()
        html = professor_client.get(reverse('grades:activity_create', args=[course.pk])).content.decode()
        assert 'Redactar con IA' in html and 'plan Plus' in html and 'modal-ai-assignment' not in html


class TestAcceso:
    def test_otro_docente_no_ve_ni_toca_la_propuesta(self, generada):
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert otro.get(reverse('ai:assignment_draft', args=[generada.pk])).status_code == 404
        assert otro.post(reverse('ai:assignment_draft', args=[generada.pk]), {'action': 'create:0'}).status_code == 404
        assert otro.get(reverse('ai:draft_status', args=[generada.pk])).status_code == 404
        assert Activity.objects.count() == 0

    def test_una_propuesta_de_tareas_no_se_abre_como_de_quiz(self, professor_client, generada):
        assert professor_client.get(reverse('ai:draft', args=[generada.pk])).status_code == 404

    def test_anonimo_va_al_login(self, generada):
        assert Client().get(reverse('ai:assignment_draft', args=[generada.pk])).status_code == 302

    def test_los_demas_grupos_no_ven_las_propuestas_pendientes(self, professor_client, generada, professor):
        otro = CourseFactory(professor=professor)
        SyllabusFactory(course=otro)
        assert drafts.open_assignment_drafts(professor, generada.organization, otro).count() == 0
