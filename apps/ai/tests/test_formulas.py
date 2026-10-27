r"""Preguntas con fórmulas: la IA escribe LaTeX entre ``\(`` y ``\)``; lo que llega roto se repara o se descarta."""

import json
import random
from types import SimpleNamespace

import pytest
from django.urls import reverse

from apps.ai import quiz_generation as gen
from apps.ai.models import AIDraft
from apps.ai.providers import ProviderError, fake
from apps.ai.providers.base import loads_lenient
from apps.ai.providers.gemini import GeminiProvider
from apps.ai.text import math_balanced, repair_math
from apps.ai.tests.test_generacion_quiz import SEMANA_1, SEMANA_2, analizar, pregunta, verdadero_falso
from apps.ai.tests.test_propuestas_quiz import accion, pedir, programar
from apps.quizzes.models import Question
from apps.syllabus.tests.factories import SyllabusFactory, SyllabusWeekFactory

pytestmark = pytest.mark.django_db

FF = '\x0c'  # lo que queda de «\f» cuando el JSON trae «\frac» sin duplicar la barra


@pytest.fixture
def semanas(course):
    temario = SyllabusFactory(course=course)
    return (
        SyllabusWeekFactory(syllabus=temario, position=1, title='La célula', topics=SEMANA_1),
        SyllabusWeekFactory(syllabus=temario, position=2, title='Organelos', topics=SEMANA_2),
    )


# ── Reparar lo que el JSON deformó ────────────────────────────────────

class TestReparar:
    @pytest.mark.parametrize('roto, bien', [
        (rf'\({FF}rac{{1}}{{2}}\)', r'\(\frac{1}{2}\)'),
        ('\\(2\timesx\\)', r'\(2\timesx\)'),
        ('\\(\x08eta+1\\)', r'\(\beta+1\)'),
        ('\\(\\left(x\right)\\)', r'\(\left(x\right)\)'),
        ('\\(a\neq b\\)', r'\(a\neq b\)'),
        ('\\(\nabla f\\)', r'\(\nabla f\)'),
        ('\\(a\nu b\\)', r'\(a\nu b\)'),
        ('\\(a\notin B\\)', r'\(a\notin B\)'),
        (rf'\[{FF}rac{{a}}{{b}}\]', r'\[\frac{a}{b}\]'),
    ])
    def test_devuelve_cada_caracter_de_control_a_su_comando(self, roto, bien):
        assert repair_math(roto) == bien

    def test_varias_formulas_en_el_mismo_texto(self):
        assert repair_math(f'Si \\({FF}rac{{1}}{{2}}\\) y \\(2\timesx\\) entonces…') == r'Si \(\frac{1}{2}\) y \(2\timesx\) entonces…'

    def test_fuera_de_una_formula_no_toca_nada(self):
        texto = f'Línea 1\nLínea 2\tcon tabulador y {FF} suelto'
        assert repair_math(texto) == texto

    def test_un_salto_de_linea_de_verdad_dentro_de_la_formula_se_queda(self):
        assert repair_math('\\(a=1\nb=2\\)') == '\\(a=1\nb=2\\)'

    def test_una_formula_bien_escrita_no_cambia(self):
        texto = r'Resuelve \(\frac{3}{4}+\sqrt{x}=\alpha\) y \[\sum_{i=1}^{n} i\]'
        assert repair_math(texto) == texto

    def test_sin_formulas(self):
        assert repair_math('Texto normal') == 'Texto normal' and repair_math('') == ''


class TestBalance:
    @pytest.mark.parametrize('texto', [
        '', 'Sin fórmulas', r'\(x\)', r'\[x\]', r'\(x\) y \(y\)', r'\(x\) luego \[y\]', 'Cuesta $15 y $20',
    ])
    def test_completas(self, texto):
        assert math_balanced(texto)

    @pytest.mark.parametrize('texto', [
        r'\(x', r'x\)', r'\[x', r'x\]', r'\(x\]', r'\[x\)', r'\(\(x\)\)', r'\(x\) y \(y', r'\) antes \(',
    ])
    def test_rotas(self, texto):
        assert not math_balanced(texto)


# ── JSON con barras sin duplicar ──────────────────────────────────────

class TestJsonTolerante:
    def test_un_json_valido_es_igual_que_json_loads(self):
        texto = json.dumps({'t': r'\(\frac{1}{2}\)', 'n': 'a\nb'})
        assert loads_lenient(texto) == json.loads(texto) == {'t': r'\(\frac{1}{2}\)', 'n': 'a\nb'}

    def test_barras_sueltas(self):
        assert loads_lenient(r'{"t": "Resuelve \(x+1\) y \[y\]"}') == {'t': r'Resuelve \(x+1\) y \[y\]'}

    def test_mezcla_de_escapes_validos_y_barras_sueltas(self):
        assert loads_lenient(r'{"t": "\(\\alpha\) \"hola\" \u00e1 \/"}') == {'t': '\\(\\alpha\\) "hola" á /'}

    def test_comando_con_barra_suelta_seguida_de_letra(self):
        assert loads_lenient(r'{"t": "\(\alpha+\gamma\)"}') == {'t': r'\(\alpha+\gamma\)'}

    def test_lo_que_no_es_json_sigue_fallando(self):
        with pytest.raises(ValueError):
            loads_lenient('esto no es json \\(')

    def test_gemini_acepta_la_respuesta_con_barras_sueltas(self):
        proveedor = GeminiProvider(api_key='k', model='m', tier='free', timeout=5)
        texto = r'{"preguntas": [{"pregunta": "¿Cuánto es \(\dfrac{1}{2}+\dfrac{1}{2}\)?"}]}'
        respuesta = SimpleNamespace(text=texto, usage_metadata=None)
        proveedor._client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: respuesta))
        assert proveedor.generate_json(prompt='p', schema={}).data['preguntas'][0]['pregunta'] == r'¿Cuánto es \(\dfrac{1}{2}+\dfrac{1}{2}\)?'

    def test_gemini_sigue_rechazando_lo_que_no_es_json(self):
        proveedor = GeminiProvider(api_key='k', model='m', tier='free', timeout=5)
        proveedor._client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **kwargs: SimpleNamespace(text='x \\(', usage_metadata=None)))
        with pytest.raises(ProviderError, match='JSON'):
            proveedor.generate_json(prompt='p', schema={})


# ── Las propuestas ────────────────────────────────────────────────────

class TestPropuestas:
    def test_una_formula_bien_escrita_pasa_tal_cual(self, semanas):
        items, dropped = analizar([pregunta(
            pregunta=r'¿Cuánto vale \(\frac{3}{4}+\frac{1}{4}\)?', opciones=[r'\(1\)', r'\(\frac{4}{8}\)', r'\(2\)'], correcta=0,
            explicacion=r'Porque \(\frac{3+1}{4}=1\).',
        )], semanas)
        assert dropped == 0 and items[0]['text'] == r'¿Cuánto vale \(\frac{3}{4}+\frac{1}{4}\)?'
        assert {c['text'] for c in items[0]['choices']} == {r'\(1\)', r'\(\frac{4}{8}\)', r'\(2\)'}
        assert items[0]['explanation'] == r'Porque \(\frac{3+1}{4}=1\).'

    def test_se_repara_en_la_pregunta_las_opciones_y_la_explicacion(self, semanas):
        items, _ = analizar([pregunta(
            pregunta=f'¿Cuánto vale \\({FF}rac{{1}}{{2}}\\)?', opciones=[f'\\({FF}rac{{1}}{{2}}\\)', '\\(2\timesx\\)', '\\(x\\)'], correcta=0,
            explicacion=f'Es \\({FF}rac{{1}}{{2}}\\).',
        )], semanas)
        assert items[0]['text'] == r'¿Cuánto vale \(\frac{1}{2}\)?' and items[0]['explanation'] == r'Es \(\frac{1}{2}\).'
        assert {c['text'] for c in items[0]['choices']} == {r'\(\frac{1}{2}\)', r'\(2\timesx\)', r'\(x\)'}

    def test_verdadero_o_falso_con_formula(self, semanas):
        items, _ = analizar([verdadero_falso(pregunta=f'\\({FF}rac{{1}}{{2}}\\) es mayor que \\({FF}rac{{1}}{{3}}\\).')], semanas)
        assert items[0]['text'] == r'\(\frac{1}{2}\) es mayor que \(\frac{1}{3}\).'

    @pytest.mark.parametrize('cambios', [
        {'pregunta': r'¿Cuánto vale \(\frac{1}{2}?'},
        {'opciones': [r'\(1\)', r'\(2', 'tres'], 'correcta': 0},
        {'opciones': [r'1\)', 'dos', 'tres'], 'correcta': 0},
        {'explicacion': r'Porque \(x+1.'},
        {'pregunta': r'\(\(x\)\)'},
    ])
    def test_una_formula_sin_cerrar_descarta_la_pregunta(self, semanas, cambios):
        assert analizar([pregunta(**cambios)], semanas) == ([], 1)

    def test_el_verdadero_falso_con_la_formula_rota_se_descarta(self, semanas):
        assert analizar([verdadero_falso(pregunta=r'\(x+1 es mayor que 0.')], semanas) == ([], 1)

    def test_la_formula_rota_no_tumba_a_las_demas(self, semanas):
        items, dropped = analizar([pregunta(pregunta=r'Rota \(x'), pregunta(), verdadero_falso()], semanas)
        assert len(items) == 2 and dropped == 1

    def test_el_dolar_se_deja_como_texto(self, semanas):
        items, _ = analizar([pregunta(pregunta='Una calculadora cuesta $15 y un cuaderno $20. ¿Cuánto es el total?')], semanas)
        assert '$15' in items[0]['text']

    def test_dos_preguntas_iguales_con_formula_siguen_siendo_repetidas(self, semanas):
        igual = pregunta(pregunta=r'¿Cuánto vale \(\frac{1}{2}\)?', opciones=['a', 'b', 'c'])
        assert len(analizar([igual, igual], semanas)[0]) == 1

    def test_con_la_formula_la_pregunta_sigue_necesitando_su_cita(self, semanas):
        assert analizar([pregunta(pregunta=r'¿Cuánto vale \(\frac{1}{2}\)?', cita='Esta cita no está en el material')], semanas) == ([], 1)

    def test_el_limite_de_largo_cuenta_la_formula_completa(self, semanas):
        largo = r'\(' + 'x+' * 400 + r'1\)'
        assert analizar([pregunta(pregunta=largo)], semanas) == ([], 1)


class TestInstruccion:
    def test_el_prompt_pide_latex_con_los_delimitadores_que_se_dibujan(self):
        assert r'«\(» y «\)»' in gen.SYSTEM and r'\(\frac{3}{4}\)' in gen.SYSTEM and 'uses «$»' in gen.SYSTEM

    def test_el_prompt_avisa_de_duplicar_las_barras_en_el_json(self):
        assert r'duplicada (por ejemplo \\frac)' in gen.SYSTEM


# ── De punta a punta ──────────────────────────────────────────────────

class TestDeExtremoAExtremo:
    @pytest.fixture(autouse=True)
    def proveedor(self):
        fake.PROVIDER.reset()
        fake.PROVIDER.tier = 'fake'
        yield
        fake.PROVIDER.reset()
        fake.PROVIDER.tier = 'fake'

    @pytest.fixture
    def plus(self, professor):
        from apps.organizations.models import Organization
        from apps.organizations.services import teaching_organization

        org = teaching_organization(professor)
        org.plan, org.ai_enabled = Organization.Plan.TEACHER_PLUS, True
        org.save()
        return org

    def test_la_formula_llega_a_la_propuesta_a_la_pantalla_y_al_banco(
        self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks,
    ):
        from apps.quizzes.tests.factories import make_quiz

        quiz = make_quiz(course, questions=1, published=False)
        programar(pregunta(
            pregunta=f'¿Cuánto vale \\({FF}rac{{3}}{{4}}+{FF}rac{{1}}{{4}}\\)?', opciones=[r'\(1\)', r'\(\frac{4}{8}\)', r'\(2\)'], correcta=0,
        ))
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        assert draft.items[0]['text'] == r'¿Cuánto vale \(\frac{3}{4}+\frac{1}{4}\)?'
        pagina = professor_client.get(reverse('ai:draft', args=[draft.pk])).content.decode()
        assert 'vendor/katex/katex.min.js' in pagina and 'js/math.js' in pagina and r'\(\frac{3}{4}+\frac{1}{4}\)' in pagina
        accion(professor_client, draft, 'apply', approve=[0])
        guardada = Question.objects.get(ai_generated=True)
        assert guardada.text == r'¿Cuánto vale \(\frac{3}{4}+\frac{1}{4}\)?'
        assert r'\(1\)' in {choice.text for choice in guardada.choices.all()}

    def test_el_docente_edita_la_formula_y_se_guarda_tal_cual(
        self, professor_client, course, semanas, plus, django_capture_on_commit_callbacks,
    ):
        from apps.quizzes.tests.factories import make_quiz

        quiz = make_quiz(course, questions=1, published=False)
        programar(pregunta(pregunta=r'¿Cuánto vale \(\frac{1}{2}\)?'))
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        accion(professor_client, draft, 'save_edit:0', edit_text=r'¿Cuánto vale \(\frac{2}{4}\)?', edit_option=['a', 'b', 'c'], edit_correct='0')
        draft.refresh_from_db()
        assert draft.items[0]['text'] == r'¿Cuánto vale \(\frac{2}{4}\)?'
