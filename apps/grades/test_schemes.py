"""Esquema de evaluación: plantilla por defecto, asignación de criterios y copia al duplicar un grupo."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError

from apps.courses.factories import AcademicYearFactory, CourseFactory
from apps.courses.services.courses import clone_course

from .factories import ActivityFactory
from .models import Activity, EvaluationCriterion, EvaluationPeriod, EvaluationScheme
from .services.schemes import copy_scheme, create_default_scheme, default_criterion, ensure_scheme

pytestmark = pytest.mark.django_db


# ── Plantilla por defecto ─────────────────────────────────────────────

class TestPlantilla:
    def test_todo_grupo_nuevo_nace_con_esquema(self, course):
        scheme = course.scheme
        assert (scheme.scale_max, scheme.pass_mark, scheme.rounding_decimals) == (10, 6, 2)
        assert scheme.organization_id == course.organization_id

    def test_un_periodo_y_cuatro_criterios_que_suman_cien(self, course):
        (periodo,) = course.scheme.periods.all()
        assert periodo.weight == 100
        criterios = list(periodo.criteria.all())
        assert [(c.name, c.weight, c.default_type) for c in criterios] == [
            ("Exámenes", 40, "exam"), ("Tareas", 30, "homework"), ("Proyecto", 20, "project"), ("Quizzes", 10, "quiz"),
        ]
        assert sum(c.weight for c in criterios) == 100

    def test_los_hijos_heredan_la_organizacion(self, course):
        assert {c.organization_id for c in course.scheme.criteria()} == {course.organization_id}
        assert {p.organization_id for p in course.scheme.periods.all()} == {course.organization_id}

    def test_cada_grupo_tiene_su_propio_esquema(self):
        a, b = CourseFactory(), CourseFactory()
        assert a.scheme.pk != b.scheme.pk
        assert EvaluationScheme.objects.count() == 2

    def test_un_solo_esquema_por_grupo(self, course):
        with pytest.raises(IntegrityError), transaction.atomic():
            EvaluationScheme.objects.create(course=course)

    def test_ensure_scheme_repone_el_que_falta(self, course):
        EvaluationScheme.objects.filter(course=course).delete()
        course.refresh_from_db()
        scheme = ensure_scheme(course)
        assert scheme.criteria().count() == 4

    def test_ensure_scheme_no_duplica(self, course):
        assert ensure_scheme(course) == course.scheme
        assert EvaluationScheme.objects.filter(course=course).count() == 1

    def test_crear_la_plantilla_no_cambia_a_otros_grupos(self, course):
        otro = CourseFactory()
        EvaluationCriterion.objects.filter(period__scheme=otro.scheme).update(weight=5)
        assert {c.weight for c in course.scheme.criteria()} == {40, 30, 20, 10}


class TestValidaciones:
    def test_el_minimo_aprobatorio_no_puede_superar_la_escala(self, course):
        course.scheme.pass_mark = 11
        with pytest.raises(ValidationError):
            course.scheme.clean()
        with pytest.raises(IntegrityError), transaction.atomic():
            course.scheme.save()

    def test_se_admiten_escalas_distintas(self, course):
        course.scheme.scale_max, course.scheme.pass_mark = 100, 60
        course.scheme.full_clean()
        course.scheme.save()

    @pytest.mark.parametrize("peso", [-1, 100.01])
    def test_los_pesos_van_de_0_a_100(self, course, peso):
        criterio = course.scheme.criteria().first()
        criterio.weight = peso
        with pytest.raises(ValidationError):
            criterio.full_clean()


# ── Asignación de criterio a las evaluaciones ─────────────────────────

class TestAsignacion:
    @pytest.mark.parametrize("tipo, criterio", [
        (Activity.Type.EXAM, "Exámenes"), (Activity.Type.HOMEWORK, "Tareas"),
        (Activity.Type.PROJECT, "Proyecto"), (Activity.Type.QUIZ, "Quizzes"),
    ])
    def test_la_evaluacion_nueva_va_al_criterio_de_su_tipo(self, course, tipo, criterio):
        assert ActivityFactory(course=course, type=tipo).criterion.name == criterio

    def test_sin_criterio_del_mismo_tipo_va_al_primero(self, course):
        EvaluationCriterion.objects.filter(period__scheme=course.scheme).update(default_type="")
        assert ActivityFactory(course=course, type=Activity.Type.EXAM).criterion == course.scheme.criteria().first()

    def test_un_criterio_explicito_se_respeta(self, course):
        tareas = course.scheme.criteria().get(name="Tareas")
        assert ActivityFactory(course=course, type=Activity.Type.EXAM, criterion=tareas).criterion == tareas

    def test_el_criterio_debe_ser_del_mismo_grupo(self, course):
        ajeno = CourseFactory().scheme.criteria().first()
        with pytest.raises(ValidationError):
            ActivityFactory(course=course, criterion=ajeno)

    def test_un_esquema_sin_criterios_no_admite_evaluaciones(self, course):
        EvaluationCriterion.objects.filter(period__scheme=course.scheme).delete()
        with pytest.raises(ValidationError, match="no tiene criterios"):
            default_criterion(course, "exam")

    def test_no_se_borra_un_criterio_con_evaluaciones(self, course):
        evaluacion = ActivityFactory(course=course)
        with pytest.raises(ProtectedError):
            evaluacion.criterion.delete()

    def test_no_se_borra_un_periodo_con_evaluaciones(self, course):
        evaluacion = ActivityFactory(course=course)
        with pytest.raises(ProtectedError):
            evaluacion.criterion.period.delete()

    def test_se_borra_un_criterio_sin_evaluaciones(self, course):
        criterio = course.scheme.criteria().get(name="Quizzes")
        criterio.delete()
        assert course.scheme.criteria().count() == 3

    def test_borrar_el_grupo_borra_su_esquema(self, course):
        course.delete()
        assert not EvaluationScheme.objects.exists() and not EvaluationCriterion.objects.exists()


# ── Copia ─────────────────────────────────────────────────────────────

class TestCopia:
    @pytest.fixture
    def personalizado(self, course):
        scheme = course.scheme
        scheme.scale_max, scheme.pass_mark, scheme.rounding_decimals = 100, 70, 0
        scheme.save()
        segundo = EvaluationPeriod.objects.create(scheme=scheme, name="Parcial 2", weight=50, position=1)
        EvaluationPeriod.objects.filter(pk=scheme.periods.first().pk).update(weight=50, name="Parcial 1")
        EvaluationCriterion.objects.create(period=segundo, name="Laboratorio", weight=100, position=0)
        return course

    def test_copia_ajustes_periodos_y_criterios(self, personalizado):
        destino = CourseFactory(professor=personalizado.professor)
        copy_scheme(personalizado, destino)
        copia = destino.scheme
        assert (copia.scale_max, copia.pass_mark, copia.rounding_decimals) == (100, 70, 0)
        assert [(p.name, p.weight) for p in copia.periods.all()] == [("Parcial 1", 50), ("Parcial 2", 50)]
        assert [c.name for c in copia.criteria()] == ["Exámenes", "Tareas", "Proyecto", "Quizzes", "Laboratorio"]

    def test_devuelve_la_correspondencia_de_criterios_y_no_comparte_filas(self, personalizado):
        destino = CourseFactory(professor=personalizado.professor)
        mapa = copy_scheme(personalizado, destino)
        origen_ids = set(personalizado.scheme.criteria().values_list("pk", flat=True))
        assert set(mapa) == origen_ids
        assert not {c.pk for c in mapa.values()} & origen_ids
        assert all(c.period.scheme.course_id == destino.pk for c in mapa.values())

    def test_editar_la_copia_no_toca_el_original(self, personalizado):
        destino = CourseFactory(professor=personalizado.professor)
        copy_scheme(personalizado, destino)
        destino.scheme.criteria().update(weight=1)
        assert {c.weight for c in personalizado.scheme.criteria() if c.name != "Laboratorio"} == {40, 30, 20, 10}

    def test_copiar_a_un_grupo_con_evaluaciones_asignadas_no_destruye_nada(self, personalizado):
        destino = CourseFactory(professor=personalizado.professor)
        ActivityFactory(course=destino)
        with pytest.raises(ProtectedError):
            copy_scheme(personalizado, destino)
        assert Activity.objects.filter(course=destino).count() == 1


class TestDuplicarGrupo:
    @pytest.fixture
    def nuevo_ciclo(self, course):
        return AcademicYearFactory(organization=course.organization)

    def test_el_grupo_duplicado_lleva_el_esquema_del_original(self, course, nuevo_ciclo):
        course.scheme.pass_mark = 7
        course.scheme.save()
        EvaluationCriterion.objects.filter(period__scheme=course.scheme, name="Tareas").update(weight=25)
        copia = clone_course(course, nuevo_ciclo)
        assert copia.scheme.pass_mark == 7
        assert copia.scheme.criteria().get(name="Tareas").weight == 25
        assert EvaluationScheme.objects.filter(course=copia).count() == 1

    def test_las_evaluaciones_copiadas_van_a_los_criterios_de_la_copia(self, course, nuevo_ciclo):
        tareas = course.scheme.criteria().get(name="Tareas")
        ActivityFactory(course=course, title="Ensayo", type=Activity.Type.EXAM, criterion=tareas, weight=2)
        copia = clone_course(course, nuevo_ciclo)
        (evaluacion,) = copia.activities.all()
        assert evaluacion.criterion.name == "Tareas"
        assert evaluacion.criterion.period.scheme.course_id == copia.pk  # no el criterio del original
        assert (evaluacion.title, evaluacion.weight, evaluacion.date) == ("Ensayo", 2, None)

    def test_el_original_conserva_sus_criterios_y_evaluaciones(self, course, nuevo_ciclo):
        evaluacion = ActivityFactory(course=course)
        clone_course(course, nuevo_ciclo)
        evaluacion.refresh_from_db()
        assert evaluacion.criterion.period.scheme.course_id == course.pk
        assert course.scheme.criteria().count() == 4

    def test_duplicar_no_deja_un_esquema_a_medias_si_algo_falla(self, course, nuevo_ciclo, monkeypatch):
        def falla(*args, **kwargs):
            raise RuntimeError("boom")

        ActivityFactory(course=course)
        monkeypatch.setattr(Activity, "save", falla)
        with pytest.raises(RuntimeError):
            clone_course(course, nuevo_ciclo)
        assert EvaluationScheme.objects.count() == 1  # solo el del original


def test_create_default_scheme_es_reutilizable(course):
    EvaluationScheme.objects.filter(course=course).delete()
    course.refresh_from_db()
    assert create_default_scheme(course).periods.count() == 1
