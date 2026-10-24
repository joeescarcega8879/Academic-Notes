"""Preguntas de quiz con IA: lo que se pide, cómo se valida lo que devuelve y que nada se fugue ni se invente."""

import random

import pytest
from django.http import QueryDict

from apps.ai import quiz_generation as gen
from apps.ai.text import normalize, quoted_in
from apps.courses.tests.factories import CourseFactory
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

SEMANA_1 = 'Ribosomas: síntesis de proteínas\nMitocondria: producción de energía en forma de ATP\nNúcleo: guarda el ADN'
SEMANA_2 = 'Cloroplastos y fotosíntesis\nAparato de Golgi: empaca y envía proteínas'


def formulario(**campos):
    data = QueryDict(mutable=True)
    for clave, valor in campos.items():
        if isinstance(valor, (list, tuple)):
            data.setlist(clave, [str(v) for v in valor])
        else:
            data[clave] = str(valor)
    return data


@pytest.fixture
def semanas(course):
    temario = SyllabusFactory(course=course)
    return (
        SyllabusWeekFactory(syllabus=temario, position=1, title='La célula', topics=SEMANA_1),
        SyllabusWeekFactory(syllabus=temario, position=2, title='Organelos', topics=SEMANA_2, objectives='Distinguir organelos'),
    )


def pregunta(**cambios):
    base = {
        'tipo': 'opcion_multiple', 'pregunta': '¿Cuál es la función de los ribosomas?',
        'opciones': ['Fabricar proteínas', 'Producir ATP', 'Guardar el ADN'], 'correcta': 0,
        'explicacion': 'Sintetizan proteínas.', 'cita': 'Ribosomas: síntesis de proteínas',
    }
    return {**base, **cambios}


def verdadero_falso(**cambios):
    base = {
        'tipo': 'verdadero_falso', 'pregunta': 'La mitocondria produce ATP.', 'verdadero': True,
        'explicacion': '', 'cita': 'producción de energía en forma de ATP',
    }
    return {**base, **cambios}


def analizar(preguntas, semanas, **params):
    base = {'count': 10, 'mix': 'mix', 'difficulty': 'medium', 'points': '1', 'instructions': ''}
    return gen.parse_items({'preguntas': preguntas}, list(semanas), {**base, **params}, rng=random.Random(1))


class TestTexto:
    def test_normalizar_ignora_acentos_signos_y_mayusculas(self):
        assert normalize('  Ribosomas: SÍNTESIS… de proteínas! ') == 'ribosomas sintesis de proteinas'

    def test_una_cita_corta_no_vale(self):
        assert not quoted_in('la', normalize('la célula es la unidad'))
        assert quoted_in('Unidad básica', normalize('La célula es la unidad básica de la vida'))


class TestPeticion:
    def test_pide_al_menos_una_semana(self, course, semanas):
        with pytest.raises(gen.RequestError, match='al menos una semana'):
            gen.clean_params(formulario(count=10), course)

    def test_una_semana_vacia_o_sin_clase_no_se_puede_elegir(self, course, semanas):
        vacia = SyllabusWeekFactory(syllabus=semanas[0].syllabus, position=3, title='Vacía', topics='', objectives='')
        sin_clase = SyllabusWeekFactory(syllabus=semanas[0].syllabus, position=4, topics='Algo', no_class=True)
        for semana in (vacia, sin_clase):
            with pytest.raises(gen.RequestError, match='no tiene temas'):
                gen.clean_params(formulario(weeks=[semana.pk]), course)

    def test_ignora_semanas_de_otro_grupo(self, course, semanas):
        ajena = SyllabusWeekFactory(syllabus=SyllabusFactory(course=CourseFactory()), topics='Tema ajeno')
        with pytest.raises(gen.RequestError):
            gen.clean_params(formulario(weeks=[ajena.pk]), course)
        params = gen.clean_params(formulario(weeks=[semanas[0].pk, ajena.pk]), course)
        assert params['week_ids'] == [semanas[0].pk]

    def test_valores_por_omision_y_saneados(self, course, semanas):
        params = gen.clean_params(formulario(weeks=[semanas[0].pk, semanas[0].pk], count=99, mix='x', difficulty='y'), course)
        assert params == {
            'week_ids': [semanas[0].pk], 'count': 10, 'mix': 'mix', 'difficulty': 'medium', 'points': '1', 'instructions': '',
        }

    @pytest.mark.parametrize('puntos', ['0', '-1', 'abc', '101', 'nan'])
    def test_puntos_invalidos(self, course, semanas, puntos):
        with pytest.raises(gen.RequestError, match='puntos'):
            gen.clean_params(formulario(weeks=[semanas[0].pk], points=puntos), course)

    def test_puntos_con_coma_y_sin_ceros_de_mas(self, course, semanas):
        assert gen.clean_params(formulario(weeks=[semanas[0].pk], points='2,50'), course)['points'] == '2.5'
        assert gen.clean_params(formulario(weeks=[semanas[0].pk], points='10'), course)['points'] == '10'

    def test_instrucciones_demasiado_largas(self, course, semanas):
        with pytest.raises(gen.RequestError, match='500'):
            gen.clean_params(formulario(weeks=[semanas[0].pk], instructions='x' * 501), course)

    def test_el_texto_enviado_es_solo_el_de_las_semanas_elegidas(self, semanas):
        prompt = gen.build_prompt({'count': 5, 'mix': 'true_false', 'difficulty': 'hard', 'instructions': 'Sin fechas'}, [semanas[1]])
        assert 'Cloroplastos' in prompt and 'Ribosomas' not in prompt
        assert 'Sin fechas' in prompt and 'solo de verdadero/falso' in prompt and '5 preguntas' in prompt


class TestValidacion:
    def test_acepta_una_pregunta_valida_con_su_cita(self, semanas):
        items, descartadas = analizar([pregunta(), verdadero_falso()], semanas)
        assert descartadas == 0 and len(items) == 2
        om, vf = items
        assert om['kind'] == 'multiple_choice' and om['week'] == 1 and om['topic'] == 'La célula' and om['state'] == 'pending'
        assert [c['text'] for c in om['choices'] if c['correct']] == ['Fabricar proteínas']
        assert sorted(c['text'] for c in om['choices']) == ['Fabricar proteínas', 'Guardar el ADN', 'Producir ATP']
        assert vf['kind'] == 'true_false' and vf['true_is_correct'] is True and vf['choices'] == []

    def test_descarta_lo_que_no_cita_el_temario(self, semanas):
        items, descartadas = analizar([pregunta(cita='Los ribosomas nacen en el nucleolo'), pregunta(cita='')], semanas)
        assert items == [] and descartadas == 2

    def test_una_cita_que_junta_varios_temas_no_vale(self, semanas):
        items, descartadas = analizar([pregunta(cita='Ribosomas: síntesis de proteínas Mitocondria: producción de energía')], semanas)
        assert items == [] and descartadas == 1

    def test_la_semana_la_decide_la_cita_no_el_modelo(self, semanas):
        items, _ = analizar([pregunta(cita='Cloroplastos y fotosíntesis', semana=1)], semanas)
        assert items[0]['week'] == 2 and items[0]['topic'] == 'Organelos'

    def test_la_cita_puede_variar_en_acentos_y_signos(self, semanas):
        items, _ = analizar([pregunta(cita='ribosomas - sintesis de PROTEINAS')], semanas)
        assert len(items) == 1

    @pytest.mark.parametrize('cambios', [
        {'correcta': 5}, {'correcta': -1}, {'correcta': True}, {'correcta': '0'},
        {'opciones': ['Solo una']}, {'opciones': ['A', 'A', 'B']}, {'opciones': ['A', '', 'B'], 'correcta': 1},
        {'opciones': 'no es lista'}, {'pregunta': ''}, {'pregunta': 'x' * 601}, {'opciones': ['x' * 501, 'B'], 'correcta': 1},
        {'tipo': 'ensayo'},
    ])
    def test_descarta_opcion_multiple_invalida(self, semanas, cambios):
        items, descartadas = analizar([pregunta(**cambios)], semanas)
        assert items == [] and descartadas == 1

    def test_verdadero_falso_exige_un_booleano(self, semanas):
        assert analizar([verdadero_falso(verdadero='si')], semanas)[0] == []
        assert len(analizar([verdadero_falso(verdadero=False)], semanas)[0]) == 1

    def test_respeta_el_tipo_pedido(self, semanas):
        items, descartadas = analizar([pregunta(), verdadero_falso()], semanas, mix='true_false')
        assert [i['kind'] for i in items] == ['true_false'] and descartadas == 1

    def test_respeta_la_cantidad_pedida(self, semanas):
        textos = [
            '¿Qué organelo fabrica proteínas?', 'Menciona la fuente de energía celular.', 'El ADN se guarda en el núcleo.',
            'Describe cómo se empacan las proteínas.', '¿Dónde ocurre la fotosíntesis?', 'Los lisosomas digieren desechos.',
            'La membrana controla lo que entra a la célula.', 'Explica la función del citoplasma.',
        ]
        muchas = [pregunta(pregunta=texto) for texto in textos]
        items, descartadas = analizar(muchas, semanas, count=5)
        assert len(items) == 5 and descartadas == 3

    def test_descarta_repetidas_dentro_del_lote(self, semanas):
        items, descartadas = analizar([pregunta(), pregunta(pregunta='¿Cuál es la función de los ribosomas?')], semanas)
        assert len(items) == 1 and descartadas == 1

    def test_avisa_si_se_parece_a_una_del_banco(self, semanas):
        existentes = [(7, '¿Cuál es la función de los ribosomas?'), (8, 'Otra cosa muy distinta')]
        items, _ = gen.parse_items({'preguntas': [pregunta()]}, list(semanas), {'count': 5, 'mix': 'mix', 'points': '1'}, existing=existentes)
        assert items[0]['similar'] == {'id': 7, 'text': '¿Cuál es la función de los ribosomas?'}

    def test_la_respuesta_no_es_una_lista_de_preguntas(self, semanas):
        base = {'count': 5, 'mix': 'mix', 'points': '1'}
        for basura in (None, [], 'texto', {'preguntas': 'no'}, {'otra': 1}):
            assert gen.parse_items(basura, list(semanas), base) == ([], 0)

    def test_mezcla_las_opciones_para_que_la_correcta_no_quede_siempre_primera(self, semanas):
        posiciones = set()
        for semilla in range(30):
            items, _ = gen.parse_items(
                {'preguntas': [pregunta()]}, list(semanas), {'count': 1, 'mix': 'mix', 'points': '1'}, rng=random.Random(semilla),
            )
            posiciones.add(next(i for i, c in enumerate(items[0]['choices']) if c['correct']))
        assert len(posiciones) > 1
