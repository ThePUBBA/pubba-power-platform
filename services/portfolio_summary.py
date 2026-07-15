"""Authoritative portfolio summary business logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from domain.contracts import DispatchStatus, METRIC_VERSION
from domain.metrics import energy_throughput, energy_weighted_spread, trading_return
from supabase import get_default_portfolio, get_portfolio_summary_records


LEGACY_COMPLETED_STATUSES = {"simulated"}
COMPLETED_STATUSES = {DispatchStatus.COMPLETED.value, *LEGACY_COMPLETED_STATUSES}
ZERO = Decimal("0")


class PortfolioSummaryError(ValueError):
    def __init__(self, code: str, message: str, *, field: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


def _decimal(value: object, field: str) -> Decimal:
    if value in (None, ""):
        return ZERO
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise PortfolioSummaryError(
            "malformed_persisted_numeric",
            f"Persisted {field} is not a valid decimal value",
            field=field,
        ) from exc
    if not number.is_finite():
        raise PortfolioSummaryError(
            "malformed_persisted_numeric",
            f"Persisted {field} is not a finite decimal value",
            field=field,
        )
    return number


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def reporting_period_starts(now: datetime, zone: ZoneInfo) -> dict[str, datetime]:
    local = now.astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    month = midnight.replace(day=1)
    quarter_month = ((local.month - 1) // 3) * 3 + 1
    return {
        "today": midnight.astimezone(timezone.utc),
        "week": (midnight - timedelta(days=local.weekday())).astimezone(timezone.utc),
        "month": month.astimezone(timezone.utc),
        "quarter": month.replace(month=quarter_month).astimezone(timezone.utc),
        "year": midnight.replace(month=1, day=1).astimezone(timezone.utc),
    }


def build_portfolio_summary(
    *,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    timezone_name: str | None = None,
    now: datetime | None = None,
    portfolio_resolver: Callable[[], dict] = get_default_portfolio,
    records_loader: Callable[[dict], tuple[list[dict], list[dict]]] = get_portfolio_summary_records,
) -> dict:
    portfolio = portfolio_resolver()
    zone_name = timezone_name or portfolio["reporting_timezone"]
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise PortfolioSummaryError(
            "invalid_timezone", f"Unknown timezone: {zone_name}", field="timezone"
        ) from exc
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (start_at and start_at.tzinfo is None) or (end_at and end_at.tzinfo is None):
        raise PortfolioSummaryError(
            "invalid_timestamp", "start_at and end_at must include a timezone offset"
        )
    period_end = (end_at or generated_at).astimezone(timezone.utc)
    period_start = start_at.astimezone(timezone.utc) if start_at else None
    if period_start and period_start > period_end:
        raise PortfolioSummaryError(
            "invalid_date_range", "start_at must be on or before end_at", field="start_at"
        )

    assets, raw_dispatches = records_loader(portfolio)
    dispatches = [
        item for item in raw_dispatches
        if str(item.get("status", "")).strip().lower() in COMPLETED_STATUSES
    ]
    selected = [
        item for item in dispatches
        if (stamp := _timestamp(item.get("dispatch_timestamp")))
        and (period_start is None or stamp >= period_start)
        and stamp <= period_end
    ]

    def total(records: list[dict], field: str) -> Decimal:
        return sum((_decimal(record.get(field), field) for record in records), ZERO)

    gross = total(selected, "discharge_revenue")
    charging = total(selected, "charging_cost")
    net = total(selected, "net_profit")
    purchased = total(selected, "purchased_energy_mwh")
    sold = total(selected, "sold_energy_mwh")
    spreads = []
    for record in selected:
        sold_mwh = _decimal(record.get("sold_energy_mwh"), "sold_energy_mwh")
        buy = _decimal(record.get("average_buy_price_per_mwh"), "average_buy_price_per_mwh")
        sell = _decimal(record.get("average_sell_price_per_mwh"), "average_sell_price_per_mwh")
        spreads.append((sell - buy, sold_mwh))

    starts = reporting_period_starts(generated_at, zone)
    period_revenue = {
        name: total([
            item for item in dispatches
            if (stamp := _timestamp(item.get("dispatch_timestamp")))
            and boundary <= stamp <= generated_at
        ], "discharge_revenue")
        for name, boundary in starts.items()
    }
    dispatch_times = [
        stamp for item in selected
        if (stamp := _timestamp(item.get("discharge_end") or item.get("dispatch_timestamp")))
    ]
    dispatch_freshness = [
        stamp for item in dispatches
        if (stamp := _timestamp(item.get("updated_at") or item.get("discharge_end")))
    ]
    asset_freshness = [
        stamp for asset in assets if (stamp := _timestamp(asset.get("updated_at")))
    ]
    freshness = max(dispatch_freshness) if dispatch_freshness else (
        max(asset_freshness) if asset_freshness else None
    )
    weighted_spread = energy_weighted_spread(spreads)
    return {
        "portfolio": {
            key: portfolio[key] for key in (
                "id", "code", "name", "default_market", "reporting_timezone",
                "currency_code",
            )
        },
        "period": {"start_at": period_start, "end_at": period_end, "timezone": zone_name},
        "financial": {
            "gross_revenue": gross,
            "charging_cost": charging,
            "net_profit": net,
            "total_portfolio_profit": total(dispatches, "net_profit"),
            "trading_return": trading_return(net, charging) or ZERO,
            "weighted_average_spread_per_mwh": weighted_spread or ZERO,
        },
        "period_revenue": period_revenue,
        "operations": {
            "total_dispatches": len(selected),
            "purchased_energy_mwh": purchased,
            "sold_energy_mwh": sold,
            "energy_throughput_mwh": energy_throughput(purchased, sold),
            "last_dispatch_at": max(dispatch_times) if dispatch_times else None,
        },
        "fleet": {
            "active_assets": len(assets),
            "power_capacity_mw": total(assets, "power_mw"),
            "energy_capacity_mwh": total(assets, "energy_mwh"),
        },
        "metadata": {
            "metric_version": METRIC_VERSION,
            "data_freshness_at": freshness,
            "generated_at": generated_at,
        },
    }
