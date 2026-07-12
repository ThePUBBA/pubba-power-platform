from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import quote

import requests


AIRTABLE_API_URL = "https://api.airtable.com/v0"
AIRTABLE_TIMEOUT_SECONDS = 10


class AirtableError(RuntimeError):
    """Raised when a configured Airtable write cannot be completed."""


def airtable_is_configured() -> bool:
    return all(
        os.getenv(name, "").strip()
        for name in (
            "AIRTABLE_API_KEY",
            "AIRTABLE_BASE_ID",
            "AIRTABLE_TABLE_NAME",
        )
    )


def save_simulation_to_airtable(simulation_result: dict) -> None:
    """Write one completed simulation to Airtable when credentials are configured."""

    api_key = os.getenv("AIRTABLE_API_KEY", "").strip()
    base_id = os.getenv("AIRTABLE_BASE_ID", "").strip()
    table_name = os.getenv("AIRTABLE_TABLE_NAME", "").strip()
    if not api_key or not base_id or not table_name:
        return

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
        "charging_window_start": simulation_result["charging_window"][
            "start_timestamp"
        ],
        "charging_window_end": simulation_result["charging_window"]["end_timestamp"],
        "discharging_window_start": simulation_result["discharging_window"][
            "start_timestamp"
        ],
        "discharging_window_end": simulation_result["discharging_window"][
            "end_timestamp"
        ],
    }
    url = f"{AIRTABLE_API_URL}/{quote(base_id, safe='')}/{quote(table_name, safe='')}"

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"fields": fields, "typecast": True},
            timeout=AIRTABLE_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            raise _response_error(response, api_key)
    except requests.RequestException as exc:
        message = _redact(str(exc), api_key)
        raise AirtableError(
            "Airtable record write failed: "
            f"HTTP status=unavailable; error_type=request_error; "
            f"message={message}; response_body=unavailable"
        ) from exc


def _response_error(response: requests.Response, api_key: str) -> AirtableError:
    response_body = _redact(response.text or "", api_key)
    error_type = "unknown"
    error_message = "Airtable rejected the record"
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
            error_type = str(error)
            error_message = str(error)

    error_type = _redact(error_type, api_key)
    error_message = _redact(error_message, api_key)
    return AirtableError(
        "Airtable record write failed: "
        f"HTTP status={response.status_code}; error_type={error_type}; "
        f"message={error_message}; response_body={response_body}"
    )


def _redact(value: str, secret: str) -> str:
    return value.replace(secret, "[REDACTED]") if secret else value
