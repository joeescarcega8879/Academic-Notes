"""Pruebas de ciclos escolares, archivado de grupos y duplicado para un nuevo ciclo."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.grades.factories import ActivityFactory, GradeFactory
from apps.grades.models import Activity, Grade
from apps.organizations.factories import OrganizationFactory

from .factories import AcademicYearFactory, CourseFactory, EnrollmentFactory, StudentRecordFactory
from .models import AcademicYear, Course, Enrollment
from .services.courses import archive_course, clone_course, unarchive_course

pytestmark = pytest.mark.django_db


# ── Ciclo escolar ─────────────────────────────────────────────────────

class TestCicloEscolar:
    @pytest.mark.parametrize("hoy, nombre", [
        (datetime.date(2026, 10, 11), "2026–2027"),
        (datetime.date(2027, 3, 1), "2026–2027"),
        (datetime.date(2026, 8, 1), "2026–2027"),
        (datetime.date(2027, 7, 31), "2026–2027"),
        (datetime.date(2027, 8, 1), "2027–2028"),
    ])
    def test_periodo_por_defecto_es_agosto_julio(self, hoy, nombre):
        assert AcademicYear.default_period(hoy)[0] == nombre

    def test_el_periodo_por_defecto_abarca_de_agosto_a_julio(self):
        _, inicio, fin = AcademicYear.default_period(datetime.date(2026, 10, 11))
        assert (inicio, fin) == (datetime.date(2026, 8, 1), datetime.date(2027, 7, 31))

    def test_current_for_crea_el_ciclo_en_curso_y_es_idempotente(self):
        organizacion = OrganizationFactory()
        ciclo = AcademicYear.current_for(organizacion)
        assert ciclo.is_current
        assert AcademicYear.current_for(organizacion) == ciclo
        assert AcademicYear.objects.filter(organization=organizacion).count() == 1

    def test_marcar_uno_como_actual_desmarca_el_anterior(self):
        organizacion = OrganizationFactory()
        viejo = AcademicYearFactory(organization=organizacion, is_current=True)
        nuevo = AcademicYearFactory(organization=organizacion, is_current=True)
        viejo.refresh_from_db()
        assert not viejo.is_current and nuevo.is_current

    def test_el_actual_de_una_organizacion_no_afecta_a_otra(self):
        a = AcademicYearFactory(is_current=True)
        AcademicYearFactory(is_current=True)  # otra organización
        a.refresh_from_db()
        assert a.is_current

    def test_no_puede_terminar_antes_de_empezar(self):
        ciclo = AcademicYearFactory.build(
            organization=OrganizationFactory(), start_date=datetime.date(2026, 8, 1), end_date=datetime.date(2026, 7, 1),
        )
        with pytest.raises(ValidationError):
            ciclo.clean()
        with pytest.raises(IntegrityError), transaction.atomic():
            ciclo.save()

    def test_nombre_unico_por_organizacion(self):
        ciclo = AcademicYearFactory(name="2026–2027")
        with pytest.raises(IntegrityError), transaction.atomic():
            AcademicYearFactory(organization=ciclo.organization, name="2026–2027")
        AcademicYearFactory(name="2026–2027")  # otra organización

    def test_el_grupo_nuevo_toma_el_ciclo_actual_de_su_organizacion(self):
        grupo = CourseFactory()
        assert grupo.academic_year.is_current
        assert grupo.academic_year.organization_id == grupo.organization_id

    def test_un_grupo_no_puede_usar_el_ciclo_de_otra_organizacion(self):
        with pytest.raises(ValidationError):
            CourseFactory(academic_year=AcademicYearFactory())

    def test_el_codigo_se_puede_repetir_en_otro_ciclo_pero_no_en_el_mismo(self):
        grupo = CourseFactory(code="MAT1")
        otro_ciclo = AcademicYearFactory(organization=grupo.organization)
        CourseFactory(professor=grupo.professor, code="MAT1", academic_year=otro_ciclo)
        with pytest.raises(IntegrityError), transaction.atomic():
            CourseFactory(professor=grupo.professor, code="MAT1", academic_year=grupo.academic_year)

    def test_el_codigo_se_puede_repetir_entre_organizaciones(self):
        CourseFactory(code="MAT1")
        CourseFactory(code="MAT1")
        assert Course.objects.filter(code="MAT1").count() == 2


# ── Archivar ──────────────────────────────────────────────────────────

class TestArchivar:
    def test_archivar_marca_estado_y_fecha(self, course):
        archive_course(course)
        course.refresh_from_db()
        assert course.is_archived and course.archived_at is not None

    def test_archivar_es_idempotente(self, course):
        archive_course(course)
        primera = Course.objects.get(pk=course.pk).archived_at
        archive_course(Course.objects.get(pk=course.pk))
        assert Course.objects.get(pk=course.pk).archived_at == primera

    def test_desarchivar_lo_devuelve_a_activo(self, course):
        archive_course(course)
        unarchive_course(course)
        course.refresh_from_db()
        assert not course.is_archived and course.archived_at is None

    def test_un_grupo_archivado_es_de_solo_lectura(self, course, activity, enrollment):
        nota = GradeFactory(activity=activity, student=enrollment.student)
        archive_course(course)

        with pytest.raises(ValidationError):
            Enrollment.objects.create(student=StudentRecordFactory(organization=course.organization), course=course)
        with pytest.raises(ValidationError):
            ActivityFactory(course=course)
        activity.title = "Otro"
        with pytest.raises(ValidationError):
            activity.save()
        nota.score = 1
        with pytest.raises(ValidationError):
            nota.save()
        with pytest.raises(ValidationError):
            GradeFactory(activity=activity, student=StudentRecordFactory(organization=course.organization))

    def test_sigue_siendo_consultable(self, course, activity, enrollment):
        GradeFactory(activity=activity, student=enrollment.student)
        archive_course(course)
        assert Grade.objects.filter(activity__course=course).count() == 1
        assert course.enrollments.count() == 1

    def test_al_desarchivar_vuelve_a_poder_editarse(self, course, activity):
        archive_course(course)
        unarchive_course(course)
        ActivityFactory(course=course)  # ya no lanza


# ── Duplicar para un nuevo ciclo ──────────────────────────────────────

class TestDuplicar:
    @pytest.fixture
    def nuevo_ciclo(self, course):
        return AcademicYearFactory(organization=course.organization)

    @pytest.fixture
    def grupo_completo(self, course, enrollment):
        e1 = ActivityFactory(course=course, title="Parcial", max_score=100, weight=3, date=datetime.date(2026, 10, 1))
        ActivityFactory(course=course, title="Tarea", weight=1, date=datetime.date(2026, 10, 5))
        GradeFactory(activity=e1, student=enrollment.student, score=90)
        course.description = "Descripción"
        course.schedule = "Lun 8:00"
        course.color = "#123456"
        course.save()
        return course

    def test_copia_los_datos_del_grupo(self, grupo_completo, nuevo_ciclo):
        copia = clone_course(grupo_completo, nuevo_ciclo)
        assert copia.pk != grupo_completo.pk
        assert (copia.name, copia.code, copia.description, copia.schedule, copia.color) == (
            grupo_completo.name, grupo_completo.code, "Descripción", "Lun 8:00", "#123456",
        )
        assert copia.academic_year == nuevo_ciclo
        assert copia.professor == grupo_completo.professor
        assert copia.organization == grupo_completo.organization
        assert not copia.is_archived

    def test_copia_las_evaluaciones_sin_fechas(self, grupo_completo, nuevo_ciclo):
        copia = clone_course(grupo_completo, nuevo_ciclo)
        copiadas = {(e.title, e.max_score, e.weight, e.date) for e in copia.activities.all()}
        assert copiadas == {("Parcial", 100, 3, None), ("Tarea", 10.0, 1, None)}

    def test_no_copia_alumnos_inscripciones_ni_notas(self, grupo_completo, nuevo_ciclo):
        copia = clone_course(grupo_completo, nuevo_ciclo)
        assert copia.enrollments.count() == 0
        assert Grade.objects.filter(activity__course=copia).count() == 0

    def test_no_modifica_el_original(self, grupo_completo, nuevo_ciclo):
        clone_course(grupo_completo, nuevo_ciclo)
        assert grupo_completo.enrollments.count() == 1
        assert {e.date for e in grupo_completo.activities.all()} == {datetime.date(2026, 10, 1), datetime.date(2026, 10, 5)}
        assert Grade.objects.filter(activity__course=grupo_completo).count() == 1

    def test_los_alumnos_persisten_para_inscribirlos_en_el_nuevo_ciclo(self, grupo_completo, nuevo_ciclo, enrollment):
        copia = clone_course(grupo_completo, nuevo_ciclo)
        Enrollment.objects.create(student=enrollment.student, course=copia)
        assert enrollment.student.enrollments.count() == 2

    def test_admite_nuevo_codigo_y_nombre(self, grupo_completo, nuevo_ciclo):
        copia = clone_course(grupo_completo, nuevo_ciclo, code=" NUEVO ", name="Nombre nuevo")
        assert (copia.code, copia.name) == ("NUEVO", "Nombre nuevo")

    def test_rechaza_un_codigo_repetido_en_el_ciclo_destino(self, grupo_completo, nuevo_ciclo):
        clone_course(grupo_completo, nuevo_ciclo)
        with pytest.raises(ValidationError):
            clone_course(grupo_completo, nuevo_ciclo)
        assert Course.objects.filter(academic_year=nuevo_ciclo).count() == 1

    def test_rechaza_un_ciclo_de_otra_organizacion(self, grupo_completo):
        with pytest.raises(ValidationError):
            clone_course(grupo_completo, AcademicYearFactory())

    def test_un_fallo_no_deja_copias_a_medias(self, grupo_completo, nuevo_ciclo, monkeypatch):
        def falla(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(Activity, "save", falla)
        with pytest.raises(RuntimeError):
            clone_course(grupo_completo, nuevo_ciclo)
        assert not Course.objects.filter(academic_year=nuevo_ciclo).exists()

    def test_se_puede_duplicar_un_grupo_archivado(self, grupo_completo, nuevo_ciclo):
        archive_course(grupo_completo)
        copia = clone_course(grupo_completo, nuevo_ciclo)
        assert not copia.is_archived
        assert copia.activities.count() == 2
