"""El flujo de T3 con preguntas: pedir, esperar, revisar, editar, regenerar y aprobar. La IA propone; el docente decide."""

import datetime

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory
from apps.ai import drafts
from apps.ai.models import AIDraft, AIRequest
from apps.ai.providers import ProviderError, fake
from apps.courses.tests.factories import EnrollmentFactory
from apps.grades.models import Activity
from apps.organizations.models import Organization
from apps.organizations.services import teaching_organization
from apps.quizzes.models import Question
from apps.quizzes.tests.factories import QuestionFactory, QuizAttemptFactory, make_quiz
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


@pytest.fixture
def quiz(course, plus):
    return make_quiz(course, questions=1, published=False)


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
        'explicacion': 'Genera la energía de la célula.', 'cita': 'producción de energía en forma de ATP',
    }
    return {**base, **cambios}


def programar(*preguntas):
    fake.PROVIDER.responses.append({'preguntas': list(preguntas)})


def pedir(client, course, semanas, callbacks, **extra):
    datos = {'weeks': [s.pk for s in semanas], 'count': 10, 'mix': 'mix', 'difficulty': 'medium', 'points': '1', **extra}
    with callbacks(execute=True):
        return client.post(reverse('ai:quiz_generate', args=[course.pk]), datos)


def accion(client, draft, valor, **extra):
    return client.post(reverse('ai:draft', args=[draft.pk]), {'action': valor, **extra})


@pytest.fixture
def generada(professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
    """Una propuesta lista para revisar, con una pregunta de cada tipo."""
    programar(pregunta(), verdadero_falso())
    pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
    return AIDraft.objects.get()


class TestPedir:
    def test_genera_y_deja_las_propuestas_por_revisar(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        programar(pregunta(), verdadero_falso())
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        assert respuesta.status_code == 302 and respuesta.url == reverse('ai:draft', args=[draft.pk])
        assert draft.status == AIDraft.Status.READY and len(draft.items) == 2 and draft.activity == quiz.activity
        assert draft.requested_by == course.professor and draft.organization == course.organization
        assert AIRequest.objects.get().kind == AIRequest.Kind.QUIZ
        # Nada existe todavía: ni preguntas nuevas ni cambios en el quiz.
        assert Question.objects.filter(ai_generated=True).count() == 0 and quiz.questions.count() == 1

    def test_mientras_no_corre_la_tarea_queda_generando(self, professor_client, course, semanas, quiz):
        programar(pregunta())
        professor_client.post(reverse('ai:quiz_generate', args=[course.pk]), {'weeks': [semanas[0].pk], 'activity': quiz.activity.pk})
        assert AIDraft.objects.get().status == AIDraft.Status.PENDING and fake.PROVIDER.calls == []

    def test_la_pantalla_de_espera_se_actualiza_sola(self, professor_client, course, semanas, quiz):
        professor_client.post(reverse('ai:quiz_generate', args=[course.pk]), {'weeks': [semanas[0].pk], 'activity': quiz.activity.pk})
        draft = AIDraft.objects.get()
        html = professor_client.get(reverse('ai:draft', args=[draft.pk])).content.decode()
        assert 'Generando' in html and reverse('ai:draft_status', args=[draft.pk]) in html
        assert professor_client.get(reverse('ai:draft_status', args=[draft.pk])).json() == {'busy': True}

    def test_el_texto_enviado_no_lleva_datos_de_alumnos(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        inscritos = [EnrollmentFactory(course=course) for _ in range(3)]
        programar(pregunta())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk, instructions='Sin fechas')
        recibido = ' '.join(f"{c['system']} {c['prompt']}" for c in fake.PROVIDER.calls)
        for alta in inscritos:
            student = alta.student
            for secreto in (student.first_name, student.last_name, student.email, student.student_number):
                if secreto:
                    assert str(secreto) not in recibido
        assert not AIRequest.objects.get().contains_student_data
        assert 'Ribosomas' in recibido

    def test_con_una_clave_gratuita_si_funciona(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        """El temario no lleva datos de alumnos: el candado de la clave gratuita no aplica."""
        fake.PROVIDER.tier = 'free'
        programar(pregunta())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.get().status == AIDraft.Status.READY

    @pytest.mark.parametrize('plan, interruptor, texto', [
        (Organization.Plan.TEACHER, True, 'plan Plus'),
        (Organization.Plan.TEACHER_PLUS, False, 'desactivada'),
    ])
    def test_sin_plan_o_con_la_ia_apagada_no_se_crea_nada(
        self, professor_client, professor, course, semanas, plan, interruptor, texto, django_capture_on_commit_callbacks,
    ):
        org = teaching_organization(professor)
        org.plan, org.ai_enabled = plan, interruptor
        org.save()
        activity = make_quiz(course, questions=0, published=False).activity
        respuesta = pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=activity.pk)
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == []
        assert respuesta.url == reverse('quizzes:builder', args=[activity.pk])
        assert texto in ' '.join(str(m) for m in respuesta.wsgi_request._messages)

    def test_sin_cuota_no_se_crea_nada(self, professor_client, plus, course, semanas, quiz, django_capture_on_commit_callbacks):
        AIRequest.objects.bulk_create([AIRequest(organization=plus, kind='probe', provider='fake', status='ok') for _ in range(300)])
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.count() == 0

    def test_una_semana_vacia_se_rechaza_antes_de_llamar_a_la_ia(self, professor_client, plus, course, semanas, quiz, django_capture_on_commit_callbacks):
        vacia = SyllabusWeekFactory(syllabus=semanas[0].syllabus, position=3, topics='', objectives='')
        pedir(professor_client, course, [vacia], django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == []

    def test_un_quiz_con_intentos_no_admite_propuestas(self, professor_client, plus, course, semanas, quiz, django_capture_on_commit_callbacks):
        QuizAttemptFactory(quiz=quiz, student=EnrollmentFactory(course=course).student)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.count() == 0 and fake.PROVIDER.calls == []

    def test_un_grupo_archivado_no_se_puede(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        course.status = course.Status.ARCHIVED
        course.save()
        assert pedir(professor_client, course, semanas, django_capture_on_commit_callbacks).status_code == 404

    def test_solo_el_docente_del_grupo(self, plus, course, semanas, student_client, django_capture_on_commit_callbacks):
        assert pedir(student_client, course, semanas, django_capture_on_commit_callbacks).status_code in (302, 403)
        assert AIDraft.objects.count() == 0
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert pedir(otro, course, semanas, django_capture_on_commit_callbacks).status_code == 404


class TestFallos:
    def test_si_el_proveedor_falla_queda_con_el_motivo_y_no_cuenta_el_uso(
        self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks,
    ):
        fake.PROVIDER.error = ProviderError('Gemini respondió 503', retryable=True)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED and 'No se pudo completar' in draft.error
        assert AIRequest.objects.count() == 3 and set(AIRequest.objects.values_list('status', flat=True)) == {AIRequest.Status.ERROR}
        html = professor_client.get(reverse('ai:draft', args=[draft.pk])).content.decode()
        assert 'Intentar de nuevo' in html and 'no se descontó ningún uso' in html

    def test_reintentar_vuelve_a_generar(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('caído')
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        fake.PROVIDER.error = None
        programar(pregunta())
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, draft, 'retry')
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.READY and draft.error == '' and len(draft.items) == 1

    def test_si_ninguna_pregunta_cita_el_temario_falla(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        programar(pregunta(cita='Algo que el temario nunca dijo'), pregunta(cita=''))
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED and 'no citaban el temario' in draft.error and draft.items == []

    def test_una_semana_que_ya_no_existe_falla_con_motivo(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        fake.PROVIDER.responses.append({'preguntas': [pregunta()]})
        with django_capture_on_commit_callbacks(execute=False) as pendientes:
            professor_client.post(reverse('ai:quiz_generate', args=[course.pk]), {'weeks': [semanas[0].pk], 'activity': quiz.activity.pk})
        semanas[0].delete()
        for callback in pendientes:
            callback()
        assert 'ya no existe' in AIDraft.objects.get().error

    def test_un_error_inesperado_no_deja_la_propuesta_generando(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks, monkeypatch):
        monkeypatch.setattr(drafts.quiz_gen, 'parse_items', lambda *a, **k: 1 / 0)
        programar(pregunta())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        draft = AIDraft.objects.get()
        assert draft.status == AIDraft.Status.FAILED and 'Algo salió mal' in draft.error

    def test_una_generacion_perdida_se_cancela_sola(self, professor_client, course, semanas, quiz):
        professor_client.post(reverse('ai:quiz_generate', args=[course.pk]), {'weeks': [semanas[0].pk], 'activity': quiz.activity.pk})
        draft = AIDraft.objects.get()
        AIDraft.objects.filter(pk=draft.pk).update(updated_at=timezone.now() - datetime.timedelta(minutes=11))
        html = professor_client.get(reverse('ai:draft', args=[draft.pk])).content.decode()
        draft.refresh_from_db()
        assert draft.status == AIDraft.Status.FAILED and 'tardó demasiado' in html


class TestRevisar:
    def test_la_pantalla_muestra_la_clave_la_explicacion_y_la_cita(self, professor_client, generada):
        html = professor_client.get(reverse('ai:draft', args=[generada.pk])).content.decode()
        assert '¿Cuál es la función de los ribosomas?' in html and 'Fabricar proteínas' in html and 'Correcta' in html
        assert 'Sintetizan proteínas.' in html and 'Cita del temario' in html and 'Ribosomas: síntesis de proteínas' in html
        assert 'Semana 1 · La célula' in html and 'Verdadero o falso' in html

    def test_guardar_lo_marcado_aprueba_y_pone_puntos(self, professor_client, generada):
        accion(professor_client, generada, 'save', approve=[0], **{'points-0': '2,5', 'points-1': 'basura'})
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['approved', 'pending']
        assert [i['points'] for i in generada.items] == ['2.5', '1']

    def test_descartar_y_recuperar_conservan_lo_marcado(self, professor_client, generada):
        accion(professor_client, generada, 'discard:1', approve=[0])
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['approved', 'discarded']
        accion(professor_client, generada, 'restore:1', approve=[0])
        generada.refresh_from_db()
        assert [i['state'] for i in generada.items] == ['approved', 'pending']

    def test_las_descartadas_no_se_aprueban_aunque_lleguen_marcadas(self, professor_client, generada):
        accion(professor_client, generada, 'discard:1')
        accion(professor_client, generada, 'save', approve=[0, 1])
        generada.refresh_from_db()
        assert generada.items[1]['state'] == 'discarded'

    def test_una_posicion_inexistente_no_rompe(self, professor_client, generada):
        for valor in ('discard:99', 'edit:99', 'regen:99', 'discard:', 'discard:abc'):
            assert accion(professor_client, generada, valor).status_code == 302
        generada.refresh_from_db()
        assert len(generada.items) == 2

    def test_editar_abre_el_formulario_de_esa_pregunta(self, professor_client, generada):
        respuesta = accion(professor_client, generada, 'edit:0', approve=[1])
        assert respuesta.url.endswith('?editar=0#p1')
        html = professor_client.get(respuesta.url).content.decode()
        assert 'name="edit_text"' in html and 'name="edit_option"' in html
        generada.refresh_from_db()
        assert generada.items[1]['state'] == 'approved'

    def test_guardar_cambios_de_opcion_multiple(self, professor_client, generada):
        accion(professor_client, generada, 'save_edit:0', **{
            'edit_text': '¿Qué fabrican los ribosomas?', 'edit_explanation': 'Proteínas.', 'edit_correct': '1',
            'edit_option': ['ATP', 'Proteínas', 'ADN'],
        })
        generada.refresh_from_db()
        item = generada.items[0]
        assert item['text'] == '¿Qué fabrican los ribosomas?' and item['edited'] is True and item['similar'] is None
        assert [c['text'] for c in item['choices'] if c['correct']] == ['Proteínas']
        assert [c['text'] for c in item['choices']] == ['ATP', 'Proteínas', 'ADN']

    def test_guardar_cambios_de_verdadero_falso(self, professor_client, generada):
        accion(professor_client, generada, 'save_edit:1', edit_text='La mitocondria no produce ATP.', edit_correct='false')
        generada.refresh_from_db()
        assert generada.items[1]['true_is_correct'] is False and generada.items[1]['edited']

    @pytest.mark.parametrize('datos, mensaje', [
        ({'edit_text': ' ', 'edit_correct': '0', 'edit_option': ['A', 'B']}, 'vacía'),
        ({'edit_text': 'P', 'edit_option': ['A', 'B']}, 'exactamente una'),
        ({'edit_text': 'P', 'edit_correct': '0', 'edit_option': ['A', 'A']}, 'repetidas'),
        ({'edit_text': 'P', 'edit_correct': '0', 'edit_option': ['A']}, 'al menos'),
        ({'edit_text': 'P', 'edit_correct': '5', 'edit_option': ['A', 'B']}, 'exactamente una'),
    ])
    def test_los_cambios_invalidos_no_se_guardan_y_se_vuelve_a_editar(self, professor_client, generada, datos, mensaje):
        antes = generada.items[0]['text']
        respuesta = accion(professor_client, generada, 'save_edit:0', **datos)
        assert respuesta.url.endswith('?editar=0#p1')
        assert mensaje in ' '.join(str(m) for m in respuesta.wsgi_request._messages)
        generada.refresh_from_db()
        assert generada.items[0]['text'] == antes and not generada.items[0]['edited']

    def test_regenerar_cambia_la_pregunta_y_cuenta_un_uso(self, professor_client, generada, django_capture_on_commit_callbacks):
        usos = AIRequest.objects.filter(status='ok').count()
        programar(pregunta(pregunta='¿Dónde se guarda el ADN?', opciones=['Núcleo', 'Ribosoma'], correcta=0, cita='Núcleo: guarda el ADN'))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:0', approve=[0], **{'points-0': '3'})
        generada.refresh_from_db()
        item = generada.items[0]
        assert item['text'] == '¿Dónde se guarda el ADN?' and item['state'] == 'pending' and item['points'] == '3'
        assert AIRequest.objects.filter(status='ok').count() == usos + 1
        assert '¿Cuál es la función de los ribosomas?' in fake.PROVIDER.calls[-1]['prompt']  # para no repetir las otras
        assert 'solo de opción múltiple' in fake.PROVIDER.calls[-1]['prompt']

    def test_si_regenerar_falla_la_pregunta_se_queda_con_un_aviso(self, professor_client, generada, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('caído')
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:0')
        generada.refresh_from_db()
        item = generada.items[0]
        assert item['state'] == 'pending' and item['text'] == '¿Cuál es la función de los ribosomas?' and 'No se pudo completar' in item['note']
        assert 'No se pudo completar' in professor_client.get(reverse('ai:draft', args=[generada.pk])).content.decode()

    def test_si_regenerar_devuelve_algo_invalido_se_avisa(self, professor_client, generada, django_capture_on_commit_callbacks):
        programar(pregunta(cita='Inventada'))
        with django_capture_on_commit_callbacks(execute=True):
            accion(professor_client, generada, 'regen:0')
        generada.refresh_from_db()
        assert generada.items[0]['state'] == 'pending' and 'no devolvió una pregunta válida' in generada.items[0]['note']

    def test_regenerando_la_pantalla_espera(self, professor_client, generada):
        with drafts.locked(generada.pk) as draft:
            draft.items[0]['state'] = 'regenerating'
            draft.save()
        html = professor_client.get(reverse('ai:draft', args=[generada.pk])).content.decode()
        assert 'Regenerando' in html and reverse('ai:draft_status', args=[generada.pk]) in html
        assert professor_client.get(reverse('ai:draft_status', args=[generada.pk])).json() == {'busy': True}

    def test_descartar_todo_no_agrega_nada(self, professor_client, generada, quiz):
        respuesta = accion(professor_client, generada, 'discard_all', approve=[0, 1])
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.DISCARDED and respuesta.url == reverse('quizzes:builder', args=[quiz.activity.pk])
        assert Question.objects.filter(ai_generated=True).count() == 0 and quiz.questions.count() == 1

    def test_una_propuesta_resuelta_ya_no_se_modifica(self, professor_client, generada):
        accion(professor_client, generada, 'discard_all')
        accion(professor_client, generada, 'discard:0')
        generada.refresh_from_db()
        assert generada.items[0]['state'] == 'pending'


class TestAprobar:
    def test_guarda_en_el_banco_del_grupo_y_en_el_quiz(self, professor_client, generada, quiz, course, professor):
        respuesta = accion(professor_client, generada, 'apply', approve=[0, 1], **{'points-0': '2'})
        generada.refresh_from_db()
        assert respuesta.url == reverse('quizzes:builder', args=[quiz.activity.pk])
        assert generada.status == AIDraft.Status.APPLIED and generada.applied_by == professor and generada.applied_at is not None
        banco = Question.objects.filter(ai_generated=True).order_by('id')
        assert [(q.course, q.author, q.topic, q.points, q.kind) for q in banco] == [
            (course, professor, 'La célula', 2, 'multiple_choice'), (course, professor, 'La célula', 1, 'true_false'),
        ]
        assert [q.pk for q in banco] == [i['question_id'] for i in generada.items]
        assert [c.text for c in banco[0].choices.all() if c.is_correct] == ['Fabricar proteínas']
        nuevas = quiz.questions.filter(ai_generated=True)
        assert nuevas.count() == 2 and quiz.questions.count() == 3
        assert set(nuevas.values_list('source_id', flat=True)) == {q.pk for q in banco}
        quiz.activity.refresh_from_db()
        assert quiz.activity.published is False

    def test_solo_agrega_las_aprobadas(self, professor_client, generada, quiz):
        accion(professor_client, generada, 'apply', approve=[1])
        assert Question.objects.filter(ai_generated=True).get().kind == 'true_false' and quiz.questions.count() == 2

    def test_sin_aprobadas_no_hace_nada(self, professor_client, generada, quiz):
        respuesta = accion(professor_client, generada, 'apply')
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.READY and respuesta.url == reverse('ai:draft', args=[generada.pk])
        assert Question.objects.filter(ai_generated=True).count() == 0

    def test_todo_o_nada_si_el_quiz_ya_tiene_intentos(self, professor_client, generada, quiz, course):
        QuizAttemptFactory(quiz=quiz, student=EnrollmentFactory(course=course).student)
        accion(professor_client, generada, 'apply', approve=[0, 1])
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.READY
        assert Question.objects.filter(ai_generated=True).count() == 0 and quiz.questions.count() == 1

    def test_un_grupo_archivado_no_recibe_preguntas(self, professor_client, generada, course, quiz):
        course.status = course.Status.ARCHIVED
        course.save()
        accion(professor_client, generada, 'apply', approve=[0])
        assert Question.objects.filter(ai_generated=True).count() == 0

    def test_no_se_aplica_dos_veces(self, professor_client, generada, quiz):
        accion(professor_client, generada, 'apply', approve=[0, 1])
        accion(professor_client, generada, 'apply', approve=[0, 1])
        assert Question.objects.filter(ai_generated=True).count() == 2 and quiz.questions.count() == 3

    def test_el_constructor_marca_las_preguntas_hechas_con_ia(self, professor_client, generada, quiz):
        accion(professor_client, generada, 'apply', approve=[0])
        html = professor_client.get(reverse('quizzes:builder', args=[quiz.activity.pk])).content.decode()
        assert 'Hecha con IA' in html
        assert 'Hecha con IA' not in professor_client.get(reverse('quizzes:builder', args=[make_quiz(quiz.activity.course, 1).activity.pk])).content.decode()

    def test_las_aprobadas_no_borran_las_que_ya_habia_en_el_banco(self, professor_client, generada, course, professor):
        previa = QuestionFactory(author=professor, course=course, text='Una pregunta previa')
        accion(professor_client, generada, 'apply', approve=[0])
        assert Question.objects.filter(pk=previa.pk, ai_generated=False).exists()

    def test_el_tope_de_preguntas_del_plan_frena_todo(self, professor_client, generada, plus, monkeypatch):
        from apps.organizations import limits

        def lleno(organization, key, *, adding=1):
            raise limits.PlanLimitError('Tu banco está lleno.', limit='questions')

        monkeypatch.setattr(limits, 'check_limit', lleno)
        respuesta = accion(professor_client, generada, 'apply', approve=[0, 1])
        generada.refresh_from_db()
        assert generada.status == AIDraft.Status.READY and Question.objects.filter(ai_generated=True).count() == 0
        assert 'Tu banco está lleno.' in ' '.join(str(m) for m in respuesta.wsgi_request._messages)


class TestDesdeUnaSemana:
    def test_crea_el_quiz_en_borrador_enlazado_a_la_semana(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        programar(pregunta(), verdadero_falso(cita='Cloroplastos y fotosíntesis'))
        pedir(professor_client, course, [semanas[0], semanas[1]], django_capture_on_commit_callbacks, title='Quiz de la célula', points='2')
        draft = AIDraft.objects.get()
        assert draft.activity is None and draft.status == AIDraft.Status.READY
        respuesta = accion(professor_client, draft, 'apply', approve=[0, 1])
        actividad = Activity.objects.get()
        assert respuesta.url == reverse('quizzes:builder', args=[actividad.pk])
        assert (actividad.title, actividad.type, actividad.course, actividad.published) == ('Quiz de la célula', 'quiz', course, False)
        assert actividad.syllabus_week == semanas[0] and actividad.max_score == 4
        assert actividad.quiz.questions.count() == 2

    def test_el_nombre_por_omision_sale_de_la_semana(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        programar(pregunta())
        pedir(professor_client, course, [semanas[0]], django_capture_on_commit_callbacks)
        accion(professor_client, AIDraft.objects.get(), 'apply', approve=[0])
        assert Activity.objects.get().title == 'Quiz · La célula'

    def test_si_la_semana_desaparece_el_quiz_se_crea_sin_semana(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        programar(pregunta())
        pedir(professor_client, course, [semanas[0]], django_capture_on_commit_callbacks, title='Mi quiz')
        semanas[0].delete()
        accion(professor_client, AIDraft.objects.get(), 'apply', approve=[0])
        actividad = Activity.objects.get()
        assert actividad.title == 'Mi quiz' and actividad.syllabus_week is None

    def test_el_editor_de_la_semana_ofrece_el_boton_y_las_propuestas_pendientes(self, professor_client, plus, course, semanas, django_capture_on_commit_callbacks):
        programar(pregunta())
        pedir(professor_client, course, [semanas[0]], django_capture_on_commit_callbacks, title='Mi quiz')
        html = professor_client.get(reverse('syllabus:index', args=[course.pk]) + '?semana=1').content.decode()
        assert 'Generar quiz con IA' in html and 'modal-ai-quiz' in html and 'Revisar 1 pregunta propuesta' in html
        assert 'value="Quiz · La célula"' in html


class TestAcceso:
    def test_otro_docente_no_ve_la_propuesta(self, generada):
        otro = Client()
        otro.force_login(ProfessorFactory())
        assert otro.get(reverse('ai:draft', args=[generada.pk])).status_code == 404
        assert otro.get(reverse('ai:draft_status', args=[generada.pk])).status_code == 404
        assert otro.post(reverse('ai:draft', args=[generada.pk]), {'action': 'discard_all'}).status_code == 404

    def test_ni_siquiera_otro_docente_de_la_misma_organizacion(self, generada, course):
        from apps.organizations.models import Membership
        from apps.organizations.tests.factories import MembershipFactory

        colega = ProfessorFactory()
        MembershipFactory(user=colega, organization=course.organization, role=Membership.Role.TEACHER)
        cliente = Client()
        cliente.force_login(colega)
        assert cliente.get(reverse('ai:draft', args=[generada.pk])).status_code == 404

    def test_anonimo_va_al_login(self, generada):
        assert Client().get(reverse('ai:draft', args=[generada.pk])).status_code == 302

    def test_las_propuestas_pendientes_salen_en_el_quiz(self, professor_client, generada, quiz):
        html = professor_client.get(reverse('quizzes:builder', args=[quiz.activity.pk])).content.decode()
        assert 'Propuestas de IA' in html and reverse('ai:draft', args=[generada.pk]) in html and 'Revisar 2 preguntas propuestas' in html

    def test_el_boton_del_quiz_dice_por_que_esta_apagado(self, professor_client, professor, course, semanas):
        org = teaching_organization(professor)
        org.plan = Organization.Plan.FREE
        org.save()
        quiz = make_quiz(course, 1, published=False)
        html = professor_client.get(reverse('quizzes:builder', args=[quiz.activity.pk])).content.decode()
        assert 'Generar con IA' in html and 'plan Plus' in html and 'modal-ai-quiz' not in html

    def test_sin_semanas_en_el_temario_se_explica(self, professor_client, plus, course):
        quiz = make_quiz(course, 1, published=False)
        html = professor_client.get(reverse('quizzes:builder', args=[quiz.activity.pk])).content.decode()
        assert 'Arma primero las semanas del temario' in html


class TestReintentos:
    """Un fallo pasajero del proveedor (servidor saturado) se reintenta solo; el docente no se entera ni paga el intento."""

    def test_un_fallo_pasajero_se_reintenta_y_sale_bien(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        fake.PROVIDER.errors = [ProviderError('Gemini respondió 503', retryable=True), ProviderError('Gemini respondió 503', retryable=True)]
        programar(pregunta())
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.get().status == AIDraft.Status.READY and len(fake.PROVIDER.calls) == 3
        assert sorted(AIRequest.objects.values_list('status', flat=True)) == ['error', 'error', 'ok']
        from apps.ai import services

        assert services.uses_this_month(course.organization) == 1  # los intentos fallidos no cuentan

    def test_si_sigue_fallando_se_rinde_tras_tres_intentos(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('Gemini respondió 503', retryable=True)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.get().status == AIDraft.Status.FAILED and len(fake.PROVIDER.calls) == 3

    def test_un_fallo_que_no_es_pasajero_no_se_reintenta(self, professor_client, course, semanas, quiz, django_capture_on_commit_callbacks):
        fake.PROVIDER.error = ProviderError('Gemini respondió 400', retryable=False)
        pedir(professor_client, course, semanas, django_capture_on_commit_callbacks, activity=quiz.activity.pk)
        assert AIDraft.objects.get().status == AIDraft.Status.FAILED and len(fake.PROVIDER.calls) == 1

    def test_espera_entre_intentos_lo_que_dice_la_configuracion(self, plus, professor, monkeypatch):
        esperas = []
        monkeypatch.setattr(drafts.time, 'sleep', esperas.append)
        monkeypatch.setattr(drafts, 'RETRY_DELAYS', (3, 8))
        fake.PROVIDER.error = ProviderError('503', retryable=True)
        from apps.ai import services

        with pytest.raises(services.AIFailed):
            drafts._generate(organization=plus, user=professor, kind=AIRequest.Kind.QUIZ, prompt='x', schema={})
        assert esperas == [3, 8] and len(fake.PROVIDER.calls) == 3
