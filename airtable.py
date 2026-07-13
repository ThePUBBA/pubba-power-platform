from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import quote

import requests


AIRTABLE_API_URL = "https://api.airtable.com/v0"
AIRTABLE_TIMEOUT_SECONDS = 10

DEFAULT_TABLES = {
    "AIRTABLE_SIMULATIONS_TABLE": "Simulation Results",
    "AIRTABLE_ASSETS_TABLE": "Assets",
    "AIRTABLE_DISPATCH_EVENTS_TABLE": "Dispatch Events",
    "AIRTABLE_DAILY_PNL_TABLE": "Daily P&L",
}


class AirtableError(RuntimeError):
    """Raised when a configured Airtable request cannot be completed."""


class AirtableIntegrityError(AirtableError):
    """Raised when Airtable contains duplicate ledger records."""


def airtable_is_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in ("AIRTABLE_API_KEY", "AIRTABLE_BASE_ID")
    ) and bool(_table_name("AIRTABLE_SIMULATIONS_TABLE"))


def save_simulation_to_airtable(simulation_result: dict) -> str | None:
    """Write one completed simulation and return its Airtable record ID."""

    if not airtable_is_configured():
        return None

    fields = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "location": simulation_result.get("location"),
        "market": simulation_result.get("market"),
        "date": simulation_result.get("date"),
        "power_mw": simulation_result["power_mw"],
        "duration_hours": simulation_result["duration_hours"],
        "round_trip_efficiency": simulation_result["round_trip_efficiency"],
        "cycles": simulation_result["cycles"],
        "charging_cost": simulation_result["charging_cost"],
        "discharge_revenue": simulation_result["discharge_revenue"],
        "gross_arbitrage_margin": simulation_result["gross_arbitrage_margin"],
        "estimated_net_margin": simulation_result["estimated_net_margin"],
        "charging_window_start": simulation_result["charging_window"]["start_timestamp"],
        "charging_window_end": simulation_result["charging_window"]["end_timestamp"],
        "discharging_window_start": simulation_result["discharging_window"]["start_timestamp"],
        "discharging_window_end": simulation_result["discharging_window"]["end_timestamp"],
    }
    payload = _request(
        "post",
        _table_name("AIRTABLE_SIMULATIONS_TABLE"),
        json={"fields": fields, "typecast": True},
    )
    return payload.get("id") if isinstance(payload, dict) else None


def find_asset_by_asset_id(asset_id: str) -> dict | None:
    records = _list_records(
        _table_name("AIRTABLE_ASSETS_TABLE"),
        params={
            "filterByFormula": f"{{asset_id}}='{_escape_formula_value(asset_id)}'",
            "maxRecords": 1,
        },
    )
    return records[0] if records else None


def create_dispatch_event(
    asset: dict,
    simulation_result: dict,
    simulation_record_id: str,
) -> dict:
    if not asset.get("id") or not simulation_record_id:
        raise AirtableError(
            "Dispatch creation requires Airtable asset and simulation record IDs"
        )
    dispatch_id = f"dispatch:{simulation_record_id}"
    existing = _list_records(
        _table_name("AIRTABLE_DISPATCH_EVENTS_TABLE"),
        params={
            "filterByFormula": (
                f"{{dispatch_id}}='{_escape_formula_value(dispatch_id)}'"
            ),
            "maxRecords": 2,
        },
    )
    if len(existing) > 1:
        raise AirtableIntegrityError(
            f"Duplicate Dispatch Events rows found for dispatch_id={dispatch_id}"
        )
    if existing:
        return existing[0]

    fields = {
        "dispatch_id": dispatch_id,
        "asset_id": [asset["id"]],
        "simulation": [simulation_record_id],
        "charge_start": simulation_result["charging_window"]["start_timestamp"],
        "charge_end": simulation_result["charging_window"]["end_timestamp"],
        "discharge_start": simulation_result["discharging_window"]["start_timestamp"],
        "discharge_end": simulation_result["discharging_window"]["end_timestamp"],
        "charging_cost": simulation_result["charging_cost"],
        "discharge_revenue": simulation_result["discharge_revenue"],
        "estimated_profit": simulation_result["estimated_net_margin"],
    }
    return _request(
        "post",
        _table_name("AIRTABLE_DISPATCH_EVENTS_TABLE"),
        json={"fields": fields, "typecast": True},
    )


def recalculate_daily_pnl(date_value: str) -> dict:
    """Upsert exact Daily P&L totals derived from Dispatch Events for one UTC day."""

    dispatches = _list_records(
        _table_name("AIRTABLE_DISPATCH_EVENTS_TABLE"),
        params={
            "filterByFormula": (
                f"LEFT({{charge_start}}, 10)='{_escape_formula_value(date_value)}'"
            )
        },
    )
    totals = {
        "date": date_value,
        "gross_revenue": 0.0,
        "charging_cost": 0.0,
        "storage_cost": 0.0,
        "net_profit": 0.0,
    }
    for dispatch in dispatches:
        fields = dispatch.get("fields", {})
        revenue = _number(fields.get("discharge_revenue"))
        charging_cost = _number(fields.get("charging_cost"))
        net_profit = _number(fields.get("estimated_profit"))
        totals["gross_revenue"] += revenue
        totals["charging_cost"] += charging_cost
        totals["storage_cost"] += revenue - charging_cost - net_profit
        totals["net_profit"] += net_profit

    daily_records = _list_records(
        _table_name("AIRTABLE_DAILY_PNL_TABLE"),
        params={
            "filterByFormula": f"{{date}}='{_escape_formula_value(date_value)}'",
            "maxRecords": 2,
        },
    )
    if len(daily_records) > 1:
        raise AirtableIntegrityError(
            f"Duplicate Daily P&L rows found for date={date_value}"
        )
    if daily_records:
        return _request(
            "patch",
            _table_name("AIRTABLE_DAILY_PNL_TABLE"),
            record_id=daily_records[0]["id"],
            json={"fields": totals, "typecast": True},
        )
    return _request(
        "post",
        _table_name("AIRTABLE_DAILY_PNL_TABLE"),
        json={"fields": totals, "typecast": True},
    )


def get_portfolio_summary() -> dict[str, int | float]:
    assets = _list_records(_table_name("AIRTABLE_ASSETS_TABLE"))
    simulations = _list_records(_table_name("AIRTABLE_SIMULATIONS_TABLE"))
    dispatches = _list_records(_table_name("AIRTABLE_DISPATCH_EVENTS_TABLE"))
    daily_records = _list_records(_table_name("AIRTABLE_DAILY_PNL_TABLE"))
    return {
        "total_assets": len(assets),
        "active_assets": sum(
            1
            for record in assets
            if str(record.get("fields", {}).get("status", "")).strip().lower()
            == "active"
        ),
        "total_simulations": len(simulations),
        "total_dispatches": len(dispatches),
        "cumulative_revenue": sum(
            _number(record.get("fields", {}).get("gross_revenue"))
            for record in daily_records
        ),
        "cumulative_charging_cost": sum(
            _number(record.get("fields", {}).get("charging_cost"))
            for record in daily_records
        ),
        "cumulative_storage_cost": sum(
            _number(record.get("fields", {}).get("storage_cost"))
            for record in daily_records
        ),
        "cumulative_net_profit": sum(
            _number(record.get("fields", {}).get("net_profit"))
            for record in daily_records
        ),
    }


def _table_name(environment_name: str) -> str:
    if environment_name == "AIRTABLE_SIMULATIONS_TABLE":
        legacy = os.getenv("AIRTABLE_TABLE_NAME", "").strip()
        return os.getenv(environment_name, "").strip() or legacy or DEFAULT_TABLES[environment_name]
    return os.getenv(environment_name, "").strip() or DEFAULT_TABLES[environment_name]


def _list_records(table_name: str, params: dict | None = None) -> list[dict]:
    records: list[dict] = []
    request_params = dict(params or {})
    request_params.setdefault("pageSize", 100)
    while True:
        payload = _request("get", table_name, params=request_params)
        records.extend(payload.get("records", []))
        offset = payload.get("offset")
        if not offset or "maxRecords" in request_params:
            return records
        request_params["offset"] = offset


def _request(
    method: str,
    table_name: str,
    *,
    record_id: str | None = None,
    params: dict | None = None,
    json: dict | None = None,
) -> dict:
    api_key = os.getenv("AIRTABLE_API_KEY", "").strip()
    base_id = os.getenv("AIRTABLE_BASE_ID", "").strip()
    if not api_key or not base_id:
        raise AirtableError("Airtable is not configured")
    url = f"{AIRTABLE_API_URL}/{quote(base_id, safe='')}/{quote(table_name, safe='')}"
    if record_id:
        url = f"{url}/{quote(record_id, safe='')}"
    try:
        response = requests.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            params=params,
            json=json,
            timeout=AIRTABLE_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise _response_error(response, api_key)
        return response.json()
    except requests.RequestException as exc:
        message = _redact(str(exc), api_key)
        raise AirtableError(
            "Airtable request failed: HTTP status=unavailable; "
            f"error_type=request_error; message={message}; response_body=unavailable"
        ) from exc


def _response_error(response: requests.Response, api_key: str) -> AirtableError:
    response_body = _redact(response.text or "", api_key)
    error_type = "unknown"
    error_message = "Airtable rejected the request"
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type") or error_type)
            error_message = str(error.get("message") or error_message)
        elif error:
            error_type = error_message = str(error)
    return AirtableError(
        "Airtable request failed: "
        f"HTTP status={response.status_code}; error_type={_redact(error_type, api_key)}; "
        f"message={_redact(error_message, api_key)}; response_body={response_body}"
    )


def _escape_formula_value(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _number(value) -> float:
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AirtableError(f"Airtable numeric field contains invalid value: {value!r}") from exc


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "[REDACTED]") if secret else value
