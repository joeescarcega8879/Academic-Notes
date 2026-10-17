"""Editor del esquema de evaluación y presentación de la calificación final."""

import pytest
from django.urls import reverse

from apps.courses.tests.factories import CourseFactory
from apps.courses.services.courses import archive_course
from apps.organizations.tests.factories import MembershipFactory
from apps.organizations.models import Membership

from .factories import ActivityFactory, GradeFactory
from .models import Activity, EvaluationCriterion, EvaluationPeriod

pytestmark = pytest.mark.django_db


def url(course):
    return reverse("grades:scheme", args=[course.pk])


def datos(formset, accion, **cambios):
    """Datos de POST de un formset tal como llega del servidor, más los ``cambios`` indicados.

    ``cambios`` usa ``"<fila>-<campo>"`` como clave, con la fila contando desde 0.
    """
    data = {"action": accion}
    prefijo = formset.prefix
    for campo in ("TOTAL_FORMS", "INITIAL_FORMS", "MIN_NUM_FORMS", "MAX_NUM_FORMS"):
        data[f"{prefijo}-{campo}"] = formset.management_form[campo].value()
    for i, form in enumerate(formset.forms):
        for name in form.fields:
            valor = form[name].value()
            if valor is not None and valor is not False:  # `0 in (None, False)` es verdadero: no usar `in`
                data[f"{prefijo}-{i}-{name}"] = valor
    for clave, valor in cambios.items():
        data[f"{prefijo}-{clave}"] = valor
    return data


@pytest.fixture
def pagina(professor_client, course):
    return professor_client.get(url(course)).context


# ── Acceso ────────────────────────────────────────────────────────────

class TestAcceso:
    def test_el_docente_ve_las_cuatro_secciones(self, professor_client, course):
        response = professor_client.get(url(course))
        assert response.status_code == 200
        html = response.content.decode()
        for titulo in ("Escala y aprobación", "Periodos", "Criterios", "Actividades del grupo"):
            assert titulo in html

    def test_grupo_de_otro_docente_es_404(self, professor_client):
        assert professor_client.get(url(CourseFactory())).status_code == 404

    def test_grupo_archivado_es_404(self, professor_client, course):
        archive_course(course)
        assert professor_client.get(url(course)).status_code == 404
        assert professor_client.post(url(course), {"action": "settings"}).status_code == 404

    def test_el_alumno_no_accede(self, student_client, course, enrollment):
        assert student_client.get(url(course)).status_code == 302

    def test_anonimo_va_al_login(self, client, course):
        assert client.get(url(course)).url.startswith("/login/")

    def test_grupo_de_otra_organizacion_activa_es_404(self, professor_client, professor):
        otra = MembershipFactory(user=professor, role=Membership.Role.TEACHER).organization
        ajeno = CourseFactory(professor=professor, organization=otra)
        assert professor_client.get(url(ajeno)).status_code == 404

    def test_accion_desconocida(self, professor_client, course):
        response = professor_client.post(url(course), {"action": "otra"}, follow=True)
        assert any("desconocida" in str(m) for m in response.context["messages"])

    def test_el_enlace_aparece_en_el_detalle_solo_para_grupos_activos(self, professor_client, course):
        enlace = url(course)
        assert enlace in professor_client.get(course.get_absolute_url()).content.decode()
        archive_course(course)
        assert enlace not in professor_client.get(course.get_absolute_url()).content.decode()


# ── Ajustes ───────────────────────────────────────────────────────────

class TestAjustes:
    def test_guarda_escala_minimo_y_redondeo(self, professor_client, course):
        response = professor_client.post(url(course), {
            "action": "settings", "scale_max": 100, "pass_mark": "70", "rounding_decimals": 0,
        })
        assert response.status_code == 302
        course.scheme.refresh_from_db()
        assert (course.scheme.scale_max, float(course.scheme.pass_mark), course.scheme.rounding_decimals) == (100, 70.0, 0)

    def test_el_minimo_no_puede_superar_la_escala(self, professor_client, course):
        response = professor_client.post(url(course), {
            "action": "settings", "scale_max": 10, "pass_mark": "11", "rounding_decimals": 2,
        })
        assert response.status_code == 200 and response.context["settings_form"].errors
        course.scheme.refresh_from_db()
        assert float(course.scheme.pass_mark) == 6.0

    @pytest.mark.parametrize("campo, valor", [("scale_max", 0), ("scale_max", "abc"), ("pass_mark", -1), ("rounding_decimals", 5)])
    def test_valores_invalidos(self, professor_client, course, campo, valor):
        base = {"action": "settings", "scale_max": 10, "pass_mark": "6", "rounding_decimals": 2}
        response = professor_client.post(url(course), {**base, campo: valor})
        assert response.status_code == 200 and campo in response.context["settings_form"].errors

    def test_cambiar_la_escala_cambia_la_final_y_la_aprobacion(self, professor_client, course, enrollment, activity):
        GradeFactory(activity=activity, student=enrollment.student, score=6.5)  # 65 %
        professor_client.post(url(course), {"action": "settings", "scale_max": 100, "pass_mark": "70", "rounding_decimals": 1})
        detalle = professor_client.get(course.get_absolute_url())
        resultado = detalle.context["enrollments"][0].result
        assert (resultado.final, resultado.passed) == (65.0, False)  # 65 de 100 con mínimo 70
        html = detalle.content.decode()
        assert "65.0" in html and "No aprobado" in html


# ── Periodos ──────────────────────────────────────────────────────────

class TestPeriodos:
    def test_agrega_un_periodo_al_final(self, professor_client, course, pagina):
        formset = pagina["period_formset"]
        professor_client.post(url(course), datos(formset, "periods", **{"1-name": "Parcial 2", "1-weight": "50"}))
        assert [p.name for p in course.scheme.periods.all()] == ["Periodo único", "Parcial 2"]
        assert list(course.scheme.periods.values_list("position", flat=True)) == [0, 1]

    def test_renombra_y_cambia_el_peso(self, professor_client, course, pagina):
        professor_client.post(url(course), datos(pagina["period_formset"], "periods", **{"0-name": "Ciclo completo", "0-weight": "80"}))
        (periodo,) = course.scheme.periods.all()
        assert (periodo.name, float(periodo.weight)) == ("Ciclo completo", 80.0)

    def test_no_se_puede_dejar_sin_periodos(self, professor_client, course, pagina):
        response = professor_client.post(url(course), datos(pagina["period_formset"], "periods", **{"0-DELETE": "on"}))
        assert response.status_code == 200
        assert "al menos un periodo" in str(response.context["period_formset"].non_form_errors())
        assert course.scheme.periods.count() == 1

    def test_borra_un_periodo_vacio(self, professor_client, course, pagina):
        extra = EvaluationPeriod.objects.create(scheme=course.scheme, name="Sobra", weight=0, position=1)
        pagina = professor_client.get(url(course)).context
        professor_client.post(url(course), datos(pagina["period_formset"], "periods", **{"1-DELETE": "on"}))
        assert not EvaluationPeriod.objects.filter(pk=extra.pk).exists()

    def test_no_borra_un_periodo_con_evaluaciones(self, professor_client, course, activity):
        pagina = professor_client.get(url(course)).context
        # Se agrega otro periodo para poder intentar borrar el primero sin quedarse vacío.
        EvaluationPeriod.objects.create(scheme=course.scheme, name="Otro", weight=0, position=1)
        pagina = professor_client.get(url(course)).context
        response = professor_client.post(url(course), datos(pagina["period_formset"], "periods", **{"0-DELETE": "on"}), follow=True)
        assert any("actividades asignadas" in str(m) for m in response.context["messages"])
        assert course.scheme.periods.count() == 2

    def test_peso_fuera_de_rango(self, professor_client, course, pagina):
        response = professor_client.post(url(course), datos(pagina["period_formset"], "periods", **{"0-weight": "150"}))
        assert response.status_code == 200 and response.context["period_formset"].errors[0]["weight"]

    def test_la_suma_se_muestra_y_avisa_si_no_es_cien(self, professor_client, course):
        assert "Suman 100 %" in professor_client.get(url(course)).content.decode()
        EvaluationPeriod.objects.filter(scheme=course.scheme).update(weight=80)
        assert "Suman 80 %" in professor_client.get(url(course)).content.decode()


# ── Criterios ─────────────────────────────────────────────────────────

class TestCriterios:
    def test_cambia_los_pesos(self, professor_client, course, pagina):
        professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **{"0-weight": "55", "1-weight": "45"}))
        assert [float(c.weight) for c in course.scheme.criteria()] == [55.0, 45.0, 20.0, 10.0]

    def test_agrega_un_criterio(self, professor_client, course, pagina):
        formset = pagina["criterion_formset"]
        periodo = course.scheme.periods.first().pk
        professor_client.post(url(course), datos(formset, "criteria", **{
            "4-period": periodo, "4-name": "Laboratorio", "4-weight": "10", "4-default_type": "",
        }))
        nuevo = course.scheme.criteria().get(name="Laboratorio")
        assert (float(nuevo.weight), nuevo.default_type, nuevo.position) == (10.0, "", 4)

    def test_no_se_puede_usar_un_periodo_de_otro_grupo(self, professor_client, course, pagina):
        ajeno = CourseFactory().scheme.periods.first()
        response = professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **{
            "4-period": ajeno.pk, "4-name": "Intruso", "4-weight": "10",
        }))
        assert response.status_code == 200 and "period" in response.context["criterion_formset"].errors[4]
        assert not EvaluationCriterion.objects.filter(name="Intruso").exists()

    def test_no_borra_un_criterio_con_evaluaciones_y_avisa(self, professor_client, course):
        evaluacion = ActivityFactory(course=course, type=Activity.Type.EXAM)
        pagina = professor_client.get(url(course)).context
        response = professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **{"0-DELETE": "on"}), follow=True)
        assert any("actividades asignadas" in str(m) for m in response.context["messages"])
        evaluacion.refresh_from_db()
        assert course.scheme.criteria().count() == 4

    def test_borra_un_criterio_sin_evaluaciones(self, professor_client, course, pagina):
        professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **{"3-DELETE": "on"}))
        assert [c.name for c in course.scheme.criteria()] == ["Exámenes", "Tareas", "Proyecto"]

    def test_no_se_puede_dejar_sin_criterios(self, professor_client, course, pagina):
        cambios = {f"{i}-DELETE": "on" for i in range(4)}
        response = professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **cambios))
        assert "al menos un criterio" in str(response.context["criterion_formset"].non_form_errors())
        assert course.scheme.criteria().count() == 4

    def test_las_evaluaciones_nuevas_siguen_el_tipo_configurado(self, professor_client, course, pagina):
        # Los quizzes pasan a ir a "Tareas".
        professor_client.post(url(course), datos(pagina["criterion_formset"], "criteria", **{"1-default_type": "homework", "3-default_type": ""}))
        assert ActivityFactory(course=course, type=Activity.Type.HOMEWORK).criterion.name == "Tareas"
        assert ActivityFactory(course=course, type=Activity.Type.QUIZ).criterion.name == "Exámenes"  # el primero


# ── Evaluaciones ──────────────────────────────────────────────────────

class TestAsignacion:
    def test_reasigna_una_evaluacion_a_otro_criterio(self, professor_client, course):
        evaluacion = ActivityFactory(course=course, type=Activity.Type.EXAM)
        proyecto = course.scheme.criteria().get(name="Proyecto")
        pagina = professor_client.get(url(course)).context
        professor_client.post(url(course), datos(pagina["assignment_formset"], "evals", **{"0-criterion": proyecto.pk}))
        evaluacion.refresh_from_db()
        assert evaluacion.criterion == proyecto

    def test_no_acepta_un_criterio_de_otro_grupo(self, professor_client, course):
        evaluacion = ActivityFactory(course=course)
        original = evaluacion.criterion
        ajeno = CourseFactory().scheme.criteria().first()
        pagina = professor_client.get(url(course)).context
        response = professor_client.post(url(course), datos(pagina["assignment_formset"], "evals", **{"0-criterion": ajeno.pk}))
        assert response.status_code == 200 and response.context["assignment_formset"].errors[0]
        evaluacion.refresh_from_db()
        assert evaluacion.criterion == original

    def test_reasignar_cambia_la_calificacion_final(self, professor_client, course, enrollment):
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM)
        tarea = ActivityFactory(course=course, type=Activity.Type.HOMEWORK)
        GradeFactory(activity=examen, student=enrollment.student, score=10)
        GradeFactory(activity=tarea, student=enrollment.student, score=4)
        antes = professor_client.get(course.get_absolute_url()).context["enrollments"][0].result.final
        assert antes == 7.43  # (10·40 + 4·30) / 70
        # La tarea pasa a Exámenes: todo cae en un criterio, media simple de 10 y 4
        pagina = professor_client.get(url(course)).context
        examenes = course.scheme.criteria().get(name="Exámenes")
        indice = [e.pk for e in pagina["assignment_formset"].queryset].index(tarea.pk)
        professor_client.post(url(course), datos(pagina["assignment_formset"], "evals", **{f"{indice}-criterion": examenes.pk}))
        despues = professor_client.get(course.get_absolute_url()).context["enrollments"][0].result.final
        assert despues == 7.0

    def test_sin_evaluaciones_lo_dice(self, professor_client, course):
        assert "Aún no hay actividades" in professor_client.get(url(course)).content.decode()


# ── Calificación final en el detalle ──────────────────────────────────

class TestDetalle:
    @pytest.fixture
    def con_notas(self, course, enrollment):
        examen = ActivityFactory(course=course, type=Activity.Type.EXAM)
        GradeFactory(activity=examen, student=enrollment.student, score=8)
        return enrollment

    def test_el_docente_ve_la_final_y_el_estado_de_cada_alumno(self, professor_client, course, con_notas):
        html = professor_client.get(course.get_absolute_url()).content.decode()
        assert "Calificación final" in html and "8.00" in html and "Aprobado" in html

    def test_alumno_sin_notas_no_tiene_final(self, professor_client, course, enrollment):
        (inscripcion,) = professor_client.get(course.get_absolute_url()).context["enrollments"]
        assert inscripcion.result is None

    def test_el_alumno_ve_su_final_y_el_desglose(self, student_client, course, con_notas):
        response = student_client.get(course.get_absolute_url())
        assert response.context["course_average"] == 8.0
        html = response.content.decode()
        assert "Calificación final: 8.00 / 10" in html
        assert "Aprobado" in html and "Cómo se calcula tu calificación" in html
        assert "Exámenes" in html and "80 %" in html and "Sin calificar" in html  # los otros criterios

    def test_el_alumno_sin_notas_no_ve_desglose(self, student_client, course, enrollment):
        html = student_client.get(course.get_absolute_url()).content.decode()
        assert "Cómo se calcula tu calificación" not in html

    def test_el_alumno_no_ve_el_editor_ni_el_codigo(self, student_client, course, con_notas):
        html = student_client.get(course.get_absolute_url()).content.decode()
        assert url(course) not in html
