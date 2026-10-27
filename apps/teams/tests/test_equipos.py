"""Equipos de un proyecto: formarlos, moverlos, borrarlos y repartir al azar."""

import random

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.courses.models import Enrollment
from apps.courses.services.courses import archive_course
from apps.courses.services.roster import remove_from_course
from apps.courses.tests.factories import CourseFactory, EnrollmentFactory
from apps.grades.models import Activity, Submission
from apps.grades.services.gradebook import grade_activity
from apps.grades.tests.factories import ActivityFactory
from apps.teams.models import Team, TeamMember
from apps.teams.services import teams
from apps.teams.tests.factories import enroll, make_team, team_project

pytestmark = pytest.mark.django_db


@pytest.fixture
def proyecto(course):
    return team_project(course)


@pytest.fixture
def alumnos(course):
    return enroll(course, 6)


class TestModelo:
    def test_solo_un_proyecto_se_entrega_por_equipos(self, course):
        with pytest.raises(ValidationError) as error:
            ActivityFactory(course=course, type=Activity.Type.HOMEWORK, by_teams=True)
        assert 'by_teams' in error.value.message_dict

    def test_un_proyecto_existente_sigue_siendo_individual(self, course):
        assert ActivityFactory(course=course, type=Activity.Type.PROJECT).by_teams is False

    def test_un_alumno_no_puede_estar_en_dos_equipos_del_mismo_proyecto(self, proyecto, alumnos):
        uno, otro = make_team(proyecto, alumnos[0]), teams.create_team(proyecto)
        with pytest.raises(IntegrityError), transaction.atomic():
            TeamMember.objects.create(team=otro, student=alumnos[0])
        assert uno.members.count() == 1

    def test_dos_equipos_no_comparten_nombre_en_un_proyecto(self, proyecto):
        Team.objects.create(activity=proyecto, name='Águilas')
        with pytest.raises(IntegrityError), transaction.atomic():
            Team.objects.create(activity=proyecto, name='Águilas')

    def test_la_organizacion_sale_del_proyecto(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        assert team.organization_id == proyecto.organization_id
        assert team.members.get().organization_id == proyecto.organization_id
        assert team.members.get().activity_id == proyecto.pk


class TestCrear:
    def test_nombres_por_omision(self, proyecto):
        assert [teams.create_team(proyecto).name for _ in range(3)] == ['Equipo 1', 'Equipo 2', 'Equipo 3']

    def test_reusa_el_primer_numero_libre(self, proyecto):
        for _ in range(3):
            teams.create_team(proyecto)
        teams.delete_team(proyecto.teams.get(name='Equipo 2'))
        assert teams.create_team(proyecto).name == 'Equipo 2'

    def test_nombre_propio_sin_espacios_de_sobra(self, proyecto):
        assert teams.create_team(proyecto, '   Los   Genios ').name == 'Los Genios'

    def test_nombre_repetido_sin_importar_mayusculas(self, proyecto):
        teams.create_team(proyecto, 'Águilas')
        with pytest.raises(ValidationError, match='Ya hay un equipo'):
            teams.create_team(proyecto, 'águilas')

    def test_nombre_demasiado_largo(self, proyecto):
        with pytest.raises(ValidationError, match='80 caracteres'):
            teams.create_team(proyecto, 'x' * 81)

    def test_tope_de_equipos(self, proyecto, monkeypatch):
        monkeypatch.setattr(teams, 'MAX_TEAMS', 2)
        teams.create_team(proyecto)
        teams.create_team(proyecto)
        with pytest.raises(ValidationError, match='más de 2 equipos'):
            teams.create_team(proyecto)

    def test_un_proyecto_individual_no_tiene_equipos(self, course):
        with pytest.raises(ValidationError, match='no se entrega por equipos'):
            teams.create_team(ActivityFactory(course=course, type=Activity.Type.PROJECT))

    def test_un_grupo_archivado_es_de_solo_lectura(self, course, proyecto):
        archive_course(course)
        with pytest.raises(ValidationError):
            teams.create_team(proyecto)


class TestRenombrar:
    def test_cambia_el_nombre(self, proyecto):
        team = teams.create_team(proyecto)
        assert teams.rename_team(team, ' Halcones ').name == 'Halcones'

    def test_su_propio_nombre_no_choca_consigo_mismo(self, proyecto):
        team = teams.create_team(proyecto, 'Halcones')
        assert teams.rename_team(team, 'halcones').name == 'halcones'

    def test_no_puede_quedar_vacio_ni_repetido(self, proyecto):
        uno, dos = teams.create_team(proyecto, 'Uno'), teams.create_team(proyecto, 'Dos')
        with pytest.raises(ValidationError, match='necesita un nombre'):
            teams.rename_team(uno, '  ')
        with pytest.raises(ValidationError, match='Ya hay un equipo'):
            teams.rename_team(uno, 'DOS')
        assert (uno.name, dos.name) == ('Uno', 'Dos')


class TestAsignar:
    def test_pone_al_alumno_en_el_equipo(self, proyecto, alumnos):
        team = teams.create_team(proyecto)
        teams.assign(proyecto, alumnos[0], team)
        assert teams.team_of(proyecto, alumnos[0]) == team

    def test_mover_lo_saca_del_anterior(self, proyecto, alumnos):
        uno, dos = make_team(proyecto, alumnos[0]), teams.create_team(proyecto)
        teams.assign(proyecto, alumnos[0], dos)
        assert teams.team_of(proyecto, alumnos[0]) == dos and not uno.members.exists()

    def test_sin_equipo(self, proyecto, alumnos):
        make_team(proyecto, alumnos[0])
        teams.assign(proyecto, alumnos[0], None)
        assert teams.team_of(proyecto, alumnos[0]) is None

    def test_repetir_la_asignacion_no_hace_nada(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        teams.assign(proyecto, alumnos[0], team)
        teams.assign(proyecto, alumnos[1], None)
        assert team.members.count() == 1

    def test_solo_alumnos_del_grupo(self, proyecto):
        team = teams.create_team(proyecto)
        ajeno = EnrollmentFactory(course=CourseFactory(professor=proyecto.course.professor)).student
        with pytest.raises(ValidationError, match='no está inscrito'):
            teams.assign(proyecto, ajeno, team)

    def test_solo_equipos_del_mismo_proyecto(self, course, proyecto, alumnos):
        otro = team_project(course)
        with pytest.raises(ValidationError, match='no es de este proyecto'):
            teams.assign(proyecto, alumnos[0], teams.create_team(otro))

    def test_quien_ya_tiene_calificacion_no_se_mueve(self, proyecto, alumnos):
        team, otro = make_team(proyecto, alumnos[0]), teams.create_team(proyecto)
        grade_activity(proyecto, alumnos[0], score=8)
        with pytest.raises(ValidationError, match='ya tiene calificación'):
            teams.assign(proyecto, alumnos[0], otro)
        with pytest.raises(ValidationError, match='ya tiene calificación'):
            teams.assign(proyecto, alumnos[0], None)
        assert teams.team_of(proyecto, alumnos[0]) == team

    def test_quien_salio_del_grupo_sale_del_equipo(self, course, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        remove_from_course(course, alumnos[0])
        assert list(teams.members_of(team)) == [alumnos[1]] and team.members.count() == 1

    def test_miembros_en_orden_alfabetico(self, proyecto, course):
        zapata = EnrollmentFactory(course=course, student__last_name='Zapata', student__first_name='Ana').student
        alvarez = EnrollmentFactory(course=course, student__last_name='Álvarez', student__first_name='Luis').student
        assert teams.members_of(make_team(proyecto, zapata, alvarez)) == [alvarez, zapata]


class TestBorrar:
    def test_borra_y_deja_a_los_integrantes_sin_equipo(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        teams.delete_team(team)
        assert not Team.objects.filter(pk=team.pk).exists()
        assert [e.student for e in teams.unassigned_enrollments(proyecto)].count(alumnos[0]) == 1

    def test_con_entrega_no(self, proyecto, alumnos):
        from apps.grades.services.submissions import submit

        team = make_team(proyecto, alumnos[0])
        submit(proyecto, alumnos[0], text='listo')
        with pytest.raises(ValidationError, match='ya entregó'):
            teams.delete_team(team)

    def test_con_calificacion_no(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        grade_activity(proyecto, alumnos[0], score=7)
        with pytest.raises(ValidationError, match='ya entregó o tiene calificaciones'):
            teams.delete_team(team)


class TestAlAzar:
    def test_reparte_a_todos_los_que_no_tienen_equipo(self, proyecto, alumnos):
        creados = teams.split_randomly(proyecto, 3, rng=random.Random(1))
        assert [t.name for t in creados] == ['Equipo 1', 'Equipo 2', 'Equipo 3']
        assert sorted(t.members.count() for t in creados) == [2, 2, 2]
        assert not teams.unassigned_enrollments(proyecto)

    def test_reparto_parejo_cuando_no_alcanza_exacto(self, proyecto, course, alumnos):
        enroll(course, 1)  # con los 6 de la fixture, 7 en total
        creados = teams.split_randomly(proyecto, 3, rng=random.Random(2))
        assert sorted(t.members.count() for t in creados) == [2, 2, 3]

    def test_con_otra_semilla_cambia_quien_queda_con_quien(self, proyecto, alumnos):
        def grupos(seed):
            creados = teams.split_randomly(proyecto, 3, rng=random.Random(seed))
            resultado = {frozenset(t.members.values_list('student_id', flat=True)) for t in creados}
            Team.objects.filter(activity=proyecto).delete()
            return resultado

        assert grupos(1) != grupos(7)

    def test_no_toca_a_los_que_ya_tienen_equipo(self, proyecto, alumnos):
        fijo = make_team(proyecto, alumnos[0], name='Fijo')
        creados = teams.split_randomly(proyecto, 2, rng=random.Random(3))
        assert list(fijo.members.values_list('student_id', flat=True)) == [alumnos[0].pk]
        assert sum(t.members.count() for t in creados) == 5

    def test_no_incluye_a_los_ya_calificados(self, proyecto, alumnos):
        grade_activity(proyecto, alumnos[0], score=9)
        creados = teams.split_randomly(proyecto, 2, rng=random.Random(4))
        assert sum(t.members.count() for t in creados) == 5
        assert teams.team_of(proyecto, alumnos[0]) is None

    @pytest.mark.parametrize('cuantos', [0, 1, 7])
    def test_cantidad_fuera_de_rango(self, proyecto, alumnos, cuantos):
        with pytest.raises(ValidationError, match='elige entre 2 y 6'):
            teams.split_randomly(proyecto, cuantos)
        assert not Team.objects.filter(activity=proyecto).exists()

    def test_un_alumno_solo_no_se_reparte(self, proyecto, course):
        with pytest.raises(ValidationError, match='al menos 2 alumnos'):
            teams.split_randomly(proyecto, 2)

    def test_los_nombres_nuevos_no_chocan_con_los_que_ya_hay(self, proyecto, alumnos):
        teams.create_team(proyecto, 'Equipo 1')
        assert [t.name for t in teams.split_randomly(proyecto, 2, rng=random.Random(5))] == ['Equipo 2', 'Equipo 3']


class TestCopiar:
    def test_copia_equipos_y_miembros(self, course, proyecto, alumnos):
        make_team(proyecto, alumnos[0], alumnos[1], name='Uno')
        make_team(proyecto, alumnos[2], name='Dos')
        nuevo = team_project(course)
        assert teams.copy_teams(proyecto, nuevo) == 2
        assert {t.name: t.members.count() for t in nuevo.teams.all()} == {'Uno': 2, 'Dos': 1}
        assert proyecto.teams.count() == 2  # el original no cambia

    def test_omite_a_quien_ya_no_esta_en_el_grupo(self, course, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        Enrollment.objects.filter(course=course, student=alumnos[1]).delete()  # la señal lo saca del equipo...
        TeamMember.objects.create(team=team, student=alumnos[1])  # ...así que se vuelve a poner a mano
        nuevo = team_project(course)
        teams.copy_teams(proyecto, nuevo)
        assert list(nuevo.teams.get().members.values_list('student_id', flat=True)) == [alumnos[0].pk]

    def test_solo_con_equipos_vacios_de_destino(self, course, proyecto, alumnos):
        make_team(proyecto, alumnos[0])
        nuevo = team_project(course)
        teams.create_team(nuevo)
        with pytest.raises(ValidationError, match='ya tiene equipos'):
            teams.copy_teams(proyecto, nuevo)

    def test_origen_sin_equipos(self, course, proyecto):
        with pytest.raises(ValidationError, match='no tiene equipos que copiar'):
            teams.copy_teams(proyecto, team_project(course))

    def test_origen_de_otro_grupo_o_individual(self, course, proyecto, alumnos):
        make_team(proyecto, alumnos[0])
        ajeno = team_project(CourseFactory(professor=course.professor))
        individual = ActivityFactory(course=course, type=Activity.Type.PROJECT)
        for origen in (ajeno, individual, proyecto):
            with pytest.raises(ValidationError, match='Elige otro proyecto'):
                teams.copy_teams(origen, proyecto)


class TestPanorama:
    def test_filas_y_sin_equipo(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0], alumnos[1])
        vacio = teams.create_team(proyecto)
        filas, sin_equipo = teams.overview(proyecto)
        assert [f['team'] for f in filas] == [team, vacio]
        assert filas[0]['members'] == sorted(filas[0]['members'], key=lambda s: (s.last_name.lower(), s.first_name.lower(), s.pk))
        assert len(sin_equipo) == 4
        assert filas[0]['deletable'] and filas[0]['submission'] is None

    def test_con_entrega_y_calificados(self, proyecto, alumnos):
        from apps.grades.services.submissions import submit

        team = make_team(proyecto, alumnos[0], alumnos[1])
        submit(proyecto, alumnos[0], text='listo')
        grade_activity(proyecto, alumnos[1], score=9)
        fila = teams.overview(proyecto)[0][0]
        assert fila['team'] == team and fila['submission'].submitted_by == alumnos[0]
        assert fila['graded'] == 1 and fila['locked'] == {alumnos[1].pk} and not fila['deletable']
        assert Submission.objects.filter(team=team).count() == 2


class TestCasosBorde:
    def test_quien_no_sigue_inscrito_no_cuenta_como_integrante(self, course, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        Enrollment.objects.filter(course=course, student=alumnos[0]).delete()
        TeamMember.objects.create(team=team, student=alumnos[0])  # la señal lo sacó: se vuelve a poner a mano
        assert teams.members_of(team) == []

    def test_volver_a_poner_a_quien_ya_esta_no_toca_su_calificacion(self, proyecto, alumnos):
        team = make_team(proyecto, alumnos[0])
        grade_activity(proyecto, alumnos[0], score=8)
        teams.assign(proyecto, alumnos[0], team)  # ya está ahí: no hay nada que mover, aunque tenga calificación
        assert teams.team_of(proyecto, alumnos[0]) == team

    def test_el_reparto_respeta_el_tope_de_equipos(self, proyecto, alumnos, monkeypatch):
        monkeypatch.setattr(teams, 'MAX_TEAMS', 3)
        teams.create_team(proyecto)
        teams.create_team(proyecto)
        with pytest.raises(ValidationError, match='más de 3 equipos'):
            teams.split_randomly(proyecto, 2)
        assert proyecto.teams.count() == 2
