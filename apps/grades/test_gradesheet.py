"""La libreta: tabla alumnos × actividades, edición de una celda y sus respuestas."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.courses.tests.factories import EnrollmentFactory
from apps.courses.services.courses import archive_course

from .factories import ActivityFactory, GradeFactory
from .models import Activity, EvaluationCriterion, EvaluationPeriod, Grade, GradeHistory
from .services.gradebook import grade_activity
from .services.grading import results_by_course
from .services.gradesheet import build_gradesheet, fmt, parse_score, set_cell
from .services.schemes import ensure_scheme
from .services.submissions import submit

pytestmark = pytest.mark.django_db

AHORA = timezone.now()
UN_DIA = datetime.timedelta(days=1)


def inscribir(course, apellido, nombre='Ana'):
    """Alumno sin cuenta inscrito en el grupo."""
    return EnrollmentFactory(
        course=course, student__user=None, student__first_name=nombre, student__last_name=apellido,
    ).student


@pytest.fixture
def alumno(enrollment):
    return enrollment.student


# ── Formato y lectura de lo escrito ───────────────────────────────────

class TestFormato:
    @pytest.mark.parametrize("valor, decimales, trim, esperado", [
        (8.0, 2, True, "8"), (8.5, 2, True, "8.5"), (7.125, 2, True, "7.13"), (0, 2, True, "0"), (10, 2, True, "10"),
        (8.0, 2, False, "8.00"), (7.5, 1, False, "7.5"), (7.46, 1, False, "7.5"), (7.5, 0, False, "8"), (100, 0, True, "100"),
        (None, 2, True, ""), (0.1 + 0.2, 2, True, "0.3"),
    ])
    def test_fmt(self, valor, decimales, trim, esperado):
        assert fmt(valor, decimales, trim=trim) == esperado


class TestParseScore:
    @pytest.mark.parametrize("texto, esperado", [
        ("8", 8.0), (" 8.5 ", 8.5), ("8,5", 8.5), ("0", 0.0), ("10", 10.0), ("0,0", 0.0),
        ("", None), ("   ", None), (None, None),
    ])
    def test_valores_validos(self, texto, esperado):
        assert parse_score(texto, 10) == esperado

    @pytest.mark.parametrize("texto", ["abc", "8.5.5", "-1", "10.01", "11", "nan", "inf", "-inf", "1e400", "x" * 50, "8 9", "--8"])
    def test_valores_invalidos(self, texto):
        with pytest.raises(ValidationError):
            parse_score(texto, 10)

    def test_mensajes(self):
        with pytest.raises(ValidationError, match="Escribe un número"):
            parse_score("hola", 10)
        with pytest.raises(ValidationError, match="entre 0 y 10"):
            parse_score("11", 10)

    def test_el_maximo_es_el_de_la_actividad(self):
        assert parse_score("100", 100) == 100.0
        with pytest.raises(ValidationError, match="entre 0 y 2.5"):
            parse_score("3", 2.5)


# ── Edición de una celda ──────────────────────────────────────────────

class TestSetCell:
    def test_crea_la_calificacion(self, activity, alumno, professor):
        nota = set_cell(activity, alumno, "8,5", by=professor)
        assert (nota.raw_score, nota.score, nota.source) == (8.5, 8.5, Grade.Source.MANUAL)
        assert GradeHistory.objects.get().changed_by == professor

    def test_cambia_la_calificacion(self, activity, alumno, professor):
        set_cell(activity, alumno, "6", by=professor)
        set_cell(activity, alumno, "9", by=professor)
        assert Grade.objects.get().score == 9
        assert [h.action for h in GradeHistory.objects.order_by("id")] == ["created", "updated"]

    def test_el_mismo_valor_no_toca_ni_ensucia_la_bitacora(self, activity, alumno, professor):
        set_cell(activity, alumno, "6", by=professor)
        set_cell(activity, alumno, "6.0", by=professor)
        set_cell(activity, alumno, "6,00", by=professor)
        assert GradeHistory.objects.count() == 1

    def test_celda_vacia_quita_la_calificacion_y_deja_constancia(self, activity, alumno, professor):
        set_cell(activity, alumno, "6", by=professor)
        assert set_cell(activity, alumno, "  ", by=professor) is None
        assert not Grade.objects.exists()
        ultima = GradeHistory.objects.first()
        assert (ultima.action, ultima.changed_by, ultima.old_score) == ("deleted", professor, 6)

    def test_celda_vacia_sin_calificacion_no_hace_nada(self, activity, alumno, professor):
        assert set_cell(activity, alumno, "", by=professor) is None
        assert not GradeHistory.objects.exists()

    def test_conserva_el_comentario(self, activity, alumno, professor):
        grade_activity(activity, alumno, score=6, feedback="Falta la conclusión", by=professor)
        set_cell(activity, alumno, "7", by=professor)
        assert Grade.objects.get().feedback == "Falta la conclusión"

    def test_valor_invalido_no_cambia_nada(self, activity, alumno, professor):
        set_cell(activity, alumno, "6", by=professor)
        for texto in ("11", "-2", "abc"):
            with pytest.raises(ValidationError):
                set_cell(activity, alumno, texto, by=professor)
        assert Grade.objects.get().score == 6

    def test_alumno_que_no_es_del_grupo(self, activity, professor):
        ajeno = EnrollmentFactory().student
        with pytest.raises(ValidationError, match="no está inscrito"):
            set_cell(activity, ajeno, "8", by=professor)

    def test_grupo_archivado_es_de_solo_lectura(self, course, activity, alumno, professor):
        set_cell(activity, alumno, "6", by=professor)
        archive_course(course)
        activity.refresh_from_db()
        with pytest.raises(ValidationError):
            set_cell(activity, alumno, "9", by=professor)
        with pytest.raises(ValidationError):
            set_cell(activity, alumno, "", by=professor)
        assert Grade.objects.get().score == 6

    def test_pisar_una_nota_automatica_la_vuelve_del_docente(self, activity, alumno):
        grade_activity(activity, alumno, score=5, source=Grade.Source.QUIZ)
        set_cell(activity, alumno, "9")
        assert Grade.objects.get().source == Grade.Source.MANUAL

    def test_repetir_la_nota_automatica_no_le_quita_el_origen(self, activity, alumno):
        grade_activity(activity, alumno, score=5, source=Grade.Source.QUIZ)
        set_cell(activity, alumno, "5")
        assert Grade.objects.get().source == Grade.Source.QUIZ


class TestPenalizacion:
    @pytest.fixture
    def tarea(self, course):
        return ActivityFactory(
            course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=20, max_score=10,
        )

    def test_una_entrega_tardia_se_penaliza_al_editar_la_celda(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        nota = set_cell(tarea, alumno, "10")
        assert (nota.raw_score, nota.score) == (10, 8)

    def test_cambiar_la_nota_no_aplica_la_penalizacion_dos_veces(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        set_cell(tarea, alumno, "10")
        nota = set_cell(tarea, alumno, "9")
        assert (nota.raw_score, nota.score) == (9, 7.2)

    def test_si_el_docente_perdono_la_penalizacion_se_sigue_perdonando(self, tarea, alumno):
        submit(tarea, alumno, text="tarde", now=AHORA)
        grade_activity(tarea, alumno, score=10, waive_penalty=True)
        nota = set_cell(tarea, alumno, "9")
        assert (nota.score, float(nota.late_penalty)) == (9, 0)

    def test_sin_entrega_no_hay_nada_que_perdonar(self, tarea, alumno):
        set_cell(tarea, alumno, "10")
        assert Grade.objects.get().score == 10


# ── La tabla ──────────────────────────────────────────────────────────

class TestConstruccion:
    def test_filas_en_orden_alfabetico_y_columnas_por_criterio(self, course):
        zapata, alvarez = inscribir(course, "Zapata"), inscribir(course, "Álvarez", "Luis")
        quiz = ActivityFactory(course=course, type=Activity.Type.QUIZ)  # nace en borrador
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM)
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        hoja = build_gradesheet(course)
        assert [r.student for r in hoja.rows] == [alvarez, zapata]
        # Orden del esquema por defecto: Exámenes, Tareas, Proyecto, Quizzes.
        assert [c.activity for c in hoja.columns] == [examen, tarea, quiz]
        assert [g.criterion.name for g in hoja.periods[0].criteria] == ["Exámenes", "Tareas", "Quizzes"]
        assert not hoja.multiple_periods

    def test_dentro_de_un_criterio_van_por_fecha_y_las_sin_fecha_al_final(self, course):
        sin_fecha = ActivityFactory(course=course, date=None)
        tarde = ActivityFactory(course=course, date=datetime.date(2026, 11, 20))
        temprano = ActivityFactory(course=course, date=datetime.date(2026, 9, 1))
        assert [c.activity for c in build_gradesheet(course).columns] == [temprano, tarde, sin_fecha]

    def test_hay_una_celda_por_columna_aunque_no_haya_nota(self, course, alumno, activity):
        otra = ActivityFactory(course=course)
        grade_activity(activity, alumno, score=7)
        fila = build_gradesheet(course).rows[0]
        assert len(fila.cells) == 2
        por_actividad = {c["activity_id"]: c for c in fila.cells}
        assert por_actividad[activity.pk]["raw"] == "7" and por_actividad[otra.pk]["raw"] == ""

    def test_la_final_coincide_con_el_calculo_del_esquema(self, course, alumno):
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM, max_score=10)
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK, max_score=20)
        grade_activity(examen, alumno, score=8)
        grade_activity(tarea, alumno, score=10)
        esperado = results_by_course(Grade.objects.filter(student=alumno).select_related("activity"))[course.pk]
        fila = build_gradesheet(course).rows[0]
        assert fila.final == {"text": f"{esperado.final:.2f}", "passed": esperado.passed}

    def test_sin_calificaciones_la_final_esta_vacia(self, course, alumno, activity):
        assert build_gradesheet(course).rows[0].final == {"text": "", "passed": None}

    def test_la_final_respeta_el_redondeo_del_esquema(self, course, alumno, activity):
        esquema = ensure_scheme(course)
        esquema.rounding_decimals = 0
        esquema.save()
        grade_activity(activity, alumno, score=7.6)
        assert build_gradesheet(course).rows[0].final["text"] == "8"

    def test_un_borrador_aparece_pero_no_cuenta_para_la_final(self, course, alumno):
        borrador = ActivityFactory(course=course, published=False)
        grade_activity(borrador, alumno, score=3)
        hoja = build_gradesheet(course)
        assert [c.activity for c in hoja.columns] == [borrador]
        assert hoja.rows[0].cells[0]["raw"] == "3"
        assert hoja.rows[0].final["text"] == ""

    def test_reprobado_se_marca(self, course, alumno, activity):
        grade_activity(activity, alumno, score=4)
        assert build_gradesheet(course).rows[0].final["passed"] is False

    def test_las_notas_de_alumnos_que_ya_no_estan_no_cuentan(self, course, activity):
        sigue, se_fue = inscribir(course, "Sigue"), inscribir(course, "Se fue")
        grade_activity(activity, sigue, score=10)
        grade_activity(activity, se_fue, score=2)
        course.enrollments.filter(student=se_fue).delete()
        hoja = build_gradesheet(course)
        columna = hoja.columns[0]
        assert (columna.graded, columna.average) == (1, "10")
        assert hoja.group["students"] == 1 and hoja.group["average"] == "10.00"

    def test_promedio_y_conteo_por_actividad(self, course, activity):
        a, b, c = inscribir(course, "A"), inscribir(course, "B"), inscribir(course, "C")
        grade_activity(activity, a, score=10)
        grade_activity(activity, b, score=5)
        columna = build_gradesheet(course).columns[0]
        assert (columna.graded, columna.average) == (2, "7.5")
        assert c  # el tercero queda sin calificar

    def test_el_promedio_usa_la_nota_efectiva_con_penalizacion(self, course, alumno):
        tarea = ActivityFactory(
            course=course, type=Activity.Type.HOMEWORK, due_at=AHORA - UN_DIA, allow_late=True, late_penalty=50,
        )
        submit(tarea, alumno, text="tarde", now=AHORA)
        grade_activity(tarea, alumno, score=10)
        hoja = build_gradesheet(course)
        assert hoja.columns[0].average == "5"
        celda = hoja.rows[0].cells[0]
        assert celda["raw"] == "10" and celda["score"] == "5" and "50" in celda["note"]

    def test_notas_de_celda(self, course, alumno, activity):
        grade_activity(activity, alumno, score=5, source=Grade.Source.QUIZ)
        celda = build_gradesheet(course).rows[0].cells[0]
        assert celda["auto"] is True and "automática" in celda["note"]

    def test_estadisticas_del_grupo(self, course, activity):
        bien, mal, sin = inscribir(course, "Bien"), inscribir(course, "Mal"), inscribir(course, "Sin")
        grade_activity(activity, bien, score=10)
        grade_activity(activity, mal, score=2)
        assert sin
        assert build_gradesheet(course).group == {"average": "6.00", "passed": 1, "students": 2}

    def test_grupo_vacio(self, course):
        hoja = build_gradesheet(course)
        assert (hoja.rows, hoja.columns, hoja.group) == ([], [], {"average": "", "passed": 0, "students": 0})

    def test_varios_periodos(self, course, alumno):
        esquema = ensure_scheme(course)
        segundo = EvaluationPeriod.objects.create(scheme=esquema, name="Segundo parcial", weight=50, position=1)
        criterio = EvaluationCriterion.objects.create(period=segundo, name="Final", weight=100, position=0)
        primera = ActivityFactory(course=course, type=Activity.Type.EXAM)
        ultima = ActivityFactory(course=course, criterion=criterio)
        hoja = build_gradesheet(course)
        assert hoja.multiple_periods
        assert [g.span for g in hoja.periods] == [1, 1]
        assert [c.activity for c in hoja.columns] == [primera, ultima]

    def test_consultas_constantes_aunque_crezca_el_grupo(self, course, django_assert_max_num_queries):
        actividades = [ActivityFactory(course=course) for _ in range(3)]
        for i in range(12):
            alumno = inscribir(course, f"Alumno{i:02d}")
            for actividad in actividades:
                grade_activity(actividad, alumno, score=7)
        with django_assert_max_num_queries(10):
            build_gradesheet(course)


# ── Vistas ────────────────────────────────────────────────────────────

class TestPagina:
    def url(self, course):
        return reverse("grades:gradesheet", args=[course.pk])

    def test_el_docente_ve_la_libreta(self, professor_client, course, alumno, activity):
        grade_activity(activity, alumno, score=8)
        response = professor_client.get(self.url(course))
        html = response.content.decode()
        assert response.status_code == 200
        assert alumno.last_name in html and activity.title in html
        assert reverse("grades:gradesheet_cell", args=[course.pk]) in html
        assert 'value="8"' in html and "disabled" not in html

    def test_sin_alumnos_o_sin_actividades_explica_que_hacer(self, professor_client, course, enrollment):
        assert "Aún no hay actividades" in professor_client.get(self.url(course)).content.decode()
        course.enrollments.all().delete()
        assert "no tiene alumnos" in professor_client.get(self.url(course)).content.decode()

    def test_grupo_archivado_se_ve_pero_no_se_edita(self, professor_client, course, alumno, activity):
        grade_activity(activity, alumno, score=8)
        archive_course(course)
        response = professor_client.get(self.url(course))
        html = response.content.decode()
        assert response.status_code == 200 and "solo lectura" in html and "disabled" in html
        assert reverse("grades:activity_create", args=[course.pk]) not in html

    def test_otro_docente_recibe_404(self, professor_client):
        from apps.courses.tests.factories import CourseFactory

        assert professor_client.get(self.url(CourseFactory())).status_code == 404

    def test_el_alumno_no_accede(self, student_client, course, enrollment):
        assert student_client.get(self.url(course)).status_code == 302

    def test_anonimo_va_al_login(self, client, course):
        assert client.get(self.url(course)).url.startswith("/login/")

    def test_el_grupo_enlaza_a_la_libreta(self, professor_client, course):
        assert self.url(course) in professor_client.get(reverse("course_detail", args=[course.pk])).content.decode()

    def test_los_nombres_se_escapan(self, professor_client, course, activity):
        EnrollmentFactory(course=course, student__user=None, student__first_name="<script>alert(1)</script>")
        html = professor_client.get(self.url(course)).content.decode()
        assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


class TestCelda:
    def url(self, course):
        return reverse("grades:gradesheet_cell", args=[course.pk])

    def post(self, client, course, activity, student, score):
        return client.post(self.url(course), {"activity": activity.pk, "student": student.pk, "score": score})

    def test_guarda_y_devuelve_lo_que_cambia_en_pantalla(self, professor_client, course, activity, alumno):
        response = self.post(professor_client, course, activity, alumno, "8,5")
        datos = response.json()
        assert response.status_code == 200 and datos["ok"] is True
        assert datos["cell"]["raw"] == "8.5" and datos["cell"]["auto"] is False
        assert datos["final"] == {"text": "8.50", "passed": True}
        assert datos["column"] == {"graded": 1, "average": "8.5"}
        assert datos["group"] == {"average": "8.50", "passed": 1, "students": 1}
        assert Grade.objects.get().raw_score == 8.5

    def test_deja_constancia_de_quien_lo_hizo(self, professor_client, course, activity, alumno, professor):
        self.post(professor_client, course, activity, alumno, "7")
        assert GradeHistory.objects.get().changed_by == professor

    def test_celda_vacia_quita_la_nota(self, professor_client, course, activity, alumno):
        self.post(professor_client, course, activity, alumno, "7")
        datos = self.post(professor_client, course, activity, alumno, "").json()
        assert datos["ok"] and datos["cell"]["raw"] == "" and datos["final"] == {"text": "", "passed": None}
        assert datos["column"] == {"graded": 0, "average": ""}
        assert not Grade.objects.exists()

    @pytest.mark.parametrize("texto, mensaje", [("abc", "Escribe un número"), ("11", "entre 0 y 10"), ("-1", "entre 0 y 10")])
    def test_valor_invalido(self, professor_client, course, activity, alumno, texto, mensaje):
        response = self.post(professor_client, course, activity, alumno, texto)
        assert response.status_code == 400 and mensaje in response.json()["error"]
        assert not Grade.objects.exists()

    @pytest.mark.parametrize("actividad, alumno", [("", "1"), ("1", ""), ("x", "1"), ("1", "²"), ("9" * 40, "1"), ("-1", "1")])
    def test_identificadores_invalidos_son_400_no_500(self, professor_client, course, actividad, alumno):
        response = professor_client.post(self.url(course), {"activity": actividad, "student": alumno, "score": "5"})
        assert response.status_code == 400

    def test_actividad_de_otro_grupo_es_404(self, professor_client, course, alumno):
        ajena = ActivityFactory()
        assert self.post(professor_client, course, ajena, alumno, "5").status_code == 404
        assert not Grade.objects.exists()

    def test_actividad_de_otro_grupo_del_mismo_docente_es_404(self, professor_client, course, professor, alumno):
        from apps.courses.tests.factories import CourseFactory

        hermana = ActivityFactory(course=CourseFactory(professor=professor))
        assert self.post(professor_client, course, hermana, alumno, "5").status_code == 404

    def test_alumno_que_no_es_del_grupo_es_404(self, professor_client, course, activity):
        ajeno = EnrollmentFactory().student
        assert self.post(professor_client, course, activity, ajeno, "5").status_code == 404
        assert not Grade.objects.exists()

    def test_alumno_de_la_organizacion_pero_de_otro_grupo_es_404(self, professor_client, course, activity):
        from apps.courses.tests.factories import StudentRecordFactory

        sin_inscribir = StudentRecordFactory(organization=course.organization, user=None)
        assert self.post(professor_client, course, activity, sin_inscribir, "5").status_code == 404
        assert not Grade.objects.exists()

    def test_grupo_de_otro_docente_es_404(self, professor_client, activity, alumno):
        ajeno = ActivityFactory()
        enrollment = EnrollmentFactory(course=ajeno.course)
        assert self.post(professor_client, ajeno.course, ajeno, enrollment.student, "5").status_code == 404

    def test_grupo_archivado_no_se_edita(self, professor_client, course, activity, alumno):
        self.post(professor_client, course, activity, alumno, "6")
        archive_course(course)
        response = self.post(professor_client, course, activity, alumno, "9")
        assert response.status_code == 400 and "archiv" in response.json()["error"].lower()
        assert Grade.objects.get().score == 6

    def test_el_alumno_no_puede(self, student_client, course, activity, enrollment):
        response = self.post(student_client, course, activity, enrollment.student, "10")
        assert response.status_code == 302 and not Grade.objects.exists()

    def test_anonimo_no_puede(self, client, course, activity, alumno):
        assert self.post(client, course, activity, alumno, "10").status_code == 302
        assert not Grade.objects.exists()

    def test_solo_post(self, professor_client, course):
        assert professor_client.get(self.url(course)).status_code == 405

    def test_exige_csrf(self, professor, course, activity, alumno):
        from django.test import Client

        cliente = Client(enforce_csrf_checks=True)
        cliente.force_login(professor)
        assert cliente.post(self.url(course), {"activity": activity.pk, "student": alumno.pk, "score": "9"}).status_code == 403
        assert not Grade.objects.exists()

    def test_pisar_una_nota_de_quiz_se_refleja_como_del_docente(self, professor_client, course, activity, alumno):
        grade_activity(activity, alumno, score=5, source=Grade.Source.QUIZ)
        datos = self.post(professor_client, course, activity, alumno, "9").json()
        assert datos["cell"]["auto"] is False

    def test_una_celda_no_afecta_a_las_demas(self, professor_client, course, activity, alumno):
        otro = inscribir(course, "Otro")
        otra = ActivityFactory(course=course)
        self.post(professor_client, course, activity, alumno, "9")
        self.post(professor_client, course, otra, otro, "4")
        assert Grade.objects.count() == 2
        assert Grade.objects.get(activity=activity).student == alumno


class TestCalificarPorGrupoSigueIgual:
    """La pantalla de calificar toda la actividad usa ahora el mismo lector de notas."""

    def test_notas_invalidas_siguen_sin_guardar_nada(self, professor_client, course, activity, alumno):
        otro = inscribir(course, "Otro")
        response = professor_client.post(
            reverse("grades:activity_grading", args=[activity.pk]), {f"score_{alumno.pk}": "7", f"score_{otro.pk}": "nan"},
        )
        assert response.status_code == 200 and not Grade.objects.exists()
        assert any("entre 0 y 10" in (row.get("error") or "") for row in response.context["rows"])

    def test_coma_decimal_y_filas_vacias(self, professor_client, course, activity, alumno):
        otro = inscribir(course, "Otro")
        professor_client.post(
            reverse("grades:activity_grading", args=[activity.pk]), {f"score_{alumno.pk}": "7,5", f"score_{otro.pk}": ""},
        )
        assert Grade.objects.get().score == 7.5


class TestColegaDeLaMismaOrganizacion:
    """Otro docente de la MISMA organización tampoco puede ver ni editar la libreta de un grupo ajeno."""

    @pytest.fixture
    def grupo_del_colega(self, course):
        from apps.accounts.tests.factories import ProfessorFactory
        from apps.courses.tests.factories import CourseFactory
        from apps.organizations.tests.factories import MembershipFactory
        from apps.organizations.models import Membership

        colega = ProfessorFactory()
        MembershipFactory(user=colega, organization=course.organization, role=Membership.Role.TEACHER)
        ajeno = CourseFactory(professor=colega, organization=course.organization)
        assert ajeno.organization == course.organization
        return ajeno

    def test_no_ve_la_libreta(self, professor_client, grupo_del_colega):
        assert professor_client.get(reverse("grades:gradesheet", args=[grupo_del_colega.pk])).status_code == 404

    def test_no_edita_celdas(self, professor_client, grupo_del_colega):
        actividad = ActivityFactory(course=grupo_del_colega)
        alumno = inscribir(grupo_del_colega, "Ajeno")
        response = professor_client.post(
            reverse("grades:gradesheet_cell", args=[grupo_del_colega.pk]),
            {"activity": actividad.pk, "student": alumno.pk, "score": "10"},
        )
        assert response.status_code == 404 and not Grade.objects.exists()


def test_graderfactory_sigue_disponible_para_la_libreta(course, activity):
    # Las notas creadas sin pasar por el servicio (admin, scripts) también aparecen en la libreta.
    alumno = inscribir(course, "Directa")
    GradeFactory(activity=activity, student=alumno, score=9)
    assert build_gradesheet(course).rows[0].cells[0]["raw"] == "9"
