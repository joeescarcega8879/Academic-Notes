"""La puerta de entrada a la IA: plan, interruptor, cuota, clave gratuita y registro de cada uso."""

import datetime

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.accounts.tests.factories import ProfessorFactory
from apps.ai import services
from apps.ai.models import AIRequest
from apps.ai.providers import ProviderError, fake
from apps.organizations.models import Organization
from apps.organizations.services import teaching_organization

pytestmark = pytest.mark.django_db

SCHEMA = {'type': 'object', 'properties': {'titulo': {'type': 'string'}, 'puntos': {'type': 'integer'}}}


@pytest.fixture(autouse=True)
def proveedor():
    """El proveedor de mentira, limpio en cada prueba."""
    fake.PROVIDER.reset()
    fake.PROVIDER.tier = 'fake'
    yield fake.PROVIDER
    fake.PROVIDER.reset()
    fake.PROVIDER.tier = 'fake'


def organizacion(profesor, plan, *, ia=True):
    org = teaching_organization(profesor)
    org.plan, org.ai_enabled = plan, ia
    org.save()
    return org


@pytest.fixture
def plus(professor):
    return organizacion(professor, Organization.Plan.TEACHER_PLUS)


def pedir(org, user, **extra):
    return services.generate_json(
        organization=org, user=user, kind=AIRequest.Kind.PROBE, prompt='Texto de prueba', schema=SCHEMA, **extra,
    )


def usos_ok(org, cantidad, **campos):
    AIRequest.objects.bulk_create([
        AIRequest(organization=org, kind='probe', provider='fake', status=AIRequest.Status.OK, **campos) for _ in range(cantidad)
    ])


class TestRevisiones:
    @pytest.mark.parametrize('plan', [Organization.Plan.FREE, Organization.Plan.TEACHER])
    def test_los_planes_sin_ia_no_pasan(self, professor, plan):
        org = organizacion(professor, plan)
        with pytest.raises(services.AIUnavailable) as error:
            pedir(org, professor)
        assert error.value.reason == 'plan' and 'Plus' in error.value.messages[0]
        assert not AIRequest.objects.exists()

    def test_plus_con_el_interruptor_apagado_no_pasa(self, professor):
        org = organizacion(professor, Organization.Plan.TEACHER_PLUS, ia=False)
        with pytest.raises(services.AIUnavailable) as error:
            pedir(org, professor)
        assert error.value.reason == 'disabled' and 'Ajustes' in error.value.messages[0]

    def test_el_interruptor_nace_apagado(self, professor):
        assert teaching_organization(professor).ai_enabled is False

    def test_es_un_validation_error_para_que_los_formularios_lo_muestren(self, professor):
        with pytest.raises(ValidationError):
            pedir(organizacion(professor, Organization.Plan.FREE), professor)

    def test_la_cuota_agotada_avisa_cuando_se_renueva(self, professor, plus):
        usos_ok(plus, 300)
        with pytest.raises(services.AIUnavailable) as error:
            pedir(plus, professor)
        renueva = services.next_month_start()
        assert error.value.reason == 'quota'
        assert f'1 de {services.MONTHS[renueva.month - 1]}' in error.value.messages[0] and '300' in error.value.messages[0]

    def test_con_un_uso_de_sobra_todavia_pasa(self, professor, plus):
        usos_ok(plus, 299)
        assert pedir(plus, professor)
        with pytest.raises(services.AIUnavailable):
            pedir(plus, professor)

    def test_las_solicitudes_fallidas_no_gastan_cuota(self, professor, plus):
        AIRequest.objects.bulk_create([
            AIRequest(organization=plus, kind='probe', provider='fake', status=AIRequest.Status.ERROR) for _ in range(300)
        ])
        assert services.uses_this_month(plus) == 0
        assert pedir(plus, professor)

    def test_la_cuota_es_del_mes_y_de_la_organizacion(self, professor, plus):
        usos_ok(plus, 300)
        AIRequest.objects.filter(organization=plus).update(created_at=services.month_start() - datetime.timedelta(days=1))
        otra = organizacion(ProfessorFactory(), Organization.Plan.TEACHER_PLUS)
        usos_ok(otra, 5)
        assert services.uses_this_month(plus) == 0 and services.uses_this_month(otra) == 5
        assert pedir(plus, professor)

    def test_diciembre_renueva_en_enero(self):
        diciembre = timezone.make_aware(datetime.datetime(2026, 12, 15, 10, 0))
        assert services.next_month_start(diciembre) == timezone.make_aware(datetime.datetime(2027, 1, 1))
        assert services.month_start(diciembre) == timezone.make_aware(datetime.datetime(2026, 12, 1))

    def test_resumen_de_uso(self, professor, plus):
        usos_ok(plus, 12)
        assert services.usage_summary(plus) == {'used': 12, 'limit': 300, 'remaining': 288}
        assert services.usage_summary(organizacion(ProfessorFactory(), Organization.Plan.TEACHER)) is None

    def test_una_clave_gratuita_rechaza_datos_de_alumnos(self, professor, plus, proveedor):
        proveedor.tier = 'free'
        with pytest.raises(services.AIUnavailable) as error:
            pedir(plus, professor, contains_student_data=True)
        assert error.value.reason == 'tier' and proveedor.calls == []
        assert pedir(plus, professor)  # con datos inventados sí se puede

    def test_una_clave_de_pago_acepta_datos_de_alumnos(self, professor, plus, proveedor):
        proveedor.tier = 'paid'
        assert pedir(plus, professor, contains_student_data=True)
        assert AIRequest.objects.get().contains_student_data is True

    def test_un_proveedor_mal_configurado_avisa_sin_detalles(self, professor, plus, settings):
        settings.AI_PROVIDER = 'gemini'
        settings.GEMINI_API_KEY = ''
        with pytest.raises(services.AIUnavailable) as error:
            pedir(plus, professor)
        assert error.value.reason == 'config' and 'GEMINI' not in error.value.messages[0]


class TestRegistro:
    def test_devuelve_lo_que_responde_el_proveedor_y_lo_registra(self, professor, plus, proveedor, settings):
        settings.AI_PRICING = {'fake-1': (1.0, 4.0)}
        proveedor.responses = [{'titulo': 'Álgebra', 'puntos': 5}]
        assert pedir(plus, professor) == {'titulo': 'Álgebra', 'puntos': 5}
        registro = AIRequest.objects.get()
        assert (registro.organization, registro.user, registro.kind, registro.provider, registro.model) == (
            plus, professor, 'probe', 'fake', 'fake-1',
        )
        assert registro.status == AIRequest.Status.OK and registro.error == ''
        assert registro.tokens_in > 0 and registro.tokens_out > 0 and registro.input_chars == len('\nTexto de prueba')
        assert float(registro.cost_usd) == pytest.approx((registro.tokens_in * 1.0 + registro.tokens_out * 4.0) / 1_000_000)

    def test_sin_precios_configurados_no_estima_el_costo(self, professor, plus):
        pedir(plus, professor)
        assert AIRequest.objects.get().cost_usd is None

    def test_no_guarda_lo_que_se_envia_ni_lo_que_se_recibe(self, professor, plus, proveedor):
        secreto = 'Matrícula 20240042 de Ana López'
        proveedor.responses = [{'titulo': 'respuesta con datos de Ana López'}]
        services.generate_json(
            organization=plus, user=professor, kind='probe', prompt=secreto, schema=SCHEMA, system='Instrucciones internas',
        )
        valores = ' '.join(str(v) for v in AIRequest.objects.values().get().values())
        assert 'Ana' not in valores and '2024004' not in valores and 'Instrucciones' not in valores
        assert len(AIRequest.objects.get().input_hash) == 64

    def test_la_misma_entrada_da_la_misma_huella(self, professor, plus):
        pedir(plus, professor)
        pedir(plus, professor)
        primera, segunda = AIRequest.objects.all()
        assert primera.input_hash == segunda.input_hash

    def test_el_proveedor_recibe_el_prompt_el_esquema_y_las_instrucciones(self, professor, plus, proveedor):
        pedir(plus, professor, system='Eres un asistente')
        assert proveedor.calls == [{'prompt': 'Texto de prueba', 'schema': SCHEMA, 'system': 'Eres un asistente'}]

    def test_si_el_proveedor_falla_registra_el_error_y_avisa_sin_filtrar_nada(self, professor, plus, proveedor):
        proveedor.error = ProviderError('Gemini respondió 503 UNAVAILABLE', retryable=True)
        with pytest.raises(services.AIFailed) as error:
            pedir(plus, professor)
        assert error.value.retryable is True and '503' not in error.value.messages[0]
        registro = AIRequest.objects.get()
        assert registro.status == AIRequest.Status.ERROR and '503' in registro.error and registro.tokens_in == 0
        assert services.uses_this_month(plus) == 0

    def test_un_error_que_no_conviene_reintentar_se_distingue(self, professor, plus, proveedor):
        proveedor.error = ProviderError('Gemini respondió 400 INVALID_ARGUMENT')
        with pytest.raises(services.AIFailed) as error:
            pedir(plus, professor)
        assert error.value.retryable is False
