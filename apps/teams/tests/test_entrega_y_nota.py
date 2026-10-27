"""Un proyecto por equipos: la entrega de todos, y la calificación con la rúbrica para todo el equipo."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.core.files.storage import storages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.courses.models import Enrollment
from apps.grades.models import Grade, Submission
from apps.grades.services.gradebook import grade_activity, remove_grade
from apps.grades.services.submissions import submit
from apps.rubrics.tests.factories import choices_for
from apps.teams.services import grading, teams
from apps.teams.tests.factories import enroll, make_team, team_project

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


def archivo(nombre='proyecto.pdf', contenido=b'%PDF-1.4 equipo'):
    return SimpleUploadedFile(nombre, contenido)


def existe(entrega):
    return storages['submissions'].exists(entrega.file.name)


@pytest.fixture
def proyecto(course):
    return team_project(course, due_at=AHORA + UN_DIA)


@pytest.fixture
def equipo(proyecto, course):
    ana, luis, marta = enroll(course, 3)
    return make_team(proyecto, ana, luis, marta, name='Águilas'), (ana, luis, marta)


# ── Entregar ──────────────────────────────────────────────────────────

class TestEntregar:
    def test_cualquiera_entrega_y_todos_quedan_con_lo_mismo(self, proyecto, equipo):
        team, (ana, luis, marta) = equipo
        entrega = submit(proyecto, luis, text='Nuestro proyecto', link='https://ejemplo.mx/p', file=archivo(), now=AHORA)
        assert entrega.student == luis
        filas = Submission.objects.filter(activity=proyecto)
        assert filas.count() == 3
        assert {f.student_id for f in filas} == {ana.pk, luis.pk, marta.pk}
        assert {(f.team_id, f.submitted_by_id, f.text, f.link, f.original_name) for f in filas} == {
            (team.pk, luis.pk, 'Nuestro proyecto', 'https://ejemplo.mx/p', 'proyecto.pdf'),
        }

    def test_el_archivo_se_guarda_una_sola_vez(self, proyecto, equipo):
        _, (ana, luis, marta) = equipo
        submit(proyecto, ana, file=archivo(), now=AHORA)
        assert len({f.file.name for f in Submission.objects.filter(activity=proyecto)}) == 1
        carpetas = storages['submissions'].listdir(f'{proyecto.organization_id}/{proyecto.course_id}/{proyecto.pk}')[0]
        # Solo está la carpeta de quien lo subió: los demás integrantes comparten ese archivo, no tienen copia en disco.
        assert str(ana.pk) in carpetas and not {str(luis.pk), str(marta.pk)} & set(carpetas)

    def test_otro_integrante_reemplaza_la_entrega_de_todos(self, proyecto, equipo):
        _, (ana, luis, marta) = equipo
        primera = submit(proyecto, ana, text='v1', file=archivo('uno.pdf', b'%PDF-1.4 uno'), now=AHORA)
        viejo = primera.file.name
        nueva = submit(proyecto, marta, text='v2', file=archivo('dos.pdf', b'%PDF-1.4 dos'), now=AHORA + UN_DIA / 2)
        filas = list(Submission.objects.filter(activity=proyecto))
        assert len(filas) == 3 and {f.text for f in filas} == {'v2'}
        assert {f.submitted_by_id for f in filas} == {marta.pk} and {f.original_name for f in filas} == {'dos.pdf'}
        assert len({f.file.name for f in filas}) == 1 and viejo not in {f.file.name for f in filas}
        assert not storages['submissions'].exists(viejo) and existe(nueva)

    def test_actualizar_sin_archivo_conserva_el_del_equipo(self, proyecto, equipo):
        _, (ana, luis, _marta) = equipo
        submit(proyecto, ana, file=archivo(), now=AHORA)
        submit(proyecto, luis, text='Nota nueva', now=AHORA)
        filas = list(Submission.objects.filter(activity=proyecto))
        assert {f.original_name for f in filas} == {'proyecto.pdf'} and {f.text for f in filas} == {'Nota nueva'}
        assert len({f.file.name for f in filas}) == 1 and all(existe(f) for f in filas)

    def test_sin_equipo_no_entrega(self, proyecto, course):
        suelto, = enroll(course, 1)
        with pytest.raises(ValidationError, match='no te asignó a un equipo'):
            submit(proyecto, suelto, text='hola', now=AHORA)
        assert not Submission.objects.exists()

    def test_tarde_para_todo_el_equipo(self, course):
        proyecto = team_project(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=10)
        ana, luis = enroll(course, 2)
        make_team(proyecto, ana, luis)
        submit(proyecto, ana, text='tarde', now=AHORA)
        assert [f.is_late for f in Submission.objects.filter(activity=proyecto)] == [True, True]

    def test_cerrado_no_entrega_nadie(self, course):
        proyecto = team_project(course, due_at=AHORA - UN_DIA, allow_late=False)
        ana, = enroll(course, 1)
        make_team(proyecto, ana)
        with pytest.raises(ValidationError, match='fecha límite'):
            submit(proyecto, ana, text='hola', now=AHORA)

    def test_calificada_ya_no_se_cambia(self, proyecto, equipo):
        _, (ana, luis, _marta) = equipo
        submit(proyecto, ana, text='v1', now=AHORA)
        grade_activity(proyecto, luis, score=8)
        with pytest.raises(ValidationError, match='ya fue calificada'):
            submit(proyecto, ana, text='v2', now=AHORA)
        assert {f.text for f in Submission.objects.filter(activity=proyecto)} == {'v1'}

    def test_un_error_no_deja_entregas_a_medias(self, proyecto, equipo):
        _, (ana, *_rest) = equipo
        with pytest.raises(ValidationError):
            submit(proyecto, ana, file=archivo('virus.exe'), now=AHORA)
        assert not Submission.objects.exists()

    def test_el_equipo_de_otro_no_se_mezcla(self, proyecto, equipo, course):
        otro_a, otro_b = enroll(course, 2)
        make_team(proyecto, otro_a, otro_b, name='Halcones')
        submit(proyecto, equipo[1][0], text='de águilas', now=AHORA)
        assert not Submission.objects.filter(student__in=[otro_a, otro_b]).exists()


# ── Cambios en el equipo con entrega hecha ────────────────────────────

class TestIntegrantesConEntrega:
    def test_el_que_llega_recibe_la_entrega(self, proyecto, equipo, course):
        team, (ana, *_rest) = equipo
        submit(proyecto, ana, text='listo', file=archivo(), now=AHORA)
        nuevo, = enroll(course, 1)
        teams.assign(proyecto, nuevo, team)
        copia = Submission.objects.get(student=nuevo)
        original = Submission.objects.get(student=ana)
        assert (copia.team, copia.text, copia.file.name, copia.submitted_by, copia.submitted_at) == (
            team, 'listo', original.file.name, ana, original.submitted_at,
        )

    def test_el_que_sale_pierde_su_copia_pero_el_equipo_no(self, proyecto, equipo):
        team, (ana, luis, marta) = equipo
        submit(proyecto, ana, file=archivo(), now=AHORA)
        teams.assign(proyecto, marta, None)
        assert not Submission.objects.filter(student=marta).exists()
        assert Submission.objects.filter(team=team).count() == 2
        assert all(existe(f) for f in Submission.objects.filter(team=team))  # el archivo compartido sigue ahí

    def test_pasar_a_otro_equipo_le_da_la_entrega_del_nuevo(self, proyecto, equipo, course):
        team, (ana, _luis, marta) = equipo
        otro_a, otro_b = enroll(course, 2)
        otro = make_team(proyecto, otro_a, otro_b, name='Halcones')
        submit(proyecto, ana, text='águilas', now=AHORA)
        submit(proyecto, otro_a, text='halcones', now=AHORA)
        teams.assign(proyecto, marta, otro)
        assert Submission.objects.get(student=marta).text == 'halcones'
        assert Submission.objects.get(student=marta).team == otro and Submission.objects.filter(team=team).count() == 2

    def test_borrar_una_entrega_no_borra_el_archivo_de_las_demas(self, proyecto, equipo):
        _, (ana, luis, _marta) = equipo
        submit(proyecto, ana, file=archivo(), now=AHORA)
        Submission.objects.get(student=luis).delete()
        assert all(existe(f) for f in Submission.objects.filter(activity=proyecto))

    def test_borrar_todas_borra_el_archivo(self, proyecto, equipo):
        submit(proyecto, equipo[1][0], file=archivo(), now=AHORA)
        nombre = Submission.objects.first().file.name
        Submission.objects.filter(activity=proyecto).delete()
        assert not storages['submissions'].exists(nombre)

    def test_quien_sale_del_grupo_pierde_su_copia(self, proyecto, equipo, course):
        _, (ana, luis, _marta) = equipo
        submit(proyecto, ana, text='listo', now=AHORA)
        Enrollment.objects.get(course=course, student=luis).delete()
        assert not Submission.objects.filter(student=luis).exists() and Submission.objects.count() == 2


# ── Calificar al equipo ───────────────────────────────────────────────

class TestCalificar:
    def calificar(self, proyecto, team, nivel=0, **kwargs):
        return grading.grade_team(proyecto, team, choices=choices_for(proyecto.rubric_version, nivel), **kwargs)

    def test_la_misma_calificacion_para_todos(self, proyecto, equipo):
        team, alumnos = equipo
        resultado = self.calificar(proyecto, team, feedback='Buen trabajo')
        assert set(resultado.graded) == set(alumnos) and not resultado.kept
        notas = Grade.objects.filter(activity=proyecto)
        assert {(g.score, g.source, g.feedback) for g in notas} == {(10.0, Grade.Source.RUBRIC, 'Buen trabajo')}
        assert notas.count() == 3 and all(g.rubric_scores.count() == 2 for g in notas)

    def test_respeta_el_ajuste_a_mano(self, proyecto, equipo):
        team, (ana, luis, marta) = equipo
        self.calificar(proyecto, team)
        grade_activity(proyecto, luis, score=6, feedback='No participó')
        resultado = self.calificar(proyecto, team, nivel=1)
        assert resultado.kept == [luis] and set(resultado.graded) == {ana, marta}
        assert Grade.objects.get(student=luis).score == 6
        assert Grade.objects.get(student=ana).score == 7.5

    def test_reemplazar_el_ajuste(self, proyecto, equipo):
        team, (_ana, luis, _marta) = equipo
        self.calificar(proyecto, team)
        grade_activity(proyecto, luis, score=6)
        resultado = self.calificar(proyecto, team, nivel=1, replace_adjusted=True)
        assert not resultado.kept and Grade.objects.get(student=luis).score == 7.5
        assert Grade.objects.get(student=luis).source == Grade.Source.RUBRIC

    def test_un_nivel_sin_elegir_no_califica_a_nadie(self, proyecto, equipo):
        team, _ = equipo
        elegidos = choices_for(proyecto.rubric_version)
        elegidos.popitem()
        with pytest.raises(ValidationError, match='Elige un nivel'):
            grading.grade_team(proyecto, team, choices=elegidos)
        assert not Grade.objects.exists()

    def test_la_penalizacion_es_la_de_la_entrega_de_cada_uno(self, course):
        proyecto = team_project(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20)
        ana, luis = enroll(course, 2)
        team = make_team(proyecto, ana, luis)
        submit(proyecto, ana, text='tarde', now=AHORA)
        self.calificar(proyecto, team)
        assert {g.score for g in Grade.objects.filter(activity=proyecto)} == {8.0}

    def test_se_puede_perdonar_la_penalizacion(self, course):
        proyecto = team_project(course, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20)
        ana, luis = enroll(course, 2)
        team = make_team(proyecto, ana, luis)
        submit(proyecto, ana, text='tarde', now=AHORA)
        self.calificar(proyecto, team, waive_penalty=True)
        assert {g.score for g in Grade.objects.filter(activity=proyecto)} == {10.0}

    def test_un_equipo_sin_integrantes(self, proyecto):
        with pytest.raises(ValidationError, match='no tiene integrantes'):
            self.calificar(proyecto, teams.create_team(proyecto))

    def test_solo_cuentan_los_que_siguen_en_el_grupo(self, proyecto, equipo, course):
        team, (ana, luis, marta) = equipo
        Enrollment.objects.filter(course=course, student=marta).delete()
        resultado = self.calificar(proyecto, team)
        assert set(resultado.graded) == {ana, luis} and not Grade.objects.filter(student=marta).exists()

    def test_los_integrantes_ajustados(self, proyecto, equipo):
        team, (ana, luis, _marta) = equipo
        self.calificar(proyecto, team)
        assert grading.adjusted_members(proyecto, team) == []
        grade_activity(proyecto, luis, score=5)
        assert grading.adjusted_members(proyecto, team) == [luis]
        remove_grade(Grade.objects.get(student=luis))
        assert grading.adjusted_members(proyecto, team) == []

    def test_cada_nota_queda_en_la_bitacora(self, proyecto, equipo):
        from apps.grades.models import GradeHistory

        self.calificar(proyecto, equipo[0])
        assert GradeHistory.objects.filter(activity=proyecto, action=GradeHistory.Action.CREATED).count() == 3


class TestCasosBorde:
    def test_el_texto_se_guarda_sin_espacios_de_sobra(self, proyecto, equipo):
        submit(proyecto, equipo[1][0], text='  hola  ', link='  https://ejemplo.mx  ', now=AHORA)
        assert {(f.text, f.link) for f in Submission.objects.filter(activity=proyecto)} == {('hola', 'https://ejemplo.mx')}

    def test_el_lote_de_pdfs_no_recibe_proyectos_por_equipos(self, proyecto):
        from apps.batches.services import batch

        with pytest.raises(ValidationError, match='no recibe entregas'):
            batch.upload(proyecto, [], cover_pages=1)
