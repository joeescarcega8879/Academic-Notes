"""Las pantallas del proyecto por equipos: armarlos, entregar, calificar y los permisos."""

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory
from apps.courses.services.courses import clone_course
from apps.courses.tests.factories import AcademicYearFactory, CourseFactory
from apps.grades.models import Activity, Grade, Submission
from apps.grades.services.gradebook import grade_activity
from apps.grades.services.submissions import submit
from apps.grades.tests.factories import ActivityFactory
from apps.organizations.models import Membership
from apps.organizations.services import SESSION_KEY
from apps.organizations.tests.factories import MembershipFactory
from apps.rubrics.tests.factories import choices_for, make_rubric
from apps.teams.models import Team
from apps.teams.services import teams
from apps.teams.tests.factories import enroll, make_team, team_project

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


def ir(client, nombre, *args, **datos):
    return client.post(reverse(nombre, args=args), datos, follow=True)


def mensajes(response):
    return [str(m) for m in response.context['messages']]


def cliente_de(usuario):
    client = Client()
    client.force_login(usuario)
    return client


@pytest.fixture
def proyecto(course):
    return team_project(course, due_at=AHORA + UN_DIA)


@pytest.fixture
def alumnos(course):
    return enroll(course, 4)


# ── Armar equipos ─────────────────────────────────────────────────────

class TestPantallaDeEquipos:
    def test_muestra_equipos_y_alumnos_sin_equipo(self, professor_client, proyecto, alumnos):
        make_team(proyecto, alumnos[0], name='Águilas')
        pagina = professor_client.get(reverse('teams:index', args=[proyecto.pk])).content.decode()
        assert 'Águilas' in pagina and str(alumnos[0]) in pagina and str(alumnos[1]) in pagina
        assert '3 de 4 alumnos aún sin equipo' in pagina

    def test_sin_alumnos(self, professor_client, proyecto):
        assert 'El grupo no tiene alumnos todavía' in professor_client.get(reverse('teams:index', args=[proyecto.pk])).content.decode()

    def test_crear_equipo(self, professor_client, proyecto):
        response = ir(professor_client, 'teams:create', proyecto.pk, name='Halcones')
        assert proyecto.teams.get().name == 'Halcones' and mensajes(response) == ['Se creó «Halcones».']

    def test_un_nombre_repetido_avisa_y_no_crea(self, professor_client, proyecto):
        teams.create_team(proyecto, 'Halcones')
        response = ir(professor_client, 'teams:create', proyecto.pk, name='halcones')
        assert proyecto.teams.count() == 1 and mensajes(response) == ['Ya hay un equipo con ese nombre.']

    def test_repartir_al_azar(self, professor_client, proyecto, alumnos):
        response = ir(professor_client, 'teams:random', proyecto.pk, count='2')
        assert proyecto.teams.count() == 2 and 'Se repartieron' in mensajes(response)[0]
        assert not teams.unassigned_enrollments(proyecto)

    @pytest.mark.parametrize('cuantos', ['', 'abc', '-3', '1', '9'])
    def test_repartir_con_una_cantidad_invalida(self, professor_client, proyecto, alumnos, cuantos):
        response = ir(professor_client, 'teams:random', proyecto.pk, count=cuantos)
        assert not proyecto.teams.exists() and mensajes(response)

    def test_asignar_y_quitar(self, professor_client, proyecto, alumnos):
        team = teams.create_team(proyecto)
        response = ir(professor_client, 'teams:assign', proyecto.pk, student=alumnos[0].pk, team=team.pk)
        assert teams.team_of(proyecto, alumnos[0]) == team and mensajes(response) == [f'{alumnos[0]} está en «Equipo 1».']
        response = ir(professor_client, 'teams:assign', proyecto.pk, student=alumnos[0].pk, team='')
        assert teams.team_of(proyecto, alumnos[0]) is None and mensajes(response) == [f'{alumnos[0]} quedó sin equipo.']

    def test_asignar_a_un_equipo_de_otro_proyecto_es_404(self, professor_client, course, proyecto, alumnos):
        ajeno = teams.create_team(team_project(course))
        response = professor_client.post(reverse('teams:assign', args=[proyecto.pk]), {'student': alumnos[0].pk, 'team': ajeno.pk})
        assert response.status_code == 404 and teams.team_of(proyecto, alumnos[0]) is None

    def test_asignar_a_alguien_de_otro_grupo_es_404(self, professor_client, proyecto):
        otro = enroll(CourseFactory(professor=proyecto.course.professor), 1)[0]
        team = teams.create_team(proyecto)
        assert professor_client.post(reverse('teams:assign', args=[proyecto.pk]), {'student': otro.pk, 'team': team.pk}).status_code == 404

    def test_un_dato_que_no_es_numero_es_404_y_no_500(self, professor_client, proyecto):
        assert professor_client.post(reverse('teams:assign', args=[proyecto.pk]), {'student': 'x', 'team': ''}).status_code == 404

    def test_quien_ya_tiene_calificacion_no_se_mueve(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        grade_activity(proyecto, alumnos[0], score=8)
        response = ir(professor_client, 'teams:assign', proyecto.pk, student=alumnos[0].pk, team='')
        assert teams.team_of(proyecto, alumnos[0]) == team and 'ya tiene calificación' in mensajes(response)[0]

    def test_renombrar(self, professor_client, proyecto):
        team = teams.create_team(proyecto)
        response = ir(professor_client, 'teams:rename', proyecto.pk, team.pk, name='Las Águilas')
        team.refresh_from_db()
        assert team.name == 'Las Águilas' and mensajes(response) == ['El equipo ahora se llama «Las Águilas».']

    def test_borrar(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        response = ir(professor_client, 'teams:delete', proyecto.pk, team.pk)
        assert not Team.objects.exists() and 'quedaron sin equipo' in mensajes(response)[0]

    def test_no_se_borra_con_entrega(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        submit(proyecto, alumnos[0], text='listo', now=AHORA)
        response = ir(professor_client, 'teams:delete', proyecto.pk, team.pk)
        assert Team.objects.filter(pk=team.pk).exists() and 'ya entregó' in mensajes(response)[0]
        assert 'Borrar equipo' not in professor_client.get(reverse('teams:index', args=[proyecto.pk])).content.decode()

    def test_copiar_equipos(self, professor_client, course, proyecto, alumnos):
        make_team(proyecto, alumnos[0], name='Uno')
        nuevo = team_project(course)
        pagina = professor_client.get(reverse('teams:index', args=[nuevo.pk])).content.decode()
        assert 'Copiar sus equipos' in pagina and proyecto.title in pagina
        response = ir(professor_client, 'teams:copy', nuevo.pk, source=proyecto.pk)
        assert nuevo.teams.get().name == 'Uno' and mensajes(response) == [f'Se copiaron 1 equipos de «{proyecto.title}».']

    def test_copiar_de_un_proyecto_de_otro_grupo_es_404(self, professor_client, proyecto):
        ajeno = team_project(CourseFactory(professor=proyecto.course.professor))
        assert professor_client.post(reverse('teams:copy', args=[proyecto.pk]), {'source': ajeno.pk}).status_code == 404

    def test_las_acciones_solo_por_post(self, professor_client, proyecto):
        team = teams.create_team(proyecto)
        for nombre, args in (('create', ()), ('random', ()), ('copy', ()), ('assign', ()), ('rename', (team.pk,)), ('delete', (team.pk,))):
            assert professor_client.get(reverse(f'teams:{nombre}', args=[proyecto.pk, *args])).status_code == 405


class TestPermisos:
    RUTAS = (
        ('index', 'get'), ('grade_list', 'get'), ('create', 'post'), ('random', 'post'), ('copy', 'post'), ('assign', 'post'),
    )

    def prueba(self, client, proyecto, esperado):
        for nombre, metodo in self.RUTAS:
            response = getattr(client, metodo)(reverse(f'teams:{nombre}', args=[proyecto.pk]))
            assert response.status_code == esperado, nombre

    def test_un_alumno_no_entra(self, student_client, proyecto, enrollment):
        self.prueba(student_client, proyecto, 302)  # el alumno vuelve a su panel

    def test_un_docente_ajeno_no_entra(self, proyecto):
        self.prueba(cliente_de(ProfessorFactory()), proyecto, 404)

    def test_el_docente_de_otro_grupo_de_la_misma_organizacion_no_entra(self, proyecto):
        otro = ProfessorFactory()
        MembershipFactory(user=otro, organization=proyecto.organization, role=Membership.Role.TEACHER)
        CourseFactory(professor=otro, organization=proyecto.organization)
        client = cliente_de(otro)
        sesion = client.session
        sesion[SESSION_KEY] = proyecto.organization_id
        sesion.save()
        self.prueba(client, proyecto, 404)

    def test_anonimo_va_al_login(self, client, proyecto):
        assert client.get(reverse('teams:index', args=[proyecto.pk])).url.startswith('/login/')

    def test_un_proyecto_individual_no_tiene_pantalla_de_equipos(self, professor_client, course):
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        assert professor_client.get(reverse('teams:index', args=[individual.pk])).status_code == 404
        assert professor_client.get(reverse('teams:grade_list', args=[individual.pk])).status_code == 404

    def test_un_grupo_archivado_es_404(self, professor_client, course, proyecto):
        from apps.courses.services.courses import archive_course

        archive_course(course)
        assert professor_client.get(reverse('teams:index', args=[proyecto.pk])).status_code == 404


# ── Calificar ─────────────────────────────────────────────────────────

class TestCalificarEnPantalla:
    def datos(self, proyecto, nivel=0, **extra):
        elegidos = choices_for(proyecto.rubric_version, nivel)
        return {**{f'c_{k}': v for k, v in elegidos.items()}, **extra}

    def test_calificar_y_listar_van_por_equipos(self, professor_client, proyecto, alumnos):
        make_team(proyecto, alumnos[0], alumnos[1], name='Águilas')
        for nombre in ('grades:activity_grading', 'rubrics:grade_list'):
            response = professor_client.get(reverse(nombre, args=[proyecto.pk]))
            assert response.url == reverse('teams:grade_list', args=[proyecto.pk])
        pagina = professor_client.get(reverse('teams:grade_list', args=[proyecto.pk])).content.decode()
        assert 'Águilas' in pagina and 'Calificar equipo' in pagina and 'Sin equipo' in pagina

    def test_un_solo_alumno_sigue_calificandose_a_solas(self, professor_client, proyecto, alumnos):
        response = professor_client.get(reverse('grades:activity_grading', args=[proyecto.pk]) + f'?alumno={alumnos[0].pk}')
        assert response.url == reverse('rubrics:grade_student', args=[proyecto.pk, alumnos[0].pk])

    def test_guardar_califica_a_todos(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), self.datos(proyecto, feedback='Bien'), follow=True)
        assert response.redirect_chain[-1][0] == reverse('teams:grade_list', args=[proyecto.pk])
        assert {g.score for g in Grade.objects.all()} == {10.0} and Grade.objects.count() == 2
        assert mensajes(response) == ['Se guardó la calificación de «Equipo 1» para 2 integrantes.']

    def test_conserva_el_ajuste_y_lo_dice(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        url = reverse('teams:grade', args=[proyecto.pk, team.pk])
        professor_client.post(url, self.datos(proyecto))
        grade_activity(proyecto, alumnos[1], score=6)
        pagina = professor_client.get(url).content.decode()
        assert 'Se conservará el ajuste a mano' in pagina and 'name="replace"' in pagina
        response = professor_client.post(url, self.datos(proyecto, 1), follow=True)
        assert 'Se conservó el ajuste a mano de' in mensajes(response)[0]
        assert Grade.objects.get(student=alumnos[1]).score == 6 and Grade.objects.get(student=alumnos[0]).score == 7.5
        professor_client.post(url, self.datos(proyecto, 1, replace='on'))
        assert Grade.objects.get(student=alumnos[1]).score == 7.5

    def test_un_nivel_sin_elegir_vuelve_a_la_pantalla_con_el_error(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        datos = self.datos(proyecto)
        datos.popitem()
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), datos)
        assert response.status_code == 200 and 'Elige un nivel' in response.content.decode() and not Grade.objects.exists()

    def test_guardar_y_siguiente(self, professor_client, proyecto, alumnos):
        uno, dos = make_team(proyecto, alumnos[0], name='Uno'), make_team(proyecto, alumnos[1], name='Dos')
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, uno.pk]), self.datos(proyecto, siguiente='1'))
        assert response.url == reverse('teams:grade', args=[proyecto.pk, dos.pk])
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, dos.pk]), self.datos(proyecto, siguiente='1'))
        assert response.url == reverse('teams:grade_list', args=[proyecto.pk])

    def test_la_pantalla_muestra_a_los_integrantes_y_la_entrega(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        submit(proyecto, alumnos[1], text='Texto del equipo', now=AHORA)
        pagina = professor_client.get(reverse('teams:grade', args=[proyecto.pk, team.pk])).content.decode()
        assert 'Calificar a Equipo 1' in pagina and 'misma calificación para los 2 integrantes' in pagina
        assert f'Enviada por {alumnos[1]}' in pagina and 'Texto del equipo' in pagina

    def test_el_equipo_calificado_se_muestra_con_su_nota(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), self.datos(proyecto, 1))
        pagina = professor_client.get(reverse('teams:grade_list', args=[proyecto.pk])).content.decode()
        assert '7.5' in pagina and 'Revisar' in pagina
        assert 'checked' in professor_client.get(reverse('teams:grade', args=[proyecto.pk, team.pk])).content.decode()

    def test_un_equipo_de_otro_proyecto_es_404(self, professor_client, course, proyecto):
        ajeno = teams.create_team(team_project(course))
        assert professor_client.get(reverse('teams:grade', args=[proyecto.pk, ajeno.pk])).status_code == 404

    def test_la_nota_llega_a_la_libreta_de_cada_alumno(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), self.datos(proyecto))
        pagina = professor_client.get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert pagina.count('Rúbrica</span>') >= 2


# ── La actividad: docente y alumno ────────────────────────────────────

class TestActividad:
    def test_el_docente_ve_equipos_y_no_lote_ni_ia(self, professor_client, proyecto, alumnos):
        make_team(proyecto, alumnos[0], name='Águilas')
        pagina = professor_client.get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert reverse('teams:index', args=[proyecto.pk]) in pagina and 'Por equipos' in pagina
        assert '<th>Equipo</th>' in pagina and 'Águilas' in pagina and 'Sin equipo' in pagina
        assert 'Lote de PDFs' not in pagina and 'Revisar con IA' not in pagina

    def test_un_proyecto_individual_sigue_igual(self, professor_client, course):
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        pagina = professor_client.get(reverse('grades:activity_detail', args=[individual.pk])).content.decode()
        assert 'Lote de PDFs' in pagina and 'Revisar con IA' in pagina and 'Por equipos' not in pagina
        assert reverse('teams:index', args=[individual.pk]) not in pagina

    def test_lote_y_revision_con_ia_no_aplican(self, professor_client, proyecto):
        assert professor_client.get(reverse('batches:index', args=[proyecto.pk])).status_code == 404
        assert professor_client.get(reverse('ai:review', args=[proyecto.pk])).status_code == 404

    def test_el_alumno_ve_su_equipo(self, proyecto, course):
        yo, otro = enroll(course, 2)
        make_team(proyecto, yo, otro, name='Águilas')
        pagina = cliente_de(yo.user).get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert 'Tu equipo' in pagina and 'Águilas' in pagina and str(otro) in pagina and '2 integrantes' in pagina
        assert 'Lo que envíes reemplaza la entrega de todo el equipo' in pagina

    def test_el_alumno_sin_equipo_no_puede_entregar(self, proyecto, course):
        suelto, = enroll(course, 1)
        client = cliente_de(suelto.user)
        pagina = client.get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert 'todavía no te asignó a un equipo' in pagina and 'Necesitas un equipo para entregar' in pagina
        assert '<form method="post" action="/actividades/' not in pagina
        response = client.post(reverse('grades:activity_submit', args=[proyecto.pk]), {'text': 'hola'})
        assert response.status_code == 200 and 'no te asignó a un equipo' in response.content.decode() and not Submission.objects.exists()

    def test_entregar_por_el_equipo(self, proyecto, course):
        yo, otro = enroll(course, 2)
        make_team(proyecto, yo, otro, name='Águilas')
        archivo = SimpleUploadedFile('p.pdf', b'%PDF-1.4 x')
        response = cliente_de(yo.user).post(
            reverse('grades:activity_submit', args=[proyecto.pk]), {'text': 'listo', 'file': archivo}, follow=True,
        )
        assert mensajes(response) == ['Tu entrega quedó registrada.'] and Submission.objects.count() == 2
        del_otro = cliente_de(otro.user).get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert f'Enviada por <strong>{yo}</strong>' in del_otro and 'p.pdf' in del_otro
        assert 'Actualizar entrega' in del_otro

    def test_el_alumno_ve_la_nota_del_equipo(self, professor_client, proyecto, course):
        yo, otro = enroll(course, 2)
        team = make_team(proyecto, yo, otro)
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), TestCalificarEnPantalla().datos(proyecto))
        pagina = cliente_de(yo.user).get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert 'Calificación del equipo' in pagina and 'ya fue calificada' not in pagina or 'La entrega de tu equipo ya fue calificada' in pagina
        assert '10' in pagina

    def test_un_alumno_de_otro_equipo_no_ve_la_entrega(self, proyecto, course):
        a, b, c = enroll(course, 3)
        make_team(proyecto, a, b, name='Uno')
        make_team(proyecto, c, name='Dos')
        submit(proyecto, a, text='secreto del uno', now=AHORA)
        pagina = cliente_de(c.user).get(reverse('grades:activity_detail', args=[proyecto.pk])).content.decode()
        assert 'secreto del uno' not in pagina

    def test_el_detalle_de_la_entrega_dice_de_quien_es(self, professor_client, proyecto, course):
        yo, otro = enroll(course, 2)
        make_team(proyecto, yo, otro, name='Águilas')
        entrega = submit(proyecto, yo, text='listo', now=AHORA)
        pagina = professor_client.get(reverse('grades:submission_detail', args=[entrega.pk])).content.decode()
        assert 'Entrega de <strong>Águilas</strong>' in pagina and f'enviada por {yo}' in pagina


# ── El formulario de la actividad y duplicar el grupo ─────────────────

BASE = {
    'title': 'Proyecto', 'type': 'project', 'criterion': '', 'max_score': '10', 'weight': '1',
    'instructions': 'Hagan el proyecto.', 'allow_late': 'on', 'late_penalty': '0',
}


class TestFormulario:
    def crear(self, client, course, profesor, **cambios):
        return client.post(
            reverse('grades:activity_create', args=[course.pk]), {**BASE, 'rubric': make_rubric(profesor).pk, **cambios},
        )

    def test_un_proyecto_por_equipos(self, professor_client, course, professor):
        self.crear(professor_client, course, professor, by_teams='on')
        assert Activity.objects.get().by_teams is True

    def test_por_omision_es_individual(self, professor_client, course, professor):
        self.crear(professor_client, course, professor)
        assert Activity.objects.get().by_teams is False

    def test_una_tarea_no_se_entrega_por_equipos(self, professor_client, course, professor):
        response = self.crear(professor_client, course, professor, type='homework', by_teams='on')
        assert 'by_teams' in response.context['form'].errors and not Activity.objects.exists()

    def test_con_equipos_armados_ya_no_se_cambia(self, professor_client, proyecto, alumnos):
        make_team(proyecto, alumnos[0])
        form = professor_client.get(reverse('grades:activity_update', args=[proyecto.pk])).context['form']
        assert form.fields['by_teams'].disabled and 'Ya no se puede cambiar' in form.fields['by_teams'].help_text
        professor_client.post(reverse('grades:activity_update', args=[proyecto.pk]), {
            **BASE, 'rubric': proyecto.rubric_version.rubric_id, 'criterion': proyecto.criterion_id,
        })  # sin by_teams en el POST: el campo deshabilitado no puede apagarlo
        proyecto.refresh_from_db()
        assert proyecto.by_teams is True

    def test_con_calificaciones_individuales_tampoco(self, professor_client, course):
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        grade_activity(individual, enroll(course, 1)[0], score=8)
        form = professor_client.get(reverse('grades:activity_update', args=[individual.pk])).context['form']
        assert form.fields['by_teams'].disabled

    def test_sin_trabajo_hecho_se_puede_cambiar(self, professor_client, course):
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        professor_client.post(reverse('grades:activity_update', args=[individual.pk]), {
            **BASE, 'rubric': individual.rubric_version.rubric_id, 'criterion': individual.criterion_id, 'by_teams': 'on',
        })
        individual.refresh_from_db()
        assert individual.by_teams is True

    def test_el_formulario_trae_la_casilla_y_su_script(self, professor_client, course):
        pagina = professor_client.get(reverse('grades:activity_create', args=[course.pk])).content.decode()
        assert 'id="id_by_teams"' in pagina and 'js/rubrica.js' in pagina  # el script lo muestra solo en proyectos

    def test_duplicar_el_grupo_conserva_el_modo_pero_no_los_equipos(self, course, proyecto, alumnos):
        make_team(proyecto, alumnos[0])
        copia = clone_course(course, AcademicYearFactory(organization=course.organization))
        clonado = copia.activities.get(type=Activity.Type.PROJECT)
        assert clonado.by_teams is True and not clonado.teams.exists()


class TestCasosBorde:
    def test_siguiente_salta_a_los_equipos_ya_calificados_y_a_los_vacios(self, professor_client, proyecto, alumnos):
        uno = make_team(proyecto, alumnos[0], name='Uno')
        dos = make_team(proyecto, alumnos[1], name='Dos')
        tres = make_team(proyecto, alumnos[2], name='Tres')
        teams.create_team(proyecto, 'Vacío')
        datos = TestCalificarEnPantalla().datos(proyecto)
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, dos.pk]), datos)
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, uno.pk]), {**datos, 'siguiente': '1'})
        assert response.url == reverse('teams:grade', args=[proyecto.pk, tres.pk])
        response = professor_client.post(reverse('teams:grade', args=[proyecto.pk, tres.pk]), {**datos, 'siguiente': '1'})
        assert response.url == reverse('teams:grade_list', args=[proyecto.pk])  # «Vacío» no se ofrece

    def test_la_nota_del_equipo_no_es_la_de_un_ajuste(self, professor_client, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), TestCalificarEnPantalla().datos(proyecto, 1))
        primero = teams.members_of(team)[0]
        grade_activity(proyecto, primero, score=2)  # el primero de la lista tiene un ajuste
        response = professor_client.get(reverse('teams:grade_list', args=[proyecto.pk]))
        assert response.context['rows'][0]['team_grade'].score == 7.5 and 'Ajustada a mano' in response.content.decode()

    def test_sin_penalizacion_desde_la_pantalla(self, professor_client, course):
        proyecto = team_project(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20)
        ana, luis = enroll(course, 2)
        team = make_team(proyecto, ana, luis)
        submit(proyecto, ana, text='tarde', now=AHORA)
        professor_client.post(reverse('teams:grade', args=[proyecto.pk, team.pk]), TestCalificarEnPantalla().datos(proyecto, waive='on'))
        assert {g.score for g in Grade.objects.all()} == {10.0}

    def test_solo_se_ofrece_copiar_de_proyectos_con_equipos(self, professor_client, course, proyecto):
        sin_equipos = team_project(course, title='Sin equipos todavía')
        pagina = professor_client.get(reverse('teams:index', args=[proyecto.pk])).content.decode()
        assert 'Copiar sus equipos' not in pagina
        make_team(sin_equipos, enroll(course, 1)[0])
        assert 'Sin equipos todavía' in professor_client.get(reverse('teams:index', args=[proyecto.pk])).content.decode()

    @pytest.mark.parametrize('alumnos_sin_equipo, esperado', [(2, 2), (7, 2), (8, 2), (12, 3), (20, 5)])
    def test_cantidad_sugerida_de_equipos(self, professor_client, course, proyecto, alumnos_sin_equipo, esperado):
        enroll(course, alumnos_sin_equipo)
        response = professor_client.get(reverse('teams:index', args=[proyecto.pk]))
        assert response.context['default_count'] == esperado

    def test_con_solo_una_entrega_ya_no_se_cambia_el_modo(self, professor_client, course):
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        Submission.objects.create(activity=individual, student=enroll(course, 1)[0], text='hola', submitted_at=AHORA)
        form = professor_client.get(reverse('grades:activity_update', args=[individual.pk])).context['form']
        assert form.fields['by_teams'].disabled
