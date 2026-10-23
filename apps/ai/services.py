"""La única puerta de entrada a la IA: ``generate_json``.

Antes de llamar al proveedor revisa, en este orden, que (1) el plan incluya IA, (2) la organización la tenga encendida,
(3) quede cuota del mes y (4) una clave gratuita no reciba datos de alumnos. Después registra la solicitud en
``AIRequest`` (sin guardar su contenido). Quien la use (generar un quiz, revisar una tarea) llama solo a esta función.
"""

import hashlib
import time
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.organizations import limits

from .models import AIRequest
from .providers import ProviderError, get_provider

MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


class AIUnavailable(ValidationError):
    """La IA no se puede usar ahora. El mensaje ya está listo para mostrarse al docente."""

    def __init__(self, message, *, reason):
        super().__init__(message, code='ai_unavailable')
        self.reason = reason  # 'plan' | 'disabled' | 'quota' | 'tier' | 'config'


class AIFailed(ValidationError):
    """El proveedor falló. ``retryable``: tiene sentido volver a intentar."""

    def __init__(self, message, *, retryable=False):
        super().__init__(message, code='ai_failed')
        self.retryable = retryable


# ── Cuota mensual ─────────────────────────────────────────────────────

def month_start(now=None):
    now = timezone.localtime(now or timezone.now())
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def next_month_start(now=None):
    start = month_start(now)
    return start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)


def renewal_label(now=None):
    """«1 de noviembre»: cuándo vuelve a llenarse la cuota."""
    renew = next_month_start(now)
    return f'1 de {MONTHS[renew.month - 1]}'


def uses_this_month(organization, now=None):
    """Solicitudes correctas de este mes calendario (las fallidas no cuentan)."""
    return AIRequest.objects.for_organization(organization).filter(
        status=AIRequest.Status.OK, created_at__gte=month_start(now),
    ).count()


def monthly_limit(organization):
    return limits.plan_for(organization).ai_monthly_uses


def usage_summary(organization, now=None):
    """``{'used', 'limit', 'remaining'}`` del mes, o ``None`` si el plan no incluye IA."""
    if not limits.has_feature(organization, 'ai_assistant'):
        return None
    limit = monthly_limit(organization)
    used = uses_this_month(organization, now)
    return {'used': used, 'limit': limit, 'remaining': None if limit is None else max(0, limit - used)}


# ── Revisiones ────────────────────────────────────────────────────────

def check_available(organization, *, now=None):
    """Lanza ``AIUnavailable`` si la organización no puede usar la IA ahora."""
    plan = limits.plan_for(organization)
    if not limits.has_feature(organization, 'ai_assistant'):
        raise AIUnavailable(f'Tu plan {plan.name} no incluye la IA asistida. Está disponible en el plan Plus.', reason='plan')
    if not organization.ai_enabled:
        raise AIUnavailable(
            'La IA está desactivada en tu organización. El propietario puede activarla en Ajustes.', reason='disabled',
        )
    summary = usage_summary(organization, now)
    if summary['limit'] is not None and summary['used'] >= summary['limit']:
        raise AIUnavailable(
            f'Ya usaste los {summary["limit"]} usos de IA de tu plan {plan.name} este mes. '
            f'Se renuevan el {renewal_label(now)}.', reason='quota',
        )


def _cost(provider, tokens_in, tokens_out):
    prices = settings.AI_PRICING.get(provider.model)
    if not prices:
        return None
    per_million = Decimal(1_000_000)
    return (Decimal(str(prices[0])) * tokens_in + Decimal(str(prices[1])) * tokens_out) / per_million


def generate_json(*, organization, user, kind, prompt, schema, system='', contains_student_data=False):
    """Pide a la IA un JSON que cumpla ``schema`` y devuelve el dato ya interpretado.

    ``contains_student_data``: el texto lleva contenido de alumnos; una clave gratuita lo rechaza. Lanza
    ``AIUnavailable`` (plan, interruptor, cuota o configuración) o ``AIFailed`` (falló el proveedor).
    """
    check_available(organization)
    try:
        provider = get_provider()
    except ProviderError as error:
        raise AIUnavailable('La IA no está configurada en el servidor. Avisa al administrador.', reason='config') from error
    if contains_student_data and provider.tier == 'free':
        raise AIUnavailable(
            'Este servidor usa una clave gratuita de IA, que no puede recibir datos de alumnos.', reason='tier',
        )
    sent = f'{system}\n{prompt}'
    record = dict(
        organization=organization, user=user, kind=kind, provider=provider.name, model=provider.model,
        input_chars=len(sent), input_hash=hashlib.sha256(sent.encode('utf-8')).hexdigest(),
        contains_student_data=contains_student_data,
    )
    started = time.monotonic()
    try:
        result = provider.generate_json(prompt=prompt, schema=schema, system=system)
    except ProviderError as error:
        AIRequest.objects.create(
            status=AIRequest.Status.ERROR, error=str(error)[:200], duration_ms=int((time.monotonic() - started) * 1000), **record,
        )
        raise AIFailed(
            'No se pudo completar la solicitud de IA. Intenta de nuevo en unos minutos.', retryable=error.retryable,
        ) from error
    AIRequest.objects.create(
        status=AIRequest.Status.OK, tokens_in=result.tokens_in, tokens_out=result.tokens_out,
        cost_usd=_cost(provider, result.tokens_in, result.tokens_out), duration_ms=int((time.monotonic() - started) * 1000),
        **{**record, 'model': result.model or provider.model},
    )
    return result.data
