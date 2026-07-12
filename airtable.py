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
            json={"fields": fields},
            timeout=AIRTABLE_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise AirtableError(f"Airtable record write failed: {exc}") from exc
