"""Decimal-safe presentation formatting for dashboard values."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


CURRENCY_SYMBOLS = {"USD": "$"}


def as_decimal(value: object) -> Decimal:
    try:
        number = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Value is not numeric") from exc
    if not number.is_finite():
        raise ValueError("Value must be finite")
    return number


def format_currency(value: object, currency_code: str = "USD") -> str:
    number = as_decimal(value)
    symbol = CURRENCY_SYMBOLS.get(currency_code.upper(), f"{currency_code.upper()} ")
    absolute = f"{abs(number):,.2f}"
    return f"-{symbol}{absolute}" if number < 0 else f"{symbol}{absolute}"


def format_energy(value: object) -> str:
    return f"{as_decimal(value):,.2f} MWh"


def format_power(value: object) -> str:
    return f"{as_decimal(value):,.2f} MW"


def format_spread(value: object, currency_code: str = "USD") -> str:
    return f"{format_currency(value, currency_code)}/MWh"


def format_trading_return(value: object) -> str:
    """Format the backend's decimal ratio contract as a percentage."""
    return f"{as_decimal(value) * Decimal('100'):,.2f}%"


def format_date(value: object, *, fallback: str = "Not available") -> str:
    """Format a date-only value consistently for labels and chart axes."""
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(str(value)).strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return fallback


def format_chart_time_tick(
    value: object,
    timezone_name: str,
    *,
    fallback: str = "Not available",
) -> str:
    """Format chart time ticks, including the date only at local midnight."""
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo(timezone_name))
        hour = local.strftime("%I").lstrip("0") or "12"
        time_label = f'{hour}{local.strftime(":%M %p")}'
        if local.hour == 0 and local.minute == 0:
            return f'{time_label}<br>{local.strftime("%b %d, %Y")}'
        return time_label
    except (ValueError, TypeError):
        return fallback


def format_dispatch_axis_label(
    value: object,
    timezone_name: str,
    *,
    fallback: str = "Not available",
) -> str:
    """Format a compact categorical dispatch label without raw timestamps."""
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo(timezone_name))
        hour = local.strftime("%I").lstrip("0") or "12"
        return f'{local.strftime("%b %d")} · {hour}{local.strftime(":%M %p")}'
    except (ValueError, TypeError):
        return fallback


def format_timestamp(
    value: object,
    timezone_name: str,
    *,
    fallback: str = "Not available",
) -> str:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        local = parsed.astimezone(ZoneInfo(timezone_name))
        hour = local.strftime("%I").lstrip("0") or "12"
        return f'{local.strftime("%b %d, %Y")} · {hour}{local.strftime(":%M %p %Z")}'
    except (ValueError, TypeError):
        return fallback


def format_dispatch_timestamp(
    value: object,
    timezone_name: str,
    *,
    fallback: str = "Not available",
) -> str:
    """Compatibility wrapper for the dashboard's standard timestamp format."""
    return format_timestamp(value, timezone_name, fallback=fallback)
