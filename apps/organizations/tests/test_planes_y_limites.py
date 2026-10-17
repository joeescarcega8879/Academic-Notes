"""Planes y límites: la tabla de planes, ``check_limit`` / ``has_feature`` y cada lugar donde se aplican.

Reglas (sección 2 de ``New_Phases.md``): solo se bloquea crear; los archivados no cuentan; una lista que excede
el tope se rechaza completa; lo que ya existe nunca se borra ni se bloquea.
"""

import itertools

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.tests.factories import ProfessorFactory, StudentFactory
from apps.courses.tests.factories import AcademicYearFactory, CourseFactory, StudentRecordFactory
from apps.courses.models import Course, Enrollment, Student
from apps.courses.services import importing, roster
from apps.courses.services.courses import archive_course, clone_course, unarchive_course
from apps.grades.tests.factories import ActivityFactory
from apps.organizations import limits, plans
from apps.organizations.limits import PlanLimitError
from apps.organizations.models import Membership, Organization
from apps.quizzes.tests.factories import QuestionFactory, make_quiz
from apps.quizzes.models import Question, QuizConfig
from apps.quizzes.services import bank
from apps.reports.services import pdf, workbook
from apps.reports.services.transcript import build_transcripts

pytestmark = pytest.mark.django_db

Plan = Organization.Plan
_numeros = itertools.count(1)


# ── Ayudas ────────────────────────────────────────────────────────────

def cliente(user):
    client = Client()
    client.force_login(user)
    return client


def org_de(user):
    return Membership.objects.get(user=user).organization


def con_plan(user, plan):
    organization = org_de(user)
    organization.plan = plan
    organization.save(update_fields=['plan'])
    return organization


def inscribir_en(course, fichas):
    """Inscribe fichas en el grupo en bloque (``bulk_create`` no pasa por ``save``, que fija la organización)."""
    Enrollment.objects.bulk_create([Enrollment(organization=course.organization, student=f, course=course) for f in fichas])


def llenar_alumnos(course, cantidad):
    """``cantidad`` alumnos sin cuenta inscritos en el grupo (en bloque: es mucho más rápido que las fábricas)."""
    fichas = Student.objects.bulk_create([
        Student(organization=course.organization, first_name=f'Alumno{next(_numeros)}', last_name='Prueba') for _ in range(cantidad)
    ])
    inscribir_en(course, fichas)
    return fichas


def llenar_banco(user, cantidad):
    for _ in range(cantidad):
        QuestionFactory(author=user)


def mensajes(response):
    return [str(m) for m in response.context['messages']] if response.context else []


@pytest.fixture
def docente():
    return ProfessorFactory()


@pytest.fixture
def org(docente):
    return org_de(docente)


# ══ La tabla de planes ════════════════════════════════════════════════

class TestTablaDePlanes:
    def test_el_plan_gratis_tiene_los_topes_aprobados(self):
        gratis = plans.FREE
        assert (gratis.groups, gratis.students, gratis.questions) == (2, 60, 30)
        assert not (gratis.timed_quizzes or gratis.custom_workbook or gratis.clean_transcripts)

    def test_el_plan_docente_cuesta_lo_aprobado_y_no_tiene_topes(self):
        docente = plans.TEACHER
        assert (docente.monthly_price, docente.annual_price) == (149, 1490)
        assert (docente.groups, docente.students, docente.questions) == (None, None, None)
        assert docente.timed_quizzes and docente.custom_workbook and docente.clean_transcripts

    @pytest.mark.parametrize('plan', [Plan.TEACHER_PLUS, Plan.BASIC, Plan.STANDARD, Plan.ENTERPRISE])
    def test_los_planes_asignados_a_mano_no_tienen_topes_ni_precio_de_autoservicio(self, plan):
        spec = plans.spec_for(plan)
        assert spec.groups is None and spec.students is None and spec.questions is None
        assert spec.timed_quizzes and spec.custom_workbook and spec.clean_transcripts
        assert spec.monthly_price is None and spec.annual_price is None

    def test_todos_los_planes_del_modelo_tienen_especificacion(self):
        assert {p.value for p in Plan} == {str(k) for k in plans.PLANS}

    def test_un_plan_desconocido_se_trata_como_gratis(self):
        assert plans.spec_for('inventado') is plans.FREE

    def test_la_organizacion_nueva_nace_en_gratis(self, org):
        assert org.plan == Plan.FREE and limits.plan_for(org).is_free


# ══ check_limit / has_feature ═════════════════════════════════════════

class TestCheckLimit:
    def test_grupos_hasta_el_tope(self, docente, org):
        CourseFactory(professor=docente)
        limits.check_limit(org, 'groups')  # 1 de 2: cabe otro
        CourseFactory(professor=docente)
        with pytest.raises(PlanLimitError) as error:
            limits.check_limit(org, 'groups')
        assert 'Tu plan Gratis permite 2 grupos activos y ya tienes 2' in str(error.value.messages[0])

    def test_los_grupos_archivados_no_cuentan(self, docente, org):
        primero, _ = CourseFactory(professor=docente), CourseFactory(professor=docente)
        archive_course(primero)
        limits.check_limit(org, 'groups')

    def test_alumnos_se_cuentan_una_sola_vez_aunque_esten_en_varios_grupos(self, docente, org):
        uno, dos = CourseFactory(professor=docente), CourseFactory(professor=docente)
        fichas = llenar_alumnos(uno, 5)
        inscribir_en(dos, fichas)
        assert limits.usage(org)['students'] == 5

    def test_los_alumnos_de_un_grupo_archivado_no_cuentan(self, docente, org):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 7)
        archive_course(grupo)
        assert limits.usage(org)['students'] == 0

    def test_un_alumno_sin_inscripcion_no_cuenta(self, org):
        StudentRecordFactory(organization=org, user=None)
        assert limits.usage(org)['students'] == 0

    def test_agregar_varios_a_la_vez(self, docente, org):
        llenar_alumnos(CourseFactory(professor=docente), 40)
        limits.check_limit(org, 'students', adding=20)  # 60 justo
        with pytest.raises(PlanLimitError, match='agregaría 21 alumnos a los 40'):
            limits.check_limit(org, 'students', adding=21)

    def test_las_preguntas_archivadas_no_cuentan(self, docente, org):
        llenar_banco(docente, 29)
        archivada = QuestionFactory(author=docente)
        Question.objects.filter(pk=archivada.pk).update(is_archived=True)
        limits.check_limit(org, 'questions')  # 29 activas de 30
        QuestionFactory(author=docente)
        with pytest.raises(PlanLimitError, match='30 preguntas en el banco y ya tienes 30'):
            limits.check_limit(org, 'questions')

    def test_el_plan_docente_no_tiene_topes_ni_consulta_la_base(self, docente):
        organization = con_plan(docente, Plan.TEACHER)
        with CaptureQueriesContext(connection) as consultas:
            for key in plans.LIMIT_KEYS:
                limits.check_limit(organization, key, adding=10_000)
            limits.check_students(organization, [1, 2, 3])
        assert len(consultas) == 0

    def test_agregar_cero_no_hace_nada(self, docente, org):
        llenar_alumnos(CourseFactory(professor=docente), 60)
        limits.check_limit(org, 'students', adding=0)

    def test_limite_desconocido(self, org):
        with pytest.raises(ValueError):
            limits.check_limit(org, 'inventado')

    def test_el_error_es_un_validation_error_para_que_los_formularios_lo_muestren(self, docente, org):
        from django.core.exceptions import ValidationError

        CourseFactory.create_batch(2, professor=docente)
        with pytest.raises(ValidationError):
            limits.check_limit(org, 'groups')


class TestHasFeature:
    @pytest.mark.parametrize('funcion', plans.FEATURE_KEYS)
    def test_gratis_no_las_tiene_y_docente_si(self, docente, funcion):
        assert not limits.has_feature(org_de(docente), funcion)
        assert limits.has_feature(con_plan(docente, Plan.TEACHER), funcion)

    def test_funcion_desconocida(self, org):
        with pytest.raises(ValueError):
            limits.has_feature(org, 'inventada')


# ══ Grupos ════════════════════════════════════════════════════════════

class TestGrupos:
    def test_crear_un_grupo_con_espacio_funciona(self, docente):
        CourseFactory(professor=docente)
        client = cliente(docente)
        assert client.get(reverse('course_create')).status_code == 200

    def test_al_tope_avisa_y_manda_al_inicio_sin_dejar_llenar_el_formulario(self, docente):
        CourseFactory.create_batch(2, professor=docente)
        respuesta = cliente(docente).get(reverse('course_create'), follow=True)
        assert respuesta.redirect_chain[-1][0] == reverse('professor_dashboard')
        html = respuesta.content.decode()
        assert 'permite 2 grupos activos y ya tienes 2' in html
        assert f'href="{reverse("organizations:plan")}"' in html and 'Mejorar plan' in html

    def datos_validos(self, org):
        ciclo = AcademicYearFactory(organization=org)
        return {'name': 'Tercero', 'code': 'T3', 'academic_year': ciclo.pk, 'schedule': '', 'color': '#336699', 'description': ''}

    def test_con_espacio_el_post_crea_el_grupo(self, docente, org):
        CourseFactory(professor=docente)
        respuesta = cliente(docente).post(reverse('course_create'), self.datos_validos(org))
        assert respuesta.status_code == 302 and Course.objects.filter(organization=org, code='T3').exists()

    def test_al_tope_el_post_tampoco_crea(self, docente, org):
        CourseFactory.create_batch(2, professor=docente)
        respuesta = cliente(docente).post(reverse('course_create'), self.datos_validos(org))
        assert respuesta.status_code == 302 and respuesta.url == reverse('professor_dashboard')
        assert Course.objects.filter(organization=org).count() == 2

    def test_archivar_libera_un_lugar(self, docente, org):
        primero, _ = CourseFactory(professor=docente), CourseFactory(professor=docente)
        client = cliente(docente)
        client.post(reverse('course_archive', args=[primero.pk]))
        assert client.get(reverse('course_create')).status_code == 200

    def test_el_plan_docente_crea_los_que_quiera(self, docente):
        con_plan(docente, Plan.TEACHER)
        CourseFactory.create_batch(5, professor=docente)
        assert cliente(docente).get(reverse('course_create')).status_code == 200

    def test_desarchivar_verifica_el_tope_de_grupos(self, docente):
        archivado = CourseFactory(professor=docente)
        archive_course(archivado)
        CourseFactory.create_batch(2, professor=docente)
        respuesta = cliente(docente).post(reverse('course_unarchive', args=[archivado.pk]), follow=True)
        archivado.refresh_from_db()
        assert archivado.is_archived
        assert 'permite 2 grupos activos' in respuesta.content.decode()

    def test_desarchivar_con_espacio_funciona(self, docente):
        archivado = CourseFactory(professor=docente)
        archive_course(archivado)
        unarchive_course(archivado)
        assert not archivado.is_archived

    def test_desarchivar_verifica_los_alumnos_que_volverian_a_contar(self, docente):
        archivado = CourseFactory(professor=docente)
        llenar_alumnos(archivado, 30)
        archive_course(archivado)
        llenar_alumnos(CourseFactory(professor=docente), 40)
        with pytest.raises(PlanLimitError, match='agregaría 30 alumnos a los 40'):
            unarchive_course(archivado)
        assert archivado.is_archived

    def test_desarchivar_un_grupo_cuyos_alumnos_ya_cuentan_no_suma(self, docente):
        activo = CourseFactory(professor=docente)
        fichas = llenar_alumnos(activo, 60)
        archivado = CourseFactory(professor=docente)
        inscribir_en(archivado, fichas)
        archive_course(archivado)
        unarchive_course(archivado)  # los mismos 60 alumnos: no cuentan de más
        assert not archivado.is_archived

    def test_duplicar_cuenta_como_un_grupo_mas(self, docente, org):
        original = CourseFactory(professor=docente)
        CourseFactory(professor=docente)
        with pytest.raises(PlanLimitError):
            clone_course(original, AcademicYearFactory(organization=original.organization), code='NUEVO')
        assert Course.objects.filter(organization=org).count() == 2

    def test_duplicar_en_la_pantalla_muestra_el_error_en_el_formulario(self, docente):
        original = CourseFactory(professor=docente)
        CourseFactory(professor=docente)
        ciclo_nuevo = AcademicYearFactory(organization=original.organization)
        respuesta = cliente(docente).post(
            reverse('course_clone', args=[original.pk]), {'academic_year': ciclo_nuevo.pk, 'name': 'Copia', 'code': 'COPIA-1'},
        )
        assert respuesta.status_code == 200
        assert 'permite 2 grupos activos' in str(respuesta.context['form'].non_field_errors())

    def test_duplicar_con_espacio_funciona(self, docente):
        original = CourseFactory(professor=docente)
        nuevo = clone_course(original, AcademicYearFactory(organization=original.organization), code='OTRO')
        assert nuevo.pk != original.pk


# ══ Alumnos ═══════════════════════════════════════════════════════════

class TestAlumnos:
    def test_agregar_un_alumno_en_el_tope_no_se_crea(self, docente, org):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 60)
        with pytest.raises(PlanLimitError, match='permite 60 alumnos en grupos activos y ya tienes 60'):
            roster.add_student(grupo, first_name='Uno', last_name='Más')
        assert Student.objects.filter(organization=org).count() == 60

    def test_el_alumno_60_si_entra(self, docente):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 59)
        roster.add_student(grupo, first_name='Último', last_name='Lugar')
        assert limits.usage(grupo.organization)['students'] == 60

    def test_en_la_pantalla_avisa_con_enlace_y_no_agrega(self, docente, org):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 60)
        respuesta = cliente(docente).post(
            reverse('student_add', args=[grupo.pk]), {'action': 'new', 'first_name': 'Uno', 'last_name': 'Más'},
        )
        assert respuesta.status_code == 200
        html = respuesta.content.decode()
        assert 'permite 60 alumnos' in html and 'Mejorar plan' in html
        assert Student.objects.filter(organization=org).count() == 60

    def test_inscribir_en_otro_grupo_a_quien_ya_cuenta_no_suma(self, docente):
        uno, dos = CourseFactory(professor=docente), CourseFactory(professor=docente)
        fichas = llenar_alumnos(uno, 60)
        roster.enroll_existing(dos, fichas[0])
        assert limits.usage(uno.organization)['students'] == 60

    def test_inscribir_a_quien_no_cuenta_si_suma(self, docente, org):
        uno, dos = CourseFactory(professor=docente), CourseFactory(professor=docente)
        llenar_alumnos(uno, 60)
        aparte = StudentRecordFactory(organization=org, user=None)  # sin inscripción: no cuenta todavía
        with pytest.raises(PlanLimitError):
            roster.enroll_existing(dos, aparte)

    def test_el_plan_docente_no_tiene_tope_de_alumnos(self, docente):
        organization = con_plan(docente, Plan.TEACHER)
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 80)
        roster.add_student(grupo, first_name='Más', last_name='Allá')
        assert limits.usage(organization)['students'] == 81


class TestImportarLista:
    def csv(self, cantidad, desde=0):
        filas = ['Matrícula,Nombre,Apellidos,Correo'] + [f'M{desde + i:04d},Nombre{desde + i},Apellido,' for i in range(cantidad)]
        return '\n'.join(filas).encode('utf-8')

    def preparar(self, client, grupo, contenido):
        client.post(reverse('student_import', args=[grupo.pk]), {'file': SimpleUploadedFile('lista.csv', contenido)})
        return reverse('student_import_preview', args=[grupo.pk])

    CAMPOS = {'action': 'confirm', 'map_student_number': 0, 'map_first_name': 1, 'map_last_name': 2, 'map_email': 3}

    def test_una_lista_que_pasa_el_tope_se_rechaza_completa(self, docente, org):
        grupo = CourseFactory(professor=docente)
        client = cliente(docente)
        url = self.preparar(client, grupo, self.csv(70))
        respuesta = client.post(url, self.CAMPOS)
        assert respuesta.status_code == 200
        assert 'agregaría 70 alumnos' in respuesta.content.decode()
        assert Student.objects.filter(organization=org).count() == 0  # ni siquiera los primeros 60

    def test_la_vista_previa_avisa_y_no_deja_confirmar(self, docente):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 40)
        client = cliente(docente)
        respuesta = client.get(self.preparar(client, grupo, self.csv(30)))
        assert 'agregaría 30 alumnos a los 40' in respuesta.context['limit_error']
        assert respuesta.context['can_confirm'] is False
        assert 'Mejorar plan' in respuesta.content.decode()

    def test_una_lista_que_cabe_justo_se_importa(self, docente, org):
        grupo = CourseFactory(professor=docente)
        client = cliente(docente)
        url = self.preparar(client, grupo, self.csv(60))
        respuesta = client.get(url)
        assert respuesta.context['limit_error'] == '' and respuesta.context['can_confirm'] is True
        client.post(url, self.CAMPOS)
        assert limits.usage(org)['students'] == 60

    def test_resubir_la_lista_actualizada_no_cuenta_de_mas(self, docente, org):
        grupo = CourseFactory(professor=docente)
        client = cliente(docente)
        client.post(self.preparar(client, grupo, self.csv(60)), self.CAMPOS)
        url = self.preparar(client, grupo, self.csv(60))  # los mismos 60 (se actualizan, no se agregan)
        assert client.get(url).context['limit_error'] == ''

    def test_cuentan_solo_los_nuevos_cuando_la_lista_mezcla_conocidos(self, docente):
        grupo = CourseFactory(professor=docente)
        client = cliente(docente)
        client.post(self.preparar(client, grupo, self.csv(50)), self.CAMPOS)
        # 50 ya estaban + 10 nuevos = 60: cabe.  50 + 11 nuevos = 61: no.
        assert client.get(self.preparar(client, grupo, self.csv(60))).context['limit_error'] == ''
        assert 'agregaría 11' in client.get(self.preparar(client, grupo, self.csv(61))).context['limit_error']

    def test_importar_en_otro_grupo_a_alumnos_que_ya_cuentan_no_suma(self, docente, org):
        uno, dos = CourseFactory(professor=docente), CourseFactory(professor=docente)
        client = cliente(docente)
        client.post(self.preparar(client, uno, self.csv(60)), self.CAMPOS)  # el grupo uno ya tiene sus 60
        url = self.preparar(client, dos, self.csv(60))  # los mismos 60, ahora también en el grupo dos
        vista_previa = client.get(url)
        assert vista_previa.context['plan'].to_enroll == 60  # sí se inscriben...
        assert vista_previa.context['limit_error'] == ''  # ...pero no cuentan de más
        client.post(url, self.CAMPOS)
        assert limits.usage(org)['students'] == 60

    def test_el_servicio_rechaza_igual_si_alguien_se_salta_la_pantalla(self, docente, org):
        grupo = CourseFactory(professor=docente)
        headers, rows = importing.read_table('lista.csv', self.csv(70))
        plan = importing.analyze(grupo, rows, importing.detect_mapping(headers))
        with pytest.raises(PlanLimitError):
            importing.apply_import(grupo, plan)
        assert Student.objects.filter(organization=org).count() == 0

    def test_plan_docente_importa_listas_grandes(self, docente, org):
        con_plan(docente, Plan.TEACHER)
        grupo = CourseFactory(professor=docente)
        client = cliente(docente)
        client.post(self.preparar(client, grupo, self.csv(120)), self.CAMPOS)
        assert limits.usage(org)['students'] == 120


# ══ Banco de preguntas ════════════════════════════════════════════════

CABECERA = 'Pregunta,Tipo,Opción A,Opción B,Correcta'


class TestBancoDePreguntas:
    def test_al_tope_no_se_crea_una_pregunta(self, docente, org):
        llenar_banco(docente, 30)
        with pytest.raises(PlanLimitError, match='30 preguntas'):
            bank.save_question(
                organization=org, author=docente, kind=Question.Kind.TRUE_FALSE, text='¿Una más?', points=1, true_is_correct=True,
            )

    def test_editar_una_existente_no_cuenta(self, docente, org):
        llenar_banco(docente, 30)
        existente = Question.objects.filter(organization=org).first()
        bank.save_question(
            organization=org, author=docente, kind=existente.kind, text='Editada', points=1,
            choices=[(c.text, c.is_correct) for c in existente.choices.all()], question=existente,
        )
        assert Question.objects.get(pk=existente.pk).text == 'Editada'

    def test_la_pantalla_de_nueva_pregunta_avisa_antes_de_dejar_escribir(self, docente):
        llenar_banco(docente, 30)
        respuesta = cliente(docente).get(reverse('quizzes:question_create', args=['multiple_choice']), follow=True)
        assert respuesta.redirect_chain[-1][0] == reverse('quizzes:bank')
        assert 'permite 30 preguntas' in respuesta.content.decode() and 'Mejorar plan' in respuesta.content.decode()

    def test_el_post_directo_tampoco_crea(self, docente, org):
        llenar_banco(docente, 30)
        datos = {'text': '¿Cuánto es 2+2?', 'points': 1, 'correct': 'true', 'explanation': '', 'topic': ''}
        respuesta = cliente(docente).post(reverse('quizzes:question_create', args=['true_false']), datos)
        assert respuesta.status_code == 200 and 'permite 30 preguntas' in respuesta.content.decode()
        assert Question.objects.filter(organization=org).count() == 30

    def test_duplicar_una_pregunta_cuenta(self, docente, org):
        llenar_banco(docente, 30)
        original = Question.objects.filter(organization=org).first()
        respuesta = cliente(docente).post(reverse('quizzes:question_duplicate', args=[original.pk]), follow=True)
        assert 'permite 30 preguntas' in respuesta.content.decode()
        assert Question.objects.filter(organization=org).count() == 30

    def test_archivar_libera_y_volver_al_banco_verifica(self, docente, org):
        llenar_banco(docente, 30)
        client = cliente(docente)
        primera, segunda = list(Question.objects.filter(organization=org)[:2])
        client.post(reverse('quizzes:question_archive', args=[primera.pk]))
        assert limits.usage(org)['questions'] == 29
        QuestionFactory(author=docente)  # vuelve a quedar en 30
        respuesta = client.post(reverse('quizzes:question_archive', args=[primera.pk]), follow=True)
        assert Question.objects.get(pk=primera.pk).is_archived
        assert 'permite 30 preguntas' in respuesta.content.decode()

    def test_una_importacion_que_pasa_el_tope_se_rechaza_completa(self, docente, org):
        llenar_banco(docente, 20)
        filas = [f'Pregunta importada {i},Verdadero/Falso,,,Verdadero' for i in range(15)]
        client = cliente(docente)
        client.post(reverse('quizzes:import'), {'file': SimpleUploadedFile('p.csv', (CABECERA + '\n' + '\n'.join(filas)).encode())})
        vista_previa = client.get(reverse('quizzes:import_preview'))
        assert 'agregaría 15 preguntas a las 20' in vista_previa.context['limit_error']
        assert vista_previa.context['can_confirm'] is False
        respuesta = client.post(reverse('quizzes:import_preview'), follow=True)
        assert 'agregaría 15 preguntas' in respuesta.content.decode()
        assert Question.objects.filter(organization=org).count() == 20  # ninguna de las 15

    def test_el_servicio_rechaza_la_importacion_completa_con_su_mensaje(self, docente, org):
        from apps.courses.services.importing import read_table
        from apps.quizzes.services import question_import

        llenar_banco(docente, 20)
        filas = [f'Pregunta importada {i},Verdadero/Falso,,,Verdadero' for i in range(15)]
        headers, rows = read_table('p.csv', '\n'.join([CABECERA, *filas]).encode())
        plan = question_import.analyze(org, headers, rows)
        with pytest.raises(PlanLimitError, match='agregaría 15 preguntas a las 20'):
            question_import.apply_import(org, docente, plan)
        assert Question.objects.filter(organization=org).count() == 20

    def test_una_importacion_que_cabe_se_aplica(self, docente, org):
        llenar_banco(docente, 20)
        filas = [f'Pregunta importada {i},Verdadero/Falso,,,Verdadero' for i in range(10)]
        client = cliente(docente)
        client.post(reverse('quizzes:import'), {'file': SimpleUploadedFile('p.csv', (CABECERA + '\n' + '\n'.join(filas)).encode())})
        client.post(reverse('quizzes:import_preview'))
        assert limits.usage(org)['questions'] == 30

    def test_plan_docente_sin_tope_de_preguntas(self, docente, org):
        con_plan(docente, Plan.TEACHER)
        llenar_banco(docente, 45)
        assert limits.usage(org)['questions'] == 45


# ══ Funciones: quiz con tiempo límite ═════════════════════════════════

class TestQuizConTiempo:
    @pytest.fixture
    def quiz(self, docente):
        return make_quiz(CourseFactory(professor=docente), questions=1)

    def datos(self, **extra):
        base = {
            'action': 'settings', 'attempts_allowed': 1, 'shuffle_questions': '', 'shuffle_choices': '',
            'feedback_mode': 'after_submit', 'attempt_policy': 'highest',
        }
        return {**base, **extra}

    def test_en_gratis_el_campo_sale_deshabilitado_con_su_explicacion(self, docente, quiz):
        respuesta = cliente(docente).get(reverse('quizzes:builder', args=[quiz.activity.pk]))
        campo = respuesta.context['config_form'].fields['time_limit_minutes']
        assert campo.disabled and 'plan Pro' in campo.help_text
        assert 'Ver planes' in respuesta.content.decode()

    def test_en_gratis_un_post_con_tiempo_se_ignora(self, docente, quiz):
        cliente(docente).post(reverse('quizzes:builder', args=[quiz.activity.pk]), self.datos(time_limit_minutes=45, attempts_allowed=3))
        quiz.refresh_from_db()
        assert quiz.attempts_allowed == 3  # lo demás sí se guardó
        assert quiz.time_limit_minutes is None  # el tiempo no

    def test_en_gratis_se_conserva_un_tiempo_ya_fijado_al_guardar_otra_cosa(self, docente, quiz):
        QuizConfig.objects.filter(pk=quiz.pk).update(time_limit_minutes=30)  # p. ej. de cuando tenía plan Pro
        cliente(docente).post(reverse('quizzes:builder', args=[quiz.activity.pk]), self.datos(time_limit_minutes='', attempts_allowed=2))
        quiz.refresh_from_db()
        assert quiz.time_limit_minutes == 30 and quiz.attempts_allowed == 2

    def test_en_docente_se_fija_el_tiempo(self, docente, quiz):
        con_plan(docente, Plan.TEACHER)
        cliente(docente).post(reverse('quizzes:builder', args=[quiz.activity.pk]), self.datos(time_limit_minutes=45))
        quiz.refresh_from_db()
        assert quiz.time_limit_minutes == 45

    def test_en_docente_el_campo_no_esta_bloqueado(self, docente, quiz):
        con_plan(docente, Plan.TEACHER)
        respuesta = cliente(docente).get(reverse('quizzes:builder', args=[quiz.activity.pk]))
        assert not respuesta.context['config_form'].fields['time_limit_minutes'].disabled


# ══ Funciones: Excel y boletas ════════════════════════════════════════

class TestConcentradoExcel:
    @pytest.fixture
    def grupo(self, docente):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 2)
        return grupo

    def cabecera(self, contenido):
        from io import BytesIO

        from openpyxl import load_workbook

        return [c.value for c in load_workbook(BytesIO(contenido))['Concentrado'][1]]

    def fijas(self, grupo):
        """Las columnas fijas, armadas directamente con el servicio (sin pasar por el plan)."""
        return self.cabecera(workbook.build_workbook(grupo, list(workbook.DEFAULT_KEYS)))

    def test_gratis_muestra_las_columnas_fijas_y_bloqueadas(self, docente, grupo):
        respuesta = cliente(docente).get(reverse('reports:workbook', args=[grupo.pk]))
        assert respuesta.context['locked'] is True
        assert [r['column'].key for r in respuesta.context['rows']] == list(workbook.DEFAULT_KEYS)
        html = respuesta.content.decode()
        assert 'columnas fijas' in html and 'disabled' in html and 'data-move' not in html

    def test_gratis_descarga_siempre_las_columnas_fijas_aunque_pidan_otras(self, docente, grupo):
        client = cliente(docente)
        pedido = client.get(reverse('reports:workbook_download', args=[grupo.pk]), {'cols': ['final', 'last_name']})
        normal = client.get(reverse('reports:workbook_download', args=[grupo.pk]))
        assert self.cabecera(pedido.content) == self.cabecera(normal.content) == self.fijas(grupo)
        assert 'Apellidos' in self.cabecera(pedido.content)[1:2]  # el orden de siempre, no el pedido

    def test_gratis_no_puede_usar_una_eleccion_guardada_de_antes(self, docente, grupo):
        con_plan(docente, Plan.TEACHER)
        client = cliente(docente)
        client.get(reverse('reports:workbook_download', args=[grupo.pk]), {'cols': ['final', 'last_name']})
        con_plan(docente, Plan.FREE)
        assert self.cabecera(client.get(reverse('reports:workbook_download', args=[grupo.pk])).content) == self.fijas(grupo)

    def test_docente_elige_y_ordena(self, docente, grupo):
        con_plan(docente, Plan.TEACHER)
        client = cliente(docente)
        respuesta = client.get(reverse('reports:workbook_download', args=[grupo.pk]), {'cols': ['final', 'last_name']})
        assert self.cabecera(respuesta.content) == ['Calificación final', 'Apellidos']
        assert client.get(reverse('reports:workbook', args=[grupo.pk])).context['locked'] is False


class TestBoletasPdf:
    MARCA = b'Generado con Academic Notes'

    @pytest.fixture
    def grupo(self, docente):
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 3)
        ActivityFactory(course=grupo)
        return grupo

    def test_con_marca_de_agua_en_cada_pagina(self, grupo):
        contenido = pdf.render_transcripts(build_transcripts(grupo), compress=False, watermark=True)
        assert contenido.count(self.MARCA) == 3  # una por boleta (una página cada una)

    def test_sin_marca_de_agua(self, grupo):
        contenido = pdf.render_transcripts(build_transcripts(grupo), compress=False, watermark=False)
        assert self.MARCA not in contenido

    def test_la_marca_no_tapa_el_contenido(self, grupo):
        contenido = pdf.render_transcripts(build_transcripts(grupo), compress=False, watermark=True)
        assert b'Boleta de calificaciones' in contenido
        # Se dibuja antes del contenido de la página: queda detrás.
        assert contenido.index(self.MARCA) < contenido.index(b'Boleta de calificaciones')

    def test_la_vista_pide_marca_en_gratis_y_no_en_docente(self, docente, grupo, monkeypatch):
        pedidas = []
        original = pdf.render_transcripts
        monkeypatch.setattr(pdf, 'render_transcripts', lambda *a, **k: pedidas.append(k.get('watermark')) or original(*a, **k))
        client = cliente(docente)
        client.get(reverse('reports:transcripts', args=[grupo.pk]))
        con_plan(docente, Plan.TEACHER)
        client.get(reverse('reports:transcripts', args=[grupo.pk]))
        assert pedidas == [True, False]

    def test_la_boleta_de_un_alumno_tambien_lleva_marca_en_gratis(self, docente, grupo, monkeypatch):
        pedidas = []
        original = pdf.render_transcripts
        monkeypatch.setattr(pdf, 'render_transcripts', lambda *a, **k: pedidas.append(k.get('watermark')) or original(*a, **k))
        ficha = Student.objects.filter(organization=grupo.organization).first()
        respuesta = cliente(docente).get(reverse('reports:transcript', args=[grupo.pk, ficha.pk]))
        assert respuesta.status_code == 200 and pedidas == [True]


# ══ «Plan y facturación», Ajustes y admin ═════════════════════════════

URL_PLAN = reverse('organizations:plan')


class TestPantallaDelPlan:
    def test_sin_sesion_va_al_login(self):
        respuesta = Client().get(URL_PLAN)
        assert respuesta.status_code == 302 and '/login/' in respuesta.url

    def test_un_alumno_no_entra(self):
        respuesta = cliente(StudentFactory()).get(URL_PLAN)
        assert respuesta.status_code == 302 and respuesta.url != URL_PLAN

    def test_gratis_muestra_el_uso_los_precios_y_como_pedir_el_plan(self, docente, settings):
        settings.SUPPORT_EMAIL = 'ayuda@ejemplo.mx'
        grupo = CourseFactory(professor=docente)
        llenar_alumnos(grupo, 12)
        llenar_banco(docente, 3)
        html = cliente(docente).get(URL_PLAN).content.decode()
        assert 'Tu plan: Gratis' in html
        assert '1</div>' in html or '1 / 2' in html  # grupos
        for esperado in ('12 / 60', '3 / 30', '$149', '$1,490', 'Todavía no cobramos en línea'):
            assert esperado in html, esperado
        assert 'mailto:ayuda@ejemplo.mx?subject=Quiero%20el%20plan%20Pro' in html
        assert org_de(docente).name.replace(' ', '%20') in html  # la organización va en el cuerpo del correo

    def test_docente_no_ofrece_comprar_y_dice_sin_tope(self, docente):
        con_plan(docente, Plan.TEACHER)
        CourseFactory.create_batch(3, professor=docente)
        html = cliente(docente).get(URL_PLAN).content.decode()
        assert 'Tu plan: Pro' in html and 'sin tope' in html
        assert 'Pedir el plan' not in html and 'Cambios y cancelación' in html

    def test_por_encima_del_tope_explica_que_no_se_pierde_nada(self, docente):
        organization = con_plan(docente, Plan.TEACHER)
        CourseFactory.create_batch(4, professor=docente)  # 4 grupos activos
        con_plan(docente, Plan.FREE)  # bajó de plan: 4 de 2
        respuesta = cliente(docente).get(URL_PLAN)
        assert respuesta.context['over_limit'] is True
        assert 'por encima de los límites de tu plan' in respuesta.content.decode()
        assert organization.pk  # (la organización sigue siendo la misma)

    def test_por_encima_del_tope_no_borra_ni_bloquea_lo_existente(self, docente):
        con_plan(docente, Plan.TEACHER)
        grupos = CourseFactory.create_batch(4, professor=docente)
        llenar_alumnos(grupos[0], 70)
        con_plan(docente, Plan.FREE)
        client = cliente(docente)
        # Se sigue viendo y trabajando en todo lo que ya existe...
        for grupo in grupos:
            assert client.get(reverse('course_detail', args=[grupo.pk])).status_code == 200
        assert Course.objects.filter(professor=docente, status='active').count() == 4
        assert Student.objects.filter(organization=org_de(docente)).count() == 70
        # ...pero no se puede crecer. (Se vuelve a leer el grupo: el objeto de arriba conserva el plan anterior.)
        with pytest.raises(PlanLimitError):
            roster.add_student(Course.objects.get(pk=grupos[0].pk), first_name='Uno', last_name='Más')

    def test_un_docente_no_ve_los_numeros_de_otra_organizacion(self, docente):
        otro = ProfessorFactory()
        llenar_alumnos(CourseFactory(professor=otro), 50)
        assert '0 / 60' in cliente(docente).get(URL_PLAN).content.decode()


class TestAjustesYAdmin:
    def test_ajustes_resume_el_plan_con_enlace(self, docente):
        CourseFactory(professor=docente)
        html = cliente(docente).get(reverse('organizations:settings')).content.decode()
        assert 'Plan y facturación' in html and 'Gratis' in html and 'Ver planes y mejorar' in html
        assert f'href="{URL_PLAN}"' in html

    def test_ajustes_con_plan_docente(self, docente):
        con_plan(docente, Plan.TEACHER)
        html = cliente(docente).get(reverse('organizations:settings')).content.decode()
        assert 'Ver mi plan' in html and 'Ver planes y mejorar' not in html

    def test_el_plan_se_cambia_desde_la_lista_del_admin(self):
        from django.contrib import admin

        modelo = admin.site._registry[Organization]
        assert 'plan' in modelo.list_editable and 'plan' in modelo.list_display

    def test_el_admin_puede_pasar_una_organizacion_al_plan_docente(self, docente, org):
        from django.contrib.auth import get_user_model

        admin_user = get_user_model().objects.create_superuser(username='admin', email='admin@x.test', password='x', role='professor', dni='1')
        client = cliente(admin_user)
        datos = {
            'form-TOTAL_FORMS': 1, 'form-INITIAL_FORMS': 1, 'form-MIN_NUM_FORMS': 0, 'form-MAX_NUM_FORMS': 1000,
            'form-0-id': org.pk, 'form-0-plan': Plan.TEACHER, '_save': 'Guardar',
        }
        client.post('/admin/organizations/organization/', datos, HTTP_HOST='testserver')
        org.refresh_from_db()
        assert org.plan == Plan.TEACHER


class TestAvisoEnLosMensajes:
    def test_el_mensaje_de_limite_lleva_el_enlace_y_uno_normal_no(self, docente):
        CourseFactory.create_batch(2, professor=docente)
        client = cliente(docente)
        con_aviso = client.get(reverse('course_create'), follow=True).content.decode()
        assert con_aviso.count('Mejorar plan') >= 1
        sin_aviso = client.post(reverse('course_archive', args=[Course.objects.filter(professor=docente).first().pk]), follow=True)
        assert 'Mejorar plan' not in sin_aviso.content.decode()


# ══ La escuela de ejemplo ═════════════════════════════════════════════

class TestDemo:
    def test_la_escuela_de_ejemplo_usa_el_plan_docente(self):
        from apps.onboarding import demo

        demo.build_demo()
        organization = Membership.objects.get(user__email=demo.TEACHER_EMAIL).organization
        assert organization.plan == Plan.TEACHER
