"""Exámenes con IA: más preguntas y más tipos (respuesta corta, ordenar, relacionar) que un quiz, con la misma aprobación."""

import random

import pytest
from django.urls import reverse

from apps.ai import drafts
from apps.ai import quiz_generation as gen
from apps.ai.models import AIDraft
from apps.ai.providers import fake
from apps.ai.tests.test_generacion_quiz import SEMANA_1, SEMANA_2, formulario
from apps.ai.tests.test_propuestas_quiz import accion, pedir, programar
from apps.grades.models import Activity
from apps.organizations.models import Organization
from apps.organizations.services import teaching_organization
from apps.quizzes.models import Question, QuizConfig
from apps.quizzes.services import exams
from apps.quizzes.tests.factories import make_quiz
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

CITA = 'Ribosomas: síntesis de proteínas'
TODOS = ['opcion_multiple', 'verdadero_falso', 'respuesta_corta', 'ordenar', 'relacionar']


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


@pytest.fixture
def examen(course, plus):
    """Examen en borrador aplicado en línea y sin preguntas."""
    actividad = Activity.objects.create(course=course, type=Activity.Type.EXAM, title='Examen parcial', published=False, max_score=10)
    exams.enable_online(actividad)
    return actividad


def corta(**cambios):
    return {
        'tipo': 'respuesta_corta', 'pregunta': '¿Qué organelo sintetiza las proteínas?', 'respuestas': ['Ribosoma', 'Ribosomas'],
        'explicacion': 'Sintetizan proteínas.', 'cita': CITA, **cambios,
    }


def ordenar(**cambios):
    return {
        'tipo': 'ordenar', 'pregunta': 'Ordena de menor a mayor tamaño.', 'elementos': ['Molécula', 'Organelo', 'Célula', 'Tejido'],
        'explicacion': '', 'cita': CITA, **cambios,
    }


def relacionar(**cambios):
    return {
        'tipo': 'relacionar', 'pregunta': 'Relaciona cada organelo con su función.',
        'parejas': [{'izquierda': 'Ribosoma', 'derecha': 'Síntesis de proteínas'}, {'izquierda': 'Mitocondria', 'derecha': 'Energía'}],
        'explicacion': '', 'cita': CITA, **cambios,
    }


def opcion(**cambios):
    return {
        'tipo': 'opcion_multiple', 'pregunta': '¿Cuál es la función de los ribosomas?', 'opciones': ['Fabricar proteínas', 'Producir ATP', 'Guardar el ADN'],
        'correcta': 0, 'explicacion': 'Sintetizan proteínas.', 'cita': CITA, **cambios,
    }


def verdadero(**cambios):
    return {'tipo': 'verdadero_falso', 'pregunta': 'La mitocondria produce ATP.', 'verdadero': True, 'explicacion': '', 'cita': 'producción de energía en forma de ATP', **cambios}


def analizar(preguntas, semanas, *, kinds=TODOS, **extra):
    params = {'count': 10, 'mix': 'mix', 'difficulty': 'medium', 'points': '1', 'instructions': '', 'exam': True, 'kinds': kinds, **extra}
    return gen.parse_items({'preguntas': preguntas}, list(semanas), params, rng=random.Random(1))


# ── Lo que se pide ────────────────────────────────────────────────────

class TestPedido:
    def test_un_examen_admite_hasta_30_y_un_quiz_hasta_20(self, course, semanas):
        base = {'weeks': [semanas[0].pk], 'kinds': ['opcion_multiple']}
        assert gen.clean_params(formulario(**base, count=30), course, exam=True)['count'] == 30
        assert gen.clean_params(formulario(**base, count=30), course)['count'] == 10  # un quiz no llega a 30

    def test_el_examen_guarda_los_tipos_en_el_orden_del_panel(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=['relacionar', 'respuesta_corta', 'opcion_multiple', 'inventado']), course, exam=True)
        assert params['exam'] is True and params['kinds'] == ['opcion_multiple', 'respuesta_corta', 'relacionar']

    def test_un_examen_necesita_al_menos_un_tipo(self, course, semanas):
        for kinds in ([], ['inventado']):
            with pytest.raises(gen.RequestError, match='al menos un tipo'):
                gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=kinds), course, exam=True)

    def test_un_quiz_no_lleva_tipos_de_examen(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=TODOS), course)
        assert 'exam' not in params and 'kinds' not in params

    def test_el_prompt_de_un_examen_pide_los_tipos_elegidos(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=['respuesta_corta', 'ordenar'], count=15), course, exam=True)
        prompt = gen.build_prompt(params, [semanas[0]])
        assert 'Redacta 15 preguntas para un examen' in prompt and 'Respuesta corta, Ordenar' in prompt and 'repartidas de forma pareja' in prompt
        assert 'Cubre el material de forma amplia' in prompt

    def test_con_un_solo_tipo_el_prompt_lo_dice(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=['relacionar']), course, exam=True)
        assert 'solo de relacionar columnas' in gen.build_prompt(params, [semanas[0]])

    def test_el_prompt_de_un_quiz_no_cambia(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk]), course)
        prompt = gen.build_prompt(params, [semanas[0]])
        assert 'para un examen' not in prompt and 'una mezcla' in prompt and 'Cubre el material' not in prompt

    def test_regenerar_pide_el_tipo_de_la_pregunta_que_se_cambia(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk], kinds=TODOS), course, exam=True)
        assert 'solo de ordenar' in gen.build_prompt(params, [semanas[0]], count=1, mix='ordering')

    def test_solo_el_examen_recibe_las_reglas_y_el_esquema_de_los_tipos_nuevos(self):
        assert 'Ordenar («ordenar»)' in gen.system_for({'exam': True}) and 'Ordenar («ordenar»)' not in gen.system_for({})
        assert gen.system_for({'exam': True}).startswith(gen.SYSTEM)
        tipos = gen.schema_for({'exam': True})['properties']['preguntas']['items']['properties']
        assert set(tipos['tipo']['enum']) == set(TODOS) and {'respuestas', 'elementos', 'parejas'} <= set(tipos)
        quiz = gen.schema_for({})['properties']['preguntas']['items']['properties']
        assert quiz['tipo']['enum'] == ['opcion_multiple', 'verdadero_falso'] and 'parejas' not in quiz

    def test_el_esquema_del_quiz_no_se_toca(self):
        gen.schema_for({'exam': True})
        assert 'parejas' not in gen.SCHEMA['properties']['preguntas']['items']['properties']


# ── Lo que devuelve la IA ─────────────────────────────────────────────

class TestRespuestaCorta:
    def test_valida_y_guarda_las_respuestas_aceptadas(self, semanas):
        items, dropped = analizar([corta()], semanas)
        assert dropped == 0 and items[0]['kind'] == Question.Kind.SHORT_ANSWER and items[0]['true_is_correct'] is None
        assert items[0]['choices'] == [{'text': 'Ribosoma', 'correct': True}, {'text': 'Ribosomas', 'correct': True}]

    @pytest.mark.parametrize('cambios', [
        {'respuestas': []}, {'respuestas': ['']}, {'respuestas': 'Ribosoma'}, {'respuestas': [{'a': 1}]}, {'respuestas': [True]},
        {'respuestas': ['Ribosoma', 'RIBOSOMA']},  # repetidas una vez normalizadas
        {'respuestas': ['x' * 201]}, {'respuestas': [str(n) for n in range(9)]}, {'respuestas': None},
    ])
    def test_sin_respuestas_validas_se_descarta(self, semanas, cambios):
        assert analizar([corta(**cambios)], semanas) == ([], 1)

    def test_acepta_numeros(self, semanas):
        items, _ = analizar([corta(pregunta='¿Cuántas cadenas tiene el ADN?', respuestas=[2, '2.0'])], semanas)
        assert [c['text'] for c in items[0]['choices']] == ['2', '2.0']


class TestOrdenar:
    def test_guarda_los_elementos_en_el_orden_correcto_sin_revolverlos(self, semanas):
        for semilla in range(5):
            items, _ = gen.parse_items(
                {'preguntas': [ordenar()]}, list(semanas), {'count': 10, 'mix': 'mix', 'points': '1', 'exam': True, 'kinds': TODOS},
                rng=random.Random(semilla),
            )
            assert [c['text'] for c in items[0]['choices']] == ['Molécula', 'Organelo', 'Célula', 'Tejido']
        assert items[0]['kind'] == Question.Kind.ORDERING and all(c['correct'] is False for c in items[0]['choices'])

    @pytest.mark.parametrize('elementos', [['Solo uno'], [], ['A', 'a'], ['A', ''], 'A, B, C', ['A', 'B', None], [str(n) for n in range(9)], ['x' * 501, 'B']])
    def test_elementos_invalidos(self, semanas, elementos):
        assert analizar([ordenar(elementos=elementos)], semanas) == ([], 1)


class TestRelacionar:
    def test_guarda_las_parejas(self, semanas):
        items, _ = analizar([relacionar()], semanas)
        assert items[0]['kind'] == Question.Kind.MATCHING
        assert items[0]['choices'] == [
            {'text': 'Ribosoma', 'correct': False, 'match': 'Síntesis de proteínas'}, {'text': 'Mitocondria', 'correct': False, 'match': 'Energía'},
        ]

    @pytest.mark.parametrize('parejas', [
        [{'izquierda': 'A', 'derecha': 'B'}],  # una sola
        [{'izquierda': 'A', 'derecha': ''}, {'izquierda': 'C', 'derecha': 'D'}],
        [{'izquierda': 'A', 'derecha': 'B'}, {'izquierda': 'a', 'derecha': 'D'}],  # izquierda repetida
        [{'izquierda': 'A', 'derecha': 'B'}, {'izquierda': 'C', 'derecha': 'b'}],  # derecha repetida
        [{'izquierda': 'A'}, {'izquierda': 'C', 'derecha': 'D'}],
        ['A-B', 'C-D'], 'A-B', None, [{'izquierda': 'A', 'derecha': ['x']}, {'izquierda': 'C', 'derecha': 'D'}],
        [{'izquierda': 'x' * 501, 'derecha': 'B'}, {'izquierda': 'C', 'derecha': 'D'}],
    ])
    def test_parejas_invalidas(self, semanas, parejas):
        assert analizar([relacionar(parejas=parejas)], semanas) == ([], 1)


class TestTiposPermitidos:
    def test_solo_se_aceptan_los_que_el_docente_pidio(self, semanas):
        preguntas = [corta(), ordenar(), relacionar(), opcion(), verdadero()]
        items, dropped = analizar(preguntas, semanas, kinds=['respuesta_corta', 'ordenar'])
        assert [i['kind'] for i in items] == [Question.Kind.SHORT_ANSWER, Question.Kind.ORDERING] and dropped == 3

    def test_un_quiz_descarta_los_tipos_de_examen(self, semanas):
        items, dropped = gen.parse_items(
            {'preguntas': [corta(), ordenar(), relacionar(), opcion()]}, list(semanas),
            {'count': 10, 'mix': 'mix', 'points': '1'}, rng=random.Random(1),
        )
        assert [i['kind'] for i in items] == [Question.Kind.MULTIPLE_CHOICE] and dropped == 3

    def test_regenerar_solo_acepta_el_tipo_de_la_que_se_cambia(self, semanas):
        params = {'count': 10, 'mix': 'mix', 'points': '1', 'exam': True, 'kinds': TODOS}
        items, _ = gen.parse_items({'preguntas': [opcion(), ordenar()]}, list(semanas), params, mix='ordering', limit=1, rng=random.Random(1))
        assert [i['kind'] for i in items] == [Question.Kind.ORDERING]

    def test_pedir_la_mezcla_acepta_solo_opcion_multiple_y_verdadero_falso(self, semanas):
        params = {'count': 10, 'mix': 'mix', 'points': '1', 'exam': True, 'kinds': TODOS}
        items, dropped = gen.parse_items(
            {'preguntas': [corta(), opcion(), verdadero()]}, list(semanas), params, mix='mix', rng=random.Random(1),
        )
        assert [i['kind'] for i in items] == [Question.Kind.MULTIPLE_CHOICE, Question.Kind.TRUE_FALSE] and dropped == 1

    def test_las_formulas_de_las_parejas_se_reparan(self, semanas):
        items, _ = analizar([relacionar(parejas=[
            {'izquierda': '\\(\x0crac{1}{2}\\)', 'derecha': '0.5'}, {'izquierda': '\\(2\timesx\\)', 'derecha': 'doble'},
        ])], semanas)
        assert [c['text'] for c in items[0]['choices']] == [r'\(\frac{1}{2}\)', r'\(2\timesx\)']

    def test_los_tres_tipos_nuevos_tambien_citan_el_temario(self, semanas):
        for pregunta in (corta(cita='Esto no está'), ordenar(cita='Tampoco'), relacionar(cita='Menos')):
            assert analizar([pregunta], semanas) == ([], 1)

    def test_las_formulas_se_reparan_y_se_validan_en_los_tipos_nuevos(self, semanas):
        ff = '\x0c'
        items, _ = analizar([
            corta(pregunta=f'¿Cuánto vale \\({ff}rac{{1}}{{2}}\\)?', respuestas=[f'\\({ff}rac{{1}}{{2}}\\)', '0.5']),
            ordenar(pregunta=r'Ordena: \(1/2\), \(1/3\)', elementos=[r'\(1/2\)', r'\(1/3\)']),
            relacionar(parejas=[{'izquierda': r'\(2^2\)', 'derecha': '4'}, {'izquierda': r'\(3^2\)', 'derecha': '9'}]),
        ], semanas)
        assert items[0]['text'] == r'¿Cuánto vale \(\frac{1}{2}\)?' and items[0]['choices'][0]['text'] == r'\(\frac{1}{2}\)'
        assert len(items) == 3 and items[2]['choices'][0]['text'] == r'\(2^2\)'

    @pytest.mark.parametrize('pregunta', [
        corta(respuestas=[r'\(x', 'otra']),
        ordenar(elementos=[r'\(x', 'B']),
        relacionar(parejas=[{'izquierda': 'A', 'derecha': r'\(x'}, {'izquierda': 'C', 'derecha': 'D'}]),
    ])
    def test_una_formula_sin_cerrar_en_los_tipos_nuevos_descarta_la_pregunta(self, semanas, pregunta):
        assert analizar([pregunta], semanas) == ([], 1)

    def test_las_preguntas_repetidas_se_descartan_aunque_cambie_el_tipo_de_respuesta(self, semanas):
        assert len(analizar([corta(), corta()], semanas)[0]) == 1


# ── Pedirlo desde la pantalla ─────────────────────────────────────────

class TestPedirUnExamen:
    def test_desde_el_constructor_de_un_examen_en_linea(self, professor_client, course, semanas, examen, django_capture_on_commit_callbacks):
        programar(corta(), ordenar(), relacionar(), opcion())
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=examen.pk, kinds=TODOS, count=30)
        draft = AIDraft.objects.get()
        assert respuesta.url == reverse('ai:draft', args=[draft.pk]) and draft.activity == examen
        assert draft.params['exam'] is True and draft.params['kinds'] == TODOS and draft.params['count'] == 30
        assert draft.status == AIDraft.Status.READY
        assert [i['kind'] for i in draft.items] == ['short_answer', 'ordering', 'matching', 'multiple_choice']

    def test_la_ia_recibe_las_reglas_de_examen_y_el_esquema_ampliado(self, professor_client, course, semanas, examen, django_capture_on_commit_callbacks):
        programar(corta())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=examen.pk, kinds=['respuesta_corta'])
        llamada = fake.PROVIDER.calls[0]
        assert 'Ordenar («ordenar»)' in llamada['system'] and 'para un examen' in llamada['prompt'] and 'solo de respuesta corta' in llamada['prompt']
        assert 'parejas' in str(llamada['schema'])

    def test_sin_tipos_no_se_genera_nada(self, professor_client, course, semanas, examen, django_capture_on_commit_callbacks):
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=examen.pk)
        assert not AIDraft.objects.exists() and respuesta.url == reverse('quizzes:builder', args=[examen.pk])
        assert 'Elige al menos un tipo de pregunta' in professor_client.get(respuesta.url).content.decode()

    def test_un_examen_sin_aplicar_en_linea_no_recibe_ia(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        a_mano = Activity.objects.create(course=course, type=Activity.Type.EXAM, title='A mano', published=False, max_score=10)
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=a_mano.pk, kinds=TODOS)
        assert not AIDraft.objects.exists() and not QuizConfig.objects.filter(activity=a_mano).exists()
        assert respuesta.status_code == 302

    def test_un_quiz_ignora_los_tipos_de_examen(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        quiz = make_quiz(course, questions=1, published=False)
        programar(corta(), opcion())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk, kinds=TODOS)
        draft = AIDraft.objects.get()
        assert 'exam' not in draft.params and [i['kind'] for i in draft.items] == ['multiple_choice']

    def test_un_examen_con_intentos_ya_no_se_toca(self, professor_client, course, semanas, examen, django_capture_on_commit_callbacks):
        from apps.courses.tests.factories import EnrollmentFactory
        from apps.quizzes.tests.factories import QuizAttemptFactory

        QuizAttemptFactory(quiz=examen.quiz, student=EnrollmentFactory(course=course).student)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=examen.pk, kinds=TODOS)
        assert not AIDraft.objects.exists()

    def test_desde_el_temario_se_elige_quiz_o_examen(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        programar(corta(), opcion())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, kind='exam', kinds=['respuesta_corta'], title='Examen del parcial')
        draft = AIDraft.objects.get()
        assert draft.activity is None and draft.params['exam'] is True and draft.new_activity_title == 'Examen del parcial'
        assert [i['kind'] for i in draft.items] == ['short_answer']

    def test_desde_el_temario_sin_elegir_sigue_siendo_un_quiz(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        programar(opcion())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, kinds=TODOS)
        assert 'exam' not in AIDraft.objects.get().params


# ── Aprobar y guardar ─────────────────────────────────────────────────

@pytest.fixture
def generada(professor_client, course, semanas, examen, django_capture_on_commit_callbacks):
    programar(corta(), ordenar(), relacionar(), opcion(), verdadero())
    pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=examen.pk, kinds=TODOS)
    return AIDraft.objects.get()


class TestAplicar:
    def test_cada_tipo_se_guarda_como_su_pregunta_y_entra_al_examen(self, professor_client, generada, examen):
        accion(professor_client, generada, 'apply', approve=[0, 1, 2, 3, 4])
        preguntas = {q.kind: q for q in Question.objects.filter(ai_generated=True)}
        assert set(preguntas) == {'short_answer', 'ordering', 'matching', 'multiple_choice', 'true_false'}
        assert [c.text for c in preguntas['short_answer'].choices.all()] == ['Ribosoma', 'Ribosomas']
        assert all(c.is_correct for c in preguntas['short_answer'].choices.all())
        assert [c.text for c in preguntas['ordering'].choices.order_by('position')] == ['Molécula', 'Organelo', 'Célula', 'Tejido']
        assert [(c.text, c.match_text) for c in preguntas['matching'].choices.order_by('position')] == [
            ('Ribosoma', 'Síntesis de proteínas'), ('Mitocondria', 'Energía'),
        ]
        assert examen.quiz.questions.count() == 5 and Question.objects.filter(ai_generated=True).count() == 5

    def test_los_mensajes_hablan_de_examen(self, professor_client, generada, examen):
        respuesta = professor_client.post(reverse('ai:draft', args=[generada.pk]), {'action': 'apply', 'approve': [0]}, follow=True)
        assert 'al banco y al examen. Revisa el examen antes de publicarlo' in ' '.join(m.message for m in respuesta.context['messages'])
        assert respuesta.redirect_chain[-1][0] == reverse('quizzes:builder', args=[examen.pk])

    def test_el_examen_sigue_en_borrador(self, professor_client, generada, examen):
        accion(professor_client, generada, 'apply', approve=[0])
        examen.refresh_from_db()
        assert examen.published is False and examen.type == Activity.Type.EXAM

    def test_un_examen_nuevo_desde_el_temario_se_crea_aplicado_en_linea(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        programar(corta(), ordenar())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, kind='exam', kinds=TODOS, title='')
        draft = AIDraft.objects.get()
        accion(professor_client, draft, 'apply', approve=[0, 1])
        actividad = Activity.objects.get(type=Activity.Type.EXAM)
        assert actividad.title == 'Examen · La célula' and actividad.published is False and actividad.syllabus_week == semanas[0]
        assert actividad.quiz.questions.count() == 2 and actividad.max_score == 2
        assert (actividad.quiz.attempts_allowed, actividad.quiz.shuffle_questions) == (1, True)  # los valores de un examen
        assert uses_engine(actividad)

    def test_un_quiz_nuevo_desde_el_temario_sigue_igual(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        programar(opcion())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks)
        accion(professor_client, AIDraft.objects.get(), 'apply', approve=[0])
        assert Activity.objects.filter(type=Activity.Type.QUIZ).count() == 1 and not Activity.objects.filter(type=Activity.Type.EXAM).exists()

    def test_si_quitaron_lo_en_linea_no_se_agrega_nada(self, professor_client, generada, examen):
        exams.disable_online(examen)
        accion(professor_client, generada, 'apply', approve=[0])
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.READY and not Question.objects.filter(ai_generated=True).exists()

    def test_el_nombre_y_los_textos_de_la_propuesta(self, generada):
        assert drafts.noun(generada) == 'examen'


def uses_engine(actividad):
    return exams.uses_quiz_engine(actividad)


# ── La pantalla de revisión ───────────────────────────────────────────

class TestPantalla:
    def pagina(self, client, draft, **query):
        url = reverse('ai:draft', args=[draft.pk])
        return client.get(url, query).content.decode()

    def test_muestra_cada_tipo_a_su_manera(self, professor_client, generada):
        pagina = self.pagina(professor_client, generada)
        for texto in ('Respuesta corta', 'Ordenar', 'Relacionar columnas', 'Opción múltiple', 'Verdadero o falso'):
            assert texto in pagina
        assert 'Respuesta aceptada' in pagina and 'Orden correcto' in pagina and 'Parejas correctas' in pagina
        assert 'Síntesis de proteínas' in pagina and 'Ribosomas' in pagina

    def test_habla_de_examen_y_no_de_quiz(self, professor_client, generada):
        pagina = self.pagina(professor_client, generada)
        assert 'y al examen' in pagina and 'agregar al examen' in pagina and 'data-ai-noun="examen"' in pagina and 'al quiz' not in pagina

    def test_un_quiz_sigue_hablando_de_quiz(self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks):
        quiz = make_quiz(course, questions=1, published=False)
        programar(opcion())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        pagina = self.pagina(professor_client, AIDraft.objects.get())
        assert 'agregar al quiz' in pagina and 'al examen' not in pagina

    @pytest.mark.parametrize('indice, esperado', [
        (0, ['name="edit_option"', 'Respuestas que se aceptan']),
        (1, ['name="edit_option"', 'en el orden correcto']),
        (2, ['name="edit_left"', 'name="edit_right"', 'Parejas']),
        (3, ['type="radio" name="edit_correct"', 'marca la correcta']),
    ])
    def test_el_formulario_de_edicion_es_de_cada_tipo(self, professor_client, generada, indice, esperado):
        pagina = self.pagina(professor_client, generada, editar=indice)
        for texto in esperado:
            assert texto in pagina


class TestEditar:
    def editar(self, client, draft, indice, **datos):
        return client.post(reverse('ai:draft', args=[draft.pk]), {'action': f'save_edit:{indice}', **datos}, follow=True)

    def item(self, draft, indice):
        draft.refresh_from_db()
        return draft.items[indice]

    def test_respuesta_corta(self, professor_client, generada):
        self.editar(professor_client, generada, 0, edit_text='¿Qué sintetiza proteínas?', edit_option=['Ribosoma', 'ribosomas', '', 'Los ribosomas'])
        item = self.item(generada, 0)
        assert item['edited'] and item['text'] == '¿Qué sintetiza proteínas?'
        assert [c['text'] for c in item['choices']] == ['Ribosoma', 'ribosomas', 'Los ribosomas']

    def test_respuesta_corta_con_repetidas_no_se_guarda(self, professor_client, generada):
        respuesta = self.editar(professor_client, generada, 0, edit_text='Otra', edit_option=['Ribosoma', 'RIBOSOMA'])
        assert 'repetidas' in ' '.join(m.message for m in respuesta.context['messages']) and self.item(generada, 0)['text'] != 'Otra'

    def test_ordenar(self, professor_client, generada):
        self.editar(professor_client, generada, 1, edit_text='Ordena.', edit_option=['Tejido', 'Órgano', 'Sistema'])
        assert [c['text'] for c in self.item(generada, 1)['choices']] == ['Tejido', 'Órgano', 'Sistema']

    def test_ordenar_con_un_solo_elemento_no_se_guarda(self, professor_client, generada):
        respuesta = self.editar(professor_client, generada, 1, edit_text='Ordena.', edit_option=['Solo uno'])
        assert 'al menos 2 elementos' in ' '.join(m.message for m in respuesta.context['messages'])
        assert len(self.item(generada, 1)['choices']) == 4

    def test_relacionar(self, professor_client, generada):
        self.editar(professor_client, generada, 2, edit_text='Relaciona.', edit_left=['A', 'B', 'C'], edit_right=['1', '2', '3'])
        assert [(c['text'], c['match']) for c in self.item(generada, 2)['choices']] == [('A', '1'), ('B', '2'), ('C', '3')]

    @pytest.mark.parametrize('izquierda, derecha, mensaje', [
        (['A', 'B'], ['1', ''], 'los dos lados'),
        (['A', 'B'], ['1', '1'], 'repetidos en la columna'),
        (['A'], ['1'], 'al menos 2 parejas'),
    ])
    def test_relacionar_invalido_no_se_guarda(self, professor_client, generada, izquierda, derecha, mensaje):
        respuesta = self.editar(professor_client, generada, 2, edit_text='Relaciona.', edit_left=izquierda, edit_right=derecha)
        assert mensaje in ' '.join(m.message for m in respuesta.context['messages']) and len(self.item(generada, 2)['choices']) == 2
        assert self.item(generada, 2)['text'] == 'Relaciona cada organelo con su función.'

    def test_la_opcion_multiple_se_edita_como_siempre(self, professor_client, generada):
        self.editar(professor_client, generada, 3, edit_text='¿Qué hacen?', edit_option=['A', 'B', 'C'], edit_correct='1')
        assert [c['correct'] for c in self.item(generada, 3)['choices']] == [False, True, False]


class TestRegenerar:
    def test_regenerar_mantiene_el_tipo(self, professor_client, generada, django_capture_on_commit_callbacks):
        programar(ordenar(pregunta='Otra para ordenar.', elementos=['Uno', 'Dos', 'Tres']))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:1')
        item = AIDraft.objects.get().items[1]
        assert item['kind'] == 'ordering' and item['text'] == 'Otra para ordenar.' and [c['text'] for c in item['choices']] == ['Uno', 'Dos', 'Tres']

    def test_regenerar_un_examen_pide_las_reglas_y_el_esquema_de_examen(self, professor_client, generada, django_capture_on_commit_callbacks):
        programar(ordenar(pregunta='Otra.', elementos=['Uno', 'Dos']))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:1')
        llamada = fake.PROVIDER.calls[-1]
        assert 'Ordenar («ordenar»)' in llamada['system'] and 'parejas' in str(llamada['schema']) and 'solo de ordenar' in llamada['prompt']

    def test_si_vuelve_otro_tipo_se_queda_la_original(self, professor_client, generada, django_capture_on_commit_callbacks):
        programar(corta(pregunta='No es de ordenar.'))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:1')
        item = AIDraft.objects.get().items[1]
        assert item['kind'] == 'ordering' and item['text'] == 'Ordena de menor a mayor tamaño.' and item['state'] == 'pending' and item.get('note')


# ── Los paneles ───────────────────────────────────────────────────────

class TestPaneles:
    def test_el_constructor_del_examen_ofrece_los_tipos_y_hasta_30(self, professor_client, examen, semanas):
        pagina = professor_client.get(reverse('quizzes:builder', args=[examen.pk])).content.decode()
        assert 'modal-ai-quiz' in pagina and 'Tipos de pregunta' in pagina and 'name="kinds"' in pagina
        for valor in TODOS:
            assert f'value="{valor}"' in pagina
        assert '<option value="30"' in pagina and 'name="mix"' not in pagina and 'name="kind"' not in pagina
        assert 'Respuesta corta' in pagina and 'Relacionar columnas' in pagina

    def test_el_constructor_del_quiz_no_cambia(self, professor_client, course, plus, semanas):
        quiz = make_quiz(course, questions=1, published=False)
        pagina = professor_client.get(reverse('quizzes:builder', args=[quiz.activity_id])).content.decode()
        assert 'name="mix"' in pagina and 'name="kinds"' not in pagina and '<option value="30"' not in pagina

    def test_el_temario_deja_elegir_entre_quiz_y_examen(self, professor_client, course, semanas, plus):
        pagina = professor_client.get(reverse('syllabus:index', args=[course.pk])).content.decode()
        assert 'name="kind" value="quiz"' in pagina and 'name="kind" value="exam"' in pagina and 'data-ai-kind' in pagina
        assert 'data-ai-exam-only' in pagina and 'data-ai-quiz-only' in pagina and 'name="mix"' in pagina

    def test_en_el_temario_los_tipos_de_examen_empiezan_apagados(self, professor_client, course, semanas, plus):
        pagina = professor_client.get(reverse('syllabus:index', args=[course.pk])).content.decode()
        bloque = pagina[pagina.index('Tipos de pregunta') - 120:pagina.index('Tipos de pregunta') + 900]
        assert 'hidden' in bloque and bloque.count(' disabled') >= 5

    def test_sin_ia_el_constructor_del_examen_muestra_el_motivo(self, professor_client, course, semanas):
        actividad = Activity.objects.create(course=course, type=Activity.Type.EXAM, title='Sin IA', published=False, max_score=10)
        exams.enable_online(actividad)
        pagina = professor_client.get(reverse('quizzes:builder', args=[actividad.pk])).content.decode()
        assert 'Generar con IA' in pagina and 'disabled' in pagina

    def test_un_examen_con_intentos_no_ofrece_ia(self, professor_client, course, examen, semanas):
        from apps.courses.tests.factories import EnrollmentFactory
        from apps.quizzes.tests.factories import QuizAttemptFactory

        QuizAttemptFactory(quiz=examen.quiz, student=EnrollmentFactory(course=course).student)
        assert 'Generar con IA' not in professor_client.get(reverse('quizzes:builder', args=[examen.pk])).content.decode()
