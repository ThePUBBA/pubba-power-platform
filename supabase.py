from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

import requests


SUPABASE_TIMEOUT_SECONDS = 10
PAGE_SIZE = 1000
DEFAULT_PORTFOLIO_CODE = "ONLY1"
logger = logging.getLogger(__name__)


class SupabaseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str = "supabase_unavailable",
        status_code: int = 502,
        operation: str | None = None,
        simulation_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.operation = operation
        self.simulation_id = simulation_id


class DuplicateAssetError(SupabaseError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(
            f"Asset already exists: {asset_id}",
            error_code="duplicate_asset",
            status_code=409,
            operation="create_asset",
        )


class MissingAssetError(SupabaseError):
    def __init__(self, asset_id: str) -> None:
        super().__init__(
            f"Asset not found: {asset_id}",
            error_code="missing_asset",
            status_code=404,
            operation="find_asset",
        )


class MissingDefaultPortfolioError(SupabaseError):
    def __init__(self, portfolio_code: str = DEFAULT_PORTFOLIO_CODE) -> None:
        super().__init__(
            f"Default portfolio was not found: {portfolio_code}",
            error_code="missing_default_portfolio",
            status_code=503,
            operation="resolve_default_portfolio",
        )


def supabase_is_configured() -> bool:
    return bool(_configuration()[0] and _configuration()[1])


def check_supabase_connectivity() -> str:
    if not supabase_is_configured():
        return "not_configured"
    try:
        _request("get", "assets", params={"select": "id", "limit": 1})
    except SupabaseError as exc:
        logger.warning(
            "Supabase connectivity check failed",
            extra={"error_code": exc.error_code},
        )
        return "unavailable"
    return "connected"


def derive_idempotency_key(request_fields: dict, simulation_result: dict) -> str:
    canonical = json.dumps(
        {"request": request_fields, "result": simulation_result},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"auto:{hashlib.sha256(canonical.encode()).hexdigest()}"


def get_default_portfolio() -> dict:
    """Resolve the current single portfolio by its stable operator code."""
    records = _request(
        "get",
        "portfolios",
        params={
            "select": "id,code,name,default_market,reporting_timezone,currency_code,status",
            "code": f"eq.{DEFAULT_PORTFOLIO_CODE}",
            "limit": 1,
        },
    )
    if not records:
        raise MissingDefaultPortfolioError()
    portfolio = records[0]
    if not portfolio.get("id"):
        raise SupabaseError(
            "Default portfolio record is missing its id",
            error_code="malformed_supabase_response",
            operation="resolve_default_portfolio",
        )
    return portfolio


def list_assets(*, limit: int | None = None, offset: int = 0) -> list[dict]:
    params: dict[str, Any] = {
        "select": "*",
        "order": "asset_id.asc,id.asc",
        "offset": offset,
    }
    if limit is not None:
        params["limit"] = limit
        return _request("get", "assets", params=params)
    return _list_all("assets", params=params)


def get_asset(asset_id: str) -> dict | None:
    records = _request(
        "get",
        "assets",
        params={
            "select": "*",
            "asset_id": f"eq.{asset_id}",
            "limit": 1,
        },
    )
    return records[0] if records else None


def create_asset(fields: dict) -> dict:
    portfolio = get_default_portfolio()
    payload = {**fields, "portfolio_id": portfolio["id"]}
    try:
        records = _request(
            "post",
            "assets",
            json_body=payload,
            prefer="return=representation",
        )
    except SupabaseError as exc:
        if exc.status_code == 409:
            raise DuplicateAssetError(str(fields.get("asset_id", ""))) from exc
        raise
    if not records:
        raise SupabaseError(
            "Supabase returned no asset after creation",
            error_code="malformed_supabase_response",
            operation="create_asset",
        )
    return records[0]


def update_asset(asset_id: str, fields: dict) -> dict:
    if not get_asset(asset_id):
        raise MissingAssetError(asset_id)
    records = _request(
        "patch",
        "assets",
        params={"asset_id": f"eq.{asset_id}"},
        json_body=fields,
        prefer="return=representation",
    )
    if not records:
        raise SupabaseError(
            "Supabase returned no asset after update",
            error_code="malformed_supabase_response",
            operation="update_asset",
        )
    return records[0]


def list_dispatch_events(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    asset_id: str | None = None,
    market: str | None = None,
    location: str | None = None,
    status: str | None = None,
    limit: int | None = 100,
    offset: int = 0,
) -> list[dict]:
    params = _dispatch_filter_params(
        start_date=start_date,
        end_date=end_date,
        asset_id=asset_id,
        market=market,
        location=location,
        status=status,
    )
    if params is None:
        return []
    params.update(
        {
            "select": "*",
            "order": "dispatch_timestamp.asc,id.asc",
            "offset": offset,
        }
    )
    if limit is not None:
        params["limit"] = limit
        return _request("get", "dispatch_events", params=params)
    return _list_all("dispatch_events", params=params)


def get_portfolio_summary_records(portfolio: dict) -> tuple[list[dict], list[dict]]:
    """Return summary inputs scoped to one resolved portfolio."""
    portfolio_id = portfolio["id"]
    assets = _list_all(
        "assets",
        params={
            "select": "id,status,power_mw,energy_mwh,updated_at",
            "portfolio_id": f"eq.{portfolio_id}",
            "status": "eq.active",
            "order": "id.asc",
        },
    )
    dispatches = _list_all(
        "dispatch_events",
        params={
            "select": (
                "id,dispatch_id,asset_id,status,dispatch_timestamp,charge_start,"
                "charge_end,discharge_start,discharge_end,updated_at,market,location,"
                "energy_mwh,"
                "purchased_energy_mwh,sold_energy_mwh,charging_cost,"
                "discharge_revenue,net_profit,average_buy_price_per_mwh,"
                "average_sell_price_per_mwh"
            ),
            "portfolio_id": f"eq.{portfolio_id}",
            "or": "(status.eq.completed,status.eq.simulated)",
            "order": "dispatch_timestamp.asc,id.asc",
        },
    )
    return assets, dispatches


def get_asset_performance() -> list[dict]:
    assets = list_assets()
    dispatches = list_dispatch_events(limit=None)
    metrics = {
        asset["asset_id"]: {
            "total_dispatches": 0,
            "total_revenue": 0.0,
            "total_charging_cost": 0.0,
            "total_profit": 0.0,
            "last_dispatch_time": None,
            "_last_dispatch_datetime": None,
        }
        for asset in assets
        if asset.get("asset_id")
    }
    for dispatch in dispatches:
        values = metrics.get(dispatch.get("asset_id"))
        if values is None:
            continue
        values["total_dispatches"] += 1
        values["total_revenue"] += _safe_number(
            dispatch.get("discharge_revenue"), "discharge_revenue"
        )
        values["total_charging_cost"] += _safe_number(
            dispatch.get("charging_cost"), "charging_cost"
        )
        values["total_profit"] += _safe_number(
            dispatch.get("net_profit"), "net_profit"
        )
        dispatch_time = _parse_timestamp(
            dispatch.get("discharge_end") or dispatch.get("dispatch_timestamp")
        )
        if dispatch_time and (
            values["_last_dispatch_datetime"] is None
            or dispatch_time > values["_last_dispatch_datetime"]
        ):
            values["_last_dispatch_datetime"] = dispatch_time
            values["last_dispatch_time"] = (
                dispatch.get("discharge_end") or dispatch.get("dispatch_timestamp")
            )

    results = []
    for asset in assets:
        values = metrics.get(asset.get("asset_id"), {})
        dispatch_count = int(values.get("total_dispatches", 0))
        total_profit = float(values.get("total_profit", 0.0))
        results.append(
            {
                "asset_id": str(asset.get("asset_id") or ""),
                "asset_name": str(asset.get("asset_name") or ""),
                "technology": str(asset.get("technology") or ""),
                "status": str(asset.get("status") or ""),
                "power_mw": _safe_number(asset.get("power_mw"), "power_mw"),
                "energy_mwh": _safe_number(asset.get("energy_mwh"), "energy_mwh"),
                "location": str(asset.get("location") or ""),
                "total_dispatches": dispatch_count,
                "total_revenue": float(values.get("total_revenue", 0.0)),
                "total_charging_cost": float(
                    values.get("total_charging_cost", 0.0)
                ),
                "total_profit": total_profit,
                "average_profit_per_dispatch": (
                    total_profit / dispatch_count if dispatch_count else 0.0
                ),
                "last_dispatch_time": values.get("last_dispatch_time"),
            }
        )
    return results


def persist_simulation(
    request_fields: dict,
    simulation_result: dict,
    idempotency_key: str,
) -> dict:
    portfolio = get_default_portfolio()
    portfolio_id = portfolio["id"]
    request_hash = hashlib.sha256(
        json.dumps(request_fields, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    simulation_id = str(uuid5(NAMESPACE_URL, f"only1:{idempotency_key}"))
    existing = _request(
        "get",
        "simulation_results",
        params={
            "select": "*",
            "external_simulation_id": f"eq.{idempotency_key}",
            "portfolio_id": f"eq.{portfolio_id}",
            "limit": 1,
        },
    )
    if existing:
        simulation = existing[0]
        if simulation.get("request_hash") != request_hash:
            raise SupabaseError(
                "Idempotency key was already used for a different simulation request",
                error_code="idempotency_conflict",
                status_code=409,
                operation="archive_simulation",
                simulation_id=simulation.get("id"),
            )
        simulation_id = simulation["id"]
    else:
        payload = _simulation_payload(
            simulation_id,
            idempotency_key,
            request_hash,
            request_fields,
            simulation_result,
            portfolio_id,
        )
        try:
            created = _request(
                "post",
                "simulation_results",
                json_body=payload,
                prefer="return=representation",
            )
        except SupabaseError as exc:
            if exc.status_code == 409:
                concurrent = _request(
                    "get",
                    "simulation_results",
                    params={
                        "select": "*",
                        "external_simulation_id": f"eq.{idempotency_key}",
                        "portfolio_id": f"eq.{portfolio_id}",
                        "limit": 1,
                    },
                )
                if concurrent and concurrent[0].get("request_hash") == request_hash:
                    simulation_id = concurrent[0]["id"]
                    created = concurrent
                else:
                    raise SupabaseError(
                        "Idempotency key conflicts with another simulation request",
                        error_code="idempotency_conflict",
                        status_code=409,
                        operation="archive_simulation",
                    ) from exc
            else:
                raise SupabaseError(
                    f"Failed to archive completed simulation: {exc}",
                    error_code="failed_simulation_archival",
                    status_code=exc.status_code,
                    operation="archive_simulation",
                    simulation_id=simulation_id,
                ) from exc
        if not created:
            raise SupabaseError(
                "Supabase returned no simulation after archival",
                error_code="malformed_supabase_response",
                operation="archive_simulation",
                simulation_id=simulation_id,
            )

    business_asset_id = request_fields.get("asset_id")
    if not business_asset_id:
        return {
            "status": "saved",
            "simulation_id": simulation_id,
            "dispatch_id": None,
            "error_code": None,
            "message": "Simulation saved; no asset_id was supplied",
        }
    try:
        asset = get_asset(str(business_asset_id))
    except SupabaseError as exc:
        raise SupabaseError(
            f"Simulation saved, but asset validation failed: {exc}",
            error_code="asset_validation_failed",
            status_code=exc.status_code,
            operation="find_asset",
            simulation_id=simulation_id,
        ) from exc
    if not asset:
        return {
            "status": "partial",
            "simulation_id": simulation_id,
            "dispatch_id": None,
            "error_code": "missing_asset",
            "message": f"Simulation saved, but asset was not found: {business_asset_id}",
        }

    try:
        _request(
            "patch",
            "simulation_results",
            params={"id": f"eq.{simulation_id}"},
            json_body={"asset_id": asset["asset_id"]},
            prefer="return=minimal",
        )
    except SupabaseError as exc:
        raise SupabaseError(
            f"Simulation saved, but asset link update failed: {exc}",
            error_code="failed_dispatch_creation",
            status_code=exc.status_code,
            operation="link_simulation_asset",
            simulation_id=simulation_id,
        ) from exc
    dispatch_id = f"dispatch:{simulation_id}"
    dispatch_payload = _dispatch_payload(
        dispatch_id,
        asset["asset_id"],
        simulation_id,
        request_fields,
        simulation_result,
        portfolio_id,
    )
    try:
        _request(
            "post",
            "dispatch_events",
            params={"on_conflict": "dispatch_id"},
            json_body=dispatch_payload,
            prefer="resolution=ignore-duplicates,return=minimal",
        )
    except SupabaseError as exc:
        raise SupabaseError(
            f"Simulation saved, but dispatch creation failed: {exc}",
            error_code="failed_dispatch_creation",
            status_code=exc.status_code,
            operation="create_dispatch",
            simulation_id=simulation_id,
        ) from exc
    return {
        "status": "saved",
        "simulation_id": simulation_id,
        "dispatch_id": dispatch_id,
        "error_code": None,
        "message": "Simulation and dispatch saved",
    }


def aggregate_report(
    period: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    dispatches = list_dispatch_events(
        start_date=start_date, end_date=end_date, limit=None
    )
    buckets: dict[date, dict] = {}
    for dispatch in dispatches:
        timestamp = _parse_timestamp(dispatch.get("dispatch_timestamp"))
        if not timestamp:
            logger.warning("Skipping dispatch with malformed timestamp in report")
            continue
        period_start, period_end = _period_bounds(timestamp.date(), period)
        bucket = buckets.setdefault(
            period_start,
            {
                "period_start": period_start.isoformat(),
                "period_end": period_end.isoformat(),
                "total_dispatches": 0,
                "total_energy_mwh": 0.0,
                "charging_cost": 0.0,
                "discharge_revenue": 0.0,
                "storage_cost": 0.0,
                "net_profit": 0.0,
            },
        )
        bucket["total_dispatches"] += 1
        bucket["total_energy_mwh"] += _safe_number(
            dispatch.get("energy_mwh"), "energy_mwh"
        )
        bucket["charging_cost"] += _safe_number(
            dispatch.get("charging_cost"), "charging_cost"
        )
        bucket["discharge_revenue"] += _safe_number(
            dispatch.get("discharge_revenue"), "discharge_revenue"
        )
        bucket["storage_cost"] += _safe_number(
            dispatch.get("storage_cost"), "storage_cost"
        )
        bucket["net_profit"] += _safe_number(
            dispatch.get("net_profit"), "net_profit"
        )
    return [buckets[key] for key in sorted(buckets)]


def verify_migration() -> dict:
    required_columns = {
        "portfolios": {
            "id", "name", "code", "default_market", "reporting_timezone",
            "currency_code", "status", "created_at", "updated_at",
        },
        "assets": {
            "id", "asset_id", "asset_name", "technology", "power_mw",
            "energy_mwh", "duration_hours", "location", "lease_cost_monthly",
            "status", "retired_at", "retirement_reason", "revision",
            "portfolio_id", "created_at", "updated_at",
        },
        "simulation_results": {
            "id", "external_simulation_id", "request_hash", "asset_id",
            "location", "market", "simulation_date", "power_mw",
            "duration_hours", "round_trip_efficiency", "cycles",
            "storage_fee_per_mwh", "variable_om_per_mwh", "charging_cost",
            "discharge_revenue", "gross_arbitrage_margin",
            "estimated_net_margin", "charging_window_start",
            "charging_window_end", "discharging_window_start",
            "discharging_window_end", "portfolio_id", "created_at",
        },
        "dispatch_events": {
            "id", "dispatch_id", "asset_id", "simulation_id",
            "dispatch_timestamp", "charge_start", "charge_end",
            "discharge_start", "discharge_end", "market", "location", "status",
            "energy_mwh", "charging_cost", "discharge_revenue", "storage_cost",
            "net_profit", "purchased_energy_mwh", "sold_energy_mwh",
            "average_buy_price_per_mwh", "average_sell_price_per_mwh",
            "portfolio_id", "created_at", "updated_at",
        },
    }
    for table, columns in required_columns.items():
        _request(
            "get",
            table,
            params={"select": ",".join(sorted(columns)), "limit": 1},
        )
    portfolio = get_default_portfolio()
    assets = list_assets()
    simulations = _list_all(
        "simulation_results", params={"select": "id,portfolio_id"}
    )
    dispatches = list_dispatch_events(limit=None)
    asset_ids = {record.get("asset_id") for record in assets}
    simulation_ids = {record.get("id") for record in simulations}
    orphaned = sum(
        1
        for record in dispatches
        if record.get("asset_id") not in asset_ids
        or record.get("simulation_id") not in simulation_ids
    )
    duplicate_ids = [
        value
        for value, count in Counter(
            record.get("dispatch_id") for record in dispatches
        ).items()
        if value and count > 1
    ]
    unowned = sum(
        record.get("portfolio_id") != portfolio["id"]
        for record in [*assets, *simulations, *dispatches]
    )
    return {
        "tables_verified": sorted(required_columns),
        "asset_count": len(assets),
        "simulation_count": len(simulations),
        "dispatch_count": len(dispatches),
        "orphaned_dispatch_count": orphaned,
        "duplicate_dispatch_ids": duplicate_ids,
        "default_portfolio_code": portfolio["code"],
        "records_outside_default_portfolio": unowned,
    }


def _simulation_payload(
    simulation_id: str,
    idempotency_key: str,
    request_hash: str,
    request_fields: dict,
    result: dict,
    portfolio_id: str,
) -> dict:
    return {
        "id": simulation_id,
        "external_simulation_id": idempotency_key,
        "request_hash": request_hash,
        "portfolio_id": portfolio_id,
        "location": request_fields.get("location"),
        "market": request_fields.get("market"),
        "simulation_date": request_fields.get("date")
        or result["charging_window"]["start_timestamp"][:10],
        "power_mw": result.get("power_mw"),
        "duration_hours": result.get("duration_hours"),
        "round_trip_efficiency": result.get("round_trip_efficiency"),
        "cycles": result.get("cycles"),
        "storage_fee_per_mwh": result.get(
            "storage_fee_per_mwh", request_fields.get("storage_fee_per_mwh", 0)
        ),
        "variable_om_per_mwh": result.get(
            "variable_om_per_mwh", request_fields.get("variable_om_per_mwh", 0)
        ),
        "charging_cost": result.get("charging_cost"),
        "discharge_revenue": result.get("discharge_revenue"),
        "gross_arbitrage_margin": result.get("gross_arbitrage_margin"),
        "estimated_net_margin": result.get("estimated_net_margin"),
        "charging_window_start": result["charging_window"]["start_timestamp"],
        "charging_window_end": result["charging_window"]["end_timestamp"],
        "discharging_window_start": result["discharging_window"]["start_timestamp"],
        "discharging_window_end": result["discharging_window"]["end_timestamp"],
    }


def _dispatch_payload(
    dispatch_id: str,
    asset_id: str,
    simulation_id: str,
    request_fields: dict,
    result: dict,
    portfolio_id: str,
) -> dict:
    return {
        "dispatch_id": dispatch_id,
        "asset_id": asset_id,
        "simulation_id": simulation_id,
        "portfolio_id": portfolio_id,
        "dispatch_timestamp": result["charging_window"]["start_timestamp"],
        "charge_start": result["charging_window"]["start_timestamp"],
        "charge_end": result["charging_window"]["end_timestamp"],
        "discharge_start": result["discharging_window"]["start_timestamp"],
        "discharge_end": result["discharging_window"]["end_timestamp"],
        "market": request_fields.get("market"),
        "location": request_fields.get("location"),
        "action": "discharge",
        "power_mw": result.get("power_mw"),
        "status": "simulated",
        "energy_mwh": result.get("discharged_energy_mwh"),
        "purchased_energy_mwh": result.get("charging_energy_required_mwh"),
        "sold_energy_mwh": result.get("discharged_energy_mwh"),
        "average_buy_price_per_mwh": (
            result.get("charging_cost") / result.get("charging_energy_required_mwh")
            if result.get("charging_energy_required_mwh")
            else None
        ),
        "average_sell_price_per_mwh": (
            result.get("discharge_revenue") / result.get("discharged_energy_mwh")
            if result.get("discharged_energy_mwh")
            else None
        ),
        "charging_cost": result.get("charging_cost"),
        "discharge_revenue": result.get("discharge_revenue"),
        "storage_cost": _safe_number(result.get("storage_lease_cost"), "storage_lease_cost")
        + _safe_number(result.get("variable_operating_cost"), "variable_operating_cost"),
        "net_profit": result.get("estimated_net_margin"),
    }


def _dispatch_filter_params(
    *,
    start_date: date | None,
    end_date: date | None,
    asset_id: str | None,
    market: str | None,
    location: str | None,
    status: str | None,
) -> dict | None:
    params: dict[str, Any] = {}
    if start_date:
        params["dispatch_timestamp"] = f"gte.{start_date.isoformat()}T00:00:00Z"
    if end_date:
        end_exclusive = end_date + timedelta(days=1)
        end_filter = f"lt.{end_exclusive.isoformat()}T00:00:00Z"
        if "dispatch_timestamp" in params:
            params["and"] = (
                f"(dispatch_timestamp.{params.pop('dispatch_timestamp')},"
                f"dispatch_timestamp.{end_filter})"
            )
        else:
            params["dispatch_timestamp"] = end_filter
    if asset_id:
        asset = get_asset(asset_id)
        if not asset:
            return None
        params["asset_id"] = f"eq.{asset['asset_id']}"
    if market:
        params["market"] = f"eq.{market}"
    if location:
        params["location"] = f"eq.{location}"
    if status:
        params["status"] = f"eq.{status}"
    return params


def _period_bounds(value: date, period: str) -> tuple[date, date]:
    if period == "daily":
        return value, value
    if period == "weekly":
        start = value - timedelta(days=value.weekday())
        return start, start + timedelta(days=6)
    if period == "monthly":
        start = value.replace(day=1)
        next_month = (
            start.replace(year=start.year + 1, month=1)
            if start.month == 12
            else start.replace(month=start.month + 1)
        )
        return start, next_month - timedelta(days=1)
    if period == "quarterly":
        month = ((value.month - 1) // 3) * 3 + 1
        start = value.replace(month=month, day=1)
        next_quarter = (
            start.replace(year=start.year + 1, month=1)
            if month == 10
            else start.replace(month=month + 3)
        )
        return start, next_quarter - timedelta(days=1)
    if period == "yearly":
        return value.replace(month=1, day=1), value.replace(month=12, day=31)
    raise ValueError(f"Unsupported report period: {period}")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_number(value: Any, field_name: str) -> float:
    if value in (None, ""):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = math.nan
    if not math.isfinite(number):
        logger.warning(
            "Ignoring malformed Supabase numeric value",
            extra={"supabase_field": field_name},
        )
        return 0.0
    return number


def _list_all(table: str, *, params: dict | None = None) -> list[dict]:
    records: list[dict] = []
    offset = int((params or {}).get("offset", 0))
    while True:
        page_params = dict(params or {})
        page_params.update({"limit": PAGE_SIZE, "offset": offset})
        page = _request("get", table, params=page_params)
        records.extend(page)
        if len(page) < PAGE_SIZE:
            return records
        offset += PAGE_SIZE


def _request(
    method: str,
    table: str,
    *,
    params: dict | None = None,
    json_body: dict | list | None = None,
    prefer: str | None = None,
) -> list[dict]:
    url, service_key = _configuration()
    if not url or not service_key:
        raise SupabaseError(
            "Supabase is not configured; set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY",
            error_code="supabase_not_configured",
            status_code=503,
        )
    endpoint = f"{url.rstrip('/')}/rest/v1/{quote(table, safe='')}"
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    try:
        response = requests.request(
            method,
            endpoint,
            headers=headers,
            params=params,
            json=json_body,
            timeout=SUPABASE_TIMEOUT_SECONDS,
        )
    except requests.Timeout as exc:
        raise SupabaseError(
            "Supabase request timed out",
            error_code="supabase_timeout",
            status_code=504,
        ) from exc
    except requests.RequestException as exc:
        message = _redact(str(exc), service_key)
        raise SupabaseError(
            f"Supabase request failed: {message}",
            error_code="supabase_unavailable",
            status_code=502,
        ) from exc
    if response.status_code >= 400:
        raise _response_error(response, service_key)
    if response.status_code == 204 or not response.content:
        return []
    try:
        payload = response.json()
    except ValueError as exc:
        raise SupabaseError(
            "Supabase returned malformed JSON",
            error_code="malformed_supabase_response",
            status_code=502,
        ) from exc
    if not isinstance(payload, list):
        raise SupabaseError(
            "Supabase returned an unexpected response shape",
            error_code="malformed_supabase_response",
            status_code=502,
        )
    return payload


def _response_error(response: requests.Response, service_key: str) -> SupabaseError:
    message = "Supabase rejected the request"
    code = "supabase_error"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        code = str(payload.get("code") or code)
        message = str(payload.get("message") or message)
    safe_message = _redact(message, service_key)
    return SupabaseError(
        f"Supabase request failed: HTTP status={response.status_code}; "
        f"code={_redact(code, service_key)}; message={safe_message}",
        error_code="supabase_unavailable",
        status_code=(409 if response.status_code == 409 else 502),
    )


def _configuration() -> tuple[str, str]:
    return (
        os.getenv("SUPABASE_URL", "").strip(),
        os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip(),
    )


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "[REDACTED]") if secret else value
